"""Принудительное оформление DOCX (§4.5, §6.1, §6.2 ТЗ).

Только стандартная библиотека: в OpenXML лезть всё равно приходится, а без
зависимостей пакет ставится за секунды и не ломается при обновлении lxml.

Зачем это нужно, если есть reference.docx: pandoc пишет ширину таблицы прямым
форматированием (tblW auto, сетка в 7920 twips независимо от размера страницы),
и стиль таблицы её не перебьёт. Границы, отступы и шапку правильнее держать в
самом reference.docx — здесь они остаются как принудительный режим для случая,
когда пользователь подставил свой шаблон.
"""

from __future__ import annotations

import io
import time
import zipfile
import xml.etree.ElementTree as ET

from .models import Profile
from .ooxml import (
    PPR_SEQ, RPR_SEQ, SECTPR_SEQ, TBLPR_SEQ, TCPR_SEQ, TRPR_SEQ,
    border_sz, ensure_child, half_points, mm_to_twips, parse, qn, serialize,
    set_child, top_level_tables,
)

A4_W, A4_H = 11906, 16838  # twips

# Моноширинные стили: если снять с них шрифт, код в документе станет Times.
MONO_STYLES = {"VerbatimChar", "SourceCode", "HTMLPreformatted", "Code", "MacroText"}

_THEME_ATTRS = ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme")


def _ensure_first(parent: ET.Element, tag: str) -> ET.Element:
    """tblPr, trPr, tcPr, pPr и rPr обязаны быть первым потомком своего элемента."""
    existing = parent.find(qn(tag))
    if existing is not None:
        return existing
    el = ET.Element(qn(tag))
    parent.insert(0, el)
    return el


def _force_rfonts(rpr: ET.Element, font: str) -> None:
    # Все четыре атрибута обязательны: кириллица резолвится через w:hAnsi,
    # а не через w:ascii (MS-OI29500 §17.3.2.26).
    set_child(rpr, "w:rFonts", RPR_SEQ, {
        "w:ascii": font, "w:hAnsi": font, "w:cs": font, "w:eastAsia": font,
    })


def _force_size(rpr: ET.Element, pt: float) -> None:
    value = half_points(pt)
    set_child(rpr, "w:sz", RPR_SEQ, {"w:val": value})
    set_child(rpr, "w:szCs", RPR_SEQ, {"w:val": value})


def enforce_fonts(styles: ET.Element, profile: Profile) -> None:
    doc_defaults = styles.find(qn("w:docDefaults"))
    if doc_defaults is not None:
        rpr_default = doc_defaults.find(qn("w:rPrDefault"))
        if rpr_default is None:
            rpr_default = ET.SubElement(doc_defaults, qn("w:rPrDefault"))
        rpr = rpr_default.find(qn("w:rPr"))
        if rpr is None:
            rpr = ET.SubElement(rpr_default, qn("w:rPr"))
        _force_rfonts(rpr, profile.font)
        _force_size(rpr, profile.font_size_pt)
        set_child(rpr, "w:lang", RPR_SEQ, {
            "w:val": profile.lang, "w:eastAsia": profile.lang,
        })

    # Стили с темой (Aptos) перебивают Normal. Снимаем у них шрифт, чтобы
    # осталась одна точка правды — docDefaults.
    for style in styles.findall(qn("w:style")):
        if style.get(qn("w:styleId")) in MONO_STYLES:
            continue
        rpr = style.find(qn("w:rPr"))
        if rpr is None:
            continue
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            continue
        if any(rfonts.get(qn(attr)) for attr in _THEME_ATTRS):
            rpr.remove(rfonts)


def enforce_page(document: ET.Element, profile: Profile) -> None:
    page = profile.page
    for sect in document.iter(qn("w:sectPr")):
        pg_sz = ensure_child(sect, "w:pgSz", SECTPR_SEQ)
        pg_sz.set(qn("w:w"), str(A4_W))
        pg_sz.set(qn("w:h"), str(A4_H))
        pg_mar = ensure_child(sect, "w:pgMar", SECTPR_SEQ)
        pg_mar.set(qn("w:top"), str(mm_to_twips(page.margin_top_mm)))
        pg_mar.set(qn("w:bottom"), str(mm_to_twips(page.margin_bottom_mm)))
        pg_mar.set(qn("w:left"), str(mm_to_twips(page.margin_left_mm)))
        pg_mar.set(qn("w:right"), str(mm_to_twips(page.margin_right_mm)))


def content_width(document: ET.Element, profile: Profile) -> int:
    """Ширина полосы набора в twips. Считается по профилю, а не по документу:
    поля к этому моменту уже принудительно выставлены."""
    page = profile.page
    return A4_W - mm_to_twips(page.margin_left_mm) - mm_to_twips(page.margin_right_mm)


def _distribute(raw: list[int], total: int) -> list[int]:
    base = sum(raw) or len(raw)
    widths = [max(1, round(total * value / base)) for value in raw]
    widths[-1] += total - sum(widths)
    return widths


def enforce_tables(document: ET.Element, profile: Profile, width: int) -> int:
    rules = profile.tables
    enforce = profile.enforce
    target = int(round(width * rules.width_percent / 100))
    touched = 0

    for tbl in top_level_tables(document):
        touched += 1
        tbl_pr = _ensure_first(tbl, "w:tblPr")

        if enforce.table_width:
            set_child(tbl_pr, "w:tblW", TBLPR_SEQ, {"w:type": "dxa", "w:w": str(target)})
            set_child(tbl_pr, "w:jc", TBLPR_SEQ, {"w:val": "center"})
            set_child(tbl_pr, "w:tblInd", TBLPR_SEQ, {"w:type": "dxa", "w:w": "0"})
            if not rules.allow_autofit:
                set_child(tbl_pr, "w:tblLayout", TBLPR_SEQ, {"w:type": "fixed"})

        if enforce.table_borders:
            borders = set_child(tbl_pr, "w:tblBorders", TBLPR_SEQ)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                el = ET.SubElement(borders, qn(f"w:{edge}"))
                el.set(qn("w:val"), "single")
                el.set(qn("w:sz"), border_sz(rules.border_pt))
                el.set(qn("w:space"), "0")
                el.set(qn("w:color"), rules.border_color)

        grid = tbl.find(qn("w:tblGrid"))
        widths: list[int] = []
        if grid is not None and enforce.table_width:
            cols = grid.findall(qn("w:gridCol"))
            if cols:
                raw = [int(float(c.get(qn("w:w")) or 0)) for c in cols]
                widths = _distribute(raw, target)
                for col, value in zip(cols, widths):
                    col.set(qn("w:w"), str(value))

        for index, row in enumerate(tbl.findall(qn("w:tr"))):
            _format_row(row, profile, widths, is_header=index == 0)

    return touched


def _format_row(row: ET.Element, profile: Profile, widths: list[int], is_header: bool) -> None:
    rules = profile.tables
    enforce = profile.enforce
    tr_pr = _ensure_first(row, "w:trPr")

    if enforce.table_header:
        set_child(tr_pr, "w:cantSplit", TRPR_SEQ, {"w:val": "true"})
        if is_header:
            set_child(tr_pr, "w:tblHeader", TRPR_SEQ, {"w:val": "true"})

    # Курсор по СЕТКЕ, а не по номеру ячейки: с w:gridSpan они расходятся,
    # и наивный enumerate даёт таблицу, уползающую вправо.
    grid_pos = 0
    grid_before = tr_pr.find(qn("w:gridBefore"))
    if grid_before is not None:
        grid_pos = int(grid_before.get(qn("w:val")) or 0)

    for cell in row.findall(qn("w:tc")):
        tc_pr = _ensure_first(cell, "w:tcPr")
        span_el = tc_pr.find(qn("w:gridSpan"))
        span = int(span_el.get(qn("w:val")) or 1) if span_el is not None else 1

        if widths and grid_pos < len(widths) and enforce.table_width:
            value = sum(widths[grid_pos:grid_pos + span])
            set_child(tc_pr, "w:tcW", TCPR_SEQ, {"w:type": "dxa", "w:w": str(value)})
        if enforce.table_header and rules.valign:
            set_child(tc_pr, "w:vAlign", TCPR_SEQ, {"w:val": rules.valign})
        grid_pos += span

        if not (is_header and enforce.table_header):
            continue
        for para in cell.findall(qn("w:p")):
            p_pr = _ensure_first(para, "w:pPr")
            if rules.header_center:
                # Снести существующий w:jc обязательно: pandoc переносит
                # выравнивание из |---:| и без замены шапка останется справа.
                set_child(p_pr, "w:jc", PPR_SEQ, {"w:val": "center"})
            if rules.header_bold:
                for run in para.findall(qn("w:r")):
                    r_pr = _ensure_first(run, "w:rPr")
                    set_child(r_pr, "w:b", RPR_SEQ, {"w:val": "true"})
                    set_child(r_pr, "w:bCs", RPR_SEQ, {"w:val": "true"})


def apply_profile(docx: bytes, profile: Profile,
                  source_date_epoch: int | None = None) -> bytes:
    with zipfile.ZipFile(io.BytesIO(docx)) as zin:
        names = zin.namelist()
        infos = {i.filename: i for i in zin.infolist()}
        blobs = {name: zin.read(name) for name in names}

    if "word/document.xml" in blobs:
        document, decl = parse(blobs["word/document.xml"])
        if profile.enforce.page:
            enforce_page(document, profile)
        enforce_tables(document, profile, content_width(document, profile))
        blobs["word/document.xml"] = serialize(document, decl)

    if profile.enforce.font and "word/styles.xml" in blobs:
        styles, decl = parse(blobs["word/styles.xml"])
        enforce_fonts(styles, profile)
        blobs["word/styles.xml"] = serialize(styles, decl)

    out = io.BytesIO()
    stamp = time.gmtime(source_date_epoch)[:6] if source_date_epoch is not None else None
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            src = infos[name]
            info = zipfile.ZipInfo(name, date_time=stamp or src.date_time)
            info.compress_type = src.compress_type
            info.external_attr = src.external_attr
            info.create_system = 0
            zout.writestr(info, blobs[name])
    return out.getvalue()
