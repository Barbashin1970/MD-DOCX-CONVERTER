"""Проверка окружения. Одна реализация на CLI, лаунчеры и веб-интерфейс.

В интернет не ходит: §8.2 обещает автономность, и проверка обновлений —
отдельное явное действие пользователя, а не побочный эффект запуска.
"""

from __future__ import annotations

import os
import platform as os_platform
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat
from .core import PROFILES_DIR, ProfileNotFound, list_profiles, load_profile
from .models import Level


@dataclass(frozen=True)
class Check:
    name: str
    level: Level
    ok: bool
    detail: str
    fix: str = ""


def _check_pandoc(expected: str | None) -> list[Check]:
    exe = plat.find_pandoc()
    if not exe:
        fix = ("winget install --id JohnMacFarlane.Pandoc"
               if os.name == "nt" else "brew install pandoc")
        return [Check("pandoc", Level.ERROR, False, "не найден", fix)]
    version = plat.pandoc_version(exe) or "версия не определилась"
    checks = [Check("pandoc", Level.INFO, True, f"{version} ({exe})")]
    if expected and version != expected:
        checks.append(Check(
            "версия pandoc", Level.WARNING, False,
            f"установлена {version}, профиль рассчитан на {expected}",
            "Вывод разных версий pandoc отличается: оформление может разойтись",
        ))
    return checks


def _check_profile(profile_id: str) -> list[Check]:
    try:
        profile = load_profile(profile_id)
    except ProfileNotFound as exc:
        return [Check("профиль", Level.ERROR, False, str(exc),
                      "Переустановите инструмент из собранного пакета")]
    size = len(profile.reference_docx)
    return [Check("профиль", Level.INFO, True,
                  f"{profile.name}: reference.docx на {size} байт")]


def _check_write_access(target: Path | None) -> list[Check]:
    directory = target or Path.cwd()
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".md2gostdocx-"):
            pass
        return [Check("права на запись", Level.INFO, True, str(directory))]
    except OSError as exc:
        return [Check("права на запись", Level.ERROR, False,
                      f"{directory}: {exc}", "Выберите другой каталог результата")]


def _check_font(name: str) -> list[Check]:
    if plat.has_font(name):
        return [Check("шрифт", Level.INFO, True, f"{name} установлен")]
    return [Check(
        "шрифт", Level.WARNING, False, f"{name} в системе не найден",
        "Для самого DOCX это не важно — имя шрифта в файле просто строка, "
        "и подставит его Word у читателя. Важно только для предпросмотра",
    )]


def run_checks(profile_id: str = "gost19", target: Path | None = None) -> list[Check]:
    profile = None
    try:
        profile = load_profile(profile_id)
    except ProfileNotFound:
        pass

    checks: list[Check] = [Check(
        "система", Level.INFO, True,
        f"{os_platform.system()} {os_platform.release()} "
        f"({os_platform.machine()}), Python {sys.version.split()[0]}",
    )]
    checks += _check_pandoc(profile.pandoc_version if profile else None)
    checks += _check_profile(profile_id)
    checks += _check_write_access(target)
    checks += _check_font(profile.font if profile else "Times New Roman")

    if not list_profiles():
        checks.append(Check(
            "профили", Level.ERROR, False,
            f"каталог {PROFILES_DIR} пуст",
            "Пакет собран без профилей — переустановите из колеса, а не из исходников",
        ))
    return checks


def worst_level(checks: list[Check]) -> Level:
    if any(c.level is Level.ERROR and not c.ok for c in checks):
        return Level.ERROR
    if any(c.level is Level.WARNING and not c.ok for c in checks):
        return Level.WARNING
    return Level.INFO
