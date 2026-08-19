"""CustomTkinter user interface for Folder Shortcuts."""

from __future__ import annotations

import os
import queue
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tkinter as tk
from tkinter import messagebox
from typing import Callable

import customtkinter as ctk

try:
    from PIL import Image
except ImportError:
    Image = None

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


def _shortcut_section(shortcut: FolderShortcut) -> str:
    if shortcut.archived:
        return "Archive"
    return shortcut.tab or "Shortcuts"


def _resource_path(relative_path: str) -> Path:
    """Resolve bundled PyInstaller assets as well as development files."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return bundle_root / relative_path


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
        self.custom_tabs = self._load_custom_tabs()
        self.statuses: dict[str, bool | None] = {}
        self._rows: dict[str, list[ctk.CTkFrame]] = {
            name: [] for name in self._section_names()
        }
        self._tooltips: list[Tooltip] = []
        self._drag_state: dict[str, int | str] | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="folder-check")
        self._ui_queue: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._closing = False
        self._save_after_id: str | None = None
        self._settings_window: ctk.CTkToplevel | None = None
        self._tab_menu_bindings: set[str] = set()

        self.title("FolderDock")
        self.minsize(520, 360)
        geometry = self.settings.get("geometry", "680x520")
        if isinstance(geometry, str) and re.fullmatch(r"\d+x\d+(?:[+-]\d+){0,2}", geometry):
            self.geometry(geometry)
        else:
            self.geometry("680x520")

        self.always_on_top = tk.BooleanVar(value=bool(self.settings.get("always_on_top", False)))
        saved_appearance = self.settings.get("appearance_mode", ctk.get_appearance_mode())
        self.dark_mode = tk.BooleanVar(value=saved_appearance == "Dark")
        self.show_folder_paths = tk.BooleanVar(
            value=bool(self.settings.get("show_folder_paths", False))
        )
        ctk.set_appearance_mode("Dark" if self.dark_mode.get() else "Light")
        self.attributes("-topmost", self.always_on_top.get())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Configure>", self._schedule_settings_save)
        self.logo_image = self._load_logo()
        self._set_window_icon()

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

        title_frame = ctk.CTkFrame(header, fg_color="transparent")
        title_frame.grid(row=0, column=0, sticky="w")
        title_column = 0
        if self.logo_image is not None:
            ctk.CTkLabel(title_frame, text="", image=self.logo_image, width=42).grid(
                row=0, column=0, padx=(0, 9)
            )
            title_column = 1
        ctk.CTkLabel(
            title_frame, text="FolderDock", font=ctk.CTkFont(size=22, weight="bold")
        ).grid(row=0, column=title_column, sticky="w")
        ctk.CTkButton(
            header,
            text="☰",
            width=42,
            font=ctk.CTkFont(size=20),
            command=self.open_settings,
        ).grid(row=0, column=1, sticky="e")
        self._last_content_tab = "Shortcuts"
        self.tabs = ctk.CTkTabview(
            self, corner_radius=10, command=self._on_tab_selected
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        self.list_frames: dict[str, ctk.CTkScrollableFrame] = {}
        for tab_name in self._section_names():
            self.tabs.add(tab_name)
            tab = self.tabs.tab(tab_name)
            tab.grid_columnconfigure(0, weight=1)
            tab.grid_rowconfigure(0, weight=1)
            frame = ctk.CTkScrollableFrame(tab, corner_radius=8)
            frame.grid(row=0, column=0, sticky="nsew")
            frame.grid_columnconfigure(0, weight=1)
            self.list_frames[tab_name] = frame
        self.tabs.add("+")
        self._bind_custom_tab_menus()

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 12))
        footer.grid_columnconfigure(0, weight=1)
        self.hint_label = ctk.CTkLabel(
            footer,
            text="Drop folders to add them; drag rows to reorder",
            text_color=("gray40", "gray65"),
            font=ctk.CTkFont(size=11),
        )
        self.hint_label.grid(row=0, column=0, sticky="w")

    def _load_logo(self) -> ctk.CTkImage | None:
        logo_path = _resource_path("Logo/FolderDock.png")
        if Image is None or not logo_path.is_file():
            return None
        try:
            with Image.open(logo_path) as image:
                logo = image.convert("RGBA").copy()
            return ctk.CTkImage(light_image=logo, dark_image=logo, size=(42, 42))
        except OSError:
            return None

    def _set_window_icon(self) -> None:
        logo_path = _resource_path("Logo/FolderDock.png")
        if not logo_path.is_file():
            return
        try:
            self._window_icon = tk.PhotoImage(file=str(logo_path))
            self.iconphoto(True, self._window_icon)
        except tk.TclError:
            self._window_icon = None

    def _load_custom_tabs(self) -> list[str]:
        raw_tabs = self.settings.get("custom_tabs", ["Clients"])
        tabs: list[str] = []
        if isinstance(raw_tabs, list):
            for value in raw_tabs:
                if isinstance(value, str):
                    name = value.strip()
                    if self._valid_new_tab_name(name, tabs):
                        tabs.append(name)
        for shortcut in self.shortcuts:
            if shortcut.tab and self._valid_new_tab_name(shortcut.tab, tabs):
                tabs.append(shortcut.tab)
        return tabs

    @staticmethod
    def _valid_new_tab_name(name: str, existing: list[str]) -> bool:
        reserved = {"shortcuts", "archive", "+"}
        used = {value.casefold() for value in existing}
        return bool(name) and name.casefold() not in reserved | used

    def _section_names(self) -> list[str]:
        return ["Shortcuts", *self.custom_tabs, "Archive"]

    def open_settings(self) -> None:
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._center_settings_window()
            self._restore_settings_window()
            return

        window = ctk.CTkToplevel(self)
        self._settings_window = window
        window.title("FolderDock Settings")
        window.geometry("340x250")
        window.resizable(False, False)
        window.transient(self)
        window.attributes("-topmost", self.always_on_top.get())
        window.protocol("WM_DELETE_WINDOW", self._close_settings)
        window.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            window,
            text="Settings",
            anchor="w",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="ew", padx=22, pady=(20, 14))

        controls = ctk.CTkFrame(window, corner_radius=10)
        controls.grid(row=1, column=0, sticky="ew", padx=20)
        controls.grid_columnconfigure(0, weight=1)

        ctk.CTkSwitch(
            controls,
            text="Dark mode",
            variable=self.dark_mode,
            command=self._toggle_dark_mode,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 10))
        ctk.CTkSwitch(
            controls,
            text="Always on top",
            variable=self.always_on_top,
            command=self._toggle_topmost,
        ).grid(row=1, column=0, sticky="w", padx=18, pady=10)
        ctk.CTkSwitch(
            controls,
            text="Show folder paths",
            variable=self.show_folder_paths,
            command=self._toggle_folder_paths,
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(10, 18))

        self._center_settings_window()
        window.after(50, window.focus_force)

    def _close_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.destroy()
            self._settings_window = None

    def _restore_settings_window(self) -> None:
        window = self._settings_window
        if window is None or not window.winfo_exists():
            return
        window.deiconify()
        window.lift()
        window.attributes("-topmost", self.always_on_top.get())
        window.focus_force()

    def _center_settings_window(self) -> None:
        window = self._settings_window
        if window is None or not window.winfo_exists():
            return
        self.update_idletasks()
        window.update_idletasks()
        width, height = 340, 250
        # winfo_x/y use the outer window position, avoiding title-bar offsets.
        x = self.winfo_x() + (self.winfo_width() - width) // 2
        y = self.winfo_y() + (self.winfo_height() - height) // 2
        window.geometry(f"{width}x{height}+{x}+{y}")

    def _on_tab_selected(self) -> None:
        selected = self.tabs.get()
        if selected == "+":
            previous = (
                self._last_content_tab
                if self._last_content_tab in self._section_names()
                else "Shortcuts"
            )
            self.tabs.set(previous)
            self.after(0, self.add_custom_tab)
        elif selected in self._section_names():
            self._last_content_tab = selected

    def _bind_custom_tab_menus(self) -> None:
        segmented = getattr(self.tabs, "_segmented_button", None)
        buttons = getattr(segmented, "_buttons_dict", {})
        for name in self.custom_tabs:
            if name in self._tab_menu_bindings:
                continue
            button = buttons.get(name)
            if button is not None:
                button.bind(
                    "<Button-3>",
                    lambda event, tab_name=name: self._show_tab_menu(event, tab_name),
                    add="+",
                )
                self._tab_menu_bindings.add(name)

    def _show_tab_menu(self, event: tk.Event, name: str) -> None:
        if name not in self.custom_tabs:
            return
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Rename Tab", command=lambda: self.rename_custom_tab(name))
        menu.add_command(label="Delete Tab", command=lambda: self.remove_custom_tab(name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def add_custom_tab(self) -> None:
        name = ctk.CTkInputDialog(
            title="Add tab", text="Name for the new tab:"
        ).get_input()
        if name is None:
            return
        name = name.strip()
        if len(name) > 24 or not self._valid_new_tab_name(name, self.custom_tabs):
            messagebox.showwarning(
                "Invalid tab name",
                "Use a unique name of 1–24 characters. Shortcuts, Archive, and + are reserved.",
                parent=self._settings_window,
            )
            return

        self.custom_tabs.append(name)
        self.tabs.insert(len(self.custom_tabs), name)
        tab = self.tabs.tab(name)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        frame = ctk.CTkScrollableFrame(tab, corner_radius=8)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        self.list_frames[name] = frame
        self._rows[name] = []
        self.tabs.set(name)
        self._last_content_tab = name
        self._bind_custom_tab_menus()
        self._render_shortcuts()
        self._save_settings()

    def rename_custom_tab(self, old_name: str) -> None:
        if old_name not in self.custom_tabs:
            return
        name = ctk.CTkInputDialog(
            title="Rename tab", text=f"New name for {old_name}:"
        ).get_input()
        if name is None:
            return
        name = name.strip()
        other_tabs = [value for value in self.custom_tabs if value != old_name]
        if len(name) > 24 or not self._valid_new_tab_name(name, other_tabs):
            messagebox.showwarning(
                "Invalid tab name",
                "Use a unique name of 1–24 characters. Shortcuts, Archive, and + are reserved.",
                parent=self,
            )
            return

        position = self.custom_tabs.index(old_name)
        self.custom_tabs[position] = name
        self._tab_menu_bindings.discard(old_name)
        for shortcut in self.shortcuts:
            if shortcut.tab == old_name:
                shortcut.tab = name
        self.tabs.rename(old_name, name)
        self.list_frames[name] = self.list_frames.pop(old_name)
        self._rows[name] = self._rows.pop(old_name)
        self.tabs.set(name)
        self._last_content_tab = name
        self._bind_custom_tab_menus()
        self._save_and_render()
        self._save_settings()

    def remove_custom_tab(self, name: str) -> None:
        if name not in self.custom_tabs:
            return
        affected = sum(shortcut.tab == name for shortcut in self.shortcuts)
        detail = (
            f" {affected} saved folder{'s' if affected != 1 else ''} will move to Shortcuts."
            if affected
            else ""
        )
        if not messagebox.askyesno(
            "Remove tab",
            f'Remove the tab "{name}"?{detail}\n\nNo folders will be deleted.',
            parent=self,
        ):
            return
        for shortcut in self.shortcuts:
            if shortcut.tab == name:
                shortcut.tab = ""
        self.tabs.set("Shortcuts")
        self._last_content_tab = "Shortcuts"
        self.tabs.delete(name)
        self.custom_tabs.remove(name)
        self._tab_menu_bindings.discard(name)
        self.list_frames.pop(name, None)
        self._rows.pop(name, None)
        self._save_and_render()
        self._save_settings()

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
        selected_tab = self.tabs.get()
        destination = selected_tab if selected_tab in self.custom_tabs else ""
        for path in folders:
            self._add_shortcut(path, tab=destination)

    def _add_shortcut(self, path: str, tab: str = "") -> None:
        cleaned = os.path.normpath(path.strip())
        if not cleaned or cleaned == ".":
            messagebox.showwarning("Folder Shortcuts", "Enter a valid folder path.", parent=self)
            return
        if any(_path_key(item.path) == _path_key(cleaned) for item in self.shortcuts):
            messagebox.showinfo("Folder Shortcuts", "That folder is already saved.", parent=self)
            return

        fallback = default_shortcut_name(cleaned)
        self.shortcuts.append(FolderShortcut(name=fallback, path=cleaned, tab=tab))
        self._save_and_render()
        self._check_availability(len(self.shortcuts) - 1)

    def _render_shortcuts(self) -> None:
        for frame in self.list_frames.values():
            for child in frame.winfo_children():
                child.destroy()
        self._rows = {name: [] for name in self._section_names()}
        self._tooltips.clear()

        for section_name in self._section_names():
            frame = self.list_frames[section_name]
            section = [
                (index, shortcut)
                for index, shortcut in enumerate(self.shortcuts)
                if _shortcut_section(shortcut) == section_name
            ]
            if not section:
                if section_name == "Shortcuts":
                    empty_message = "No shortcuts yet\nDrop a folder here to get started."
                elif section_name == "Archive":
                    empty_message = "Nothing archived\nArchived shortcuts remain saved here."
                else:
                    empty_message = f"Nothing in {section_name} yet\nDrop a folder here or move one from another tab."
                ctk.CTkLabel(
                    frame,
                    text=empty_message,
                    text_color=("gray40", "gray65"),
                    font=ctk.CTkFont(size=14),
                ).grid(row=0, column=0, pady=70)
                continue

            for view_position, (index, shortcut) in enumerate(section):
                self._render_shortcut_row(
                    frame, section_name, view_position, index, shortcut
                )

    def _render_shortcut_row(
        self,
        frame: ctk.CTkScrollableFrame,
        section_name: str,
        view_position: int,
        index: int,
        shortcut: FolderShortcut,
    ) -> None:
        show_path = self.show_folder_paths.get()
        row = ctk.CTkFrame(frame, corner_radius=8, border_width=0)
        row.grid(
            row=view_position,
            column=0,
            sticky="ew",
            padx=2,
            pady=(2, 7) if show_path else (1, 3),
        )
        row.grid_columnconfigure(1, weight=1)
        row_span = 2 if show_path else 1

        handle = ctk.CTkLabel(
            row,
            text="≡",
            width=22,
            cursor="fleur",
            text_color=("gray45", "gray60"),
            font=ctk.CTkFont(size=18),
        )
        handle.grid(row=0, column=0, rowspan=row_span, padx=(8, 0))

        name = ctk.CTkLabel(
            row,
            text=shortcut.name,
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        name.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 6),
            pady=(6, 6) if not show_path else (10, 0),
        )

        path_label: ctk.CTkLabel | None = None
        if show_path:
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
        status_label.grid(row=0, column=2, rowspan=row_span, padx=3)

        actions_button = ctk.CTkButton(
            row,
            text="•••",
            width=42,
            height=26 if not show_path else 28,
            fg_color=("gray70", "gray30"),
            hover_color=("gray60", "gray40"),
        )
        actions_button.configure(
            command=lambda button=actions_button, i=index, s=section_name: self._show_action_menu(
                button, i, s
            )
        )
        actions_button.grid(row=0, column=3, rowspan=row_span, padx=(5, 10))

        draggable_widgets: list[tk.Misc] = [row, handle, name, status_label]
        if path_label is not None:
            draggable_widgets.append(path_label)
        for widget in draggable_widgets:
            widget.bind("<Double-Button-1>", lambda _event, i=index: self.open_shortcut(i))
            widget.bind(
                "<Button-3>",
                lambda event, i=index, p=view_position, s=section_name: self._show_context_menu(
                    event, i, p, s
                ),
            )
            widget.bind(
                "<ButtonPress-1>",
                lambda event, p=view_position, s=section_name: self._start_row_drag(event, s, p),
                add="+",
            )
            widget.bind("<B1-Motion>", self._drag_row, add="+")
            widget.bind("<ButtonRelease-1>", self._end_row_drag, add="+")
        self._rows[section_name].append(row)

    @staticmethod
    def _status_style(status: bool | None) -> tuple[str, tuple[str, str]]:
        if status is True:
            return "● Available", ("#237a3b", "#55c878")
        if status is False:
            return "⚠ Unavailable", ("#a13b31", "#f08073")
        return "○ Checking", ("gray45", "gray65")

    def _start_row_drag(self, _event: tk.Event, section: str, view_position: int) -> None:
        self._drag_state = {
            "section": section,
            "from_position": view_position,
            "target_position": view_position,
        }

    def _drag_row(self, event: tk.Event) -> None:
        if self._drag_state is None:
            return
        section = str(self._drag_state["section"])
        rows = self._rows[section]
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
        section = str(state["section"])
        start = int(state["from_position"])
        target = int(state["target_position"])
        for row in self._rows[section]:
            row.configure(border_width=0)
        if start != target:
            self._reorder_section(section, start, target)

    def _section_indices(self, section: str) -> list[int]:
        return [
            index
            for index, shortcut in enumerate(self.shortcuts)
            if _shortcut_section(shortcut) == section
        ]

    def _reorder_section(self, section: str, start: int, target: int) -> None:
        slots = self._section_indices(section)
        if not (0 <= start < len(slots) and 0 <= target < len(slots)):
            return
        ordered = [self.shortcuts[index] for index in slots]
        moved = ordered.pop(start)
        ordered.insert(target, moved)
        for index, shortcut in zip(slots, ordered):
            self.shortcuts[index] = shortcut
        self._save_and_render()

    def _show_context_menu(
        self, event: tk.Event, index: int, view_position: int, section: str
    ) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Open Folder", command=lambda: self.open_shortcut(index))
        menu.add_command(label="Copy Path", command=lambda: self.copy_path(index))
        menu.add_command(label="Rename Shortcut", command=lambda: self.rename_shortcut(index))
        menu.add_separator()
        self._add_section_actions(menu, index, section)
        menu.add_separator()
        section_size = len(self._section_indices(section))
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

    def _show_action_menu(
        self, button: ctk.CTkButton, index: int, section: str
    ) -> None:
        menu = tk.Menu(self, tearoff=False)
        menu.add_command(label="Open Folder", command=lambda: self.open_shortcut(index))
        self._add_section_actions(menu, index, section)
        menu.add_separator()
        menu.add_command(label="Remove Shortcut", command=lambda: self.remove_shortcut(index))
        try:
            menu.tk_popup(
                button.winfo_rootx() + button.winfo_width(),
                button.winfo_rooty() + button.winfo_height(),
            )
        finally:
            menu.grab_release()

    def _add_section_actions(self, menu: tk.Menu, index: int, section: str) -> None:
        if section == "Archive":
            destination = self.shortcuts[index].tab or "Shortcuts"
            menu.add_command(
                label=f"Restore to {destination}",
                command=lambda: self.set_archived(index, False),
            )
            return
        destinations = ["Shortcuts", *self.custom_tabs]
        destinations = [name for name in destinations if name != section]
        if destinations:
            move_menu = tk.Menu(menu, tearoff=False)
            for destination in destinations:
                move_menu.add_command(
                    label=destination,
                    command=lambda name=destination: self.move_to_tab(index, name),
                )
            menu.add_cascade(label="Move to", menu=move_menu)
        menu.add_command(
            label="Archive Shortcut",
            command=lambda: self.set_archived(index, True),
        )

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

    def move_to_tab(self, index: int, tab_name: str) -> None:
        if not 0 <= index < len(self.shortcuts):
            return
        if tab_name not in ["Shortcuts", *self.custom_tabs]:
            return
        self.shortcuts[index].tab = "" if tab_name == "Shortcuts" else tab_name
        self.shortcuts[index].archived = False
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
        section = _shortcut_section(self.shortcuts[index])
        slots = self._section_indices(section)
        try:
            position = slots.index(index)
        except ValueError:
            return
        self._reorder_section(section, position, position + offset)

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
        enabled = self.always_on_top.get()
        self.attributes("-topmost", enabled)
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.attributes("-topmost", enabled)
        self._save_settings()

    def _toggle_dark_mode(self) -> None:
        ctk.set_appearance_mode("Dark" if self.dark_mode.get() else "Light")
        self._save_settings()
        # Appearance changes can temporarily withdraw a CTkToplevel on Windows.
        self.after(20, self._restore_settings_window)

    def _toggle_folder_paths(self) -> None:
        self._render_shortcuts()
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
        self.settings["appearance_mode"] = "Dark" if self.dark_mode.get() else "Light"
        self.settings["show_folder_paths"] = self.show_folder_paths.get()
        self.settings["custom_tabs"] = self.custom_tabs
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
