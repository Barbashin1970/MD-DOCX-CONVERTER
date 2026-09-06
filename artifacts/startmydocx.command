#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/md_to_docx_gui.py"

if [ ! -f "$PYTHON_SCRIPT" ]; then
  osascript -e 'display alert "Не найден файл md_to_docx_gui.py" message "Поместите startmydocx.command и md_to_docx_gui.py в одну папку."'
  exit 1
fi

python3 "$PYTHON_SCRIPT"
