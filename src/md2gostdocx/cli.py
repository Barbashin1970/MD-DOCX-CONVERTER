"""Командная строка. Коды возврата — это интерфейс для CI и pre-commit,
менять их нельзя:

    0   успех
    1   есть предупреждения и передан --strict
    2   ошибки валидации Markdown
    3   pandoc вернул ненулевой код
    4   окружение сломано (нет pandoc, нет профиля)
    64  ошибка использования
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import platform as plat
from . import mermaid
from .core import ProfileNotFound, build, list_profiles, load_profile
from .doctor import run_checks, worst_level
from .models import BuildRequest, Diagnostic, Level
from .validate import validate

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_VALIDATION = 2
EXIT_PANDOC = 3
EXIT_ENVIRONMENT = 4
EXIT_USAGE = 64

MD_SUFFIXES = {".md", ".markdown", ".mdown", ".mkdn"}


def _report(path: Path, diagnostics: list[Diagnostic], fmt: str) -> None:
    if fmt == "json":
        print(json.dumps([{
            "file": str(path), "code": d.code, "level": d.level.value,
            "line": d.line, "message": d.message,
        } for d in diagnostics], ensure_ascii=False, indent=2))
        return
    for d in diagnostics:
        if fmt == "github":
            print(d.as_github(str(path)))
        else:
            print(d.as_text(str(path)))


def _validate_file(path: Path, mermaid_rendered: bool | None = None) -> list[Diagnostic]:
    text = path.read_text(encoding="utf-8")
    if mermaid_rendered is None:
        # Если mmdc есть, предупреждать про Mermaid не о чем.
        mermaid_rendered = mermaid.find_mmdc() is not None
    return validate(
        text,
        exists=lambda target: (path.parent / target).is_file(),
        mermaid_rendered=mermaid_rendered,
    )


def _collect(paths: list[str], recursive: bool) -> list[Path]:
    # Обход дерева делает сам инструмент: bash-глоб docs/**/*.md нерекурсивен
    # по умолчанию и молча пропускает файлы верхнего уровня.
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            if not recursive:
                print(f"{p} — каталог, нужен --recursive", file=sys.stderr)
                continue
            out += sorted(f for f in p.rglob("*") if f.suffix.lower() in MD_SUFFIXES)
        elif p.is_file():
            out.append(p)
        else:
            print(f"{p} не найден", file=sys.stderr)
    return out


def cmd_check(args: argparse.Namespace) -> int:
    files = _collect(args.paths, args.recursive)
    if not files:
        return EXIT_USAGE
    worst = EXIT_OK
    for path in files:
        diagnostics = _validate_file(path)
        _report(path, diagnostics, args.format)
        if any(d.level is Level.ERROR for d in diagnostics):
            worst = EXIT_VALIDATION
        elif args.strict and diagnostics and worst == EXIT_OK:
            worst = EXIT_WARNINGS
    return worst


def cmd_build(args: argparse.Namespace) -> int:
    source = Path(args.file).expanduser()
    if not source.is_file():
        print(f"Файл не найден: {source}", file=sys.stderr)
        return EXIT_USAGE

    try:
        profile = load_profile(
            args.profile,
            Path(args.reference).expanduser() if args.reference else None,
        )
    except ProfileNotFound as exc:
        print(exc, file=sys.stderr)
        return EXIT_ENVIRONMENT

    diagnostics = _validate_file(source)
    _report(source, diagnostics, args.format)
    if any(d.level is Level.ERROR for d in diagnostics):
        print("Сборка отменена: сначала исправьте ошибки", file=sys.stderr)
        return EXIT_VALIDATION

    out_dir = Path(args.out).expanduser() if args.out else source.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / (source.stem + ".docx")
    if output.exists() and not args.force:
        if sys.stdin.isatty():
            answer = input(f"{output.name} уже существует. Заменить? [д/Н]: ")
            if answer.strip().lower() not in {"д", "да", "y", "yes"}:
                return EXIT_OK
        else:
            print(f"{output} уже существует, нужен --force", file=sys.stderr)
            return EXIT_USAGE

    epoch = int(source.stat().st_mtime) if args.reproducible else None
    try:
        result = build(BuildRequest(
            markdown=source.read_text(encoding="utf-8"),
            profile=profile,
            resource_dir=str(source.parent),
            source_date_epoch=epoch,
            render_mermaid=not args.no_mermaid,
        ))
    except plat.PandocMissing as exc:
        print(exc, file=sys.stderr)
        return EXIT_ENVIRONMENT

    _report(source, list(result.diagnostics), args.format)
    if result.has_errors or not result.docx:
        return EXIT_PANDOC

    output.write_bytes(result.docx)
    print(f"Готово: {output}")
    if args.open:
        plat.open_file(output)
    if args.strict and (result.has_warnings or diagnostics):
        return EXIT_WARNINGS
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_checks(args.profile)
    if args.json:
        print(json.dumps([{
            "name": c.name, "ok": c.ok, "level": c.level.value,
            "detail": c.detail, "fix": c.fix,
        } for c in checks], ensure_ascii=False, indent=2))
    else:
        for c in checks:
            mark = "[ок]" if c.ok else ("[!]" if c.level is Level.WARNING else "[ошибка]")
            print(f"  {mark:9} {c.name}: {c.detail}")
            if c.fix and not c.ok:
                print(f"            → {c.fix}")
    return EXIT_ENVIRONMENT if worst_level(checks) is Level.ERROR else EXIT_OK


def cmd_profiles(_: argparse.Namespace) -> int:
    for profile_id, name in list_profiles():
        print(f"{profile_id}\t{name}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="md2gostdocx",
        description="Сборка DOCX из Markdown по профилям оформления ГОСТ 19",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=["text", "json", "github"], default="text")
    common.add_argument("--strict", action="store_true",
                        help="считать предупреждения поводом для ненулевого кода")

    b = sub.add_parser("build", parents=[common], help="собрать DOCX")
    b.add_argument("file")
    b.add_argument("--profile", default="gost19")
    b.add_argument("--reference", help="свой reference.docx вместо профильного")
    b.add_argument("--out", help="каталог результата (по умолчанию рядом с исходником)")
    b.add_argument("--reproducible", action="store_true",
                   help="фиксировать метки времени по дате исходного файла")
    b.add_argument("--force", action="store_true", help="перезаписать без вопроса")
    b.add_argument("--open", action="store_true", help="открыть результат")
    b.add_argument("--no-mermaid", action="store_true",
                   help="не рисовать диаграммы (оставить блоки текстом)")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("check", parents=[common], help="проверить Markdown")
    c.add_argument("paths", nargs="+")
    c.add_argument("--recursive", action="store_true")
    c.set_defaults(func=cmd_check)

    d = sub.add_parser("doctor", help="проверить окружение")
    d.add_argument("--profile", default="gost19")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)

    p = sub.add_parser("profiles", help="показать доступные профили")
    p.set_defaults(func=cmd_profiles)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
