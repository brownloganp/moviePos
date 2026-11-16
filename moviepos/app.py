"""Main window: top bar with navigation, and the three screens."""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime
from types import SimpleNamespace

from .checkin import CheckInScreen
from .concessions import ConcessionsScreen
from .customer_display import CustomerDisplay, CustomerView
from .returns import ReturnsScreen
from .sell import SellScreen
from .settings import SettingsScreen
from .store import Store
from .ticket_print import TicketPrinter
from .theme import ACCENT, BG, BTN, F, PANEL, SUBTLE, TEXT, init_fonts
from .widgets import TouchButton
from . import fmt
from .keys import has_modifier


class App(tk.Tk):
    def __init__(self, store: Store, fullscreen: bool = False, phone=None, customer_display: bool = True, customer_fullscreen: bool = False,
        printer_name: str | None = None, printer_dots: int = 576, printer_cut: bool = True,
    ):
        super().__init__()
        self.phone = phone  # PhoneAccess for the QR code, or None when the web app is off
        init_fonts()
        self.store = store
        self.title("Movie POS")
        self.configure(bg=BG)
        self.geometry("1280x800")
        self.minsize(1024, 700)
        if fullscreen:
            self.attributes("-fullscreen", True)
            self.bind("<Escape>", lambda _e: self.attributes("-fullscreen", False))

        bar = tk.Frame(self, bg=PANEL)
        bar.pack(fill="x")
        tk.Label(bar, text="🎬  Movie POS", bg=PANEL, fg=TEXT, font=F["h2"]).pack(side="left", padx=20)
        self.clock = tk.Label(bar, bg=PANEL, fg=SUBTLE, font=F["base"])
        self.clock.pack(side="right", padx=20)
        self.customer_btn = TouchButton(bar, "CUSTOMER SCREEN", self._show_customer, width=17, pady=14, font=F["base"])
        self.customer_btn.pack(side="right", pady=8)
        self.nav: dict[str, TouchButton] = {}
        for key, label in [
            ("sell", "SELL  F1"), ("concessions", "CONCESSIONS  F5"), ("returns", "RETURNS  F2"),
            ("checkin", "TICKET TAKER  F3"), ("settings", "SETTINGS  F4"),
        ]:
            self.nav[key] = TouchButton(bar, label, lambda k=key: self.show(k), padx=18, pady=14, font=F["base"])
            self.nav[key].pack(side="left", padx=(8, 0), pady=8)

        container = tk.Frame(self, bg=BG)
        container.pack(fill="both", expand=True)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)
        self.printer = TicketPrinter(self, printer_name, printer_dots, printer_cut) if printer_name else None
        self.screens = {
            "sell": SellScreen(container, self),
            "concessions": ConcessionsScreen(container, self),
            "returns": ReturnsScreen(container, self),
            "checkin": CheckInScreen(container, self),
            "settings": SettingsScreen(container, self),
        }
        for screen in self.screens.values():
            screen.grid(row=0, column=0, sticky="nsew")
        self.current = "sell"
        self._venue = ("", 0.0)
        self.customer = CustomerDisplay(self, fullscreen=customer_fullscreen) if customer_display else None
        if self.customer:
            self.focus_force()  # keep the keyboard on the cashier's window
        self.customer_btn.set(enabled=self.customer is not None)
        self.show("sell")
        self.bind_all("<Key>", self._on_key)
        # Tk turns Tab / Shift+Tab into focus-traversal virtual events before <Key> sees them, on every platform.
        self.bind_all("<<NextWindow>>", lambda _e: self._on_key(SimpleNamespace(keysym="Tab", char="", state=0)))
        self.bind_all("<<PrevWindow>>", lambda _e: self._on_key(SimpleNamespace(keysym="ISO_Left_Tab", char="", state=1)))
        self._tick()

    def show(self, key: str) -> None:
        self.current = key
        for k, b in self.nav.items():
            b.set(bg=ACCENT if k == key else BTN)
        screen = self.screens[key]
        screen.refresh()
        screen.tkraise()

    def venue_name(self) -> str:
        """The theater name, re-read from the database at most every couple of seconds."""
        name, fetched = self._venue
        if time.monotonic() - fetched > 2.0:
            name = self.store.venue_name()
            self._venue = (name, time.monotonic())
        return name

    def customer_view(self) -> CustomerView:
        """What the customer-facing window should show right now."""
        if self.current == "returns":
            return self.screens["returns"].customer_view(self.venue_name())
        if self.current == "concessions":
            return self.screens["concessions"].customer_view(self.venue_name())
        return self.screens["sell"].customer_view(self.venue_name(), on_sell=self.current == "sell")

    def _show_customer(self) -> None:
        if self.customer:
            self.customer.show()

    SCREEN_KEYS = {"F1": "sell", "F2": "returns", "F3": "checkin", "F4": "settings", "F5": "concessions"}

    def _on_key(self, event):
        """Send a key press to the open dialog, or else the visible screen. F1-F4 switch screens."""
        if has_modifier(event):
            return None
        dialog = self.grab_current()
        if dialog is not None:
            handler = getattr(dialog, "handle_key", None)
        elif event.keysym in self.SCREEN_KEYS:
            self.show(self.SCREEN_KEYS[event.keysym])
            return "break"
        else:
            handler = getattr(self.screens[self.current], "handle_key", None)
        return "break" if handler and handler(event) else None

    def _tick(self) -> None:
        now = datetime.now()
        self.clock.configure(text=f"{fmt.short_day(now)}   {fmt.clock(now)}")
        self.after(15_000, self._tick)
