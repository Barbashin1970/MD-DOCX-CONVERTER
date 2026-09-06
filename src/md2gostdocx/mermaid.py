"""Рендеринг Mermaid-диаграмм в PNG до вызова pandoc.

Почему PNG, а не SVG: mmdc по умолчанию кладёт подписи в foreignObject, и такой
SVG не понимают ни Word, ни rsvg-convert — картинка приедет без текста. PNG
растеризует сам Chromium, и проблема снимается целиком.

Почему широкий PNG: pandoc сам вписывает изображение в полосу набора, читая
pgSz и pgMar из reference.docx. Атрибут {width=90%} для этого не годится — он
работает только как ограничение сверху и на GitHub виден как мусорный текст.

Исходный код диаграммы остаётся в Markdown нетронутым: GitHub рендерит его сам.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .models import Diagnostic, Level

# Ширина в пикселях: чем больше, тем чётче в Word. 2000 px хватает для A4.
RENDER_WIDTH = 2000

_BLOCK_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>```+|~~~+)[ \t]*mermaid[^\n]*\n"
    r"(?P<body>.*?)^(?P=indent)(?P=fence)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)
_CAPTION_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")


def cache_dir() -> Path:
    """Кэш вне каталога пользователя: рендер диаграммы стоит секунды,
    а её содержимое между сборками обычно не меняется."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = base / "md2gostdocx" / "mermaid"
    path.mkdir(parents=True, exist_ok=True)
    return path


def find_mmdc() -> list[str] | None:
    """mmdc, установленный глобально или локально в проекте."""
    explicit = os.environ.get("MD2GOSTDOCX_MMDC")
    if explicit and Path(explicit).is_file():
        return [explicit]
    found = shutil.which("mmdc")
    if found:
        return [found]
    local = Path("node_modules/.bin/mmdc")
    if local.is_file():
        return [str(local.resolve())]
    return None


def _key(code: str) -> str:
    payload = f"{RENDER_WIDTH}\n{code}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def render(code: str, target: Path, mmdc: list[str], timeout: int = 120) -> str | None:
    """Отрисовать одну диаграмму. Возвращает текст ошибки или None при успехе."""
    with tempfile.TemporaryDirectory(prefix="mermaid-") as tmp:
        source = Path(tmp) / "diagram.mmd"
        source.write_text(code, encoding="utf-8")
        config = Path(tmp) / "puppeteer.json"
        # Без --no-sandbox Chromium не стартует в контейнерах и в части
        # корпоративных окружений.
        config.write_text('{"args":["--no-sandbox","--disable-dev-shm-usage"]}',
                          encoding="utf-8")
        cmd = [
            *mmdc,
            "-i", str(source),
            "-o", str(target),
            "-w", str(RENDER_WIDTH),
            "-b", "white",
            "-p", str(config),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired:
            return f"рендеринг не уложился в {timeout} с"
        except OSError as exc:
            return str(exc)
    if result.returncode != 0 or not target.is_file():
        return (result.stderr or result.stdout or "mmdc вернул ошибку").strip()[:400]
    return None


def _caption_before(text: str, start: int) -> str:
    """Подпись — жирный абзац непосредственно перед блоком, если он есть."""
    head = text[:start].rstrip("\n").splitlines()
    if not head:
        return ""
    match = _CAPTION_RE.match(head[-1].strip())
    return match.group(1) if match else ""


def preprocess(text: str, enabled: bool = True) -> tuple[str, list[Diagnostic]]:
    """Заменить mermaid-блоки на ссылки на отрисованные PNG.

    Возвращает изменённый markdown и диагностику. Если mmdc не установлен,
    текст остаётся как есть — сборка не падает, но пользователь предупреждён.
    """
    diagnostics: list[Diagnostic] = []
    blocks = list(_BLOCK_RE.finditer(text))
    if not blocks:
        return text, diagnostics

    if not enabled:
        return text, diagnostics

    mmdc = find_mmdc()
    if not mmdc:
        diagnostics.append(Diagnostic(
            "MMD002", Level.WARNING,
            f"Найдено диаграмм: {len(blocks)}, но mmdc не установлен — "
            "в DOCX они попадут текстом. Установка: npm i -g @mermaid-js/mermaid-cli",
        ))
        return text, diagnostics

    cache = cache_dir()
    pieces: list[str] = []
    cursor = 0
    number = 0

    for match in blocks:
        number += 1
        code = match.group("body")
        line = text.count("\n", 0, match.start()) + 1
        target = cache / f"{_key(code)}.png"

        if not target.is_file():
            error = render(code, target, mmdc)
            if error:
                diagnostics.append(Diagnostic(
                    "MMD003", Level.ERROR,
                    f"Не удалось отрисовать диаграмму: {error}", line))
                continue

        caption = _caption_before(text, match.start()) or f"Рисунок {number}"
        pieces.append(text[cursor:match.start()])
        pieces.append(f"![{caption}]({target.as_posix()})")
        cursor = match.end()
        diagnostics.append(Diagnostic(
            "MMD004", Level.INFO,
            f"Диаграмма отрисована в {target.name}", line))

    pieces.append(text[cursor:])
    return "".join(pieces), diagnostics
