#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Markdown → DOCX (Pandoc)"
PANDOC = shutil.which("pandoc") or "/opt/homebrew/bin/pandoc"


class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.resizable(True, False)
        self.minsize(760, 330)
        self.source_var = tk.StringVar()
        self.reference_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Выберите Markdown-файл и, при необходимости, DOCX-шаблон.")
        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=18)
        root.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="Конвертация Markdown в DOCX", font=("Helvetica", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8)
        )
        ttk.Label(
            root,
            text="Итоговый DOCX будет создан рядом с исходным .md-файлом и получит то же имя.",
            wraplength=700,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 18))

        ttk.Label(root, text="Исходный Markdown (.md):").grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.source_var).grid(row=2, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(root, text="Выбрать файл…", command=self.choose_source).grid(row=2, column=2, sticky="e", pady=6)

        ttk.Label(root, text="Пример / шаблон DOCX:").grid(row=3, column=0, sticky="w", pady=6)
        ttk.Entry(root, textvariable=self.reference_var).grid(row=3, column=1, sticky="ew", padx=10, pady=6)
        ttk.Button(root, text="Выбрать файл…", command=self.choose_reference).grid(row=3, column=2, sticky="e", pady=6)

        ttk.Label(
            root,
            text="Шаблон необязателен. Если выбрать DOCX, Pandoc возьмёт из него стили: Times New Roman, поля, заголовки, таблицы и колонтитулы.",
            foreground="#555555",
            wraplength=700,
        ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(4, 18))

        ttk.Separator(root).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Button(root, text="Создать DOCX", command=self.convert).grid(row=6, column=0, sticky="w")
        ttk.Label(root, textvariable=self.status_var, wraplength=530).grid(row=6, column=1, columnspan=2, sticky="w", padx=10)

        ttk.Label(
            root,
            text="Требование: Pandoc должен быть установлен. Проверка: pandoc --version",
            foreground="#666666",
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(18, 0))

    def choose_source(self):
        path = filedialog.askopenfilename(
            title="Выберите исходный Markdown-файл",
            filetypes=[("Markdown", "*.md *.markdown *.mdown *.mkdn"), ("Все файлы", "*.*")],
        )
        if path:
            self.source_var.set(path)
            source = Path(path)
            default_ref = source.parent / "gost19-reference.docx"
            if not self.reference_var.get() and default_ref.is_file():
                self.reference_var.set(str(default_ref))

    def choose_reference(self):
        path = filedialog.askopenfilename(
            title="Выберите пример или reference-шаблон DOCX",
            filetypes=[("Документ Word", "*.docx"), ("Все файлы", "*.*")],
        )
        if path:
            self.reference_var.set(path)

    def convert(self):
        source = Path(self.source_var.get().strip()).expanduser()
        reference_text = self.reference_var.get().strip()
        reference = Path(reference_text).expanduser() if reference_text else None

        if not source.is_file():
            messagebox.showerror(APP_TITLE, "Выберите существующий исходный Markdown-файл (.md).")
            return
        if source.suffix.lower() not in {".md", ".markdown", ".mdown", ".mkdn"}:
            proceed = messagebox.askyesno(APP_TITLE, "Файл не имеет расширение .md. Всё равно конвертировать как Markdown?")
            if not proceed:
                return
        if reference_text and not reference.is_file():
            messagebox.showerror(APP_TITLE, "Указанный пример / шаблон DOCX не найден.")
            return
        if not Path(PANDOC).is_file() and not shutil.which("pandoc"):
            messagebox.showerror(
                APP_TITLE,
                "Pandoc не найден. Откройте Terminal и проверьте командой:\n\npandoc --version",
            )
            return

        output = source.with_suffix(".docx")
        if output.exists():
            replace = messagebox.askyesno(
                APP_TITLE,
                f"Файл уже существует:\n{output.name}\n\nЗаменить его?",
            )
            if not replace:
                return

        pandoc_cmd = shutil.which("pandoc") or PANDOC
        command = [
            pandoc_cmd,
            str(source),
            "--from=gfm",
            "--standalone",
            f"--resource-path={source.parent}",
            "--output",
            str(output),
        ]
        if reference_text:
            command.extend(["--reference-doc", str(reference)])

        self.status_var.set("Выполняется конвертация…")
        self.update_idletasks()

        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Не удалось запустить Pandoc:\n{exc}")
            self.status_var.set("Ошибка запуска Pandoc.")
            return

        if result.returncode != 0:
            details = (result.stderr or result.stdout or "Pandoc завершился с ошибкой.").strip()
            messagebox.showerror(APP_TITLE, f"DOCX не создан.\n\n{details}")
            self.status_var.set("Конвертация завершилась с ошибкой.")
            return

        self.status_var.set(f"Готово: {output.name}")
        open_file = messagebox.askyesno(
            APP_TITLE,
            f"DOCX создан:\n{output}\n\nОткрыть его сейчас?",
        )
        if open_file:
            subprocess.run(["open", str(output)], check=False)


if __name__ == "__main__":
    try:
        app = ConverterApp()
        app.mainloop()
    except tk.TclError as exc:
        print(f"Не удалось открыть графический интерфейс: {exc}", file=sys.stderr)
        sys.exit(1)
