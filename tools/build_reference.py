#!/usr/bin/env python3
"""Настройка reference.docx профиля: стили, страница, семантические блоки.

Почему кодом, а не руками в Word: результат воспроизводим, виден в git-дифе
через textconv и проверяется тестом. Word остаётся судьёй на приёмке, но не
инструментом правки.

Скрипт идемпотентен — повторный запуск не меняет файл.

    python3 tools/build_reference.py [--profile gost19]
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from md2gostdocx.core import load_profile  # noqa: E402
from md2gostdocx.ooxml import (  # noqa: E402
    PPR_SEQ, RPR_SEQ, SECTPR_SEQ, TBLPR_SEQ, border_sz, half_points,
    mm_to_twips, parse, qn, serialize, set_child,
)
from md2gostdocx.postprocess import A4_H, A4_W  # noqa: E402

# Семантические блоки для ТЗ. Имена стилей должны совпадать с тем, что
# подставляют lua-фильтры: pandoc резолвит custom-style по w:name, а для
# стилей таблиц вообще не создаёт заглушку — они обязаны быть здесь заранее.
BLOCK_STYLES = (
    ("Requirement", "Requirement", {"bold": False, "italic": False, "bar": "404040"}),
    ("Term", "Term", {"bold": False, "italic": False, "bar": "808080"}),
    ("Note", "Note", {"bold": False, "italic": True, "bar": "808080"}),
    ("Tip", "Tip", {"bold": False, "italic": True, "bar": "607080"}),
    ("Important", "Important", {"bold": True, "italic": False, "bar": "404040"}),
    ("Warning", "Warning", {"bold": True, "italic": False, "bar": "000000"}),
    ("Caution", "Caution", {"bold": True, "italic": False, "bar": "000000"}),
)
TABLE_STYLES = (("RequirementsTable", "Requirements Table"),
                ("TermsTable", "Terms Table"))


def _style(styles: ET.Element, style_id: str) -> ET.Element | None:
    for style in styles.findall(qn("w:style")):
        if style.get(qn("w:styleId")) == style_id:
            return style
    return None


def _drop(styles: ET.Element, style_id: str) -> None:
    existing = _style(styles, style_id)
    if existing is not None:
        styles.remove(existing)


def _borders(parent: ET.Element, pt: float, color: str) -> None:
    borders = set_child(parent, "w:tblBorders", TBLPR_SEQ)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = ET.SubElement(borders, qn(f"w:{edge}"))
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), border_sz(pt))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)


def configure_page(document: ET.Element, profile) -> None:
    page = profile.page
    for sect in document.iter(qn("w:sectPr")):
        pg_sz = set_child(sect, "w:pgSz", SECTPR_SEQ, {
            "w:w": str(A4_W), "w:h": str(A4_H), "w:orient": "portrait",
        })
        assert pg_sz is not None
        set_child(sect, "w:pgMar", SECTPR_SEQ, {
            "w:top": str(mm_to_twips(page.margin_top_mm)),
            "w:bottom": str(mm_to_twips(page.margin_bottom_mm)),
            "w:left": str(mm_to_twips(page.margin_left_mm)),
            "w:right": str(mm_to_twips(page.margin_right_mm)),
            "w:header": "360", "w:footer": "360",
        })


def configure_defaults(styles: ET.Element, profile) -> None:
    defaults = styles.find(qn("w:docDefaults"))
    if defaults is None:
        defaults = ET.Element(qn("w:docDefaults"))
        styles.insert(0, defaults)
    run_default = defaults.find(qn("w:rPrDefault"))
    if run_default is None:
        run_default = ET.SubElement(defaults, qn("w:rPrDefault"))
    rpr = run_default.find(qn("w:rPr"))
    if rpr is None:
        rpr = ET.SubElement(run_default, qn("w:rPr"))

    # Четыре атрибута обязательны: кириллица резолвится через w:hAnsi.
    set_child(rpr, "w:rFonts", RPR_SEQ, {
        "w:ascii": profile.font, "w:hAnsi": profile.font,
        "w:cs": profile.font, "w:eastAsia": profile.font,
    })
    size = half_points(profile.font_size_pt)
    set_child(rpr, "w:sz", RPR_SEQ, {"w:val": size})
    set_child(rpr, "w:szCs", RPR_SEQ, {"w:val": size})
    # Иначе Word подчёркивает весь русский текст как ошибки.
    set_child(rpr, "w:lang", RPR_SEQ, {
        "w:val": profile.lang, "w:eastAsia": profile.lang,
    })


def configure_table_style(styles: ET.Element, style_id: str, name: str, profile) -> None:
    _drop(styles, style_id)
    style = ET.SubElement(styles, qn("w:style"))
    style.set(qn("w:type"), "table")
    style.set(qn("w:styleId"), style_id)
    if style_id == "Table":
        style.set(qn("w:default"), "1")
    ET.SubElement(style, qn("w:name")).set(qn("w:val"), name)
    if style_id != "Table":
        ET.SubElement(style, qn("w:basedOn")).set(qn("w:val"), "Table")
    ET.SubElement(style, qn("w:qFormat"))

    tbl_pr = ET.SubElement(style, qn("w:tblPr"))
    _borders(tbl_pr, profile.tables.border_pt, profile.tables.border_color)
    margins = set_child(tbl_pr, "w:tblCellMar", TBLPR_SEQ)
    for edge, value in (("top", "28"), ("left", "108"), ("bottom", "28"), ("right", "108")):
        el = ET.SubElement(margins, qn(f"w:{edge}"))
        el.set(qn("w:w"), value)
        el.set(qn("w:type"), "dxa")

    # Шапка: полужирная, по центру, вертикально по центру.
    first_row = ET.SubElement(style, qn("w:tblStylePr"))
    first_row.set(qn("w:type"), "firstRow")
    row_ppr = ET.SubElement(first_row, qn("w:pPr"))
    set_child(row_ppr, "w:jc", PPR_SEQ, {"w:val": "center"})
    row_rpr = ET.SubElement(first_row, qn("w:rPr"))
    set_child(row_rpr, "w:b", RPR_SEQ, {"w:val": "true"})
    set_child(row_rpr, "w:bCs", RPR_SEQ, {"w:val": "true"})
    row_tcpr = ET.SubElement(first_row, qn("w:tcPr"))
    ET.SubElement(row_tcpr, qn("w:vAlign")).set(qn("w:val"), "center")


def configure_block_style(styles: ET.Element, style_id: str, name: str, look: dict) -> None:
    _drop(styles, style_id)
    style = ET.SubElement(styles, qn("w:style"))
    style.set(qn("w:type"), "paragraph")
    style.set(qn("w:styleId"), style_id)
    ET.SubElement(style, qn("w:name")).set(qn("w:val"), name)
    ET.SubElement(style, qn("w:basedOn")).set(qn("w:val"), "BodyText")
    ET.SubElement(style, qn("w:qFormat"))

    ppr = ET.SubElement(style, qn("w:pPr"))
    borders = set_child(ppr, "w:pBdr", PPR_SEQ)
    left = ET.SubElement(borders, qn("w:left"))
    left.set(qn("w:val"), "single")
    left.set(qn("w:sz"), "18")
    left.set(qn("w:space"), "8")
    left.set(qn("w:color"), look["bar"])
    set_child(ppr, "w:ind", PPR_SEQ, {"w:left": "284"})
    set_child(ppr, "w:keepLines", PPR_SEQ, {"w:val": "true"})

    rpr = ET.SubElement(style, qn("w:rPr"))
    if look["bold"]:
        set_child(rpr, "w:b", RPR_SEQ, {"w:val": "true"})
        set_child(rpr, "w:bCs", RPR_SEQ, {"w:val": "true"})
    if look["italic"]:
        set_child(rpr, "w:i", RPR_SEQ, {"w:val": "true"})
        set_child(rpr, "w:iCs", RPR_SEQ, {"w:val": "true"})


def rebuild(path: Path, profile) -> None:
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        infos = {i.filename: i for i in zin.infolist()}
        blobs = {name: zin.read(name) for name in names}

    document, doc_decl = parse(blobs["word/document.xml"])
    configure_page(document, profile)
    blobs["word/document.xml"] = serialize(document, doc_decl)

    styles, styles_decl = parse(blobs["word/styles.xml"])
    configure_defaults(styles, profile)
    configure_table_style(styles, "Table", "Table", profile)
    for style_id, name in TABLE_STYLES:
        configure_table_style(styles, style_id, name, profile)
    for style_id, name, look in BLOCK_STYLES:
        configure_block_style(styles, style_id, name, look)
    blobs["word/styles.xml"] = serialize(styles, styles_decl)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            src = infos[name]
            info = zipfile.ZipInfo(name, date_time=src.date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = src.external_attr
            info.create_system = 0
            zout.writestr(info, blobs[name])
    path.write_bytes(buffer.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="gost19")
    args = parser.parse_args()

    profile = load_profile(args.profile)
    target = (Path(__file__).resolve().parents[1]
              / "src/md2gostdocx/profiles" / args.profile / "reference.docx")
    rebuild(target, profile)
    print(f"{target}: A4, {profile.font} {profile.font_size_pt} pt, "
          f"границы {profile.tables.border_pt} pt, "
          f"стили {', '.join(s[0] for s in BLOCK_STYLES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
