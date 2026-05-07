from __future__ import annotations

import os
from pathlib import Path


class ProjectPickCancelled(RuntimeError):
    pass


class ProjectPickerUnavailable(RuntimeError):
    pass


def pick_project_folder(initial_dir: str | Path | None = None) -> Path:
    override = os.environ.get("AUTOCORE_PROJECT_PICKER_RESULT")
    if override:
        return Path(override).expanduser().resolve()

    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as error:  # pragma: no cover - platform dependent
        raise ProjectPickerUnavailable("Native folder picker is unavailable in this Python environment.") from error

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(
            initialdir=str(Path(initial_dir or Path.cwd()).expanduser()),
            title="Choose the project folder AutoCore should audit",
            mustexist=True,
        )
    finally:
        root.destroy()

    if not selected:
        raise ProjectPickCancelled("Project selection was cancelled.")
    return Path(selected).expanduser().resolve()
