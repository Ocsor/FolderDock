# FolderDock

FolderDock is a compact Windows desktop utility for keeping a temporary,
ordered list of local and network folders. Open saved folders in File Explorer,
copy their paths, rename or reorder shortcuts, and remove shortcuts without ever
changing the folders themselves.

## Features

- Drag folders from File Explorer onto the Shortcuts or Clients tab
- Organize saved folders across Shortcuts, Clients, and Archive
- Open from the compact action menu or by double-clicking a shortcut row
- Right-click to open, copy the full path, rename, reorder, or remove a shortcut
- Drag shortcut rows into the preferred order; the order is saved automatically
- Archive shortcuts to remove them from the main list, then restore them from the
  Archive tab whenever they are needed again
- Non-blocking availability checks at startup and whenever a folder is opened
- JSON persistence in `%APPDATA%\FolderShortcuts`
- Remembers window size, position, and the Always on Top setting
- Light and dark modes with a remembered Dark Mode toggle

Removing an item removes only its entry from the app. FolderDock never
deletes or modifies the target folder.

## Install and run

Python 3.10 or newer is recommended. In Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
```

`tkinterdnd2` is the lightweight dependency used for drag-and-drop. The app
detects it at runtime, so all other features continue to work if that package is
not installed. To deliberately omit drag-and-drop, install only CustomTkinter:

```powershell
pip install customtkinter
```

## Local data

The app creates these files automatically:

- `%APPDATA%\FolderShortcuts\shortcuts.json` — friendly names, paths, order, and
  Clients membership, and archive state
- `%APPDATA%\FolderShortcuts\settings.json` — window geometry, appearance, and
  Always on Top

Malformed JSON is handled safely: the app starts with defaults and leaves the
malformed file untouched so it can be inspected or recovered.

## Package a Windows executable

Install PyInstaller in the active virtual environment, then build from the
project root:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --noconsole --onefile --name FolderDock --icon "Logo/FolderDock.png" --collect-all customtkinter --collect-all tkinterdnd2 --add-data "Logo/FolderDock.png;Logo" main.py
```

The executable is created at `dist\FolderDock.exe`. It uses the same
`%APPDATA%\FolderShortcuts` data directory as the Python version. If
drag-and-drop was intentionally omitted, leave out `--collect-all tkinterdnd2`.

## Project layout

```text
main.py                     Application entry point
foldershortcuts/app.py      CustomTkinter interface and Windows integration
foldershortcuts/models.py   Shortcut model and naming helper
foldershortcuts/storage.py  JSON persistence
tests/                      Storage and model tests
```

Run the automated tests with:

```powershell
python -m unittest discover -s tests -v
```
