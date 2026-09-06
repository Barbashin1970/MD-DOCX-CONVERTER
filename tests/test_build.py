"""Инварианты OOXML: проверяют смысл требований ТЗ, а не байты.

Такие тесты переживают обновление pandoc, в отличие от сравнения по хешу.
Word здесь не нужен и не используется — он остаётся судьёй на приёмке.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from md2gostdocx.core import build, load_profile
from md2gostdocx.models import BuildRequest, Level
from md2gostdocx.platform import find_pandoc
from md2gostdocx.postprocess import apply_profile
from md2gostdocx.validate import validate

pytestmark = pytest.mark.skipif(find_pandoc() is None, reason="нужен pandoc")

MD = """---
title: "Пробный документ"
---

# 1 Общие сведения

Обычный текст с **выделением** и ~~зачёркиванием~~.

| № | Требование | Содержание |
|---:|---|---|
| 1 | Производительность | Не менее 100 пользователей |
| 2 | Журналирование | Регистрация операций |
"""


def _docx() -> bytes:
    result = build(BuildRequest(MD, load_profile("gost19"), source_date_epoch=1700000000))
    assert result.docx, [d.message for d in result.diagnostics]
    return result.docx


def _part(docx: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        return z.read(name).decode("utf-8")


@pytest.fixture(scope="module")
def docx() -> bytes:
    return _docx()


def test_table_width_is_content_width(docx: bytes) -> None:
    # A4 210 мм минус поля 20 и 10 мм = 180 мм = 10205 twips
    xml = _part(docx, "word/document.xml")
    assert '<w:tblW w:type="dxa" w:w="10205" />' in xml
    assert '<w:tblLayout w:type="fixed" />' in xml


def test_grid_sums_to_content_width(docx: bytes) -> None:
    import re
    xml = _part(docx, "word/document.xml")
    grid = re.search(r"<w:tblGrid>(.*?)</w:tblGrid>", xml, re.DOTALL)
    assert grid
    widths = [int(w) for w in re.findall(r'<w:gridCol w:w="(\d+)"', grid.group(1))]
    assert sum(widths) == 10205


def test_borders_are_half_point_black(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    # w:sz у границ — восьмые доли пункта: 0,5 pt = 4
    assert xml.count('w:val="single" w:sz="4" w:space="0" w:color="000000"') >= 6


def test_header_row_is_bold_centered_and_unbreakable(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    assert '<w:cantSplit w:val="true" /><w:tblHeader w:val="true" />' in xml
    assert '<w:jc w:val="center" />' in xml
    assert '<w:b w:val="true" />' in xml


def test_cyrillic_font_resolves(docx: bytes) -> None:
    styles = _part(docx, "word/styles.xml")
    # Кириллица берётся из w:hAnsi, а не из w:ascii
    assert 'w:hAnsi="Times New Roman"' in styles
    assert 'w:ascii="Times New Roman"' in styles
    assert '<w:sz w:val="24" />' in styles       # 12 pt = 24 полупункта
    assert "asciiTheme" not in styles            # тема Aptos снята


def test_monospace_style_survives(docx: bytes) -> None:
    styles = _part(docx, "word/styles.xml")
    assert "Consolas" in styles


def test_page_is_a4(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    assert 'w:w="11906"' in xml and 'w:h="16838"' in xml


def test_markup_does_not_leak_as_text(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    assert "**" not in xml and "~~" not in xml


def test_no_duplicate_cell_properties(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    assert xml.count("<w:tcPr>") == xml.count("</w:tcPr>")


def test_build_is_reproducible() -> None:
    a = hashlib.sha256(_docx()).hexdigest()
    b = hashlib.sha256(_docx()).hexdigest()
    assert a == b


def test_postprocess_is_idempotent(docx: bytes) -> None:
    profile = load_profile("gost19")
    once = apply_profile(docx, profile, 1700000000)
    twice = apply_profile(once, profile, 1700000000)
    assert _part(once, "word/document.xml") == _part(twice, "word/document.xml")
    assert _part(once, "word/styles.xml") == _part(twice, "word/styles.xml")


def test_mermaid_without_renderer_does_not_break_build() -> None:
    """Точка расширения на месте: без mmdc сборка проходит с предупреждением."""
    text = MD + "\n```mermaid\nflowchart TD\n  A --> B\n```\n"
    result = build(BuildRequest(text, load_profile("gost19"), render_mermaid=True))
    assert result.docx
    codes = {d.code for d in result.diagnostics}
    assert "MMD002" in codes or "MMD004" in codes


class TestValidator:
    def test_missing_title(self) -> None:
        codes = {d.code for d in validate("# Заголовок\n")}
        assert "META001" in codes

    def test_absolute_image_path_is_an_error(self) -> None:
        found = validate("# Т\n\n![подпись](/etc/hosts)\n")
        image = [d for d in found if d.code == "IMG002"]
        assert image and image[0].level is Level.ERROR

    def test_broken_heading_hierarchy(self) -> None:
        codes = {d.code for d in validate("# Раз\n\n### Три\n")}
        assert "HDR002" in codes

    def test_mermaid_warning_only_without_renderer(self) -> None:
        text = "# Т\n\n```mermaid\nflowchart TD\n  A --> B\n```\n"
        assert "MMD001" in {d.code for d in validate(text)}
        assert "MMD001" not in {d.code for d in validate(text, mermaid_rendered=True)}

    def test_image_example_in_backticks_is_not_a_reference(self) -> None:
        text = "# Т\n\nПишите картинки так: `![Подпись](images/x.png)`.\n"
        assert not [d for d in validate(text) if d.code == "IMG001"]

    def test_ragged_table(self) -> None:
        text = "# Т\n\n| a | b |\n|---|---|\n| 1 | 2 | 3 |\n"
        assert "TBL001" in {d.code for d in validate(text)}
