#!/usr/bin/env python3
from pathlib import Path

def list_path(path: str = ".") -> None:
    """List the contents of a directory or display a single file."""
    target = Path(path).expanduser()

    if not target.exists():
        print(f"ls: path not found: {path}")
        return

    if target.is_file():
        print(target.name)
        return

    entries = [entry for entry in target.iterdir() if not entry.name.startswith(".")]
    entries.sort(key=lambda entry: (not entry.is_dir(), entry.name.lower()))

    for entry in entries:
        suffix = "/" if entry.is_dir() else ""
        print(f"{entry.name}{suffix}")
