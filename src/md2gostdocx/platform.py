"""Кросс-платформенные мелочи: где pandoc, чем открыть файл и папку.

Здесь собрано всё, что в исходном скрипте было прибито к macOS.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PANDOC_ENV = "MD2GOSTDOCX_PANDOC"

# Куда заглянуть, если PATH не содержит pandoc: типовые места установки.
_EXTRA_DIRS = (
    "/opt/homebrew/bin",
    "/usr/local/bin",
    r"C:\Program Files\Pandoc",
    r"C:\Program Files (x86)\Pandoc",
)


class PandocMissing(RuntimeError):
    pass


def find_pandoc() -> str | None:
    explicit = os.environ.get(PANDOC_ENV)
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("pandoc")
    if found:
        return found
    name = "pandoc.exe" if os.name == "nt" else "pandoc"
    for d in _EXTRA_DIRS:
        candidate = Path(d) / name
        if candidate.is_file():
            return str(candidate)
    return None


def require_pandoc() -> str:
    p = find_pandoc()
    if p:
        return p
    hint = (
        "winget install --id JohnMacFarlane.Pandoc"
        if os.name == "nt"
        else "brew install pandoc"
    )
    raise PandocMissing(f"pandoc не найден. Установите его: {hint}")


def run(cmd: list[str], env: dict[str, str] | None = None, timeout: int = 120):
    """Запуск с явным utf-8: без него на русской Windows stderr приходит кракозябрами."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=timeout,
        check=False,
    )


def pandoc_version(pandoc: str | None = None) -> str | None:
    exe = pandoc or find_pandoc()
    if not exe:
        return None
    r = run([exe, "--version"], timeout=20)
    if r.returncode != 0 or not r.stdout:
        return None
    first = r.stdout.splitlines()[0].strip()
    return first.split()[1] if first.lower().startswith("pandoc ") else first


def open_file(path: str | Path) -> None:
    path = str(path)
    if sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", path], check=False)


def reveal_in_folder(path: str | Path) -> None:
    p = Path(path)
    if sys.platform == "darwin":
        subprocess.run(["open", "-R", str(p)], check=False)
    elif os.name == "nt":
        subprocess.run(["explorer", "/select,", str(p)], check=False)
    else:
        subprocess.run(["xdg-open", str(p.parent)], check=False)


def has_font(name: str) -> bool:
    """Грубая проверка наличия шрифта. Нужна только для предпросмотра:
    в самом DOCX имя шрифта — просто строка, подставляет его Word у читателя."""
    dirs = [
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
        Path.home() / "Library/Fonts",
        Path(r"C:\Windows\Fonts"),
        Path("/usr/share/fonts"),
    ]
    needle = name.replace(" ", "").lower()
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            for f in d.rglob("*"):
                if f.suffix.lower() in {".ttf", ".otf", ".ttc"} and needle in f.stem.replace(" ", "").lower():
                    return True
        except OSError:
            continue
    return False
