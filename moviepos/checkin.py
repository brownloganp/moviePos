"""Ticket taker screen: scan (or type) a ticket ID and check the party in."""
from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta

from . import fmt
from .dialogs import Dialog, alert, confirm
from .keys import ENTER, key_char
from .phone_ui import show_phone_dialog
from .theme import ACCENT, BAD, BG, BTN, F, GOOD, PANEL, SUBTLE, TEXT, WARN
from .widgets import NumPad, TouchButton

MAX_DIGITS = 12
GOOD_FG = "#4ade80"


class CheckInCountsDialog(Dialog):
    """How many tickets have been checked in, per showing, for one day."""

    PER_PAGE = 6

    def __init__(self, master, store):
        super().__init__(master, "Check-in counts")
        self.store, self.day, self.page = store, date.today(), 0
        self.rows: list = []
        self.close_on_enter = True

        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=20, pady=(20, 8))
        TouchButton(nav, "◀", lambda: self._move_day(-1), width=4, pady=8).pack(side="left")
        TouchButton(nav, "▶", lambda: self._move_day(1), width=4, pady=8).pack(side="right")
        self.day_lbl = tk.Label(nav, bg=BG, fg=TEXT, font=F["h2"])
        self.day_lbl.pack(expand=True)
        self.total_lbl = tk.Label(self, bg=PANEL, fg=TEXT, font=F["h1"], pady=10)
        self.total_lbl.pack(fill="x", padx=20)

        self.list = tk.Frame(self, bg=BG, width=700, height=self.PER_PAGE * 62 + 8)
        self.list.pack(padx=20, pady=(8, 0))
        self.list.pack_propagate(False)

        pager = tk.Frame(self, bg=BG)
        pager.pack(fill="x", padx=20, pady=(6, 0))
        self.prev_btn = TouchButton(pager, "Previous", lambda: self._move_page(-1), pady=6, font=F["base"])
        self.prev_btn.pack(side="left")
        self.next_btn = TouchButton(pager, "More", lambda: self._move_page(1), pady=6, font=F["base"])
        self.next_btn.pack(side="right")
        self.page_lbl = tk.Label(pager, bg=BG, fg=SUBTLE, font=F["base"])
        self.page_lbl.pack(expand=True)

        self.button_row([("Close", self.cancel, BTN)])
        self._load()

    def handle_key(self, event) -> bool:
        if event.keysym == "Left":
            self._move_day(-1)
        elif event.keysym == "Right":
            self._move_day(1)
        elif event.keysym in ("Prior", "Next"):
            self._move_page(-1 if event.keysym == "Prior" else 1)
        else:
            return super().handle_key(event)
        return True

    def _move_day(self, delta: int) -> None:
        self.day += timedelta(days=delta)
        self._load()

    def _move_page(self, delta: int) -> None:
        self.page = min(max(self.page + delta, 0), self._last_page())
        self._render()

    def _last_page(self) -> int:
        return max((len(self.rows) - 1) // self.PER_PAGE, 0)

    def _load(self) -> None:
        self.rows, self.page = self.store.checkin_counts(self.day), 0
        self._render()

    def _render(self) -> None:
        sold, admitted = sum(r.sold for r in self.rows), sum(r.checked_in for r in self.rows)
        self.day_lbl.configure(text=fmt.day_label(self.day))
        self.total_lbl.configure(text=f"{admitted} of {sold} checked in" if sold else "No tickets sold")
        for w in self.list.winfo_children():
            w.destroy()
        if not self.rows:
            tk.Label(self.list, text="No tickets sold for this day.", bg=BG, fg=SUBTLE, font=F["row"]).pack(pady=40)
        first = self.page * self.PER_PAGE
        for r in self.rows[first : first + self.PER_PAGE]:
            show = r.showing
            row = tk.Frame(self.list, bg=PANEL)
            row.pack(fill="x", pady=3)
            text = tk.Frame(row, bg=PANEL)
            text.pack(side="left", padx=14, pady=6)
            tk.Label(text, text=show.title, bg=PANEL, fg=TEXT, font=F["row"], anchor="w").pack(fill="x")
            tk.Label(
                text, text=f"{fmt.clock(show.starts_at)}  ·  {show.theater_name}", bg=PANEL, fg=SUBTLE, font=F["small"], anchor="w"
            ).pack(fill="x")
            done = r.sold > 0 and r.waiting == 0
            tk.Label(
                row, text=f"{r.checked_in} of {r.sold}", bg=PANEL, fg=GOOD_FG if done else TEXT, font=F["h2"]
            ).pack(side="right", padx=16)
        pages = self._last_page() + 1
        self.page_lbl.configure(text=f"Page {self.page + 1} of {pages}" if pages > 1 else "")
        self.prev_btn.set(enabled=self.page > 0)
        self.next_btn.set(enabled=self.page < pages - 1)


class CheckInScreen(tk.Frame):
    """A keyboard-wedge barcode scanner types the ID followed by Enter, so physical digits + Enter work
    exactly like the on-screen pad."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app, self.store = app, app.store
        self.digits = ""
        self.sale = None
        self.notice = ""  # shown instead of a ticket (e.g. not found)
        self.just_admitted = 0
        self.admit = 0
        self.grid_columnconfigure(0, weight=1, uniform="cols")
        self.grid_columnconfigure(1, weight=2, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=12)
        tk.Label(left, text="SCAN TICKET OR ENTER ID", bg=BG, fg=SUBTLE, font=F["small"], anchor="w").pack(fill="x")
        self.id_lbl = tk.Label(left, bg=PANEL, fg=TEXT, font=F["h1"], anchor="e", padx=14, pady=10)
        self.id_lbl.pack(fill="x", pady=(2, 8))
        NumPad(left, self._key, self._back, allow_dot=False, pady=12).pack(fill="both", expand=True)
        TouchButton(left, "Look up", self.lookup, bg=ACCENT, pady=16).pack(fill="x", pady=(8, 0))
        TouchButton(left, "Check-in counts", self.show_counts, pady=8, font=F["base"]).pack(fill="x", pady=(8, 0))
        TouchButton(left, "Phone check-in (QR code)", lambda: show_phone_dialog(self, app), pady=8, font=F["base"]).pack(
            fill="x", pady=(8, 0)
        )

        self.panel = tk.Frame(self, bg=PANEL)
        self.panel.grid(row=0, column=1, sticky="nsew", padx=(8, 16), pady=12)
        self.banner = tk.Label(self.panel, font=F["h1"], pady=22, wraplength=640)
        self.banner.pack(fill="x")
        self.details = tk.Label(self.panel, bg=PANEL, fg=TEXT, font=F["row"], anchor="nw", justify="left", wraplength=640)
        self.details.pack(fill="both", expand=True, padx=24, pady=12)
        self.warning = tk.Label(self.panel, bg=PANEL, fg="#fbbf24", font=F["base"], anchor="w", justify="left", wraplength=640)
        self.warning.pack(fill="x", padx=24)

        self.controls = tk.Frame(self.panel, bg=PANEL)
        self.controls.pack(fill="x", padx=24, pady=(8, 20), side="bottom")
        stepper = tk.Frame(self.controls, bg=PANEL)
        stepper.pack(fill="x", pady=(0, 10))
        tk.Label(stepper, text="People checking in now", bg=PANEL, fg=SUBTLE, font=F["row"]).pack(side="left")
        TouchButton(stepper, "+", lambda: self._step(1), width=4, font=F["key"], pady=6, bg=ACCENT).pack(side="right")
        self.admit_lbl = tk.Label(stepper, bg=PANEL, fg=TEXT, font=F["h1"], width=3)
        self.admit_lbl.pack(side="right")
        TouchButton(stepper, "−", lambda: self._step(-1), width=4, font=F["key"], pady=6).pack(side="right")
        self.stepper = stepper
        self.go_btn = TouchButton(self.controls, "Check in", self.check_in, bg=GOOD, pady=20)
        self.go_btn.pack(fill="x")
        self.undo_btn = TouchButton(self.controls, "Undo check-ins", self.undo, pady=10, font=F["base"])
        self.undo_btn.pack(fill="x", pady=(10, 0))

        tk.Label(
            left, text="Scanner or keyboard: type the ID, Enter look up\nSpace check in  ·  + − count  ·  U undo  ·  C counts  ·  Esc clear",
            bg=BG, fg=SUBTLE, font=F["small"], justify="left",
        ).pack(fill="x", pady=(8, 0))
        self._render()

    def refresh(self) -> None:
        if self.sale:
            self.sale = self.store.get_sale(self.sale.id)
            self.admit = min(max(self.admit, 1), max(self.sale.not_checked_in, 1))
        self._render()

    # ---- input ----------------------------------------------------------

    def handle_key(self, event) -> bool:
        """A keyboard-wedge scanner types the digits then Enter. Check-in itself is Space, never Enter,
        so a scanner that sends Enter twice can't admit anyone by accident."""
        key, ch = event.keysym, key_char(event)
        if key in ENTER:
            self.lookup()
        elif ch.isdigit():
            self._key(ch)
        elif key == "BackSpace":
            self._back()
        elif ch == " ":
            self.check_in()
        elif ch in ("+", "="):
            self._step(1)
        elif ch == "-":
            self._step(-1)
        elif ch in ("u", "U"):
            self.undo()
        elif ch in ("c", "C"):
            self.show_counts()
        elif key == "Escape":
            self.digits, self.sale, self.notice, self.just_admitted = "", None, "", 0
            self._sync_id()
            self._render()
        else:
            return False
        return True

    def _key(self, ch: str) -> None:
        if len(self.digits) < MAX_DIGITS:
            self.digits += ch
            self._sync_id()

    def _back(self) -> None:
        self.digits = self.digits[:-1]
        self._sync_id()

    def _sync_id(self) -> None:
        self.id_lbl.configure(text=self.digits or " ")

    def lookup(self) -> None:
        if not self.digits:
            return
        number = int(self.digits)
        self.digits = ""
        self._sync_id()
        self.just_admitted = 0
        self.sale = self.store.get_sale(number)
        if self.sale is None:
            self.notice = f"No ticket with ID {fmt.tx_id(number)}"
        else:
            self.notice = ""
            self.admit = max(self.sale.not_checked_in, 1)  # default: the whole party
        self._render()

    # ---- actions --------------------------------------------------------

    def _step(self, delta: int) -> None:
        if self.sale:
            self.admit = min(max(self.admit + delta, 1), self.sale.not_checked_in)
            self._render()

    def check_in(self) -> None:
        s = self.sale
        if s is None or s.status != "sold" or s.not_checked_in == 0:
            return
        show_day = s.showing.starts_at.date()
        if show_day != date.today() and not confirm(
            self, f"This ticket is for {fmt.short_day(show_day)}, not today.\nCheck in anyway?", "Check in"
        ):
            return
        try:
            self.sale = self.store.check_in(s.id, self.admit)
        except ValueError as e:
            alert(self, str(e), "Can't check in")
            self.sale = self.store.get_sale(s.id)
            self._render()
            return
        self.just_admitted = self.admit
        self.admit = max(self.sale.not_checked_in, 1)
        self._render()

    def show_counts(self) -> None:
        CheckInCountsDialog(self, self.store).run()

    def undo(self) -> None:
        s = self.sale
        if s is None or s.status != "sold" or s.checked_in == 0:
            return
        if not confirm(self, f"Reset check-in for ticket {fmt.tx_id(s.id)}?\n{s.checked_in} checked in will be cleared.", "Undo", danger=True):
            return
        self.sale = self.store.set_checked_in(s.id, 0)
        self.just_admitted = 0
        self.admit = self.sale.not_checked_in
        self._render()

    # ---- display --------------------------------------------------------

    def _banner(self, text: str, color: str) -> None:
        self.banner.configure(text=text, bg=color, fg=TEXT)

    def _render(self) -> None:
        s = self.sale
        self.warning.configure(text="")
        self.controls.pack_forget()
        if s is None:
            if self.notice:
                self._banner(self.notice.upper(), BAD)
                self.details.configure(text="Check the number and try again, or look it up under Returns.")
            else:
                self._banner("READY TO SCAN", PANEL)
                self.banner.configure(fg=SUBTLE)
                self.details.configure(text="Scan the barcode on the ticket,\nor type the ID and tap Look up.")
            return

        sh = s.showing
        lines = [
            f"Ticket #{fmt.tx_id(s.id)}",
            sh.title,
            f"{fmt.short_day(sh.starts_at)}  ·  {fmt.clock(sh.starts_at)}  ·  {sh.theater_name}",
            "",
            *(f"{i.qty} × {i.ticket_type}" for i in s.items),
            "",
            f"Checked in: {s.checked_in} of {s.ticket_count}"
            + (f"   (last at {fmt.clock(s.checked_in_at)})" if s.checked_in_at else ""),
        ]
        self.details.configure(text="\n".join(lines))

        if s.status == "refunded":
            self._banner("REFUNDED — NOT VALID", BAD)
            return
        warnings = []
        if sh.starts_at.date() != date.today():
            warnings.append(f"⚠ This ticket is for {fmt.short_day(sh.starts_at)}, not today.")
        elif datetime.now() > sh.ends_at:
            warnings.append("⚠ This showing has already ended.")
        self.warning.configure(text="\n".join(warnings))

        left = s.not_checked_in
        if self.just_admitted:
            n = self.just_admitted
            self._banner(f"✔ CHECKED IN  ·  {n} {'person' if n == 1 else 'people'}", GOOD)
        elif left == 0:
            self._banner("ALREADY CHECKED IN", BAD)
        elif s.checked_in:
            self._banner(f"PARTLY CHECKED IN  ·  {left} still to come", WARN)
        else:
            self._banner(f"VALID  ·  {s.ticket_count} {'ticket' if s.ticket_count == 1 else 'tickets'}", GOOD)

        for w in (self.stepper, self.go_btn, self.undo_btn):
            w.pack_forget()
        if left:
            self.stepper.pack(fill="x", pady=(0, 10))
            self.go_btn.pack(fill="x")
            self.admit_lbl.configure(text=str(self.admit))
            label = f"Check in all {left}" if self.admit == left else f"Check in {self.admit} of {left}"
            self.go_btn.set(text=label)
        if s.checked_in:
            self.undo_btn.pack(fill="x", pady=(10, 0))
        if left or s.checked_in:
            self.controls.pack(fill="x", padx=24, pady=(8, 20), side="bottom")
