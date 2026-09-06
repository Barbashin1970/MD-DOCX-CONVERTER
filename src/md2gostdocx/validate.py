"""Проверка Markdown до сборки (§4.8 ТЗ). Чистая функция, никакого ввода-вывода.

Существование картинок проверяется через переданный колбэк, чтобы модуль
оставался тестируемым и пригодным для режима, где файлов на диске нет.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from .models import Diagnostic, Level

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
_HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([A-Za-z0-9_+-]*)")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_DIV_OPEN_RE = re.compile(r"""^\s*<div\s+class\s*=\s*["']([\w-]+)["']\s*>\s*$""")


def _split_front_matter(text: str) -> tuple[dict[str, str], int]:
    """Возвращает поля YAML-заголовка и номер строки, где начинается тело."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, 0
    fields: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            return fields, i + 1
        key, sep, value = line.partition(":")
        if sep and not key.startswith(" "):
            fields[key.strip()] = value.strip().strip("\"'")
    return fields, 0


def _strip_inline_code(line: str) -> str:
    """Затереть код в обратных кавычках, сохранив длину строки и позиции.

    Без этого пример вида `![подпись](images/x.png)` в тексте документации
    считается настоящей картинкой — валидатор ругается на файл, которого
    и не должно быть.
    """
    return _INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)


def _cells(row: str) -> int:
    stripped = row.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    return len(re.split(r"(?<!\\)\|", stripped))


def validate(
    text: str,
    exists: Callable[[str], bool] | None = None,
    mermaid_rendered: bool = False,
) -> list[Diagnostic]:
    out: list[Diagnostic] = []
    front, _ = _split_front_matter(text)
    lines = text.splitlines()

    if not front.get("title"):
        out.append(Diagnostic("META001", Level.WARNING,
                              "В YAML-метаданных не заполнено поле title"))

    in_fence = False
    fence_marker = ""
    seen_h1 = False
    prev_level = 0
    table_widths: list[tuple[int, int]] = []

    for n, line in enumerate(lines, start=1):
        fence = _FENCE_RE.match(line)
        if fence:
            marker, lang = fence.group(1), (fence.group(2) or "").lower()
            if not in_fence:
                in_fence, fence_marker = True, marker[0] * 3
                if lang == "mermaid" and not mermaid_rendered:
                    out.append(Diagnostic(
                        "MMD001", Level.WARNING,
                        "Mermaid-диаграмма попадёт в DOCX текстом, а не рисунком: "
                        "нужен этап рендеринга", n))
            elif marker.startswith(fence_marker):
                in_fence = False
            continue
        if in_fence:
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                seen_h1 = True
            elif not seen_h1 and level > 1 and prev_level == 0:
                out.append(Diagnostic("HDR001", Level.WARNING,
                                      "Документ начинается не с раздела верхнего уровня", n))
            if prev_level and level > prev_level + 1:
                out.append(Diagnostic(
                    "HDR002", Level.WARNING,
                    f"Нарушена иерархия: после H{prev_level} идёт H{level}", n))
            prev_level = level
            continue

        # Пустая строка после <div class="…"> обязательна: без неё pandoc
        # складывает тег и содержимое в один сырой блок и выбрасывает его —
        # текст исчезает из DOCX бесследно. Перед </div> пустая строка не
        # нужна, это проверено: там всё работает.
        if _DIV_OPEN_RE.match(line):
            following = lines[n] if n < len(lines) else ""
            if following.strip():
                out.append(Diagnostic(
                    "HTML001", Level.ERROR,
                    "После открывающего <div class=…> нужна пустая строка, "
                    "иначе содержимое блока не попадёт в DOCX", n))

        for target in _IMAGE_RE.findall(_strip_inline_code(line)):
            if target.startswith(("http://", "https://", "data:")):
                continue
            if target.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", target):
                out.append(Diagnostic(
                    "IMG002", Level.ERROR,
                    f"Абсолютный путь к изображению: {target}. Такой файл попадёт "
                    "внутрь DOCX и уедет вместе с документом", n))
                continue
            if exists is not None and not exists(target):
                out.append(Diagnostic("IMG001", Level.ERROR,
                                      f"{target} не найден", n))

        if "|" in line and n < len(lines) and _TABLE_SEP_RE.match(lines[n] if n < len(lines) else ""):
            table_widths = [(n, _cells(line))]
        elif table_widths and "|" in line and not _TABLE_SEP_RE.match(line):
            width = _cells(line)
            if width != table_widths[0][1]:
                out.append(Diagnostic(
                    "TBL001", Level.WARNING,
                    f"В таблице разное число ячеек: {width} против "
                    f"{table_widths[0][1]} в шапке", n))
                table_widths = []
        elif table_widths and "|" not in line:
            table_widths = []

    if not seen_h1:
        out.append(Diagnostic("HDR001", Level.WARNING,
                              "Не найден раздел верхнего уровня (#)"))

    return out
