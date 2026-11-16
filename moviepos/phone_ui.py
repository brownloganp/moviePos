"""POS-side UI for the phone web app: a QR code that opens it, and the controls around it."""
from __future__ import annotations

import tkinter as tk

from . import qr
from .dialogs import Dialog, confirm
from .theme import BG, BTN, F, PANEL, SUBTLE, TEXT, ERROR_FG
from .widgets import TouchButton


class QrView(tk.Canvas):
    QUIET = 4  # modules of white border the QR spec requires

    def __init__(self, parent, size: int = 360):
        super().__init__(parent, width=size, height=size, bg="white", highlightthickness=0)
        self.size = size

    def show(self, text: str) -> None:
        self.delete("all")
        matrix = qr.encode(text)
        total = len(matrix) + 2 * self.QUIET
        cell = self.size // total
        offset = (self.size - cell * total) // 2 + self.QUIET * cell
        for y, row in enumerate(matrix):
            x = 0
            while x < len(row):  # merge runs of dark modules into one rectangle
                if row[x]:
                    start = x
                    while x < len(row) and row[x]:
                        x += 1
                    self.create_rectangle(
                        offset + start * cell, offset + y * cell, offset + x * cell, offset + (y + 1) * cell,
                        fill="black", outline="black",
                    )
                else:
                    x += 1


class PhonePanel(tk.Frame):
    """QR code + instructions. `allow_reset` adds the new-access-key button."""

    def __init__(self, parent, app, allow_reset: bool = True, qr_size: int = 340):
        super().__init__(parent, bg=BG)
        self.app, self.allow_reset = app, allow_reset
        self.qr = QrView(self, qr_size)
        self.qr.pack(side="left", anchor="n", padx=(0, 28))
        right = tk.Frame(self, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        self.title = tk.Label(right, bg=BG, fg=TEXT, font=F["h2"], anchor="w", justify="left", wraplength=420)
        self.title.pack(fill="x")
        self.body = tk.Label(right, bg=BG, fg=SUBTLE, font=F["base"], anchor="nw", justify="left", wraplength=420)
        self.body.pack(fill="x", pady=(8, 12))
        self.address = tk.Label(right, bg=PANEL, fg=TEXT, font=F["base"], anchor="w", padx=12, pady=8)
        self.address.pack(fill="x")
        if allow_reset:
            TouchButton(right, "New access key", self._reset, pady=12, font=F["base"]).pack(fill="x", pady=(14, 0))
            tk.Label(
                right, bg=BG, fg=SUBTLE, font=F["small"], anchor="w", justify="left", wraplength=420,
                text="Makes a new QR code and signs out every phone that used the old one.",
            ).pack(fill="x", pady=(4, 0))
        self.refresh()

    def refresh(self) -> None:
        phone = self.app.phone
        if phone is None:
            self._unavailable("Phone check-in is turned off", "The POS was started with --no-web.")
        elif not phone.running:
            self._unavailable("Phone check-in isn't running", phone.error or "The web server did not start.")
        else:
            self.qr.show(phone.url())
            self.title.configure(text="Scan with the iPhone camera", fg=TEXT)
            self.body.configure(
                text="Opens the ticket taker page. The phone must be on the same network as this computer. "
                "Tip: in Safari, Share > Add to Home Screen for a full-screen app. A Bluetooth barcode "
                "scanner paired to the phone types ticket IDs straight into the page."
            )
            self.address.configure(text=f"http://{phone.host}:{phone.port}")

    def _unavailable(self, title: str, detail: str) -> None:
        self.qr.delete("all")
        self.title.configure(text=title, fg=ERROR_FG)
        self.body.configure(text=detail)
        self.address.configure(text="—")

    def _reset(self) -> None:
        phone = self.app.phone
        if phone is None or not phone.running:
            return
        if confirm(self, "Make a new access key?\nPhones using the old QR code will stop working until they scan the new one.", "New key", danger=True):
            phone.store.reset_web_key()
            self.refresh()


class PhoneTab(tk.Frame):
    """Settings tab wrapper."""

    def __init__(self, parent, app):
        super().__init__(parent, bg=BG)
        tk.Label(self, text="Phone check-in", bg=BG, fg=TEXT, font=F["h1"], anchor="w").pack(fill="x", pady=(0, 14))
        self.panel = PhonePanel(self, app)
        self.panel.pack(fill="x", anchor="n")

    def refresh(self) -> None:
        self.panel.refresh()


class PhoneDialog(Dialog):
    close_on_enter = True

    def __init__(self, master, app):
        super().__init__(master, "Phone check-in")
        panel = PhonePanel(self, app, allow_reset=False, qr_size=300)
        panel.pack(padx=28, pady=(28, 8))
        self.button_row([("Close", self.cancel, BTN)])


def show_phone_dialog(master, app) -> None:
    PhoneDialog(master, app).run()
