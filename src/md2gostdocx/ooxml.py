"""Работа с OpenXML на стандартной библиотеке.

Два правила, за нарушение которых Word объявляет файл повреждённым:

1. Порядок дочерних элементов внутри tblPr/trPr/tcPr/rPr/pPr задан схемой
   ECMA-376. Простой append() его ломает, поэтому вставка идёт перед первым
   элементом-преемником, а не по фиксированному индексу.
2. Пустой Element в ElementTree ложен, поэтому `parent.find(x) or SubElement(...)`
   создаёт ВТОРОЙ элемент вместо использования существующего. Проверять надо
   строго `is None`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

_PREFIXES = {
    "w": W,
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "o": "urn:schemas-microsoft-com:office:office",
    "v": "urn:schemas-microsoft-com:vml",
    "w10": "urn:schemas-microsoft-com:office:word",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
}

_XMLNS_RE = re.compile(rb'xmlns(?::([A-Za-z0-9_.-]+))?="([^"]+)"')
_DECL_RE = re.compile(rb"^\s*(<\?xml[^>]*\?>)")

TBLPR_SEQ = (
    "w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual",
    "w:tblStyleRowBandSize", "w:tblStyleColBandSize", "w:tblW", "w:jc",
    "w:tblCellSpacing", "w:tblInd", "w:tblBorders", "w:shd", "w:tblLayout",
    "w:tblCellMar", "w:tblLook", "w:tblCaption", "w:tblDescription", "w:tblPrChange",
)
TRPR_SEQ = (
    "w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter",
    "w:cantSplit", "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc",
    "w:hidden", "w:ins", "w:del", "w:trPrChange",
)
TCPR_SEQ = (
    "w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders",
    "w:shd", "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign",
    "w:hideMark", "w:headers", "w:cellIns", "w:cellDel", "w:cellMerge", "w:tcPrChange",
)
RPR_SEQ = (
    "w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps",
    "w:strike", "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint",
    "w:noProof", "w:snapToGrid", "w:vanish", "w:webHidden", "w:color", "w:spacing",
    "w:w", "w:kern", "w:position", "w:sz", "w:szCs", "w:highlight", "w:u", "w:effect",
    "w:bdr", "w:shd", "w:fitText", "w:vertAlign", "w:rtl", "w:cs", "w:em", "w:lang",
    "w:eastAsianLayout", "w:specVanish", "w:oMath",
)
PPR_SEQ = (
    "w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr",
    "w:widowControl", "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs",
    "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap", "w:overflowPunct",
    "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN", "w:bidi", "w:adjustRightInd",
    "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing", "w:mirrorIndents",
    "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
    "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr",
    "w:sectPr", "w:pPrChange",
)
SECTPR_SEQ = (
    "w:footnotePr", "w:endnotePr", "w:type", "w:pgSz", "w:pgMar", "w:paperSrc",
    "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt", "w:vAlign",
    "w:noEndnote", "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
    "w:docGrid", "w:printerSettings", "w:sectPrChange",
)


def qn(tag: str) -> str:
    prefix, _, local = tag.partition(":")
    return f"{{{_PREFIXES[prefix]}}}{local}"


def parse(data: bytes) -> tuple[ET.Element, bytes]:
    """Разбор с сохранением префиксов пространств имён.

    Без регистрации ElementTree переименует их в ns0/ns1 — на документе с
    рисунками это ломает mc:Ignorable и ссылки r:embed.
    """
    head = data[:4000]
    for prefix, uri in _XMLNS_RE.findall(head):
        ET.register_namespace(prefix.decode() if prefix else "", uri.decode())
    decl_match = _DECL_RE.match(data)
    decl = decl_match.group(1) if decl_match else b'<?xml version="1.0" encoding="UTF-8"?>'
    return ET.fromstring(data), decl


def serialize(root: ET.Element, decl: bytes) -> bytes:
    return decl + b"\n" + ET.tostring(root, encoding="utf-8", xml_declaration=False)


def _successor_index(seq: tuple[str, ...], tag: str) -> int:
    try:
        return seq.index(tag)
    except ValueError:  # элемента нет в схеме — кладём в конец
        return len(seq)


def set_child(parent: ET.Element, tag: str, seq: tuple[str, ...],
              attrs: dict[str, str] | None = None) -> ET.Element:
    """Заменить (не дописать) элемент и поставить его на место по схеме.

    Замена, а не правка атрибутов: иначе у w:rFonts остаются w:hint и *Theme,
    которые молча перебивают то, что мы ставим.
    """
    for old in parent.findall(qn(tag)):
        parent.remove(old)
    el = ET.Element(qn(tag))
    for k, v in (attrs or {}).items():
        el.set(qn(k), v)
    idx = _successor_index(seq, tag)
    for sibling in list(parent):
        sib_tag = _tag_name(sibling)
        if sib_tag and _successor_index(seq, sib_tag) > idx:
            parent.insert(list(parent).index(sibling), el)
            return el
    parent.append(el)
    return el


def ensure_child(parent: ET.Element, tag: str, seq: tuple[str, ...]) -> ET.Element:
    existing = parent.find(qn(tag))
    if existing is not None:          # именно is None: пустой Element ложен
        return existing
    return set_child(parent, tag, seq)


def _tag_name(el: ET.Element) -> str | None:
    if not isinstance(el.tag, str) or "}" not in el.tag:
        return None
    uri, _, local = el.tag[1:].partition("}")
    for prefix, known in _PREFIXES.items():
        if known == uri:
            return f"{prefix}:{local}"
    return None


def child_order(parent: ET.Element) -> list[str]:
    return [t for t in (_tag_name(c) for c in parent) if t]


def top_level_tables(root: ET.Element) -> list[ET.Element]:
    """Только таблицы верхнего уровня: вложенную растягивать на всю страницу нельзя."""
    found: list[ET.Element] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == qn("w:tbl"):
                found.append(child)
            else:
                walk(child)

    walk(root)
    return found


def mm_to_twips(mm: float) -> int:
    return int(round(mm * 1440 / 25.4))


def border_sz(pt: float) -> str:
    """w:sz у границ — восьмые доли пункта: 0,5 pt = 4. Минимум Word — 2."""
    return str(max(2, int(round(pt * 8))))


def half_points(pt: float) -> str:
    """w:sz у шрифта — половины пункта: 12 pt = 24."""
    return str(int(round(pt * 2)))
