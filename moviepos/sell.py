"""Sell screen: feature -> time -> ticket types -> payment -> done."""
from __future__ import annotations

import time
import tkinter as tk
from functools import partial
from collections import Counter
from datetime import date, datetime, timedelta

from . import fmt
from .customer_display import CustomerView, make_view
from .dialogs import alert
from .keys import ENTER, key_char
from .ticket import TicketView
from .theme import ACCENT, BG, BTN, ERROR_FG, F, GOOD, PANEL, SUBTLE, TEXT, WARN, BAD
from .widgets import NumPad, PagedGrid, TouchButton

STEPS = ["movie", "time", "tickets", "pay"]
STEP_LABELS = ["1   Feature", "2   Time", "3   Tickets", "4   Payment"]
GOOD_FG = "#4ade80"
HINTS = {
    "movie": "Keys:   1-9 choose a feature   ◀ ▶ change day   PgUp / PgDn pages   F1-F4 switch screens",
    "time": "Keys:   1-9 choose a time   PgUp / PgDn pages   Esc back",
    "tickets": "Keys:   ↑ ↓ or first letter (A S C E P) pick a type   ◀ ▶ or − + change count   "
    "0-9 type a count   Del clear   Enter payment   Esc back",
    "pay": "Keys:   Tab cash / card / store credit   0-9 and . cash received   E exact   Del clear   Enter complete sale   Esc back",
    "done": "Keys:   P print the ticket again   R print a receipt   Enter or Space for a new sale",
}


class SellScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app, self.store = app, app.store
        self.day = date.today()
        self.step = "movie"
        self._reset()

        crumbs = tk.Frame(self, bg=BG)
        crumbs.pack(fill="x", padx=16, pady=(12, 0))
        self.crumbs: list[TouchButton] = []
        for i, label in enumerate(STEP_LABELS):
            crumbs.grid_columnconfigure(i, weight=1, uniform="c")
            b = TouchButton(crumbs, label, lambda s=STEPS[i]: self.go_back_to(s), pady=8, font=F["base"])
            b.grid(row=0, column=i, sticky="ew", padx=3)
            self.crumbs.append(b)
        self.hint = tk.Label(self, bg=BG, fg=SUBTLE, font=F["small"], anchor="w")
        self.hint.pack(side="bottom", fill="x", padx=18, pady=(0, 8))
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True, padx=16, pady=10)

    # ---- state / navigation ---------------------------------------------

    def _reset(self) -> None:
        self.movie = None
        self.showing = None
        self.qty: dict[str, int] = {}
        self.method: str | None = None
        self.tendered = ""
        self.sale = None
        self.print_text, self.print_ok, self.printing = "", None, False
        self.picker = None  # the current feature/time grid, for number keys
        self.row = 0  # highlighted ticket type
        self._digit_at, self._digit_row = 0.0, None

    def refresh(self) -> None:
        if self.step == "done":
            self.new_sale()
        else:
            self.render()

    def new_sale(self) -> None:
        self._reset()
        self.step = "movie"
        self.render()

    def go_back_to(self, step: str) -> None:
        if self.step == "done" or STEPS.index(step) >= STEPS.index(self.step):
            return
        if step in ("movie", "time"):
            self.qty = {}
        if step == "movie":
            self.movie = None
        self.method, self.tendered = None, ""
        self.step = step
        self.render()

    def goto(self, step: str) -> None:
        self.step = step
        self.render()

    def render(self) -> None:
        if self.day < date.today():
            self.day = date.today()
        for w in self.body.winfo_children():
            w.destroy()
        self.picker = None
        getattr(self, f"_show_{self.step}")()
        self.hint.configure(text=HINTS[self.step])
        current = STEPS.index(self.step) if self.step in STEPS else len(STEPS)
        for i, b in enumerate(self.crumbs):
            if i == current:
                b.set(bg=ACCENT, enabled=True)
            else:
                b.set(bg=BTN, enabled=i < current and self.step != "done")

    def _title(self, text: str, sub: str = "") -> None:
        tk.Label(self.body, text=text, bg=BG, fg=TEXT, font=F["h1"], anchor="w").pack(fill="x")
        if sub:
            tk.Label(self.body, text=sub, bg=BG, fg=SUBTLE, font=F["base"], anchor="w").pack(fill="x", pady=(0, 6))

    def _upcoming(self, **filters):
        now = datetime.now()
        return [s for s in self.store.showings(day=self.day, **filters) if s.starts_at > now]

    # ---- step 1: feature ------------------------------------------------

    def _show_movie(self) -> None:
        bar = tk.Frame(self.body, bg=BG)
        bar.pack(fill="x", pady=(0, 8))
        TouchButton(bar, "◀", self._prev_day, width=4, enabled=self.day > date.today()).pack(side="left")
        TouchButton(bar, "▶", self._next_day, width=4).pack(side="right")
        tk.Label(bar, text=f"Select a feature  —  {fmt.day_label(self.day)}", bg=BG, fg=TEXT, font=F["h2"]).pack(
            expand=True
        )
        counts = Counter(s.movie_id for s in self._upcoming())
        movies = [m for m in self.store.list_movies() if m.id in counts]

        def make(parent, m):
            n = counts[m.id]
            text = f"{m.title}\n{fmt.movie_line(m.rating, m.runtime_min)}\n{n} showing{'s' if n != 1 else ''} left"
            return TouchButton(parent, text, lambda: self._pick_movie(m), wraplength=300, padx=10)

        grid = self.picker = PagedGrid(self.body, 3, 3, make, "No more showings on this day", numbered=True)
        grid.set_items(movies)
        grid.pack(fill="both", expand=True)

    def _prev_day(self) -> None:
        self.day -= timedelta(days=1)
        self.render()

    def _next_day(self) -> None:
        self.day += timedelta(days=1)
        self.render()

    def _pick_movie(self, movie) -> None:
        self.movie = movie
        self.goto("time")

    # ---- step 2: time ---------------------------------------------------

    def _show_time(self) -> None:
        self._title(self.movie.title, f"{fmt.day_label(self.day)}  ·  {fmt.movie_line(self.movie.rating, self.movie.runtime_min)}")
        shows = self._upcoming(movie_id=self.movie.id)

        def make(parent, s):
            when = fmt.clock(s.starts_at)
            if s.remaining == 0:
                return TouchButton(parent, f"{when}\n{s.theater_name}\nSOLD OUT", enabled=False)
            pct = s.pct_available
            color = GOOD if pct >= 50 else WARN if pct >= 20 else BAD
            text = f"{when}\n{s.theater_name}\n{s.remaining} seats left · {pct}% open"
            return TouchButton(parent, text, lambda: self._pick_showing(s), bg=color, font=F["btn"])

        grid = self.picker = PagedGrid(self.body, 3, 3, make, "No more showings for this feature today", numbered=True)
        grid.set_items(shows)
        grid.pack(fill="both", expand=True)

    def _pick_showing(self, showing) -> None:
        self.showing = showing
        self.qty = {}
        self.goto("tickets")

    # ---- step 3: ticket types -------------------------------------------

    def _show_tickets(self) -> None:
        fresh = self.store.get_showing(self.showing.id)
        if fresh is None or fresh.remaining == 0:
            alert(self, "That showing just sold out.")
            self.goto("time")
            return
        self.showing = fresh
        s = fresh
        self.prices = self.store.ticket_prices()
        self._title(
            s.title,
            f"{fmt.day_label(s.starts_at.date())}  ·  {fmt.clock(s.starts_at)}  ·  {s.theater_name}",
        )
        self.seats_lbl = tk.Label(self.body, bg=BG, fg=SUBTLE, font=F["base"], anchor="w")
        self.seats_lbl.pack(fill="x", pady=(0, 8))

        rows = tk.Frame(self.body, bg=BG)
        rows.pack(fill="both", expand=True)
        self.qty_lbls, self.plus, self.minus, self.row_frames = {}, {}, {}, {}
        self.row = min(self.row, len(self.prices) - 1)
        for i, (name, price) in enumerate(self.prices.items()):
            rows.grid_rowconfigure(i, weight=1, uniform="r")
            rows.grid_columnconfigure(0, weight=1)
            row = tk.Frame(rows, bg=PANEL, highlightthickness=3, highlightbackground=PANEL)
            self.row_frames[name] = row
            row.grid(row=i, column=0, sticky="nsew", pady=3)
            row.grid_columnconfigure(0, weight=1)
            tk.Label(row, text=name, bg=PANEL, fg=TEXT, font=F["h2"], anchor="w").grid(row=0, column=0, sticky="w", padx=20)
            tk.Label(row, text=fmt.money(price) if price else "Free", bg=PANEL, fg=SUBTLE, font=F["row"], width=8).grid(
                row=0, column=1
            )
            self.minus[name] = TouchButton(row, "−", lambda n=name: self._adjust(n, -1), font=F["key"], width=4, pady=6)
            self.minus[name].grid(row=0, column=2, padx=6, pady=6)
            self.qty_lbls[name] = tk.Label(row, bg=PANEL, fg=TEXT, font=F["h1"], width=3)
            self.qty_lbls[name].grid(row=0, column=3)
            self.plus[name] = TouchButton(row, "+", lambda n=name: self._adjust(n, 1), font=F["key"], width=4, pady=6, bg=ACCENT)
            self.plus[name].grid(row=0, column=4, padx=(6, 20), pady=6)

        foot = tk.Frame(self.body, bg=BG)
        foot.pack(fill="x", pady=(8, 0))
        self.total_lbl = tk.Label(foot, bg=BG, fg=TEXT, font=F["h1"], anchor="w")
        self.total_lbl.pack(side="left")
        self.next_btn = TouchButton(foot, "Payment  ▶", lambda: self.goto("pay"), bg=GOOD, padx=40, pady=14)
        self.next_btn.pack(side="right")
        TouchButton(foot, "Clear", self._clear, padx=30, pady=14).pack(side="right", padx=10)
        self._sync_tickets()

    def _count(self) -> int:
        return sum(self.qty.values())

    def _total(self) -> int:
        return sum(self.prices[n] * q for n, q in self.qty.items())

    def _adjust(self, name: str, delta: int) -> None:
        self.row = list(self.prices).index(name)
        new = self.qty.get(name, 0) + delta
        if new < 0 or self._count() + delta > self.showing.remaining:
            return
        self.qty[name] = new
        self._sync_tickets()

    def _clear(self) -> None:
        self.qty = {}
        self._sync_tickets()

    def _sync_tickets(self) -> None:
        count, left = self._count(), self.showing.remaining
        for name in self.prices:
            q = self.qty.get(name, 0)
            self.qty_lbls[name].configure(text=str(q), fg=TEXT if q else SUBTLE)
            self.minus[name].set(enabled=q > 0)
            self.plus[name].set(enabled=count < left)
            self.row_frames[name].configure(highlightbackground=ACCENT if list(self.prices).index(name) == self.row else PANEL)
        after = left - count
        self.seats_lbl.configure(
            text=f"{left} of {self.showing.capacity} seats open"
            + (f"  ·  {after} will remain after this sale" if count else "")
        )
        self.total_lbl.configure(text=f"{count} ticket{'s' if count != 1 else ''}   {fmt.money(self._total())}")
        self.next_btn.set(enabled=count > 0)

    # ---- step 4: payment ------------------------------------------------

    def _show_pay(self) -> None:
        total = self._total()
        if self.method is None:
            self.method = "cash"
        s = self.showing

        left = tk.Frame(self.body, bg=PANEL, width=340)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        tk.Label(left, text=s.title, bg=PANEL, fg=TEXT, font=F["h2"], wraplength=300, justify="left").pack(
            anchor="w", padx=16, pady=(16, 2)
        )
        tk.Label(
            left, text=f"{fmt.short_day(s.starts_at)}  ·  {fmt.clock(s.starts_at)}\n{s.theater_name}",
            bg=PANEL, fg=SUBTLE, font=F["base"], justify="left",
        ).pack(anchor="w", padx=16)
        lines = "\n".join(f"{q} × {n}   {fmt.money(self.prices[n] * q)}" for n, q in self.qty.items() if q)
        tk.Label(left, text=lines, bg=PANEL, fg=TEXT, font=F["row"], justify="left").pack(anchor="w", padx=16, pady=16)
        tk.Label(left, text=fmt.money(total), bg=PANEL, fg=TEXT, font=F["huge"]).pack(anchor="w", padx=16, side="bottom", pady=(0, 16))
        tk.Label(left, text="TOTAL DUE", bg=PANEL, fg=SUBTLE, font=F["small"]).pack(anchor="w", padx=16, side="bottom")

        right = tk.Frame(self.body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        if total == 0:
            tk.Label(right, text="No payment due", bg=BG, fg=TEXT, font=F["h1"]).pack(pady=(60, 8))
            tk.Label(right, text="Pass tickets are free.", bg=BG, fg=SUBTLE, font=F["row"]).pack()
            TouchButton(right, "Complete sale", self._complete, bg=GOOD, padx=60, pady=20).pack(pady=40)
            return
        toggles = tk.Frame(right, bg=BG)
        toggles.pack(fill="x", pady=(0, 10))
        self.method_btns = {}
        for i, (key, label) in enumerate([("cash", "Cash"), ("card", "Card"), ("credit", "Store Credit")]):
            toggles.grid_columnconfigure(i, weight=1, uniform="m")
            b = TouchButton(toggles, label, lambda k=key: self._set_method(k), pady=14)
            b.grid(row=0, column=i, sticky="ew", padx=4)
            self.method_btns[key] = b
        self.pay_detail = tk.Frame(right, bg=BG)
        self.pay_detail.pack(fill="both", expand=True)
        self._render_method()

    def _set_method(self, method: str) -> None:
        self.method = method
        self._render_method()

    def _render_method(self) -> None:
        for key, b in self.method_btns.items():
            b.set(bg=ACCENT if key == self.method else BTN)
        d = self.pay_detail
        for w in d.winfo_children():
            w.destroy()
        for c in range(2):
            d.grid_columnconfigure(c, weight=1, uniform="p")
        d.grid_rowconfigure(0, weight=1)
        if self.method in ("card", "credit"):
            heading, note, button = {
                "card": ("Charge", "Run the card on the reader, then confirm it was approved.", "Card approved — complete sale"),
                "credit": ("Store credit", "Check the customer's store credit covers the total, then confirm.", "Store credit applied — complete sale"),
            }[self.method]
            panel = tk.Frame(d, bg=BG)
            panel.grid(row=0, column=0, columnspan=2, sticky="nsew")
            tk.Label(panel, text=f"{heading} {fmt.money(self._total())}", bg=BG, fg=TEXT, font=F["h1"]).pack(pady=(50, 8))
            tk.Label(panel, text=note, bg=BG, fg=SUBTLE, font=F["row"]).pack()
            TouchButton(panel, button, self._complete, bg=GOOD, padx=50, pady=20).pack(pady=40)
            return
        NumPad(d, self._cash_key, self._cash_back, pady=12).grid(row=0, column=0, sticky="nsew")
        right = tk.Frame(d, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        tk.Label(right, text="CASH RECEIVED", bg=BG, fg=SUBTLE, font=F["small"], anchor="w").pack(fill="x")
        self.tender_lbl = tk.Label(right, bg=BG, fg=TEXT, font=F["huge"], anchor="w")
        self.tender_lbl.pack(fill="x")
        self.change_lbl = tk.Label(right, bg=BG, font=F["h1"], anchor="w")
        self.change_lbl.pack(fill="x", pady=(0, 10))
        quick = tk.Frame(right, bg=BG)
        quick.pack(fill="x")
        total = self._total()
        exact = f"{total // 100}.{total % 100:02d}"
        for i, (label, value) in enumerate([("Exact", exact), ("$5", "5"), ("$10", "10"), ("$20", "20"), ("$50", "50"), ("$100", "100")]):
            quick.grid_columnconfigure(i % 3, weight=1, uniform="q")
            TouchButton(quick, label, lambda v=value: self._set_tendered(v), pady=12).grid(
                row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3
            )
        TouchButton(right, "Clear", lambda: self._set_tendered(""), pady=10).pack(fill="x", pady=(6, 0), padx=3)
        self.complete_btn = TouchButton(right, "Complete sale", self._complete, bg=GOOD, pady=18)
        self.complete_btn.pack(fill="x", side="bottom", padx=3)
        self._sync_cash()

    def _tendered_cents(self) -> int:
        try:
            return fmt.parse_money(self.tendered)
        except ValueError:
            return 0

    def _set_tendered(self, value: str) -> None:
        self.tendered = value
        self._sync_cash()

    def _cash_key(self, ch: str) -> None:
        cur = self.tendered
        if ch == "." and "." in cur:
            return
        if "." in cur and len(cur.split(".")[1]) >= 2:
            return
        if len(cur) >= 7:
            return
        if cur == "0" and ch != ".":
            cur = ""
        self.tendered = (cur or ("0" if ch == "." else "")) + ch
        self._sync_cash()

    def _cash_back(self) -> None:
        self.tendered = self.tendered[:-1]
        self._sync_cash()

    def _sync_cash(self) -> None:
        cents, total = self._tendered_cents(), self._total()
        self.tender_lbl.configure(text=fmt.money(cents))
        if cents >= total:
            self.change_lbl.configure(text=f"Change due: {fmt.money(cents - total)}", fg=GOOD_FG)
        else:
            owed = fmt.money(total - cents)
            self.change_lbl.configure(text=f"Still owed: {owed}", fg=ERROR_FG if cents else SUBTLE)
        self.complete_btn.set(enabled=cents >= total)

    def _complete(self) -> None:
        total = self._total()
        tendered = self._tendered_cents() if total and self.method == "cash" else None
        try:
            sale = self.store.sell(self.showing.id, self.qty, self.method or "cash", tendered)
        except ValueError as e:
            alert(self, str(e), "Sale not completed")
            self.qty, self.method, self.tendered = {}, None, ""
            self.goto("time")
            return
        self.sale = sale
        self.goto("done")
        self.print_ticket()  # automatic: no tap needed

    # ---- customer display -----------------------------------------------

    def customer_view(self, venue: str, on_sell: bool = True) -> CustomerView:
        return make_view(
            on_sell=on_sell, step=self.step, venue=venue, now=datetime.now(), day=self.day, movie=self.movie,
            showing=self.showing, qty=self.qty, prices=getattr(self, "prices", {}), method=self.method,
            tendered_cents=self._tendered_cents() if self.tendered else 0, sale=self.sale,
        )

    # ---- keyboard -------------------------------------------------------

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event)
        if key == "Escape":
            if self.step == "done":
                self.new_sale()
            elif self.step != STEPS[0]:
                self.go_back_to(STEPS[STEPS.index(self.step) - 1])
            return True
        if self.step == "done":
            if key in ENTER or ch in (" ", "n", "N"):
                self.new_sale()
                return True
            if ch in ("p", "P"):
                self.print_ticket()
                return True
            if ch in ("r", "R"):
                self.print_receipt()
                return True
            return False
        if self.step in ("movie", "time"):
            return self._keys_grid(key, ch)
        if self.step == "tickets":
            return self._keys_tickets(key, ch)
        return self._keys_pay(key, ch)

    def _keys_grid(self, key: str, ch: str) -> bool:
        if ch.isdigit() and ch != "0":
            self.picker.invoke(int(ch))
        elif key in ("Prior", "Next"):
            self.picker.page_by(-1 if key == "Prior" else 1)
        elif self.step == "movie" and key == "Left":
            if self.day > date.today():
                self._prev_day()
        elif self.step == "movie" and key == "Right":
            self._next_day()
        else:
            return False
        return True

    def _keys_tickets(self, key: str, ch: str) -> bool:
        names = list(self.prices)
        name = names[self.row]
        if key in ENTER:
            if self._count() > 0:
                self.goto("pay")
            return True
        if key == "Up":
            self.row = max(self.row - 1, 0)
        elif key == "Down":
            self.row = min(self.row + 1, len(names) - 1)
        elif key in ("Left", "BackSpace") or ch in ("-", "_"):
            self._adjust(name, -1)
        elif key == "Right" or ch in ("+", "="):
            self._adjust(name, 1)
        elif key == "Delete":
            self.qty = {}
        elif ch.isdigit():
            self._type_quantity(name, int(ch))
        elif ch.isalpha():
            matches = [i for i, n in enumerate(names) if n.lower().startswith(ch.lower())]
            if not matches:
                return False
            self.row = matches[0]
        else:
            return False
        self._sync_tickets()
        return True

    def _type_quantity(self, name: str, digit: int) -> None:
        """A digit sets the count; a second digit within a second makes it two digits (1 then 2 = 12)."""
        now = time.monotonic()
        current = self.qty.get(name, 0)
        quick = self._digit_row == name and now - self._digit_at < 1.0 and current * 10 + digit <= 99
        wanted = current * 10 + digit if quick else digit
        room = self.showing.remaining - (self._count() - current)
        self.qty[name] = max(min(wanted, room), 0)
        self._digit_row, self._digit_at = name, now

    def _keys_pay(self, key: str, ch: str) -> bool:
        total = self._total()
        if key in ENTER:
            if total == 0 or self.method != "cash" or self._tendered_cents() >= total:
                self._complete()
            return True
        if total == 0:
            return False
        if key == "Tab":
            order = ("cash", "card", "credit")
            self._set_method(order[(order.index(self.method) + 1) % len(order)])
        elif self.method != "cash":
            return False
        elif ch.isdigit() or ch == ".":
            self._cash_key(ch)
        elif key == "BackSpace":
            self._cash_back()
        elif key == "Delete":
            self._set_tendered("")
        elif ch in ("e", "E"):
            self._set_tendered(f"{total // 100}.{total % 100:02d}")
        else:
            return False
        return True

    # ---- done -----------------------------------------------------------

    def print_ticket(self) -> None:
        """The sideways ticket for the finished sale (automatic after a sale, and the Print again button)."""
        self._print("Printing ticket…", "print_sale")

    def print_receipt(self) -> None:
        """The itemized receipt. Only ever printed by pressing the button."""
        self._print("Printing receipt…", "print_receipt")

    def _print(self, message: str, method: str) -> None:
        printer = self.app.printer
        if printer is None or self.sale is None or self.printing:
            return
        self.printing, self.print_ok, self.print_text = True, None, message
        self._show_print_status()
        getattr(printer, method)(self.sale, self.store.venue_name(), on_done=partial(self._print_finished, self.sale.id))

    def _print_finished(self, sale_id: int, result) -> None:
        self.printing = False
        if self.sale is not None and self.sale.id == sale_id:
            self.print_ok, self.print_text = result.ok, result.message
        self._show_print_status()

    def _show_print_status(self) -> None:
        """Update the status line and button on the sale-complete screen, if it is showing."""
        label = getattr(self, "print_lbl", None)
        if label is None or not label.winfo_exists() or self.step != "done":
            return
        color = GOOD_FG if self.print_ok else ERROR_FG if self.print_ok is False else SUBTLE
        label.configure(text=self.print_text, fg=color)
        for button in (self.print_btn, self.receipt_btn):
            button.set(enabled=self.app.printer is not None and not self.printing)

    def _show_done(self) -> None:
        sale = self.sale
        ticket = TicketView(self.body)
        ticket.pack(side="right", padx=(8, 0), anchor="n")
        ticket.show(sale, self.store.venue_name())
        box = tk.Frame(self.body, bg=BG)
        box.pack(side="left", expand=True)
        tk.Label(box, text="SALE COMPLETE", bg=BG, fg=GOOD_FG, font=F["h1"]).pack()
        tk.Label(box, text="Transaction ID", bg=BG, fg=SUBTLE, font=F["base"]).pack(pady=(14, 0))
        tk.Label(box, text=fmt.tx_id(sale.id), bg=BG, fg=TEXT, font=F["huge"]).pack()
        if sale.payment_method == "cash":
            tk.Label(box, text="CHANGE DUE", bg=BG, fg=SUBTLE, font=F["base"]).pack(pady=(22, 0))
            tk.Label(box, text=fmt.money(sale.change_cents), bg=BG, fg=GOOD_FG, font=F["huge"]).pack()
            tk.Label(
                box, text=f"{fmt.money(sale.total_cents)} due  ·  {fmt.money(sale.tendered_cents)} cash received",
                bg=BG, fg=SUBTLE, font=F["base"],
            ).pack()
        elif sale.payment_method == "card":
            tk.Label(box, text=f"Card charged {fmt.money(sale.total_cents)}", bg=BG, fg=TEXT, font=F["h2"]).pack(pady=(22, 0))
        elif sale.payment_method == "credit":
            tk.Label(box, text=f"Store credit used {fmt.money(sale.total_cents)}", bg=BG, fg=TEXT, font=F["h2"]).pack(pady=(22, 0))
        else:
            tk.Label(box, text="No payment due", bg=BG, fg=TEXT, font=F["h2"]).pack(pady=(22, 0))
        self.print_lbl = tk.Label(box, bg=BG, font=F["base"], wraplength=330, justify="center")
        self.print_lbl.pack(pady=(18, 8))
        prints = tk.Frame(box, bg=BG)
        prints.pack()
        self.print_btn = TouchButton(prints, "Print ticket again", self.print_ticket, pady=10, padx=12, font=F["base"])
        self.print_btn.grid(row=0, column=0, padx=(0, 6))
        self.receipt_btn = TouchButton(prints, "Print receipt", self.print_receipt, pady=10, padx=12, font=F["base"])
        self.receipt_btn.grid(row=0, column=1, padx=(6, 0))
        TouchButton(box, "New sale", self.new_sale, bg=ACCENT, padx=70, pady=16).pack(pady=(18, 4))
        if self.app.printer is None:
            self.print_text = "Ticket printing is turned off"
        self._show_print_status()
