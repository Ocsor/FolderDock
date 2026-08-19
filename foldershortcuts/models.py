"""Data models used by Folder Shortcuts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PureWindowsPath
from typing import Any


@dataclass(slots=True)
class FolderShortcut:
    name: str
    path: str
    archived: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> FolderShortcut | None:
        if not isinstance(value, dict):
            return None
        name = value.get("name")
        path = value.get("path")
        if not isinstance(name, str) or not isinstance(path, str):
            return None
        name, path = name.strip(), path.strip()
        archived = value.get("archived", False)
        if not isinstance(archived, bool):
            archived = False
        return cls(name=name, path=path, archived=archived) if name and path else None


def default_shortcut_name(path: str) -> str:
    """Return a useful display name for local and UNC Windows paths."""
    cleaned = path.strip().rstrip("\\/")
    if not cleaned:
        return path.strip() or "Folder"
    name = PureWindowsPath(cleaned).name
    return name or cleaned
