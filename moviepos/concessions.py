"""Concessions screen: pick items -> payment -> done (the receipt prints automatically)."""
from __future__ import annotations

import tkinter as tk
from datetime import datetime
from functools import partial

from . import fmt
from .customer_display import CustomerView, OrderLine, make_concession_view
from .dialogs import alert
from .keys import ENTER, key_char
from .payment import GOOD_FG, PaymentPanel
from .receipt import concession_order_id
from .theme import ACCENT, BG, BTN, ERROR_FG, F, GOOD, PANEL, SUBTLE, TEXT
from .widgets import PagedGrid, TouchButton

STEPS = ["order", "pay"]
STEP_LABELS = ["1   Order", "2   Payment"]
HINTS = {
    "order": "Keys:   1-9 add an item   Backspace remove the last item   Del clear   PgUp / PgDn pages   Enter payment   F1-F5 switch screens",
    "pay": "Keys:   Tab cash / card / store credit   0-9 and . cash received   E exact   Del clear   Enter complete sale   Esc back",
    "done": "Keys:   R print the receipt again   Enter or Space for a new order",
}


class ConcessionsScreen(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        self.app, self.store = app, app.store
        self.step = "order"
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
        self.qty: dict[int, int] = {}  # item id -> quantity, in the order items were first added
        self.menu: dict[int, object] = {}
        self.payment: PaymentPanel | None = None
        self.sale = None
        self.print_text, self.print_ok, self.printing = "", None, False
        self.picker: PagedGrid | None = None

    def refresh(self) -> None:
        if self.step == "done":
            self.new_order()
        else:
            self._load_menu()
            self.render()

    def _load_menu(self) -> None:
        """Re-read the menu so settings changes show up, and drop order lines for items that were removed."""
        self.menu = {i.id: i for i in self.store.list_concessions()}
        self.qty = {i: q for i, q in self.qty.items() if i in self.menu}
        if not self.qty and self.step == "pay":
            self.step = "order"

    def new_order(self) -> None:
        self._reset()
        self.step = "order"
        self._load_menu()
        self.render()

    def go_back_to(self, step: str) -> None:
        if self.step == "done" or STEPS.index(step) >= STEPS.index(self.step):
            return
        self.step = step
        self.render()

    def goto(self, step: str) -> None:
        self.step = step
        self.render()

    def render(self) -> None:
        for w in self.body.winfo_children():
            w.destroy()
        self.picker, self.payment = None, None
        getattr(self, f"_show_{self.step}")()
        self.hint.configure(text=HINTS[self.step])
        current = STEPS.index(self.step) if self.step in STEPS else len(STEPS)
        for i, b in enumerate(self.crumbs):
            if i == current:
                b.set(bg=ACCENT, enabled=True)
            else:
                b.set(bg=BTN, enabled=i < current and self.step != "done")

    # ---- step 1: order --------------------------------------------------

    def _lines(self) -> list[tuple[object, int]]:
        return [(self.menu[i], q) for i, q in self.qty.items() if i in self.menu]

    def _total(self) -> int:
        return sum(item.price_cents * q for item, q in self._lines())

    def _show_order(self) -> None:
        cart = tk.Frame(self.body, bg=PANEL, width=400)
        cart.pack(side="right", fill="y", padx=(12, 0))
        cart.pack_propagate(False)
        tk.Label(cart, text="Order", bg=PANEL, fg=TEXT, font=F["h2"]).pack(anchor="w", padx=16, pady=(14, 4))
        foot = tk.Frame(cart, bg=PANEL)
        foot.pack(side="bottom", fill="x", padx=12, pady=(0, 12))
        self.total_lbl = tk.Label(foot, bg=PANEL, fg=TEXT, font=F["h1"], anchor="w")
        self.total_lbl.pack(fill="x", pady=(0, 8))
        buttons = tk.Frame(foot, bg=PANEL)
        buttons.pack(fill="x")
        buttons.grid_columnconfigure(1, weight=1)
        self.clear_btn = TouchButton(buttons, "Clear", self._clear, pady=14, padx=20)
        self.clear_btn.grid(row=0, column=0, padx=(0, 8))
        self.next_btn = TouchButton(buttons, "Payment  ▶", self._to_payment, bg=GOOD, pady=14)
        self.next_btn.grid(row=0, column=1, sticky="ew")
        self.lines_box = tk.Frame(cart, bg=PANEL)
        self.lines_box.pack(fill="both", expand=True, padx=12)

        items = list(self.menu.values())

        def make(parent, item):
            price = fmt.money(item.price_cents) if item.price_cents else "Free"
            return TouchButton(parent, f"{item.name}\n{price}", lambda: self._add(item.id), wraplength=220, padx=8)

        self.picker = PagedGrid(self.body, 3, 4, make, "No items on the menu — add some in Settings → Concessions", numbered=True)
        self.picker.set_items(items)
        self.picker.pack(side="left", fill="both", expand=True)
        self._sync_order()

    def _sync_order(self) -> None:
        for w in self.lines_box.winfo_children():
            w.destroy()
        lines = self._lines()
        if not lines:
            tk.Label(self.lines_box, text="Tap an item to add it", bg=PANEL, fg=SUBTLE, font=F["base"]).pack(pady=24)
        for item, q in lines:
            row = tk.Frame(self.lines_box, bg=PANEL)
            row.pack(fill="x", pady=3)
            row.grid_columnconfigure(0, weight=1)
            tk.Label(row, text=item.name, bg=PANEL, fg=TEXT, font=F["base"], anchor="w", wraplength=150, justify="left").grid(
                row=0, column=0, sticky="w"
            )
            TouchButton(row, "−", lambda i=item.id: self._adjust(i, -1), font=F["key"], width=2, pady=2, padx=4).grid(row=0, column=1, padx=2)
            tk.Label(row, text=str(q), bg=PANEL, fg=TEXT, font=F["h2"], width=3).grid(row=0, column=2)
            TouchButton(row, "+", lambda i=item.id: self._adjust(i, 1), font=F["key"], width=2, pady=2, padx=4, bg=ACCENT).grid(row=0, column=3, padx=2)
            tk.Label(row, text=fmt.money(item.price_cents * q), bg=PANEL, fg=SUBTLE, font=F["base"], width=8, anchor="e").grid(row=0, column=4)
        count = sum(q for _, q in lines)
        self.total_lbl.configure(text=f"{count} item{'s' if count != 1 else ''}   {fmt.money(self._total())}")
        self.clear_btn.set(enabled=bool(lines))
        self.next_btn.set(enabled=bool(lines))

    def _add(self, item_id: int) -> None:
        self._adjust(item_id, 1)

    def _adjust(self, item_id: int, delta: int) -> None:
        new = self.qty.get(item_id, 0) + delta
        if new > 99:
            return
        if new <= 0:
            self.qty.pop(item_id, None)
        else:
            self.qty[item_id] = new
        self._sync_order()

    def _remove_last(self) -> None:
        if self.qty:
            self._adjust(list(self.qty)[-1], -1)

    def _clear(self) -> None:
        self.qty = {}
        self._sync_order()

    def _to_payment(self) -> None:
        if self.qty:
            self.goto("pay")

    # ---- step 2: payment ------------------------------------------------

    def _show_pay(self) -> None:
        total = self._total()
        left = tk.Frame(self.body, bg=PANEL, width=340)
        left.pack(side="left", fill="y", padx=(0, 12))
        left.pack_propagate(False)
        tk.Label(left, text="Concessions", bg=PANEL, fg=TEXT, font=F["h2"]).pack(anchor="w", padx=16, pady=(16, 2))
        lines = "\n".join(f"{q} × {item.name}   {fmt.money(item.price_cents * q)}" for item, q in self._lines())
        tk.Label(left, text=lines, bg=PANEL, fg=TEXT, font=F["row"], justify="left", wraplength=310).pack(anchor="w", padx=16, pady=16)
        tk.Label(left, text=fmt.money(total), bg=PANEL, fg=TEXT, font=F["huge"]).pack(anchor="w", padx=16, side="bottom", pady=(0, 16))
        tk.Label(left, text="TOTAL DUE", bg=PANEL, fg=SUBTLE, font=F["small"]).pack(anchor="w", padx=16, side="bottom")
        self.payment = PaymentPanel(self.body, total, self._complete, free_note="These items are free.")
        self.payment.pack(side="left", fill="both", expand=True)

    def _complete(self, method: str, tendered: int | None) -> None:
        try:
            sale = self.store.concession_sell(dict(self.qty), method, tendered)
        except ValueError as e:
            alert(self, str(e), "Sale not completed")
            self.qty = {}
            self.step = "order"
            self._load_menu()
            self.render()
            return
        self.sale = sale
        self.goto("done")
        self.print_receipt()  # automatic: no tap needed

    # ---- customer display -----------------------------------------------

    def customer_view(self, venue: str) -> CustomerView:
        payment = self.payment if self.step == "pay" else None
        return make_concession_view(
            venue=venue, now=datetime.now(), step=self.step,
            lines=tuple(OrderLine(item.name, q, item.price_cents) for item, q in self._lines()),
            method=payment.method if payment else None, tendered_cents=payment.tendered_cents if payment else 0,
            sale=self.sale,
        )

    # ---- keyboard -------------------------------------------------------

    def handle_key(self, event) -> bool:
        key, ch = event.keysym, key_char(event)
        if key == "Escape":
            if self.step == "done":
                self.new_order()
            elif self.step == "pay":
                self.go_back_to("order")
            return True
        if self.step == "done":
            if key in ENTER or ch in (" ", "n", "N"):
                self.new_order()
                return True
            if ch in ("r", "R"):
                self.print_receipt()
                return True
            return False
        if self.step == "pay":
            return bool(self.payment and self.payment.handle_key(event, ch))
        if key in ENTER:
            self._to_payment()
        elif ch.isdigit() and ch != "0":
            self.picker.invoke(int(ch))
        elif key in ("Prior", "Next"):
            self.picker.page_by(-1 if key == "Prior" else 1)
        elif key == "BackSpace":
            self._remove_last()
        elif key == "Delete":
            self._clear()
        else:
            return False
        return True

    # ---- done -----------------------------------------------------------

    def print_receipt(self) -> None:
        printer = self.app.printer
        if printer is None or self.sale is None or self.printing:
            return
        self.printing, self.print_ok, self.print_text = True, None, "Printing receipt…"
        self._show_print_status()
        printer.print_concession_receipt(self.sale, self.store.venue_name(), on_done=partial(self._print_finished, self.sale.id))

    def _print_finished(self, sale_id: int, result) -> None:
        self.printing = False
        if self.sale is not None and self.sale.id == sale_id:
            self.print_ok, self.print_text = result.ok, result.message
        self._show_print_status()

    def _show_print_status(self) -> None:
        label = getattr(self, "print_lbl", None)
        if label is None or not label.winfo_exists() or self.step != "done":
            return
        color = GOOD_FG if self.print_ok else ERROR_FG if self.print_ok is False else SUBTLE
        label.configure(text=self.print_text, fg=color)
        self.receipt_btn.set(enabled=self.app.printer is not None and not self.printing)

    def _show_done(self) -> None:
        sale = self.sale
        box = tk.Frame(self.body, bg=BG)
        box.pack(expand=True)
        tk.Label(box, text="ORDER COMPLETE", bg=BG, fg=GOOD_FG, font=F["h1"]).pack()
        tk.Label(box, text="Order number", bg=BG, fg=SUBTLE, font=F["base"]).pack(pady=(14, 0))
        tk.Label(box, text=concession_order_id(sale.id), bg=BG, fg=TEXT, font=F["huge"]).pack()
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
        self.print_lbl = tk.Label(box, bg=BG, font=F["base"], wraplength=400, justify="center")
        self.print_lbl.pack(pady=(18, 8))
        self.receipt_btn = TouchButton(box, "Print receipt again", self.print_receipt, pady=10, padx=12, font=F["base"])
        self.receipt_btn.pack()
        TouchButton(box, "New order", self.new_order, bg=ACCENT, padx=70, pady=16).pack(pady=(18, 4))
        if self.app.printer is None:
            self.print_text = "Receipt printing is turned off"
        self._show_print_status()
