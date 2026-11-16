"""Customer-facing display: a second window that mirrors the sale the cashier is ringing up.

make_view() decides what the customer should see (pure, easy to test); CustomerDisplay draws it.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from datetime import date, datetime

from . import fmt
from .store import ConcessionSale, Sale, Showing

BG = "#0b1018"
PANEL = "#161e2b"
TEXT = "#f8fafc"
SUBTLE = "#94a3b8"
GOLD = "#fbbf24"
GREEN = "#4ade80"
AMBER = "#fb923c"

POLL_MS = 120


@dataclass(frozen=True)
class OrderLine:
    label: str
    qty: int
    unit_cents: int

    @property
    def line_cents(self) -> int:
        return self.qty * self.unit_cents


@dataclass(frozen=True)
class CustomerView:
    mode: str = "welcome"  # welcome | feature | order | payment | thanks | lookup | refund | refunded
    venue: str = ""
    tx: str = ""  # transaction number, on the returns modes
    status: str = ""  # headline under the venue, on the returns modes
    clock: str = ""  # welcome screen only
    title: str = ""
    rating_runtime: str = ""
    day: str = ""
    time: str = ""
    theater: str = ""
    lines: tuple[OrderLine, ...] = ()
    total_cents: int = 0
    method: str = ""  # cash | card | credit | none
    tendered_cents: int = 0
    change_cents: int = 0
    concession: bool = False  # a concessions order: no movie or showtime lines

    @property
    def owed_cents(self) -> int:
        return max(self.total_cents - self.tendered_cents, 0)


def make_view(
    *,
    on_sell: bool,
    step: str,
    venue: str,
    now: datetime,
    day: date,
    movie,
    showing: Showing | None,
    qty: dict[str, int],
    prices: dict[str, int],
    method: str | None,
    tendered_cents: int,
    sale: Sale | None,
) -> CustomerView:
    if not on_sell or step == "movie":
        return _welcome_view(venue, now)

    if step == "done" and sale is not None:
        show = sale.showing
        return CustomerView(
            "thanks", venue, title=show.title, rating_runtime=fmt.movie_line(show.rating, show.runtime_min),
            day=fmt.short_day(show.starts_at), time=fmt.clock(show.starts_at), theater=show.theater_name,
            lines=tuple(OrderLine(i.ticket_type, i.qty, i.unit_price_cents) for i in sale.items),
            total_cents=sale.total_cents, method=sale.payment_method,
            tendered_cents=sale.tendered_cents, change_cents=sale.change_cents,
        )

    if step == "time" or showing is None:  # feature chosen, showtime not yet
        return CustomerView(
            "feature", venue, title=movie.title, rating_runtime=fmt.movie_line(movie.rating, movie.runtime_min),
            day=fmt.short_day(day),
        )

    lines = tuple(OrderLine(name, count, prices[name]) for name, count in qty.items() if count and name in prices)
    total = sum(line.line_cents for line in lines)
    base = dict(
        venue=venue, title=showing.title, rating_runtime=fmt.movie_line(showing.rating, showing.runtime_min),
        day=fmt.short_day(showing.starts_at), time=fmt.clock(showing.starts_at), theater=showing.theater_name,
        lines=lines, total_cents=total,
    )
    if step == "pay":
        method = "none" if total == 0 else (method or "cash")
        change = max(tendered_cents - total, 0) if method == "cash" else 0
        return CustomerView("payment", method=method, tendered_cents=tendered_cents if method == "cash" else 0,
                            change_cents=change, **base)
    return CustomerView("order", **base)


def _welcome_view(venue: str, now: datetime) -> CustomerView:
    return CustomerView("welcome", venue, clock=f"{now:%A, %B} {now.day}   ·   {fmt.clock(now)}")


def make_concession_view(
    *,
    venue: str,
    now: datetime,
    step: str,
    lines: tuple[OrderLine, ...],
    method: str | None,
    tendered_cents: int,
    sale: ConcessionSale | None,
) -> CustomerView:
    """The concessions tab: welcome until the first item is added, then the order, the payment, and the thank-you."""
    if step == "done" and sale is not None:
        return CustomerView(
            "thanks", venue, title="Concessions", concession=True,
            lines=tuple(OrderLine(i.name, i.qty, i.unit_price_cents) for i in sale.items),
            total_cents=sale.total_cents, method=sale.payment_method,
            tendered_cents=sale.tendered_cents, change_cents=sale.change_cents,
        )
    if not lines:
        return _welcome_view(venue, now)
    total = sum(line.line_cents for line in lines)
    base = dict(venue=venue, title="Concessions", concession=True, lines=lines, total_cents=total)
    if step == "pay":
        method = "none" if total == 0 else (method or "cash")
        change = max(tendered_cents - total, 0) if method == "cash" else 0
        return CustomerView("payment", method=method, tendered_cents=tendered_cents if method == "cash" else 0,
                            change_cents=change, **base)
    return CustomerView("order", **base)


def make_return_view(*, venue: str, now: datetime, sale: Sale | None, stage: str | None) -> CustomerView:
    """The returns tab: the looked-up sale as it was rung up, then the refund in progress / complete.

    stage is None while just looking, "confirming" once Refund is pressed, "done" after the refund went through.
    """
    if sale is None:
        return _welcome_view(venue, now)
    show = sale.showing
    base = dict(
        venue=venue, tx=fmt.tx_id(sale.id), title=show.title, rating_runtime=fmt.movie_line(show.rating, show.runtime_min),
        day=fmt.short_day(show.starts_at), time=fmt.clock(show.starts_at), theater=show.theater_name,
        lines=tuple(OrderLine(i.ticket_type, i.qty, i.unit_price_cents) for i in sale.items),
        total_cents=sale.total_cents, method=sale.payment_method,
        tendered_cents=sale.tendered_cents, change_cents=sale.change_cents,
    )
    if sale.status == "refunded":
        if stage == "done":
            return CustomerView("refunded", status="Refund complete", **base)
        when = f"{fmt.short_day(sale.refunded_at)} {fmt.clock(sale.refunded_at)}"
        return CustomerView("lookup", status=f"Refunded  ·  {when}", **base)
    if stage == "confirming":
        return CustomerView("refund", status="Refund in progress", **base)
    return CustomerView("lookup", **base)


class CustomerDisplay(tk.Toplevel):
    DESIGN_HEIGHT = 800  # fonts and spacing are drawn for this height and scaled to the window

    def __init__(self, app, fullscreen: bool = False):
        super().__init__(app, bg=BG)
        self.app = app
        self.title("Customer Display")
        self.protocol("WM_DELETE_WINDOW", self.withdraw)  # the POS's Customer Screen button brings it back
        if fullscreen:
            self.attributes("-fullscreen", True)
        else:
            x = max(min(app.winfo_screenwidth() - 940, 90 + 1280 + 10), 20)
            self.geometry(f"920x680+{x}+70")
            self.minsize(520, 420)
        self.view: CustomerView | None = None
        self.scale = 1.0
        self._fonts: dict[tuple[int, bool], tkfont.Font] = {}
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)
        self.bind("<Configure>", self._resized)
        self.sync()

    def show(self) -> None:
        self.deiconify()
        self.lift()

    # ---- updating ----

    def sync(self) -> None:
        """Redraw if the sale changed since last time, then check again shortly."""
        view = self.app.customer_view()
        if view != self.view:
            self.view = view
            self.render()
        self.after(POLL_MS, self.sync)

    def _resized(self, event) -> None:
        if event.widget is self and self._fit_scale():
            self.render()

    def _fit_scale(self) -> bool:
        """Scale text to the window height. Returns True if it changed enough to redraw."""
        height = self.winfo_height()
        if height < 150:  # Tk reports bogus tiny sizes while the window is being set up
            return False
        scale = min(max(height / self.DESIGN_HEIGHT, 0.55), 2.6)
        if abs(scale - self.scale) <= 0.04:
            return False
        self.scale = scale
        return True

    # ---- drawing ----

    def px(self, n: float) -> int:
        return max(1, round(n * self.scale))

    def font(self, size: int, bold: bool = False) -> tkfont.Font:
        key = (self.px(size), bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family="Helvetica", size=-key[0], weight="bold" if bold else "normal")
        return self._fonts[key]

    def _label(self, parent, text, size, bold=False, color=TEXT, **kw) -> tk.Label:
        return tk.Label(parent, text=text, bg=kw.pop("bg", BG), fg=color, font=self.font(size, bold), **kw)

    def render(self) -> None:
        self._fit_scale()
        for child in self.body.winfo_children():
            child.destroy()
        if self.view is None:
            return
        if self.view.mode == "welcome":
            self._welcome(self.view)
        else:
            self._sale(self.view)

    def _welcome(self, v: CustomerView) -> None:
        box = tk.Frame(self.body, bg=BG)
        box.place(relx=0.5, rely=0.46, anchor="center")
        wrap = max(self.winfo_width() - self.px(120), 200)
        self._label(box, "Welcome to", 40, color=SUBTLE).pack()
        self._label(box, v.venue, 84, True, wraplength=wrap, justify="center").pack(pady=self.px(8))
        self._label(box, v.clock, 32, color=GOLD).pack(pady=(self.px(28), 0))

    def _sale(self, v: CustomerView) -> None:
        pad = self.px(44)
        wrap = max(self.winfo_width() - 2 * pad, 200)
        page = tk.Frame(self.body, bg=BG)
        page.pack(fill="both", expand=True, padx=pad, pady=(self.px(26), self.px(24)))

        refunding = v.mode in ("refund", "refunded")
        header = f"{v.venue}   ·   Transaction #{v.tx}" if v.tx else v.venue
        self._label(page, header, 22, color=SUBTLE, anchor="w").pack(fill="x")
        if v.status:
            tone = GREEN if v.mode == "refunded" else AMBER
            self._label(page, v.status, 34, True, color=tone, anchor="w").pack(fill="x", pady=(self.px(6), 0))
        self._label(page, v.title, 54, True, anchor="w", justify="left", wraplength=wrap).pack(fill="x", pady=(self.px(6), 0))
        if v.rating_runtime:
            self._label(page, v.rating_runtime, 26, color=SUBTLE, anchor="w").pack(fill="x")
        if v.time:
            when = f"{v.day}   ·   {v.time}   ·   {v.theater}"
            self._label(page, when, 32, True, color=GOLD, anchor="w", wraplength=wrap, justify="left").pack(fill="x", pady=(self.px(10), 0))
        elif not v.concession:
            self._label(page, f"Showtimes for {v.day}", 30, True, color=GOLD, anchor="w").pack(fill="x", pady=(self.px(10), 0))
        if v.mode == "feature":
            return

        lines = tk.Frame(page, bg=BG)
        lines.pack(fill="x", pady=(self.px(24), 0))
        if not v.lines:
            self._label(lines, "Choose your items" if v.concession else "Choose your tickets", 30, color=SUBTLE, anchor="w").pack(fill="x")
        for line in v.lines:
            row = tk.Frame(lines, bg=BG)
            row.pack(fill="x", pady=self.px(4))
            each = "Free" if line.unit_cents == 0 else f"{fmt.money(line.unit_cents)} each"
            self._label(row, f"{line.qty} × {line.label}", 32, True).pack(side="left")
            self._label(row, each, 22, color=SUBTLE).pack(side="left", padx=(self.px(18), 0), pady=(self.px(6), 0))
            amount = "Free" if line.unit_cents == 0 else fmt.money(-line.line_cents if refunding else line.line_cents)
            self._label(row, amount, 32, True).pack(side="right")

        totals = tk.Frame(page, bg=PANEL)
        totals.pack(side="bottom", fill="x")
        inner = tk.Frame(totals, bg=PANEL)
        inner.pack(fill="x", padx=self.px(28), pady=self.px(18))
        label = {"order": "Subtotal", "refund": "Refund total", "refunded": "Refund total"}.get(v.mode, "Total")
        self._total_row(inner, label, fmt.money(-v.total_cents if refunding else v.total_cents), 52, True)
        if v.mode == "payment":
            self._payment_rows(inner, v)
        elif v.mode == "thanks":
            self._thanks_rows(inner, v)
            self._label(inner, "Thank you!" if v.concession else "Thank you!  Enjoy the show.", 40, True, color=GREEN, bg=PANEL).pack(pady=(self.px(14), 0))
        elif v.mode == "lookup":
            self._thanks_rows(inner, v)
        elif refunding:
            self._refund_rows(inner, v)

    def _total_row(self, parent, left, right, size, bold=False, color=TEXT) -> None:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=self.px(3))
        self._label(row, left, size, bold, color=color, bg=PANEL).pack(side="left")
        self._label(row, right, size, bold, color=color, bg=PANEL).pack(side="right")

    def _payment_rows(self, parent, v: CustomerView) -> None:
        if v.method == "none":
            self._total_row(parent, "No payment due", "", 30, color=GREEN)
        elif v.method == "card":
            self._total_row(parent, "Please use the card reader", "", 30, color=GOLD)
        elif v.method == "credit":
            self._total_row(parent, "Paying with store credit", "", 30, color=GOLD)
        elif v.tendered_cents > 0:
            self._total_row(parent, "Cash received", fmt.money(v.tendered_cents), 32)
            if v.tendered_cents >= v.total_cents:
                self._total_row(parent, "Change due", fmt.money(v.change_cents), 52, True, GREEN)
            else:
                self._total_row(parent, "Still to pay", fmt.money(v.owed_cents), 40, True, AMBER)

    def _thanks_rows(self, parent, v: CustomerView) -> None:
        if v.method == "cash":
            self._total_row(parent, "Cash received", fmt.money(v.tendered_cents), 32)
            self._total_row(parent, "Change", fmt.money(v.change_cents), 52, True, GREEN)
        elif v.method == "card":
            self._total_row(parent, "Paid by card", "", 30, color=SUBTLE)
        elif v.method == "credit":
            self._total_row(parent, "Paid with store credit", "", 30, color=SUBTLE)

    def _refund_rows(self, parent, v: CustomerView) -> None:
        done = v.mode == "refunded"
        color = GREEN if done else AMBER
        if v.method == "cash":
            self._total_row(parent, "Cash refunded" if done else "Cash to return", fmt.money(v.total_cents), 52, True, color)
        elif v.method == "card":
            self._total_row(parent, "Refunded to your card" if done else "Refunding to your card", "", 30, color=color)
        elif v.method == "credit":
            self._total_row(parent, "Added to your store credit" if done else "Refunding to your store credit", "", 30, color=color)
        else:
            self._total_row(parent, "No payment to return", "", 30, color=SUBTLE)
        if done:
            self._label(parent, "Thank you!", 40, True, color=GREEN, bg=PANEL).pack(pady=(self.px(14), 0))
