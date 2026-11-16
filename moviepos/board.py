"""Customer display board: a full-screen, button-free list of today's showtimes, one row per movie.

Run separately from the POS:  python3 -m moviepos.board
It only reads the POS database and refreshes itself, so it can run beside the POS.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import fmt
from .store import Showing, Store

GRACE = timedelta(minutes=15)  # keep showing a movie that started less than this long ago
REFRESH_SECONDS = 10
PAGE_SECONDS = 8

BG = "#0b1018"
ROW_A = "#131b28"
ROW_B = "#0f1622"
TEXT = "#f8fafc"
SUBTLE = "#94a3b8"
GOLD = "#fbbf24"
TILE = "#26344d"
TILE_SOLD = "#161c27"
MUTED = "#566174"
SOLD_TAG = "#ef6b6b"


def visible_showings(showings: list[Showing], now: datetime) -> list[Showing]:
    """Today's showings that haven't started, or started less than GRACE ago."""
    today = now.date()
    return [s for s in showings if s.starts_at.date() == today and now - s.starts_at < GRACE]


@dataclass(frozen=True)
class Slot:
    starts_at: datetime
    sold_out: bool


@dataclass(frozen=True)
class MovieGroup:
    title: str
    rating: str
    runtime_min: int
    slots: tuple[Slot, ...]


def group_by_movie(showings: list[Showing]) -> list[MovieGroup]:
    """One group per movie (A-Z), one slot per start time. Theaters aren't shown, so two
    screens at the same time become one slot that is sold out only when every screen is."""
    by_movie: dict[int, list[Showing]] = {}
    for s in showings:
        by_movie.setdefault(s.movie_id, []).append(s)
    groups = []
    for shows in by_movie.values():
        by_time: dict[datetime, list[Showing]] = {}
        for s in shows:
            by_time.setdefault(s.starts_at, []).append(s)
        slots = tuple(
            Slot(when, all(s.remaining == 0 for s in at_time)) for when, at_time in sorted(by_time.items())
        )
        first = shows[0]
        groups.append(MovieGroup(first.title, first.rating, first.runtime_min, slots))
    return sorted(groups, key=lambda g: g.title.casefold())


class Board(tk.Tk):
    def __init__(self, store: Store, fullscreen: bool = True):
        super().__init__()
        self.store = store
        self.title("Showtimes")
        self.configure(bg=BG)
        if fullscreen:
            self.attributes("-fullscreen", True)
            self.configure(cursor="none")
        else:
            self.geometry("1280x720")
        self.bind("<Escape>", lambda _e: self.destroy())

        self.scale = min(max(self.winfo_screenheight() / 1080, 0.6), 2.0) if fullscreen else 0.7
        px = lambda n, weight="normal": tkfont.Font(family="Helvetica", size=-round(n * self.scale), weight=weight)
        self.f = {
            "header": px(54, "bold"), "clock": px(40), "title": px(44, "bold"), "sub": px(24),
            "time": px(36, "bold"), "tag": px(17, "bold"), "empty": px(56, "bold"), "foot": px(24),
        }
        self.px = lambda n: round(n * self.scale)
        self.shows: list[Showing] = []
        self.pages: list[list[tk.Frame]] = []
        self.page = 0
        self.offline = False
        self._size = (0, 0)
        self._rendering = False
        self._render_again = False

        pad = self.px(48)
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=pad, pady=(self.px(28), self.px(14)))
        tk.Label(top, text="TODAY'S SHOWTIMES", bg=BG, fg=TEXT, font=self.f["header"]).pack(side="left")
        self.clock = tk.Label(top, bg=BG, fg=GOLD, font=self.f["clock"])
        self.clock.pack(side="right")

        self.rows = tk.Frame(self, bg=BG)
        self.rows.pack(fill="both", expand=True, padx=pad)
        self.rows.pack_propagate(False)
        self.rows.bind("<Configure>", self._on_resize)
        self.footer = tk.Label(self, bg=BG, fg=SUBTLE, font=self.f["foot"])
        self.footer.pack(pady=(4, self.px(14)))

        self._tick_count = 0
        self._tick()
        self.after(PAGE_SECONDS * 1000, self._rotate)

    # ---- timers ---------------------------------------------------------

    def _tick(self) -> None:
        now = datetime.now()
        self.clock.configure(text=f"{now:%A, %B} {now.day}    {fmt.clock(now)}")
        if self._tick_count % REFRESH_SECONDS == 0:
            self.reload()
        self._tick_count += 1
        self.after(1000, self._tick)

    def _rotate(self) -> None:
        if len(self.pages) > 1:
            self.page = (self.page + 1) % len(self.pages)
            self.render()
        self.after(PAGE_SECONDS * 1000, self._rotate)

    def reload(self) -> None:
        now = datetime.now()
        try:
            self.shows = visible_showings(self.store.showings(day=now.date()), now)
            self.offline = False
        except sqlite3.Error:
            self.offline = True  # keep showing the last good data
        self.render()

    def _on_resize(self, _event) -> None:
        size = (self.rows.winfo_width(), self.rows.winfo_height())
        if size != self._size:
            self._size = size
            self.render()

    # ---- drawing --------------------------------------------------------

    def render(self) -> None:
        if self._rendering:  # a resize event fired while measuring; redo once we're done
            self._render_again = True
            return
        self._rendering = True
        try:
            self._draw()
        finally:
            self._rendering = False
        if self._render_again:
            self._render_again = False
            self.render()

    def _draw(self) -> None:
        now = datetime.now()
        for w in self.rows.winfo_children():
            w.destroy()
        groups = group_by_movie(self.shows)
        if not groups:
            self.pages = []
            tk.Label(self.rows, text="No more showings today", bg=BG, fg=SUBTLE, font=self.f["empty"]).pack(expand=True)
        else:
            rows = [self._movie_row(g, now, ROW_A if i % 2 == 0 else ROW_B) for i, g in enumerate(groups)]
            self._paginate(rows)
        notes = []
        if len(self.pages) > 1:
            notes.append(f"Page {self.page + 1} of {len(self.pages)}")
        if self.offline:
            notes.append("Showtimes may be out of date")
        self.footer.configure(text="     ".join(notes) or " ")

    def _paginate(self, rows: list[tk.Frame]) -> None:
        self.rows.update_idletasks()
        gap = self.px(6)
        avail = max(self.rows.winfo_height(), 1)
        pages: list[list[tk.Frame]] = [[]]
        used = 0
        for row in rows:
            h = row.winfo_reqheight() + gap
            if pages[-1] and used + h > avail:
                pages.append([])
                used = 0
            pages[-1].append(row)
            used += h
        self.pages = pages
        self.page = min(self.page, len(pages) - 1)
        for i, page in enumerate(pages):
            for row in page:
                if i == self.page:
                    row.pack(fill="x", pady=(0, gap))
                else:
                    row.destroy()

    def _movie_row(self, group: MovieGroup, now: datetime, bg: str) -> tk.Frame:
        row = tk.Frame(self.rows, bg=bg)
        title_w = self.px(520)
        row.grid_columnconfigure(0, minsize=title_w)
        row.grid_columnconfigure(1, weight=1)

        info = tk.Frame(row, bg=bg)
        info.grid(row=0, column=0, sticky="w", padx=self.px(20), pady=self.px(12))
        tk.Label(info, text=group.title, bg=bg, fg=TEXT, font=self.f["title"], anchor="w",
                 justify="left", wraplength=title_w - self.px(40)).pack(anchor="w")
        tk.Label(info, text=fmt.movie_line(group.rating, group.runtime_min), bg=bg, fg=SUBTLE,
                 font=self.f["sub"]).pack(anchor="w")

        tile_w, tile_h, gap = self.px(190), self.px(112), self.px(12)
        tiles = tk.Frame(row, bg=bg)
        tiles.grid(row=0, column=1, sticky="w", padx=(0, self.px(12)), pady=self.px(10))
        usable = max(self.rows.winfo_width() - title_w - self.px(40), tile_w)
        per_line = max(1, usable // (tile_w + gap))
        for i, slot in enumerate(group.slots):
            tile = self._tile(tiles, slot, now, tile_w, tile_h)
            tile.grid(row=i // per_line, column=i % per_line, padx=(0, gap), pady=(0, gap) if len(group.slots) > per_line else 0)
        return row

    def _tile(self, parent, slot: Slot, now: datetime, w: int, h: int) -> tk.Frame:
        tile = tk.Frame(parent, width=w, height=h, bg=TILE_SOLD if slot.sold_out else TILE)
        tile.pack_propagate(False)
        tile.grid_propagate(False)
        inner = tk.Frame(tile, bg=tile["bg"])
        inner.place(relx=0.5, rely=0.5, anchor="center")
        if slot.sold_out:
            color = MUTED
        else:
            color = GOLD if slot.starts_at <= now else TEXT  # gold = already started
        tk.Label(inner, text=fmt.clock(slot.starts_at), bg=tile["bg"], fg=color, font=self.f["time"]).pack()
        if slot.sold_out:
            tk.Label(inner, text="SOLD OUT", bg=tile["bg"], fg=SOLD_TAG, font=self.f["tag"]).pack()
        return tile


def main() -> None:
    default_db = Path(__file__).resolve().parent.parent / "moviepos.db"
    parser = argparse.ArgumentParser(description="Customer showtimes display board")
    parser.add_argument("--db", default=str(default_db), help="POS database to read (default: ./moviepos.db)")
    parser.add_argument("--windowed", action="store_true", help="don't go full screen (for testing)")
    args = parser.parse_args()
    if not Path(args.db).is_file():
        sys.exit(f"Database not found: {args.db}\nStart the POS once (python3 -m moviepos) to create it.")
    store = Store(args.db, read_only=True)
    try:
        Board(store, fullscreen=not args.windowed).mainloop()
    finally:
        store.close()


if __name__ == "__main__":
    main()
