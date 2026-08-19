"""Folder Shortcuts application entry point."""

from foldershortcuts.app import FolderShortcutsApp


def main() -> None:
    app = FolderShortcutsApp()
    app.mainloop()


if __name__ == "__main__":
    main()
