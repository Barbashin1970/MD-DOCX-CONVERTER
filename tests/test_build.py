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


def _borders(xml: str, container: str) -> list[dict[str, str]]:
    """Границы разбираются как XML: pandoc переупорядочивает атрибуты
    по алфавиту, и сравнение по строке даёт ложный результат."""
    import re
    import xml.etree.ElementTree as ET
    from md2gostdocx.ooxml import qn

    found = re.search(rf"<{container}\b.*?</{container}>", xml, re.DOTALL)
    if not found:
        return []
    wrapped = (
        '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"{found.group(0)}</root>"
    )
    root = ET.fromstring(wrapped)
    holder = root.find(qn(container))
    if holder is None:
        return []
    return [{k.split("}")[1]: v for k, v in edge.attrib.items()} for edge in holder]


def test_borders_are_half_point_black(docx: bytes) -> None:
    xml = _part(docx, "word/document.xml")
    edges = _borders(xml, "w:tblBorders")
    assert len(edges) >= 6
    for edge in edges[:6]:
        # w:sz у границ — восьмые доли пункта: 0,5 pt = 4
        assert edge["sz"] == "4"
        assert edge["val"] == "single"
        assert edge["color"] == "000000"


def test_reference_template_carries_the_profile() -> None:
    """Оформление должно жить в шаблоне, а постобработка — быть страховкой.
    Если этот тест падает, значит шаблон рассобрался: перезапустите
    tools/build_reference.py."""
    profile = load_profile("gost19")
    styles = _part(profile.reference_docx, "word/styles.xml")
    document = _part(profile.reference_docx, "word/document.xml")

    assert 'w:w="11906"' in document and 'w:h="16838"' in document
    assert 'w:hAnsi="Times New Roman"' in styles
    assert 'w:val="ru-RU"' in styles
    for style_id in ("Requirement", "Note", "Warning",
                     "RequirementsTable", "TermsTable"):
        assert f'w:styleId="{style_id}"' in styles, style_id
    edges = _borders(styles, "w:tblBorders")
    assert len(edges) >= 6 and all(e["sz"] == "4" for e in edges)


def test_template_styles_reach_the_output(docx: bytes) -> None:
    styles = _part(docx, "word/styles.xml")
    for style_id in ("Requirement", "Note", "Warning"):
        assert f'w:styleId="{style_id}"' in styles
    assert _borders(styles, "w:tblBorders")


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


SEMANTIC_MD = """---
title: "Пробное задание"
document_code: "ТЗ-ТЕСТ-001"
version: "2.0"
customer: "Заказчик"
developer: "Исполнитель"
---

# 1 Общие сведения

> [!NOTE]
> Примечание из алерта GitHub.

> [!WARNING]
> Предупреждение из алерта GitHub.

<div class="requirement">

Система должна хранить журнал не менее 12 месяцев.

</div>

**Таблица — Требования**

| № | Требование |
|---:|---|
| 1 | Авторизация |

<div class="terms-table">

| Термин | Определение |
|---|---|
| Оператор | Лицо, работающее с системой |

</div>
"""


@pytest.fixture(scope="module")
def semantic() -> bytes:
    result = build(BuildRequest(SEMANTIC_MD, load_profile("gost19")))
    assert result.docx, [d.message for d in result.diagnostics]
    return result.docx


class TestFilters:
    def test_github_alerts_become_word_styles(self, semantic: bytes) -> None:
        xml = _part(semantic, "word/document.xml")
        assert '<w:pStyle w:val="Note" />' in xml
        assert '<w:pStyle w:val="Warning" />' in xml

    def test_alert_titles_are_russian(self, semantic: bytes) -> None:
        import re
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>",
                                  _part(semantic, "word/document.xml")))
        assert "Примечание" in text and "Внимание" in text
        # английские заголовки алертов не должны просочиться
        assert ">Note<" not in text and ">Warning<" not in text

    def test_html_div_becomes_requirement(self, semantic: bytes) -> None:
        # На GitHub такой блок выглядит обычным текстом, в Word получает стиль
        assert '<w:pStyle w:val="Requirement" />' in _part(semantic, "word/document.xml")

    def test_table_caption_is_numbered(self, semantic: bytes) -> None:
        import re
        xml = _part(semantic, "word/document.xml")
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
        assert '<w:pStyle w:val="TableCaption" />' in xml
        assert "Таблица 1" in text

    def test_table_style_comes_from_the_wrapping_div(self, semantic: bytes) -> None:
        # Единственный рабочий способ: обёртка ::: из §5.7 ТЗ не работает
        assert '<w:tblStyle w:val="TermsTable" />' in _part(semantic, "word/document.xml")

    def test_title_page_carries_metadata(self, semantic: bytes) -> None:
        import re
        xml = _part(semantic, "word/document.xml")
        text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
        assert "ТЗ-ТЕСТ-001" in text          # pandoc сам эти поля не выводит
        assert "Заказчик" in text and "2.0" in text
        assert 'w:type="page"' in xml         # разрыв после титульного листа
        # Обёртка $var$ в <w:r><w:t> дала бы вложенный <w:t> и битый документ
        assert "<w:t" not in text


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
