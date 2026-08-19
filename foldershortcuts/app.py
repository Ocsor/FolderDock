"""CustomTkinter user interface for Folder Shortcuts."""

from __future__ import annotations

import os
import queue
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk

from .models import FolderShortcut, default_shortcut_name
from .storage import Storage

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:  # The rest of the app remains usable without drag-and-drop.
    DND_FILES = None
    TkinterDnD = None


ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


if TkinterDnD is not None:
    class _DndEnabledCTk(ctk.CTk, TkinterDnD.DnDWrapper):  # type: ignore[misc]
        """CustomTkinter root with tkinterdnd2's widget commands mixed in."""

else:
    class _DndEnabledCTk(ctk.CTk):
        pass


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path.strip()))


def _short_path(path: str, limit: int = 76) -> str:
    if len(path) <= limit:
        return path
    side = (limit - 3) // 2
    return f"{path[:side]}...{path[-side:]}"


class Tooltip:
    def __init__(self, widget: tk.Misc, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: tk.Toplevel | None = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, _event: tk.Event | None = None) -> None:
        if self.window or not self.text:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.geometry(f"+{x}+{y}")
        label = tk.Label(
            self.window,
            text=self.text,
            background="#202020",
            foreground="#f5f5f5",
            relief="solid",
            borderwidth=1,
            padx=7,
            pady=4,
        )
        label.pack()

    def hide(self, _event: tk.Event | None = None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


class FolderShortcutsApp(_DndEnabledCTk):
    def __init__(self, storage: Storage | None = None) -> None:
        super().__init__()
        self.storage = storage or Storage()
        self.shortcuts = self.storage.load_shortcuts()
        self.settings = self.storage.load_settings()
        self.statuses: dict[str, bool | None] = {}
        self._rows: dict[bool, list[ctk.CTkFrame]] = {False: [], True: []}
        self._tooltips: list[Tooltip] = []
        self._drag_state: dict[str, int | bool] | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="folder-check")
        self._ui_queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._closing = False
        self._save_after_id: str | None = None

        self.title("Folder Shortcuts")
        self.minsize(600, 360)
        geometry = self.settings.get("geometry", "680x520")
        if isinstance(geometry, str) and re.fullmatch(r"\d+x\d+(?:[+-]\d+){0,2}", geometry):
            self.geometry(geometry)
        else:
            self.geometry("680x520")

        self.always_on_top = tk.BooleanVar(value=bool(self.settings.get("always_on_top", False)))
        self.attributes("-topmost", self.always_on_top.get())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._schedule_settings_save)

        self._build_ui()
        self._enable_drag_and_drop()
        self._render_shortcuts()
        self.after(50, self._poll_ui_queue)
        self.after(100, self.refresh_availability)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text="Folder Shortcuts", font=ctk.CTkFont(size=22, weight="bold")
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="Refresh", width=76, command=self.refresh_availability).grid(
            row=0, column=1, padx=(8, 0)
        )
        ctk.CTkButton(header, text="Paste Path", width=92, command=self.paste_path).grid(
            row=0, column=2, padx=(8, 0)
        )
        ctk.CTkButton(header, text="+ Add Folder", width=105, command=self.choose_folder).grid(
            row=0, column=3, padx=(8, 0)
        )

        self.tabs = ctk.CTkTabview(self, corner_radius=10)
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.tabs.add("Shortcuts")
        self.tabs.add("Archive")
        self.list_frames: dict[bool, ctk.CTkScrollableFrame] = {}
        for archived, tab_name in ((False, "Shortcuts"), (True, "Archive")):
            tab = self.tabs.tab(tab_name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            frame = ctk.CTkScrollableFrame(tab, corner_radius=8)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            self.list_frames[archived] = frame

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        footer.grid_columnconfigure(0, weight=1)
        self.hint_label = ctk.CTkLabel(
            footer,
            text="Drag rows to reorder, or right-click for more actions",
            text_color=("gray40", "gray65"),
            font=ctk.CTkFont(size=11),
        )
        self.hint_label.grid(row=0, column=0, sticky="w")
        ctk.CTkSwitch(
            footer,
            text="Always on top",
            variable=self.always_on_top,
            command=self._toggle_topmost,
        ).grid(row=0, column=1, sticky="e")

    def _enable_drag_and_drop(self) -> None:
        if TkinterDnD is None or DND_FILES is None:
            self.hint_label.configure(text="Drag rows to reorder, or right-click for more actions")
            return
        try:
            TkinterDnD._require(self)
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except (tk.TclError, AttributeError):
            self.hint_label.configure(text="Drag rows to reorder, or right-click for more actions")

    def _on_drop(self, event: tk.Event) -> str:
        try:
            paths = self.tk.splitlist(event.data)
        except (tk.TclError, AttributeError):
            return "break"
        future = self._executor.submit(self._existing_directories, paths)
        future.add_done_callback(
            lambda result: self._safe_after(lambda: self._finish_drop(result.result()))
        )
        return "break"

    @staticmethod
    def _existing_directories(paths: tuple[str, ...]) -> list[str]:
        return [path for path in paths if os.path.isdir(path)]

    def _finish_drop(self, folders: list[str]) -> None:
        if not folders:
            messagebox.showwarning("Folder Shortcuts", "Drop one or more folders, not files.", parent=self)
            return
        for path in folders:
            self._add_shortcut(path, ask_for_name=False)

    def choose_folder(self) -> None:
        path = filedialog.askdirectory(parent=self, title="Choose a folder", mustexist=True)
        if path:
            self._add_shortcut(path)

    def paste_path(self) -> None:
        dialog = ctk.CTkInputDialog(
            title="Paste folder path",
            text="Paste a local or UNC folder path:",
        )
        path = dialog.get_input()
        if path and path.strip():
            self._add_shortcut(path.strip().strip('"'))

    def _add_shortcut(self, path: str, ask_for_name: bool = True) -> None:
        cleaned = os.path.normpath(path.strip())
        if not cleaned or cleaned == ".":
            messagebox.showwarning("Folder Shortcuts", "Enter a valid folder path.", parent=self)
            return
        if any(_path_key(item.path) == _path_key(cleaned) for item in self.shortcuts):
            messagebox.showinfo("Folder Shortcuts", "That folder is already saved.", parent=self)
            return

        fallback = default_shortcut_name(cleaned)
        name: str | None = ""
        if ask_for_name:
            name = ctk.CTkInputDialog(
                title="Shortcut name",
                text=f"Friendly name (optional):\n{fallback}",
            ).get_input()
            if name is None:  # Cancelling the name dialog cancels the add operation.
                return
        self.shortcuts.append(FolderShortcut(name=(name or fallback).strip() or fallback, path=cleaned))
        self._save_and_render()
        self._check_availability(len(self.shortcuts) - 1)

    def _render_shortcuts(self) -> None:
        for frame in self.list_frames.values():
            for child in frame.winfo_children():
                child.destroy()
        self._rows = {False: [], True: []}
        self._tooltips.clear()

        for archived in (False, True):
            frame = self.list_frames[archived]
            section = [
                (index, shortcut)
                for index, shortcut in enumerate(self.shortcuts)
                if shortcut.archived is archived
            ]
            if not section:
                message = (
                    "No shortcuts yet\nAdd, paste, or drop a folder to get started."
                    if not archived
                    else "Nothing archived\nArchived shortcuts remain saved here."
                )
                ctk.CTkLabel(
                    frame,
                    text=message,
                    text_color=("gray40", "gray65"),
                    font=ctk.CTkFont(size=14),
                ).grid(row=0, column=0, pady=70)
                continue

            for view_position, (index, shortcut) in enumerate(section):
                self._render_shortcut_row(frame, archived, view_position, index, shortcut)

    def _render_shortcut_row(
        self,
        frame: ctk.CTkScrollableFrame,
        archived: bool,
        view_position: int,
        index: int,
        shortcut: FolderShortcut,
    ) -> None:
        row = ctk.CTkFrame(frame, corner_radius=8, border_width=0)
        row.grid(row=view_position, column=0, sticky="ew", padx=2, pady=(2, 7))
        row.grid_columnconfigure(1, weight=1)

        handle = ctk.CTkLabel(
            row,
            text="≡",
            width=22,
            cursor="fleur",
            text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=18),
        )
        handle.grid(row=0, column=0, rowspan=2, padx=(8, 0))

        name = ctk.CTkLabel(
            row,
            text=shortcut.name,
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        name.grid(row=0, column=1, sticky="ew", padx=(8, 6), pady=(10, 0))

        path_label = ctk.CTkLabel(
            row,
            text=_short_path(shortcut.path),
            anchor="w",
            text_color=("gray35", "gray70"),
            font=ctk.CTkFont(size=11),
        )
        path_label.grid(row=1, column=1, sticky="ew", padx=(8, 6), pady=(1, 10))
        self._tooltips.append(Tooltip(path_label, shortcut.path))

        status = self.statuses.get(_path_key(shortcut.path))
        status_text, status_color = self._status_style(status)
        status_label = ctk.CTkLabel(row, text=status_text, text_color=status_color, width=88)
        status_label.grid(row=0, column=2, rowspan=2, padx=3)

        ctk.CTkButton(
            row, text="Open", width=56, command=lambda i=index: self.open_shortcut(i)
        ).grid(row=0, column=3, rowspan=2, padx=3)
        ctk.CTkButton(
            row,
            text="Restore" if archived else "Archive",
            width=62,
            fg_color=("#47764f", "#35633e") if archived else ("#65707d", "#47515d"),
            hover_color=("#3c6743", "#40754b") if archived else ("#56616e", "#566270"),
            command=lambda i=index, value=not archived: self.set_archived(i, value),
        ).grid(row=0, column=4, rowspan=2, padx=3)
        ctk.CTkButton(
            row,
            text="Remove",
            width=62,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
            command=lambda i=index: self.remove_shortcut(i),
        ).grid(row=0, column=5, rowspan=2, padx=(3, 10))

        for widget in (row, handle, name, path_label, status_label):
            widget.bind("<Double-Button-1>", lambda _event, i=index: self.open_shortcut(i))
            widget.bind(
                "<Button-3>",
                lambda event, i=index, p=view_position, a=archived: self._show_context_menu(
                    event, i, p, a
                ),
            )
            widget.bind(
                "<ButtonPress-1>",
                lambda event, p=view_position, a=archived: self._start_row_drag(event, a, p),
                add="+",
            )
            widget.bind("<B1-Motion>", self._drag_row, add="+")
            widget.bind("<ButtonRelease-1>", self._end_row_drag, add="+")
        self._rows[archived].append(row)

    @staticmethod
    def _status_style(status: bool | None) -> tuple[str, tuple[str, str]]:
        if status is True:
            return "● Available", ("#237a3b", "#55c878")
        if status is False:
            return "⚠ Unavailable", ("#a13b31", "#f08073")
        return "○ Checking", ("gray45", "gray65")

    def _start_row_drag(self, _event: tk.Event, archived: bool, view_position: int) -> None:
        self._drag_state = {
            "archived": archived,
            "from_position": view_position,
            "target_position": view_position,
        }

    def _drag_row(self, event: tk.Event) -> None:
        if self._drag_state is None:
            return
        archived = bool(self._drag_state["archived"])
        rows = self._rows[archived]
        if not rows:
            return

        target = len(rows) - 1
        for position, row in enumerate(rows):
            midpoint = row.winfo_rooty() + row.winfo_height() // 2
            if event.y_root < midpoint:
                target = position
                break
        self._drag_state["target_position"] = target
        for position, row in enumerate(rows):
            row.configure(
                border_width=2 if position == target else 0,
                border_color=("#3b8ed0", "#1f6aa5"),
            )

    def _end_row_drag(self, _event: tk.Event) -> None:
        if self._drag_state is None:
            return
        state = self._drag_state
        self._drag_state = None
        archived = bool(state["archived"])
        start = int(state["from_position"])
        target = int(state["target_position"])
        for row in self._rows[archived]:
            row.configure(border_width=0)
        if start != target:
            self._reorder_section(archived, start, target)

    def _section_indices(self, archived: bool) -> list[int]:
        return [
            index
            for index, shortcut in enumerate(self.shortcuts)
            if shortcut.archived is archived
        ]

    def _reorder_section(self, archived: bool, start: int, target: int) -> None:
        slots = self._section_indices(archived)
        if not (0 <= start < len(slots) and 0 <= target < len(slots)):
            return
        ordered = [self.shortcuts[index] for index in slots]
        moved = ordered.pop(start)
        ordered.insert(target, moved)
        for index, shortcut in zip(slots, ordered):
            self.shortcuts[index] = shortcut
        self._save_and_render()

    def _show_context_menu(
        self, event: tk.Event, index: int, view_position: int, archived: bool
    ) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Open Folder", command=lambda: self.open_shortcut(index))
        menu.add_command(label="Copy Path", command=lambda: self.copy_path(index))
        menu.add_command(label="Rename Shortcut", command=lambda: self.rename_shortcut(index))
        menu.add_command(
            label="Restore Shortcut" if archived else "Archive Shortcut",
            command=lambda: self.set_archived(index, not archived),
        )
        menu.add_separator()
        section_size = len(self._section_indices(archived))
        menu.add_command(
            label="Move Up",
            command=lambda: self.move_shortcut(index, -1),
            state="normal" if view_position else "disabled",
        )
        menu.add_command(
            label="Move Down",
            command=lambda: self.move_shortcut(index, 1),
            state="normal" if view_position < section_size - 1 else "disabled",
        )
        menu.add_separator()
        menu.add_command(label="Remove Shortcut", command=lambda: self.remove_shortcut(index))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def open_shortcut(self, index: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        shortcut = self.shortcuts[index]

        def work() -> tuple[bool, str | None]:
            try:
                available = os.path.isdir(shortcut.path)
                if not available:
                    return False, "The folder is unavailable. Check the path or network connection."
                os.startfile(shortcut.path)  # type: ignore[attr-defined]
                return True, None
            except OSError as error:
                return False, f"Windows could not open this folder.\n\n{error}"

        future = self._executor.submit(work)
        future.add_done_callback(
            lambda result: self._safe_after(lambda: self._finish_open(shortcut, result.result()))
        )

    def _finish_open(self, shortcut: FolderShortcut, result: tuple[bool, str | None]) -> None:
        available, error = result
        self.statuses[_path_key(shortcut.path)] = available
        self._render_shortcuts()
        if error:
            messagebox.showerror("Unable to open folder", error, parent=self)

    def remove_shortcut(self, index: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        if messagebox.askyesno(
            "Remove shortcut",
            f'Remove the shortcut "{self.shortcuts[index].name}"?\n\nThe folder itself will not be changed.',
            parent=self,
        ):
            self.shortcuts.pop(index)
            self._save_and_render()

    def set_archived(self, index: int, archived: bool) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        self.shortcuts[index].archived = archived
        self._save_and_render()

    def rename_shortcut(self, index: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        shortcut = self.shortcuts[index]
        name = ctk.CTkInputDialog(
            title="Rename shortcut",
            text=f"New name for {shortcut.name}:",
        ).get_input()
        if name and name.strip():
            shortcut.name = name.strip()
            self._save_and_render()

    def copy_path(self, index: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        self.clipboard_clear()
        self.clipboard_append(self.shortcuts[index].path)
        self.update_idletasks()

    def move_shortcut(self, index: int, offset: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        archived = self.shortcuts[index].archived
        slots = self._section_indices(archived)
        try:
            position = slots.index(index)
        except ValueError:
            return
        self._reorder_section(archived, position, position + offset)

    def refresh_availability(self) -> None:
        for index in range(len(self.shortcuts)):
            self._check_availability(index)
        self._render_shortcuts()

    def _check_availability(self, index: int) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        shortcut = self.shortcuts[index]
        key = _path_key(shortcut.path)
        self.statuses[key] = None
        future = self._executor.submit(os.path.isdir, shortcut.path)
        future.add_done_callback(
            lambda result, item_key=key: self._safe_after(
                lambda: self._set_availability(item_key, self._future_bool(result))
            )
        )

    @staticmethod
    def _future_bool(future: object) -> bool:
        try:
            return bool(future.result())  # type: ignore[attr-defined]
        except (OSError, RuntimeError):
            return False

    def _set_availability(self, key: str, available: bool) -> None:
        self.statuses[key] = available
        self._render_shortcuts()

    def _safe_after(self, callback: Callable[[], None]) -> None:
        if not self._closing:
            self._ui_queue.put(callback)

    def _poll_ui_queue(self) -> None:
        while not self._ui_queue.empty():
            try:
                self._ui_queue.get_nowait()()
            except queue.Empty:
                break
        if not self._closing:
            self.after(50, self._poll_ui_queue)

    def _save_and_render(self) -> None:
        try:
            self.storage.save_shortcuts(self.shortcuts)
        except OSError as error:
            messagebox.showerror("Could not save shortcuts", str(error), parent=self)
        self._render_shortcuts()

    def _toggle_topmost(self) -> None:
        self.attributes("-topmost", self.always_on_top.get())
        self._save_settings()

    def _schedule_settings_save(self, event: tk.Event) -> None:
        if event.widget is not self or self._closing:
            return
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
        self._save_after_id = self.after(500, self._save_settings)

    def _save_settings(self) -> None:
        self._save_after_id = None
        if self.state() == "normal":
            self.settings["geometry"] = self.geometry()
        self.settings["always_on_top"] = self.always_on_top.get()
        try:
            self.storage.save_settings(self.settings)
        except OSError:
            pass

    def _on_close(self) -> None:
        self._closing = True
        if self._save_after_id is not None:
            self.after_cancel(self._save_after_id)
            self._save_after_id = None
        self._save_settings()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()
