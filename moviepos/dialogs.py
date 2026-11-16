"""Modal dialogs. All are touch-sized and use on-screen input instead of the system keyboard."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from typing import Callable

from .keys import ENTER, key_char, shift_held
from .theme import ACCENT, BAD, BG, BTN, ERROR_FG, F, GOOD, PANEL, SUBTLE, TEXT
from .widgets import NumPad, PagedGrid, TextKeyboard, TouchButton
from . import fmt


class Dialog(tk.Toplevel):
    def __init__(self, master, title: str):
        super().__init__(master, bg=BG)
        self.parent = master.winfo_toplevel()
        self.title(title)
        self.transient(self.parent)
        self.resizable(False, False)
        self.result = None
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.withdraw()

    def run(self):
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.parent.winfo_rootx() + max((self.parent.winfo_width() - w) // 2, 0)
        y = self.parent.winfo_rooty() + max((self.parent.winfo_height() - h) // 2, 0)
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.wait_visibility()
        underneath = self.grab_current()  # a dialog that opened this one stays modal once we close
        self.grab_set()
        self.focus_set()
        self.wait_window(self)
        if underneath is not None and underneath.winfo_exists():
            underneath.grab_set()
            underneath.focus_force()
        else:
            self.parent.focus_force()  # the OS may leave no window focused when a dialog closes
        return self.result

    close_on_enter = False  # info-only dialogs close on Enter as well as Esc

    def handle_key(self, event) -> bool:
        if event.keysym == "Escape":
            self.cancel()
            return True
        if self.close_on_enter and event.keysym in ENTER:
            self.cancel()
            return True
        return False

    def finish(self, result=True) -> None:
        self.result = result
        self.destroy()

    def cancel(self) -> None:
        self.result = None
        self.destroy()

    def button_row(self, buttons: list[tuple[str, Callable, str]]) -> tk.Frame:
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=20, pady=(8, 20))
        for i, (text, cmd, color) in enumerate(buttons):
            row.grid_columnconfigure(i, weight=1, uniform="b")
            TouchButton(row, text, cmd, bg=color, pady=14).grid(row=0, column=i, sticky="ew", padx=6)
        return row


class MessageDialog(Dialog):
    def __init__(self, master, title, text, buttons):
        super().__init__(master, title)
        tk.Label(
            self, text=text, bg=BG, fg=TEXT, font=F["h2"] if len(text) < 60 else F["base"],
            wraplength=520, justify="left",
        ).pack(padx=30, pady=(30, 20))
        self.values = [value for _, value, _ in buttons]
        self.button_row([(label, lambda v=value: self.finish(v), color) for label, value, color in buttons])

    def handle_key(self, event) -> bool:
        if event.keysym in ENTER:
            self.finish(self.values[-1])  # the main action is always the last (right-hand) button
        elif event.keysym == "Escape":
            self.finish(self.values[0] if len(self.values) > 1 else self.values[-1])
        else:
            return False
        return True


def alert(master, text: str, title: str = "Notice") -> None:
    MessageDialog(master, title, text, [("OK", True, ACCENT)]).run()


def confirm(master, text: str, ok_text: str = "Confirm", title: str = "Please confirm", danger: bool = False) -> bool:
    buttons = [("Cancel", False, BTN), (ok_text, True, BAD if danger else GOOD)]
    return bool(MessageDialog(master, title, text, buttons).run())


class ChoiceDialog(Dialog):
    """Pick one of several (key, label) options."""

    def __init__(self, master, title: str, options: list[tuple]):
        super().__init__(master, title)
        tk.Label(self, text=title, bg=BG, fg=TEXT, font=F["h2"]).pack(padx=20, pady=(20, 8))
        grid = self.choices = PagedGrid(self, 2, 5, self._make, "Nothing to choose from", numbered=True)
        grid.set_items(options)
        grid.configure(width=720, height=420)
        grid.pack(padx=20, fill="both", expand=True)
        grid.grid_propagate(False)
        self.button_row([("Cancel", self.cancel, BTN)])

    def handle_key(self, event) -> bool:
        ch = key_char(event)
        if ch.isdigit() and ch != "0":
            self.choices.invoke(int(ch))
        elif event.keysym in ("Prior", "Next"):
            self.choices.page_by(-1 if event.keysym == "Prior" else 1)
        else:
            return super().handle_key(event)
        return True

    def _make(self, parent, option):
        key, label = option
        return TouchButton(parent, label, lambda k=key: self.finish(k), font=F["row"], wraplength=320)


def choose(master, title: str, options: list[tuple]):
    return ChoiceDialog(master, title, options).run()


class FormDialog(Dialog):
    """Text/number form driven entirely by on-screen keys.

    fields: dicts with key, label, kind ('text' | 'int' | 'money'), value, optional max length.
    on_submit(values: dict[str, str]) -> error message, or None when saved. The dialog stays open on error.
    """

    def __init__(self, master, title, fields, on_submit: Callable[[dict], str | None], ok_text="Save"):
        super().__init__(master, title)
        self.fields = {f["key"]: f for f in fields}
        self.values = {f["key"]: str(f.get("value", "")) for f in fields}
        self.on_submit = on_submit
        self.active = fields[0]["key"]
        self.fresh = False

        tk.Label(self, text=title, bg=BG, fg=TEXT, font=F["h2"]).pack(padx=24, pady=(20, 6), anchor="w")
        form = tk.Frame(self, bg=BG)
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure(1, weight=1)
        self.boxes: dict[str, TouchButton] = {}
        for i, f in enumerate(fields):
            tk.Label(form, text=f["label"], bg=BG, fg=SUBTLE, font=F["base"], anchor="w", width=16).grid(
                row=i, column=0, sticky="w", pady=4
            )
            box = TouchButton(form, "", lambda k=f["key"]: self.activate(k), anchor="w", font=F["row"], pady=8)
            box.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=4)
            self.boxes[f["key"]] = box

        self.error = tk.Label(self, text=" ", bg=BG, fg=ERROR_FG, font=F["base"], wraplength=640, justify="left")
        self.error.pack(padx=24, pady=(6, 0), anchor="w")
        tk.Label(
            self, text="Type with the keyboard or the keys below  ·  Tab / ↑ ↓ next field  ·  Enter save  ·  Esc cancel",
            bg=BG, fg=SUBTLE, font=F["small"],
        ).pack(padx=24, pady=(0, 2), anchor="w")

        self.kb_area = tk.Frame(self, bg=BG, width=760, height=290)
        self.kb_area.pack(padx=20, pady=4)
        self.kb_area.pack_propagate(False)
        self.text_kb = TextKeyboard(self.kb_area, self.type_char, self.backspace)
        self.num_kb = NumPad(self.kb_area, self.type_char, self.backspace, pady=8)
        self.button_row([("Cancel", self.cancel, BTN), (ok_text, self.submit, GOOD)])
        self.activate(self.active)

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event)
        names = list(self.fields)
        if key in ENTER:
            self.submit()
        elif key in ("Tab", "ISO_Left_Tab", "Up", "Down"):
            backwards = key in ("Up", "ISO_Left_Tab") or (key == "Tab" and shift_held(event))
            self.activate(names[(names.index(self.active) + (-1 if backwards else 1)) % len(names)])
        elif key == "BackSpace":
            self.backspace()
        elif ch:
            self.type_char(ch)
        else:
            return super().handle_key(event)
        return True

    def kind(self, key=None) -> str:
        return self.fields[key or self.active].get("kind", "text")

    def activate(self, key: str) -> None:
        self.active = key
        self.fresh = self.kind() != "text" and bool(self.values[key])
        self.text_kb.pack_forget()
        self.num_kb.pack_forget()
        if self.kind() == "text":
            self.text_kb.pack(fill="both", expand=True)
        else:
            self.num_kb.set_allow_dot(self.kind() == "money")
            self.num_kb.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self) -> None:
        for key, box in self.boxes.items():
            is_active = key == self.active
            shown = self.values[key] + ("▏" if is_active else "")
            box.set(text=shown or " ", bg=ACCENT if is_active else BTN)
        if self.kind() == "text":
            current = self.values[self.active]
            self.text_kb.set_shift(current == "" or current.endswith(" "))

    def type_char(self, ch: str) -> None:
        kind, cur = self.kind(), self.values[self.active]
        if self.fresh:
            cur, self.fresh = "", False
        if kind == "int" and not ch.isdigit():
            return
        if kind == "money":
            if not (ch.isdigit() or ch == "."):
                return
            if ch == "." and "." in cur:
                return
            if "." in cur and len(cur.split(".")[1]) >= 2:
                return
        if len(cur) >= self.fields[self.active].get("max", 60):
            return
        self.values[self.active] = cur + ch
        self.refresh()

    def backspace(self) -> None:
        self.values[self.active] = "" if self.fresh else self.values[self.active][:-1]
        self.fresh = False
        self.refresh()

    def submit(self) -> None:
        error = self.on_submit({k: v.strip() for k, v in self.values.items()})
        if error:
            self.error.configure(text=error)
        else:
            self.finish(True)


def edit_form(master, title, fields, on_submit, ok_text="Save") -> bool:
    return bool(FormDialog(master, title, fields, on_submit, ok_text).run())


class ShowtimeDialog(Dialog):
    """Add or edit a showtime: movie, theater, date and time via buttons only."""

    def __init__(self, master, store, showing=None, day: date | None = None):
        super().__init__(master, "Edit showtime" if showing else "Add showtime")
        self.store, self.showing = store, showing
        self.movies = {m.id: m for m in store.list_movies()}
        self.theaters = {t.id: t for t in store.list_theaters()}
        start = showing.starts_at if showing else datetime.combine(day or date.today(), datetime.min.time())
        self.movie_id = showing.movie_id if showing else next(iter(self.movies))
        self.theater_id = showing.theater_id if showing else next(iter(self.theaters))
        self.day = start.date()
        self.hour12 = (start.hour % 12) or 12 if showing else 7
        self.minute = start.minute if showing else 0
        self.pm = start.hour >= 12 if showing else True
        self.repeat = 1
        self.time_digits = ""

        tk.Label(self, text=self.title(), bg=BG, fg=TEXT, font=F["h2"]).pack(padx=24, pady=(20, 10), anchor="w")
        form = tk.Frame(self, bg=BG)
        form.pack(padx=20, fill="x")
        form.grid_columnconfigure(1, weight=1)

        def label(row, text):
            tk.Label(form, text=text, bg=BG, fg=SUBTLE, font=F["base"], anchor="w", width=14).grid(
                row=row, column=0, sticky="w", pady=8
            )

        label(0, "Movie")
        self.movie_btn = TouchButton(form, "", self.pick_movie, anchor="w", font=F["row"], wraplength=480)
        self.movie_btn.grid(row=0, column=1, sticky="ew", pady=6)
        label(1, "Theater")
        self.theater_btn = TouchButton(form, "", self.pick_theater, anchor="w", font=F["row"])
        self.theater_btn.grid(row=1, column=1, sticky="ew", pady=6)

        label(2, "Date")
        drow = tk.Frame(form, bg=BG)
        drow.grid(row=2, column=1, sticky="ew", pady=6)
        drow.grid_columnconfigure(1, weight=1)
        TouchButton(drow, "◀", lambda: self.shift_day(-1), width=4).grid(row=0, column=0)
        self.day_lbl = tk.Label(drow, bg=BG, fg=TEXT, font=F["row"])
        self.day_lbl.grid(row=0, column=1)
        TouchButton(drow, "▶", lambda: self.shift_day(1), width=4).grid(row=0, column=2)

        label(3, "Start time")
        trow = tk.Frame(form, bg=BG)
        trow.grid(row=3, column=1, sticky="w", pady=6)
        steppers = [
            ("hour_lbl", lambda: self.step_hour(1), lambda: self.step_hour(-1)),
            ("min_lbl", lambda: self.step_min(5), lambda: self.step_min(-5)),
            ("ampm_lbl", self.toggle_pm, self.toggle_pm),
        ]
        for col, (attr, up, down) in enumerate(steppers):
            cell = tk.Frame(trow, bg=BG)
            cell.grid(row=0, column=col * 2, padx=6)
            TouchButton(cell, "▲", up, width=5, pady=4).pack()
            lbl = tk.Label(cell, bg=BG, fg=TEXT, font=F["h1"])
            lbl.pack(pady=2)
            setattr(self, attr, lbl)
            TouchButton(cell, "▼", down, width=5, pady=4).pack()
            if col == 0:
                tk.Label(trow, text=":", bg=BG, fg=TEXT, font=F["h1"]).grid(row=0, column=1)

        if not showing:
            label(4, "Repeat daily for")
            rrow = tk.Frame(form, bg=BG)
            rrow.grid(row=4, column=1, sticky="w", pady=6)
            TouchButton(rrow, "−", lambda: self.step_repeat(-1), width=4).pack(side="left")
            self.repeat_lbl = tk.Label(rrow, bg=BG, fg=TEXT, font=F["row"], width=10)
            self.repeat_lbl.pack(side="left")
            TouchButton(rrow, "+", lambda: self.step_repeat(1), width=4).pack(side="left")

        self.error = tk.Label(self, text=" ", bg=BG, fg=ERROR_FG, font=F["base"], wraplength=620, justify="left")
        self.error.pack(padx=24, pady=(6, 0), anchor="w")
        tk.Label(
            self, bg=BG, fg=SUBTLE, font=F["small"], wraplength=620, justify="left",
            text="Keys:  M movie  ·  T theater  ·  ◀ ▶ day  ·  type the time (7 15)  ·  A / P  AM / PM  ·  "
            "↑ ↓ hour  ·  PgUp PgDn minutes  ·  + − repeat days  ·  Enter save  ·  Esc cancel",
        ).pack(padx=24, pady=(0, 2), anchor="w")
        self.button_row([("Cancel", self.cancel, BTN), ("Save", self.submit, GOOD)])
        self.refresh()

    def refresh(self) -> None:
        movie = self.movies[self.movie_id]
        self.movie_btn.set(text=f"{movie.title}  ({fmt.movie_line(movie.rating, movie.runtime_min)})")
        theater = self.theaters[self.theater_id]
        self.theater_btn.set(text=f"{theater.name}  ({theater.capacity} seats)")
        self.day_lbl.configure(text=f"{self.day:%a %b} {self.day.day}, {self.day.year}")
        self.hour_lbl.configure(text=str(self.hour12))
        self.min_lbl.configure(text=f"{self.minute:02d}")
        self.ampm_lbl.configure(text="PM" if self.pm else "AM")
        if not self.showing:
            self.repeat_lbl.configure(text=f"{self.repeat} day{'s' if self.repeat != 1 else ''}")

    def start(self) -> datetime:
        hour = self.hour12 % 12 + (12 if self.pm else 0)
        return datetime.combine(self.day, datetime.min.time()).replace(hour=hour, minute=self.minute)

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event).lower()
        if key in ENTER:
            self.submit()
        elif ch == "m":
            self.pick_movie()
        elif ch == "t":
            self.pick_theater()
        elif key == "Left":
            self.shift_day(-1)
        elif key == "Right":
            self.shift_day(1)
        elif key == "Up":
            self.step_hour(1)
        elif key == "Down":
            self.step_hour(-1)
        elif key == "Prior":
            self.step_min(5)
        elif key == "Next":
            self.step_min(-5)
        elif ch in ("a", "p"):
            self.pm = ch == "p"
            self.refresh()
        elif ch in ("+", "=") and not self.showing:
            self.step_repeat(1)
        elif ch == "-" and not self.showing:
            self.step_repeat(-1)
        elif ch.isdigit():
            self.type_time(ch)
        elif key == "BackSpace":
            self.time_digits = self.time_digits[:-1]
            self.apply_typed_time()
        else:
            return super().handle_key(event)
        return True

    def type_time(self, digit: str) -> None:
        """Type the time as digits: 7 -> 7:00, 7 1 5 -> 7:15, 1 9 3 0 -> 19:30 (hours over 12 mean 24-hour)."""
        self.time_digits = (self.time_digits + digit) if len(self.time_digits) < 4 else digit
        self.apply_typed_time()

    def apply_typed_time(self) -> None:
        """Apply the typed digits when they make a real time; otherwise keep waiting for more digits."""
        d = self.time_digits
        if not d:
            return
        if len(d) <= 2:
            hour, minute = int(d), 0
        elif len(d) == 3:
            hour, minute = int(d[0]), int(d[1:])
        else:
            hour, minute = int(d[:2]), int(d[2:])
        if hour > 23 or minute > 59:
            return
        if hour > 12:
            hour, self.pm = hour - 12, True
        elif hour == 0:
            hour, self.pm = 12, False
        self.hour12, self.minute = hour, minute
        self.refresh()

    def pick_movie(self) -> None:
        key = choose(self, "Choose a movie", [(m.id, m.title) for m in self.movies.values()])
        if key is not None:
            self.movie_id = key
            self.refresh()

    def pick_theater(self) -> None:
        key = choose(self, "Choose a theater", [(t.id, f"{t.name} · {t.capacity} seats") for t in self.theaters.values()])
        if key is not None:
            self.theater_id = key
            self.refresh()

    def shift_day(self, delta: int) -> None:
        self.day += timedelta(days=delta)
        self.refresh()

    def step_hour(self, delta: int) -> None:
        self.time_digits = ""
        self.hour12 = (self.hour12 - 1 + delta) % 12 + 1
        self.refresh()

    def step_min(self, delta: int) -> None:
        self.time_digits = ""
        self.minute = (self.minute + delta) % 60
        self.refresh()

    def toggle_pm(self) -> None:
        self.pm = not self.pm
        self.refresh()

    def step_repeat(self, delta: int) -> None:
        self.repeat = min(max(self.repeat + delta, 1), 30)
        self.refresh()

    def submit(self) -> None:
        try:
            if self.showing:
                self.store.update_showtime(self.showing.id, self.movie_id, self.theater_id, self.start())
            else:
                self.store.add_showtimes(self.movie_id, self.theater_id, self.start(), self.repeat)
        except ValueError as e:
            self.error.configure(text=str(e))
            return
        self.finish(True)
