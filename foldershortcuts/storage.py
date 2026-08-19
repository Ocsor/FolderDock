"""JSON persistence for shortcuts and window settings."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import FolderShortcut


class Storage:
    def __init__(self, data_directory: Path | None = None) -> None:
        if data_directory is None:
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
            data_directory = base / "FolderShortcuts"
        self.data_directory = data_directory
        self.shortcuts_file = data_directory / "shortcuts.json"
        self.settings_file = data_directory / "settings.json"
        self.data_directory.mkdir(parents=True, exist_ok=True)
        self._ensure_file(self.shortcuts_file, [])
        self._ensure_file(self.settings_file, {})

    def load_shortcuts(self) -> list[FolderShortcut]:
        raw = self._read_json(self.shortcuts_file, [])
        if not isinstance(raw, list):
            return []
        shortcuts: list[FolderShortcut] = []
        for item in raw:
            shortcut = FolderShortcut.from_dict(item)
            if shortcut is not None:
                shortcuts.append(shortcut)
        return shortcuts

    def save_shortcuts(self, shortcuts: list[FolderShortcut]) -> None:
        self._write_json(self.shortcuts_file, [item.to_dict() for item in shortcuts])

    def load_settings(self) -> dict[str, Any]:
        raw = self._read_json(self.settings_file, {})
        return raw if isinstance(raw, dict) else {}

    def save_settings(self, settings: dict[str, Any]) -> None:
        self._write_json(self.settings_file, settings)

    @staticmethod
    def _ensure_file(path: Path, default: Any) -> None:
        if not path.exists():
            Storage._write_json(path, default)

    @staticmethod
    def _read_json(path: Path, default: Any) -> Any:
        try:
            with path.open("r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            # Keep a bad file untouched so it can be inspected or recovered.
            return default

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump(value, file, indent=2, ensure_ascii=False)
            file.write("\n")
        temporary.replace(path)
