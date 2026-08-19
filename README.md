# Folder Shortcuts

Folder Shortcuts is a compact Windows desktop utility for keeping a temporary,
ordered list of local and network folders. Open saved folders in File Explorer,
copy their paths, rename or reorder shortcuts, and remove shortcuts without ever
changing the folders themselves.

## Features

- Add folders with the Windows folder picker or paste a UNC path such as
  `\\SERVER\Jobs\12345`
- Drag folders from File Explorer onto the window
- Open with the button or by double-clicking a shortcut row
- Right-click to open, copy the full path, rename, reorder, or remove a shortcut
- Drag shortcut rows into the preferred order; the order is saved automatically
- Archive shortcuts to remove them from the main list, then restore them from the
  Archive tab whenever they are needed again
- Non-blocking availability checks at startup, on open, and on manual refresh
- JSON persistence in `%APPDATA%\FolderShortcuts`
- Remembers window size, position, and the Always on Top setting
- Follows the Windows light/dark appearance setting

Removing an item removes only its entry from the app. Folder Shortcuts never
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
  archive state
- `%APPDATA%\FolderShortcuts\settings.json` — window geometry and Always on Top

Malformed JSON is handled safely: the app starts with defaults and leaves the
malformed file untouched so it can be inspected or recovered.

## Package a Windows executable

Install PyInstaller in the active virtual environment, then build from the
project root:

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --noconsole --onefile --name FolderShortcuts --collect-all customtkinter --collect-all tkinterdnd2 main.py
```

The executable is created at `dist\FolderShortcuts.exe`. It uses the same
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
