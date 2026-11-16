"""Settings screen: manage movies, theaters (screens + capacity), showtimes, ticket prices, and the concessions menu."""
from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta

from . import fmt
from .dialogs import ShowtimeDialog, alert, confirm, edit_form
from .keys import ENTER, key_char, shift_held
from .phone_ui import PhoneTab
from .store import MAX_CONCESSION_NAME, MAX_VENUE_NAME
from .theme import ACCENT, BAD, BG, BTN, F, GOOD, PANEL, SUBTLE, TEXT
from .widgets import SelectList, TouchButton


class CrudTab(tk.Frame):
    can_add = can_edit = can_delete = True

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app, self.store = app, app.store
        side = tk.Frame(self, bg=BG, width=210)
        side.pack(side="right", fill="y", padx=(12, 0))
        side.pack_propagate(False)
        main = tk.Frame(self, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self.header = tk.Frame(main, bg=BG)
        self.header.pack(fill="x")
        self.build_header(self.header)
        self.list = SelectList(main, rows=7, on_select=lambda _k: self._sync(), empty_text=self.empty_text)
        self.list.pack(fill="both", expand=True)
        self.buttons = {}
        for name, cmd, color, enabled in [
            ("Add", self._add, GOOD, self.can_add),
            ("Edit", self._edit, ACCENT, self.can_edit),
            ("Delete", self._delete, BAD, self.can_delete),
        ]:
            if enabled:
                b = TouchButton(side, name, cmd, bg=color, pady=18)
                b.pack(fill="x", pady=(0, 10))
                self.buttons[name] = b
        keys = "Keys: ↑ ↓ select" + ("  A add" if self.can_add else "") + "  E / Enter edit" + ("  Del delete" if self.can_delete else "")
        self.hint = tk.Label(side, text=f"{self.hint_text}\n\n{keys}".strip(), bg=BG, fg=SUBTLE, font=F["small"], wraplength=200, justify="left")
        self.hint.pack(side="bottom", anchor="w")
        self._sync()

    empty_text = "Nothing here yet — tap Add"
    hint_text = ""

    def build_header(self, header) -> None:
        pass

    def items(self) -> list[tuple]:
        raise NotImplementedError

    def refresh(self) -> None:
        self.list.set_items(self.items(), keep_selection=True)
        self._sync()

    def _sync(self) -> None:
        has = self.list.selected is not None
        for name in ("Edit", "Delete"):
            if name in self.buttons:
                self.buttons[name].set(enabled=has)

    def _add(self) -> None:
        if self.add():
            self.refresh()

    def _edit(self) -> None:
        if self.list.selected is not None and self.edit(self.list.selected):
            self.refresh()

    def _delete(self) -> None:
        key = self.list.selected
        if key is None or not confirm(self, self.delete_prompt(key), "Delete", danger=True):
            return
        try:
            self.delete(key)
        except ValueError as e:
            alert(self, str(e), "Can't delete")
        self.list.selected = None
        self.refresh()

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event)
        if key in ("Up", "Down"):
            self.list.move(-1 if key == "Up" else 1)
        elif key in ("Prior", "Next"):
            self.list.page_by(-1 if key == "Prior" else 1)
        elif ch in ("a", "A") and self.can_add:
            self._add()
        elif (ch in ("e", "E") or key in ENTER) and self.can_edit:
            self._edit()
        elif key in ("Delete", "BackSpace") and self.can_delete:
            self._delete()
        else:
            return False
        return True

    def add(self) -> bool:
        return False

    def edit(self, key) -> bool:
        return False

    def delete(self, key) -> None:
        pass

    def delete_prompt(self, key) -> str:
        return "Delete this item?"


class MoviesTab(CrudTab):
    hint_text = "A movie can only be deleted after all of its showtimes are removed."

    def items(self):
        return [(m.id, f"{m.title}   ·   {fmt.movie_line(m.rating, m.runtime_min)}") for m in self.store.list_movies()]

    def _form(self, title, movie=None) -> bool:
        fields = [
            {"key": "title", "label": "Title", "value": movie.title if movie else ""},
            {"key": "rating", "label": "Rating", "value": movie.rating if movie else "", "max": 8},
            {"key": "runtime", "label": "Runtime (min)", "kind": "int", "value": movie.runtime_min if movie else 120, "max": 3},
        ]

        def submit(v):
            try:
                runtime = fmt.parse_int(v["runtime"], "Runtime")
                if movie:
                    self.store.update_movie(movie.id, v["title"], v["rating"], runtime)
                else:
                    self.store.add_movie(v["title"], v["rating"], runtime)
            except ValueError as e:
                return str(e)

        return edit_form(self, title, fields, submit)

    def add(self):
        return self._form("Add movie")

    def edit(self, key):
        return self._form("Edit movie", next(m for m in self.store.list_movies() if m.id == key))

    def delete(self, key):
        self.store.delete_movie(key)

    def delete_prompt(self, key):
        return "Delete this movie?"


class TheatersTab(CrudTab):
    hint_text = "Capacity can't be lowered below the seats already sold for an upcoming showing."

    def items(self):
        return [(t.id, f"{t.name}   ·   {t.capacity} seats") for t in self.store.list_theaters()]

    def _form(self, title, theater=None) -> bool:
        fields = [
            {"key": "name", "label": "Name", "value": theater.name if theater else f"Theater {len(self.store.list_theaters()) + 1}"},
            {"key": "capacity", "label": "Capacity (seats)", "kind": "int", "value": theater.capacity if theater else "", "max": 4},
        ]

        def submit(v):
            try:
                cap = fmt.parse_int(v["capacity"], "Capacity")
                if theater:
                    self.store.update_theater(theater.id, v["name"], cap)
                else:
                    self.store.add_theater(v["name"], cap)
            except ValueError as e:
                return str(e)

        return edit_form(self, title, fields, submit)

    def add(self):
        return self._form("Add theater")

    def edit(self, key):
        return self._form("Edit theater", next(t for t in self.store.list_theaters() if t.id == key))

    def delete(self, key):
        self.store.delete_theater(key)

    def delete_prompt(self, key):
        return "Delete this theater?"


class ShowtimesTab(CrudTab):
    empty_text = "No showtimes on this day"
    hint_text = "Showtimes with tickets sold can't be edited or deleted."

    def build_header(self, header) -> None:
        self.day = date.today()
        TouchButton(header, "◀", lambda: self._shift(-1), width=4, pady=6).pack(side="left")
        TouchButton(header, "▶", lambda: self._shift(1), width=4, pady=6).pack(side="right")
        self.day_lbl = tk.Label(header, bg=BG, fg=TEXT, font=F["h2"])
        self.day_lbl.pack(expand=True)

    def handle_key(self, event) -> bool:
        if event.keysym in ("Left", "Right"):
            self._shift(-1 if event.keysym == "Left" else 1)
            return True
        return super().handle_key(event)

    def _shift(self, delta: int) -> None:
        self.day += timedelta(days=delta)
        self.list.selected = None
        self.refresh()

    def items(self):
        self.day_lbl.configure(text=f"{fmt.day_label(self.day)}")
        return [
            (s.id, f"{fmt.clock(s.starts_at)}   {s.title}   ·   {s.theater_name}   ·   {s.sold}/{s.capacity} sold")
            for s in self.store.showings(day=self.day)
        ]

    def _need_setup(self) -> bool:
        if not self.store.list_movies() or not self.store.list_theaters():
            alert(self, "Add at least one movie and one theater first.")
            return True
        return False

    def add(self):
        return not self._need_setup() and bool(ShowtimeDialog(self, self.store, day=self.day).run())

    def edit(self, key):
        return bool(ShowtimeDialog(self, self.store, self.store.get_showing(key)).run())

    def delete(self, key):
        self.store.delete_showtime(key)

    def delete_prompt(self, key):
        return "Delete this showtime?"


class PricesTab(CrudTab):
    can_add = can_delete = False
    hint_text = "New prices apply to future sales only. Pass is free by default."

    def items(self):
        return [(n, f"{n}   ·   {fmt.money(c) if c else 'Free'}") for n, c in self.store.ticket_prices().items()]

    def edit(self, key):
        def submit(v):
            try:
                self.store.set_price(key, fmt.parse_money(v["price"]))
            except ValueError as e:
                return str(e)

        current = self.store.ticket_prices()[key]
        fields = [{"key": "price", "label": f"{key} price ($)", "kind": "money", "value": f"{current // 100}.{current % 100:02d}", "max": 7}]
        return edit_form(self, f"{key} ticket price", fields, submit)


class ConcessionsTab(CrudTab):
    hint_text = "Items appear on the Concessions screen in this order. New prices apply to future orders only."
    empty_text = "No concession items — tap Add"

    def items(self):
        return [(i.id, f"{i.name}   ·   {fmt.money(i.price_cents) if i.price_cents else 'Free'}") for i in self.store.list_concessions()]

    def _form(self, title, item=None) -> bool:
        price = item.price_cents if item else 0
        fields = [
            {"key": "name", "label": "Item name", "value": item.name if item else "", "max": MAX_CONCESSION_NAME},
            {"key": "price", "label": "Price ($)", "kind": "money", "value": f"{price // 100}.{price % 100:02d}" if item else "", "max": 7},
        ]

        def submit(v):
            try:
                cents = fmt.parse_money(v["price"])
                if item:
                    self.store.update_concession(item.id, v["name"], cents)
                else:
                    self.store.add_concession(v["name"], cents)
            except ValueError as e:
                return str(e)

        return edit_form(self, title, fields, submit)

    def add(self):
        return self._form("Add concession item")

    def edit(self, key):
        return self._form("Edit concession item", next(i for i in self.store.list_concessions() if i.id == key))

    def delete(self, key):
        self.store.delete_concession(key)

    def delete_prompt(self, key):
        return "Remove this item from the concessions menu?"


class VenueTab(tk.Frame):
    """The theater's name, printed at the top of every ticket."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.store = app.store
        tk.Label(self, text="Theater name", bg=BG, fg=TEXT, font=F["h1"], anchor="w").pack(fill="x")
        tk.Label(
            self, text="Printed at the top of every ticket.", bg=BG, fg=SUBTLE, font=F["base"], anchor="w"
        ).pack(fill="x", pady=(2, 18))
        self.name_lbl = tk.Label(self, bg=PANEL, fg=TEXT, font=F["h1"], anchor="w", padx=24, pady=28)
        self.name_lbl.pack(fill="x")
        TouchButton(self, "Rename", self._rename, bg=ACCENT, pady=18).pack(anchor="w", pady=18)

    def handle_key(self, event) -> bool:
        if event.keysym in ENTER or key_char(event) in ("r", "R"):
            self._rename()
            return True
        return False

    def refresh(self) -> None:
        self.name_lbl.configure(text=self.store.venue_name())

    def _rename(self) -> None:
        def submit(v):
            try:
                self.store.set_venue_name(v["name"])
            except ValueError as e:
                return str(e)

        fields = [{"key": "name", "label": "Theater name", "value": self.store.venue_name(), "max": MAX_VENUE_NAME}]
        if edit_form(self, "Rename theater", fields, submit):
            self.refresh()


class SettingsScreen(tk.Frame):
    TABS = [("Movies", MoviesTab), ("Theaters", TheatersTab), ("Showtimes", ShowtimesTab), ("Prices", PricesTab), ("Concessions", ConcessionsTab), ("Venue Name", VenueTab), ("Phone App", PhoneTab)]

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        nav = tk.Frame(self, bg=BG, width=200)
        nav.pack(side="left", fill="y", padx=(16, 8), pady=12)
        nav.pack_propagate(False)
        self.holder = tk.Frame(self, bg=BG)
        self.holder.pack(side="left", fill="both", expand=True, padx=(8, 16), pady=12)
        self.tabs, self.nav_btns = {}, {}
        for name, cls in self.TABS:
            self.nav_btns[name] = TouchButton(nav, name, lambda n=name: self.show_tab(n), pady=18)
            self.nav_btns[name].pack(fill="x", pady=(0, 8))
            self.tabs[name] = cls(self.holder, app)
        self.current = self.TABS[0][0]

    def refresh(self) -> None:
        self.show_tab(self.current)

    def handle_key(self, event) -> bool:
        names = [name for name, _ in self.TABS]
        if event.keysym in ("Tab", "ISO_Left_Tab"):
            backwards = event.keysym == "ISO_Left_Tab" or shift_held(event)
            self.show_tab(names[(names.index(self.current) + (-1 if backwards else 1)) % len(names)])
            return True
        handler = getattr(self.tabs[self.current], "handle_key", None)
        return bool(handler and handler(event))

    def show_tab(self, name: str) -> None:
        self.current = name
        for n, tab in self.tabs.items():
            tab.pack_forget()
            self.nav_btns[n].set(bg=ACCENT if n == name else BTN)
        self.tabs[name].pack(fill="both", expand=True)
        self.tabs[name].refresh()
