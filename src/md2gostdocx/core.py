"""Ядро: markdown + профиль -> DOCX. Всё остальное — тонкие оболочки над ним."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from . import mermaid
from . import platform as plat
from . import postprocess
from .models import (
    BuildRequest, BuildResult, Diagnostic, Enforce, Level, PageRules, Profile, TableRules,
)

PROFILES_DIR = Path(__file__).parent / "profiles"


class ProfileNotFound(RuntimeError):
    pass


def list_profiles() -> list[tuple[str, str]]:
    out = []
    if PROFILES_DIR.is_dir():
        for d in sorted(PROFILES_DIR.iterdir()):
            meta = d / "profile.json"
            if meta.is_file():
                data = json.loads(meta.read_text(encoding="utf-8"))
                out.append((d.name, data.get("name", d.name)))
    return out


def load_profile(profile_id: str = "gost19", reference: Path | None = None) -> Profile:
    directory = PROFILES_DIR / profile_id
    meta = directory / "profile.json"
    if not meta.is_file():
        known = ", ".join(pid for pid, _ in list_profiles()) or "нет ни одного"
        raise ProfileNotFound(f"Профиль {profile_id!r} не найден. Доступны: {known}")
    data = json.loads(meta.read_text(encoding="utf-8"))

    ref_path = reference or (directory / "reference.docx")
    if not ref_path.is_file():
        raise ProfileNotFound(
            f"В профиле {profile_id!r} нет reference.docx ({ref_path}). "
            "Если пакет собран без него, DOCX получится без ГОСТ-стилей"
        )

    page = data.get("page", {})
    margins = page.get("margins_mm", {})
    tables = data.get("tables", {})
    enforce = data.get("enforce", {})
    pandoc = data.get("pandoc", {})

    return Profile(
        id=profile_id,
        name=data.get("name", profile_id),
        reference_docx=ref_path.read_bytes(),
        font=data.get("font", "Times New Roman"),
        font_size_pt=data.get("font_size_pt", 12),
        lang=data.get("lang", "ru-RU"),
        page=PageRules(
            size=page.get("size", "A4"),
            margin_top_mm=margins.get("top", 20),
            margin_bottom_mm=margins.get("bottom", 20),
            margin_left_mm=margins.get("left", 20),
            margin_right_mm=margins.get("right", 10),
        ),
        tables=TableRules(
            width_percent=tables.get("width_percent", 100),
            border_pt=tables.get("border_pt", 0.5),
            border_color=tables.get("border_color", "000000"),
            header_bold=tables.get("header_bold", True),
            header_center=tables.get("header_center", True),
            valign=tables.get("valign", "center"),
            allow_autofit=tables.get("allow_autofit", False),
        ),
        enforce=Enforce(
            font=enforce.get("font", True),
            page=enforce.get("page", True),
            table_width=enforce.get("table_width", True),
            table_borders=enforce.get("table_borders", True),
            table_header=enforce.get("table_header", True),
        ),
        pandoc_from=pandoc.get("from", "gfm"),
        pandoc_version=data.get("pandoc_version"),
        toc=pandoc.get("toc", True),
        toc_depth=pandoc.get("toc_depth", 3),
        toc_title=pandoc.get("toc_title", "Содержание"),
        lua_filters=tuple(str(directory / f) for f in pandoc.get("filters", [])),
    )


def _diagnostics_from_log(path: Path) -> list[Diagnostic]:
    if not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for entry in entries:
        if entry.get("verbosity") != "WARNING":
            continue
        out.append(Diagnostic(
            "PANDOC001", Level.WARNING,
            entry.get("message", entry.get("type", "предупреждение pandoc")),
        ))
    return out


def build(req: BuildRequest) -> BuildResult:
    pandoc = plat.require_pandoc()
    profile = req.profile

    # Диаграммы рисуются до pandoc: сам он кладёт mermaid-блок в DOCX текстом.
    markdown, diagnostics = mermaid.preprocess(req.markdown, req.render_mermaid)

    with tempfile.TemporaryDirectory(prefix="md2gostdocx-") as tmp:
        work = Path(tmp)
        source = work / "source.md"
        source.write_text(markdown, encoding="utf-8")
        reference = work / "reference.docx"
        reference.write_bytes(profile.reference_docx)
        output = work / "out.docx"
        log = work / "pandoc.json"

        cmd = [
            pandoc, str(source),
            f"--from={profile.pandoc_from}",
            "--to=docx",
            f"--reference-doc={reference}",
            f"--log={log}",
            f"--output={output}",
        ]
        # resource-path нужен, потому что исходник лежит во временном каталоге,
        # а картинки — рядом с настоящим файлом пользователя.
        if req.resource_dir:
            cmd.append(f"--resource-path={req.resource_dir}")
        for lua in profile.lua_filters:
            if Path(lua).is_file():
                cmd.append(f"--lua-filter={lua}")
        if profile.toc:
            cmd += [
                "--toc",
                f"--toc-depth={profile.toc_depth}",
                f"--metadata=toc-title={profile.toc_title}",
            ]

        env = dict(os.environ)
        if req.source_date_epoch is not None:
            env["SOURCE_DATE_EPOCH"] = str(req.source_date_epoch)
            env["TZ"] = "UTC"

        result = plat.run(cmd, env=env)
        diagnostics += _diagnostics_from_log(log)

        if result.returncode != 0 or not output.is_file():
            details = (result.stderr or result.stdout or "").strip()
            diagnostics.append(Diagnostic(
                "PANDOC002", Level.ERROR,
                f"pandoc завершился с кодом {result.returncode}: {details}",
            ))
            return BuildResult(b"", tuple(diagnostics), tuple(cmd))

        docx = postprocess.apply_profile(
            output.read_bytes(), profile, req.source_date_epoch,
        )

    return BuildResult(docx, tuple(diagnostics), tuple(cmd))
