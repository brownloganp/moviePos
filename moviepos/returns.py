"""Returns screen: look up a transaction by ID and refund it."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime

from . import fmt
from .customer_display import CustomerView, make_return_view
from .dialogs import alert, confirm
from .sell import GOOD_FG
from .keys import ENTER, key_char
from .ticket import show_ticket
from .theme import BAD, BG, ERROR_FG, F, PANEL, SUBTLE, TEXT, ACCENT
from .widgets import NumPad, SelectList, TouchButton

METHOD_NAMES = {"cash": "Cash", "card": "Card", "credit": "Store Credit", "none": "No payment (pass)"}


class ReturnsScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app, self.store = app, app.store
        self.digits = ""
        self.looked_up = False
        self.sale = None
        self.refund_stage: str | None = None  # None | "confirming" | "done": drives the customer display
        for c, w in enumerate((1, 1, 2)):
            self.grid_columnconfigure(c, weight=w, uniform="cols")
        self.grid_rowconfigure(0, weight=1)

        left = tk.Frame(self, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(16, 8), pady=12)
        tk.Label(left, text="TRANSACTION ID", bg=BG, fg=SUBTLE, font=F["small"], anchor="w").pack(fill="x")
        self.id_lbl = tk.Label(left, bg=PANEL, fg=TEXT, font=F["h1"], anchor="e", padx=14, pady=10)
        self.id_lbl.pack(fill="x", pady=(2, 8))
        NumPad(left, self._key, self._back, allow_dot=False, pady=12).pack(fill="both", expand=True)
        TouchButton(left, "Look up", self.lookup, bg=ACCENT, pady=16).pack(fill="x", pady=(8, 0))
        tk.Label(
            left, text="Type the ID, Enter look up\n↑ ↓ recent sales\nR refund  ·  T ticket  ·  P receipt\nEsc clear",
            bg=BG, fg=SUBTLE, font=F["small"], justify="left",
        ).pack(fill="x", pady=(8, 0))

        mid = tk.Frame(self, bg=BG)
        mid.grid(row=0, column=1, sticky="nsew", padx=8, pady=12)
        tk.Label(mid, text="RECENT SALES", bg=BG, fg=SUBTLE, font=F["small"], anchor="w").pack(fill="x")
        self.recent = SelectList(mid, rows=7, on_select=self._pick_recent, empty_text="No sales yet", wraplength=270)
        self.recent.pack(fill="both", expand=True, pady=(2, 0))

        right = tk.Frame(self, bg=PANEL)
        right.grid(row=0, column=2, sticky="nsew", padx=(8, 16), pady=12)
        self.not_found = tk.Label(right, bg=PANEL, fg=ERROR_FG, font=F["h2"], anchor="w", wraplength=520, justify="left")
        content = self.content = tk.Frame(right, bg=PANEL)  # shown only while a transaction is loaded
        self.banner = tk.Label(content, bg=PANEL, font=F["h2"], anchor="w", wraplength=520, justify="left")
        self.banner.pack(fill="x", padx=20, pady=(18, 4))
        self.details = tk.Label(content, bg=PANEL, fg=TEXT, font=F["row"], anchor="nw", justify="left", wraplength=520)
        self.details.pack(fill="both", expand=True, padx=20)
        self.refund_btn = TouchButton(content, "Refund", self.refund, bg=BAD, pady=18)
        self.refund_btn.pack(fill="x", padx=20, pady=(0, 20), side="bottom")
        ticket_row = tk.Frame(content, bg=PANEL)
        ticket_row.pack(fill="x", padx=20, pady=(0, 10), side="bottom")
        for c in (0, 1):
            ticket_row.grid_columnconfigure(c, weight=1, uniform="ticket")
        self.ticket_btn = TouchButton(ticket_row, "View ticket", self.view_ticket, pady=14)
        self.ticket_btn.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        self.print_ticket_btn = TouchButton(ticket_row, "Print ticket", self.print_ticket, pady=14)
        self.print_ticket_btn.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.receipt_btn = TouchButton(content, "Print receipt", self.print_receipt, pady=14)
        self.receipt_btn.pack(fill="x", padx=20, pady=(0, 10), side="bottom")
        self.print_lbl = tk.Label(content, bg=PANEL, fg=SUBTLE, font=F["base"], anchor="w", wraplength=520, justify="left")
        self.print_lbl.pack(fill="x", padx=20, pady=(0, 8), side="bottom")
        self.printing = False
        self._show_sale()
        self._sync_id()

    def refresh(self) -> None:
        sales = self.store.recent_sales(30)
        items = [
            (s.id, f"#{fmt.tx_id(s.id)}  ·  {fmt.money(s.total_cents)}"
                   + ("  ·  refunded" if s.status == "refunded" else "") + f"\n{s.showing.title}")
            for s in sales
        ]
        self.recent.set_items(items)
        if self.sale:
            self.sale = self.store.get_sale(self.sale.id)
        self.refund_stage = None
        self._show_sale()

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event)
        if key in ENTER:
            self.lookup()
        elif ch.isdigit():
            self._key(ch)
        elif key == "BackSpace":
            self._back()
        elif key in ("Up", "Down"):
            self.recent.move(-1 if key == "Up" else 1)
        elif key in ("Prior", "Next"):
            self.recent.page_by(-1 if key == "Prior" else 1)
        elif ch in ("r", "R"):
            self.refund()
        elif ch in ("t", "T"):
            self.view_ticket()
        elif ch in ("p", "P"):
            self.print_receipt()
        elif key == "Escape":
            self.digits, self.sale, self.looked_up, self.refund_stage = "", None, False, None
            self._sync_id()
            self._show_sale()
        else:
            return False
        return True

    def _sync_id(self) -> None:
        self.id_lbl.configure(text=self.digits or " ")

    def _key(self, ch: str) -> None:
        if self.looked_up:  # the ID shown was already used: typing starts a new one
            self.digits, self.looked_up = "", False
        if len(self.digits) < 9:
            self.digits += ch
            self._sync_id()

    def _back(self) -> None:
        self.looked_up = False
        self.digits = self.digits[:-1]
        self._sync_id()

    def _pick_recent(self, sale_id: int) -> None:
        self.digits = str(sale_id)
        self._sync_id()
        self.lookup()

    def lookup(self) -> None:
        if not self.digits:
            return
        self.sale = self.store.get_sale(int(self.digits))
        self.refund_stage = None
        self.print_lbl.configure(text="")
        self.looked_up = True
        self._show_sale(not_found=self.sale is None)

    def _show_sale(self, not_found: bool = False, note: str = "") -> None:
        s = self.sale
        if s is None:
            self.content.pack_forget()
            if not_found:
                self.not_found.configure(text=f"No transaction found with ID {int(self.digits):06d}.")
                self.not_found.pack(fill="x", padx=20, pady=18)
            else:
                self.not_found.pack_forget()
            self.refund_btn.set(text="Refund", enabled=False)
            self.ticket_btn.set(enabled=False)
            self.print_lbl.configure(text="")
            self._sync_print_buttons()
            return
        self.not_found.pack_forget()
        self.content.pack(fill="both", expand=True)
        sh = s.showing
        lines = [
            f"Transaction #{fmt.tx_id(s.id)}",
            f"{sh.title}",
            f"{fmt.short_day(sh.starts_at)}  ·  {fmt.clock(sh.starts_at)}  ·  {sh.theater_name}",
            "",
            *(f"{i.qty} × {i.ticket_type}     {fmt.money(i.line_cents)}" for i in s.items),
            "",
            f"Total  {fmt.money(s.total_cents)}",
            f"Paid by  {METHOD_NAMES[s.payment_method]}"
            + (f"  ({fmt.money(s.tendered_cents)} tendered, {fmt.money(s.change_cents)} change)" if s.payment_method == "cash" else ""),
            f"Sold  {fmt.short_day(s.created_at)}  {fmt.clock(s.created_at)}",
            f"Checked in  {s.checked_in} of {s.ticket_count}",
        ]
        self.ticket_btn.set(enabled=True)
        self._sync_print_buttons()
        self.details.configure(text="\n".join(lines))
        if s.status == "refunded":
            when = f"{fmt.short_day(s.refunded_at)} {fmt.clock(s.refunded_at)}"
            self.banner.configure(text=note or f"REFUNDED  ·  {when}", fg=ERROR_FG)
            self.refund_btn.set(text="Already refunded", enabled=False)
        else:
            self.banner.configure(text="Valid — eligible for refund", fg=GOOD_FG)
            self.refund_btn.set(text=f"Refund {fmt.money(s.total_cents)}", enabled=True)

    def _sync_print_buttons(self) -> None:
        refunded = self.sale is not None and self.sale.status == "refunded"
        can_print = self.sale is not None and self.app.printer is not None and not self.printing
        self.receipt_btn.set(text="Print refund receipt" if refunded else "Print receipt", enabled=can_print)
        self.print_ticket_btn.set(enabled=can_print)

    def print_receipt(self) -> None:
        """Only prints when this is pressed (or P): the itemized receipt, or the refund receipt for a refunded sale."""
        self._print("Printing receipt…", "print_receipt")

    def print_ticket(self) -> None:
        """Reprint the ticket (a refunded sale's ticket prints with its VOID stamp)."""
        self._print("Printing ticket…", "print_sale")

    def _print(self, message: str, method: str) -> None:
        printer, sale = self.app.printer, self.sale
        if printer is None or sale is None or self.printing:
            return
        self.printing = True
        self.print_lbl.configure(text=message, fg=SUBTLE)
        self._sync_print_buttons()
        getattr(printer, method)(sale, self.store.venue_name(), on_done=self._print_finished)

    def _print_finished(self, result) -> None:
        self.printing = False
        self.print_lbl.configure(text=result.message, fg=GOOD_FG if result.ok else ERROR_FG)
        self._sync_print_buttons()

    def view_ticket(self) -> None:
        if self.sale:
            show_ticket(self, self.sale, self.store.venue_name())

    def refund(self) -> None:
        s = self.sale
        if s is None or s.status != "sold":
            return
        hint = {
            "cash": f"Hand the customer {fmt.money(s.total_cents)} in cash.",
            "card": f"Return {fmt.money(s.total_cents)} to the original card.",
            "credit": f"Return {fmt.money(s.total_cents)} to the customer's store credit.",
            "none": "No money to return (pass tickets).",
        }[s.payment_method]
        n = s.ticket_count
        warn = f"\n⚠ {s.checked_in} of {n} are already checked in." if s.checked_in else ""
        self.refund_stage = "confirming"  # the customer display shows the refund while the dialog is open
        if not confirm(self, f"Refund {n} ticket{'s' if n != 1 else ''} ({fmt.money(s.total_cents)})?\n{hint}{warn}", "Refund", danger=True):
            self.refund_stage = None
            return
        refunded = True
        try:
            self.sale = self.store.refund(s.id)
        except ValueError as e:
            alert(self, str(e), "Refund failed")
            self.sale = self.store.get_sale(s.id)
            refunded = False
        self.refresh()
        self.refund_stage = "done" if refunded else None
        self._show_sale(note=f"REFUNDED  ·  {hint}")

    def customer_view(self, venue: str) -> CustomerView:
        return make_return_view(venue=venue, now=datetime.now(), sale=self.sale, stage=self.refund_stage)
