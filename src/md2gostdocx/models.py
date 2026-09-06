"""Типы данных ядра. Ничего не читает и не пишет."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Level(str, Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class Diagnostic:
    """Сообщение валидатора или pandoc. Код стабилен и годится для grep."""

    code: str
    level: Level
    message: str
    line: int | None = None

    def as_text(self, path: str = "") -> str:
        where = f"{path}:{self.line}" if self.line else path
        head = f"{where}: " if where else ""
        return f"{head}{self.level.value} [{self.code}] {self.message}"

    def as_github(self, path: str) -> str:
        # Формат обязателен: пробел после команды, запятые только между полями.
        # Вариант "::error,file=..." GitHub печатает как обычный текст.
        cmd = "error" if self.level is Level.ERROR else "warning"
        line = self.line or 1
        return f"::{cmd} file={path},line={line},title={self.code}::{self.message}"


@dataclass(frozen=True)
class PageRules:
    size: str = "A4"
    margin_top_mm: float = 20
    margin_bottom_mm: float = 20
    margin_left_mm: float = 20
    margin_right_mm: float = 10


@dataclass(frozen=True)
class TableRules:
    width_percent: float = 100
    border_pt: float = 0.5
    border_color: str = "000000"
    header_bold: bool = True
    header_center: bool = True
    valign: str = "center"
    allow_autofit: bool = False


@dataclass(frozen=True)
class Enforce:
    """Что профиль правит принудительно (§6.2 ТЗ)."""

    font: bool = True
    page: bool = True
    table_width: bool = True
    table_borders: bool = True
    table_header: bool = True


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    reference_docx: bytes
    font: str = "Times New Roman"
    font_size_pt: float = 12
    lang: str = "ru-RU"
    page: PageRules = field(default_factory=PageRules)
    tables: TableRules = field(default_factory=TableRules)
    enforce: Enforce = field(default_factory=Enforce)
    pandoc_from: str = "gfm"
    pandoc_version: str | None = None
    toc: bool = True
    toc_depth: int = 3
    toc_title: str = "Содержание"
    lua_filters: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuildRequest:
    markdown: str
    profile: Profile
    resource_dir: str | None = None
    source_date_epoch: int | None = None
    render_mermaid: bool = True


@dataclass(frozen=True)
class BuildResult:
    docx: bytes
    diagnostics: tuple[Diagnostic, ...] = ()
    pandoc_command: tuple[str, ...] = ()

    @property
    def has_errors(self) -> bool:
        return any(d.level is Level.ERROR for d in self.diagnostics)

    @property
    def has_warnings(self) -> bool:
        return any(d.level is Level.WARNING for d in self.diagnostics)
