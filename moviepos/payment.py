"""Payment panel: cash / card / store credit, laid out like the ticket sale's payment step."""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from . import fmt
from .keys import ENTER
from .theme import ACCENT, BG, BTN, ERROR_FG, F, GOOD, SUBTLE, TEXT
from .widgets import NumPad, TouchButton

GOOD_FG = "#4ade80"
METHODS = (("cash", "Cash"), ("card", "Card"), ("credit", "Store Credit"))


class PaymentPanel(tk.Frame):
    """Collects how a fixed total is paid. Calls on_complete(method, tendered_cents) when the cashier confirms."""

    def __init__(self, parent, total_cents: int, on_complete: Callable[[str, int | None], None], free_note: str = "Nothing to pay."):
        super().__init__(parent, bg=BG)
        self.total, self.on_complete = total_cents, on_complete
        self.method, self.tendered = "cash", ""
        if total_cents == 0:
            self._build_free(free_note)
            return
        toggles = tk.Frame(self, bg=BG)
        toggles.pack(fill="x", pady=(0, 10))
        self.method_btns = {}
        for i, (key, label) in enumerate(METHODS):
            toggles.grid_columnconfigure(i, weight=1, uniform="m")
            b = TouchButton(toggles, label, lambda k=key: self.set_method(k), pady=14)
            b.grid(row=0, column=i, sticky="ew", padx=4)
            self.method_btns[key] = b
        self.detail = tk.Frame(self, bg=BG)
        self.detail.pack(fill="both", expand=True)
        self._render_method()

    @property
    def tendered_cents(self) -> int:
        try:
            return fmt.parse_money(self.tendered)
        except ValueError:
            return 0

    def _build_free(self, note: str) -> None:
        tk.Label(self, text="No payment due", bg=BG, fg=TEXT, font=F["h1"]).pack(pady=(60, 8))
        tk.Label(self, text=note, bg=BG, fg=SUBTLE, font=F["row"]).pack()
        TouchButton(self, "Complete sale", self._complete, bg=GOOD, padx=60, pady=20).pack(pady=40)

    def set_method(self, method: str) -> None:
        self.method = method
        self._render_method()

    def _render_method(self) -> None:
        for key, b in self.method_btns.items():
            b.set(bg=ACCENT if key == self.method else BTN)
        d = self.detail
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
            tk.Label(panel, text=f"{heading} {fmt.money(self.total)}", bg=BG, fg=TEXT, font=F["h1"]).pack(pady=(50, 8))
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
        for i, (label, value) in enumerate([("Exact", self._exact()), ("$5", "5"), ("$10", "10"), ("$20", "20"), ("$50", "50"), ("$100", "100")]):
            quick.grid_columnconfigure(i % 3, weight=1, uniform="q")
            TouchButton(quick, label, lambda v=value: self._set_tendered(v), pady=12).grid(
                row=i // 3, column=i % 3, sticky="ew", padx=3, pady=3
            )
        TouchButton(right, "Clear", lambda: self._set_tendered(""), pady=10).pack(fill="x", pady=(6, 0), padx=3)
        self.complete_btn = TouchButton(right, "Complete sale", self._complete, bg=GOOD, pady=18)
        self.complete_btn.pack(fill="x", side="bottom", padx=3)
        self._sync_cash()

    def _exact(self) -> str:
        return f"{self.total // 100}.{self.total % 100:02d}"

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
        cents = self.tendered_cents
        self.tender_lbl.configure(text=fmt.money(cents))
        if cents >= self.total:
            self.change_lbl.configure(text=f"Change due: {fmt.money(cents - self.total)}", fg=GOOD_FG)
        else:
            self.change_lbl.configure(text=f"Still owed: {fmt.money(self.total - cents)}", fg=ERROR_FG if cents else SUBTLE)
        self.complete_btn.set(enabled=cents >= self.total)

    def _complete(self) -> None:
        self.on_complete(self.method, self.tendered_cents if self.total and self.method == "cash" else None)

    def handle_key(self, event, ch: str) -> bool:
        key = event.keysym
        if key in ENTER:
            if self.total == 0 or self.method != "cash" or self.tendered_cents >= self.total:
                self._complete()
            return True
        if self.total == 0:
            return False
        if key == "Tab":
            order = [k for k, _ in METHODS]
            self.set_method(order[(order.index(self.method) + 1) % len(order)])
        elif self.method != "cash":
            return False
        elif ch.isdigit() or ch == ".":
            self._cash_key(ch)
        elif key == "BackSpace":
            self._cash_back()
        elif key == "Delete":
            self._set_tendered("")
        elif ch in ("e", "E"):
            self._set_tendered(self._exact())
        else:
            return False
        return True
