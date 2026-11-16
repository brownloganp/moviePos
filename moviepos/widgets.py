"""Touch-friendly building blocks: big buttons, paged lists, number pad, on-screen keyboard."""
from __future__ import annotations

import math
import tkinter as tk
from typing import Callable

from .theme import (
    ACCENT, BG, BTN, DISABLED, DISABLED_FG, F, SUBTLE, TEXT, lighten,
)

_UNSET = object()


class TouchButton(tk.Label):
    """A Label that behaves like a button. (tk.Button ignores colors on macOS.)"""

    def __init__(self, parent, text="", command=None, *, bg=BTN, fg=TEXT, font=None, enabled=True, **kw):
        kw.setdefault("padx", 14)
        kw.setdefault("pady", 10)
        kw.setdefault("justify", "center")
        super().__init__(parent, text=text, bg=bg, fg=fg, font=font or F["btn"], **kw)
        self._bg, self._fg = bg, fg
        self._command = command
        self._enabled = enabled
        self._down = False
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self._paint()

    def set(self, *, text=_UNSET, bg=_UNSET, fg=_UNSET, enabled=_UNSET, command=_UNSET) -> None:
        if text is not _UNSET:
            self.configure(text=text)
        if bg is not _UNSET:
            self._bg = bg
        if fg is not _UNSET:
            self._fg = fg
        if enabled is not _UNSET:
            self._enabled = enabled
        if command is not _UNSET:
            self._command = command
        self._paint()

    def _paint(self) -> None:
        if not self._enabled:
            bg, fg = DISABLED, DISABLED_FG
        else:
            bg, fg = (lighten(self._bg) if self._down else self._bg), self._fg
        self.configure(bg=bg, fg=fg)

    def _press(self, _event) -> None:
        if self._enabled:
            self._down = True
            self._paint()

    def _release(self, event) -> None:
        was_down, self._down = self._down, False
        self._paint()
        inside = 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        if was_down and inside and self._enabled and self._command:
            self._command()


class PagedGrid(tk.Frame):
    """Grid of widgets split into pages with Prev/Next buttons (paging is more reliable than scrolling on touch)."""

    def __init__(self, parent, cols: int, rows: int, make_item: Callable, empty_text="Nothing to show", numbered=False):
        super().__init__(parent, bg=BG)
        self.cols, self.rows, self.make_item, self.empty_text = cols, rows, make_item, empty_text
        self.numbered = numbered  # prefix each item with its 1-9 shortcut
        self.items: list = []
        self.page = 0
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.cells = tk.Frame(self, bg=BG)
        self.cells.grid(row=0, column=0, sticky="nsew")
        for c in range(cols):
            self.cells.grid_columnconfigure(c, weight=1, uniform="c")
        for r in range(rows):
            self.cells.grid_rowconfigure(r, weight=1, uniform="r")
        self.nav = tk.Frame(self, bg=BG)
        self.nav.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.nav.grid_columnconfigure(1, weight=1)
        self.prev_btn = TouchButton(self.nav, "◀  Prev", lambda: self.goto(self.page - 1), pady=6)
        self.next_btn = TouchButton(self.nav, "Next  ▶", lambda: self.goto(self.page + 1), pady=6)
        self.page_lbl = tk.Label(self.nav, bg=BG, fg=SUBTLE, font=F["base"])
        self.prev_btn.grid(row=0, column=0)
        self.page_lbl.grid(row=0, column=1)
        self.next_btn.grid(row=0, column=2)

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.items) / (self.cols * self.rows)))

    def set_items(self, items: list, keep_page: bool = False) -> None:
        self.items = list(items)
        if not keep_page:
            self.page = 0
        self.render()

    def goto(self, page: int) -> None:
        self.page = page
        self.render()

    def page_by(self, delta: int) -> None:
        self.goto(self.page + delta)

    def invoke(self, n: int) -> None:
        """Press the nth (1-based) item on this page, as if tapped."""
        cells = sorted(self.cells.grid_slaves(), key=lambda w: (w.grid_info()["row"], w.grid_info()["column"]))
        if 1 <= n <= len(cells) and getattr(cells[n - 1], "_enabled", False):
            command = getattr(cells[n - 1], "_command", None)
            if command:
                command()

    def render(self) -> None:
        self.page = min(max(self.page, 0), self.pages - 1)
        for w in self.cells.winfo_children():
            w.destroy()
        per = self.cols * self.rows
        chunk = self.items[self.page * per : (self.page + 1) * per]
        if not chunk:
            tk.Label(self.cells, text=self.empty_text, bg=BG, fg=SUBTLE, font=F["h2"]).grid(
                row=0, column=0, columnspan=self.cols, pady=8
            )
        for i, item in enumerate(chunk):
            widget = self.make_item(self.cells, item)
            if self.numbered and isinstance(widget, TouchButton) and i < 9:
                widget.set(text=f"{i + 1}   {widget.cget('text')}")
            widget.grid(row=i // self.cols, column=i % self.cols, sticky="nsew", padx=5, pady=5)
        if self.pages > 1:
            self.nav.grid()
            self.page_lbl.configure(text=f"Page {self.page + 1} of {self.pages}")
            self.prev_btn.set(enabled=self.page > 0)
            self.next_btn.set(enabled=self.page < self.pages - 1)
        else:
            self.nav.grid_remove()


class SelectList(tk.Frame):
    """Single-select list of (key, text) rows, paged."""

    def __init__(self, parent, rows=7, on_select: Callable | None = None, empty_text="Nothing here yet", wraplength=0):
        super().__init__(parent, bg=BG)
        self.wraplength = wraplength
        self.selected = None
        self.on_select = on_select
        self.grid_ = PagedGrid(self, 1, rows, self._make, empty_text)
        self.grid_.pack(fill="both", expand=True)

    def set_items(self, items: list[tuple], keep_selection: bool = False) -> None:
        keys = [k for k, _ in items]
        if not keep_selection or self.selected not in keys:
            self.selected = None
        self.grid_.set_items(items, keep_page=keep_selection)

    def move(self, delta: int) -> None:
        """Select the previous/next row (across pages) and show the page it is on."""
        keys = [k for k, _ in self.grid_.items]
        if not keys:
            return
        index = keys.index(self.selected) if self.selected in keys else (-1 if delta > 0 else len(keys))
        index = min(max(index + delta, 0), len(keys) - 1)
        self.grid_.page = index // (self.grid_.cols * self.grid_.rows)
        self.select(keys[index])

    def page_by(self, delta: int) -> None:
        self.grid_.page_by(delta)

    def select(self, key) -> None:
        self.selected = key
        self.grid_.render()
        if self.on_select:
            self.on_select(key)

    def _make(self, parent, item):
        key, text = item
        return TouchButton(
            parent, text, lambda k=key: self.select(k),
            bg=ACCENT if key == self.selected else BTN, anchor="w", justify="left",
            font=F["row"], padx=18, wraplength=self.wraplength,
        )


class NumPad(tk.Frame):
    def __init__(self, parent, on_key: Callable[[str], None], on_back: Callable[[], None], allow_dot=True, pady=14):
        super().__init__(parent, bg=BG)
        layout = [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], [".", "0", "⌫"]]
        for c in range(3):
            self.grid_columnconfigure(c, weight=1, uniform="k")
        self.dot = None
        for r, row in enumerate(layout):
            self.grid_rowconfigure(r, weight=1, uniform="k")
            for c, key in enumerate(row):
                cmd = on_back if key == "⌫" else (lambda k=key: on_key(k))
                b = TouchButton(self, key, cmd, font=F["key"], pady=pady)
                b.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
                if key == ".":
                    self.dot = b
        self.set_allow_dot(allow_dot)

    def set_allow_dot(self, allow: bool) -> None:
        self.dot.set(enabled=allow, text="." if allow else "")


class TextKeyboard(tk.Frame):
    ROWS = ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.-"]

    def __init__(self, parent, on_key: Callable[[str], None], on_back: Callable[[], None]):
        super().__init__(parent, bg=BG)
        self._on_key = on_key
        self._letters: dict[str, TouchButton] = {}
        self.shift = False
        for r, chars in enumerate(self.ROWS):
            row = tk.Frame(self, bg=BG)
            row.pack(fill="x", pady=2)
            if r == 3:
                TouchButton(row, "⇧", self._toggle_shift, font=F["key"], width=3, padx=0, pady=8).pack(
                    side="left", expand=True, fill="both", padx=2
                )
            for ch in chars:
                b = TouchButton(row, ch, lambda c=ch: self._press(c), font=F["key"], width=1, padx=0, pady=8)
                b.pack(side="left", expand=True, fill="both", padx=2)
                if ch.isalpha():
                    self._letters[ch] = b
            if r == 3:
                TouchButton(row, "⌫", on_back, font=F["key"], width=3, padx=0, pady=8).pack(
                    side="left", expand=True, fill="both", padx=2
                )
        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", pady=2)
        for ch in "&:!?":
            TouchButton(bottom, ch, lambda c=ch: self._press(c), font=F["key"], width=3, padx=0, pady=8).pack(
                side="left", padx=2
            )
        TouchButton(bottom, "space", lambda: self._press(" "), font=F["btn"], pady=8).pack(
            side="left", expand=True, fill="both", padx=2
        )

    def _press(self, ch: str) -> None:
        self._on_key(ch.upper() if self.shift and ch.isalpha() else ch)

    def _toggle_shift(self) -> None:
        self.set_shift(not self.shift)

    def set_shift(self, on: bool) -> None:
        self.shift = on
        for ch, b in self._letters.items():
            b.set(text=ch.upper() if on else ch)
