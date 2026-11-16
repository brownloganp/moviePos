"""Movie ticket: printer-agnostic content plus an on-screen preview.

The ticket is landscape (it prints sideways, so it is long): a customer copy taking the left
four fifths, a dotted tear line, and a compact theater-copy stub in the last fifth.
"""
from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass

from . import code128, fmt
from .dialogs import Dialog
from .store import Sale
from .theme import BG, BTN


@dataclass(frozen=True)
class TicketContent:
    venue: str
    title: str
    rating_runtime: str
    day: str  # Thu Oct 29
    time: str
    theater: str
    items: tuple[tuple[str, int], ...]  # (ticket type, count). No prices or totals on the ticket.
    admit: int
    barcode_digits: str
    id_text: str
    sold: str
    void: bool


def build_ticket(sale: Sale, venue: str) -> TicketContent:
    show = sale.showing
    return TicketContent(
        venue=venue,
        title=show.title,
        rating_runtime=fmt.movie_line(show.rating, show.runtime_min),
        day=fmt.short_day(show.starts_at),
        time=fmt.clock(show.starts_at),
        theater=show.theater_name,
        items=tuple((i.ticket_type, i.qty) for i in sale.items),
        admit=sale.ticket_count,
        barcode_digits=code128.barcode_text(sale.id),
        id_text=fmt.tx_id(sale.id),
        sold=f"Sold {fmt.short_day(sale.created_at)} {fmt.clock(sale.created_at)}",
        void=sale.status == "refunded",
    )


def wrap_lines(text: str, font, width: int) -> list[str]:
    """Break text into lines the way a Tk canvas text item does: at spaces, or mid-word if one word is too long."""
    if not width:
        return text.split("\n") or [""]
    lines: list[str] = []
    for paragraph in text.split("\n"):
        current = ""
        for word in paragraph.split(" "):
            trial = f"{current} {word}" if current else word
            if font.measure(trial) <= width:
                current = trial
                continue
            if current:
                lines.append(current)
            while font.measure(word) > width and len(word) > 1:  # a single word wider than the column
                cut = len(word)
                while cut > 1 and font.measure(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            current = word
        lines.append(current)
    return lines


class TicketView(tk.Canvas):
    W, H, M = 820, 300, 10  # ticket size and the margin around it
    STUB_W = W // 5
    MAIN_W = W - STUB_W
    PAPER = "#fffdf7"
    INK = "#111111"
    VOID = "#b91c1c"

    def __init__(self, parent):
        super().__init__(parent, width=self.W + 2 * self.M, height=self.H + 2 * self.M, bg=BG, highlightthickness=0)
        self._fonts: dict[tuple[int, bool], tkfont.Font] = {}

    def font(self, px: int, bold: bool = False) -> tkfont.Font:
        key = (px, bold)
        if key not in self._fonts:
            self._fonts[key] = tkfont.Font(family="Helvetica", size=-px, weight="bold" if bold else "normal")
        return self._fonts[key]

    def show(self, sale: Sale, venue: str) -> None:
        self.delete("all")
        self._barcode_box = None
        c = build_ticket(sale, venue)
        self._paper()
        self._fit("main", lambda k: self._main_text(c, k), (1.2, 1.1, 1.0, 0.92, 0.85, 0.78, 0.7, 0.62))
        self._right_column(c)
        self._fit("stub", lambda k: self._stub(c, k))
        self._small_print(c)
        if c.void:
            self._void()

    # ---- export for the printer ----

    def primitives(self) -> list[tuple]:
        """The laid-out ticket as plain drawing instructions, in ticket pixels with (0, 0) at the paper's
        top-left corner. Text is already wrapped. Used by the receipt printer so it matches the preview.

        ("rect", x0, y0, x1, y1) | ("line", x0, y0, x1, y1, width, dashed)
        ("barcode", modules, x, y, width, height)
        ("text", [(x, baseline_y, text), ...], px, bold, angle_degrees)
        """
        m, out = self.M, []
        for item in self.find_all():
            kind = self.type(item)
            if "bar" in self.gettags(item):
                continue
            if kind == "rectangle":
                x0, y0, x1, y1 = self.coords(item)
                if self.itemcget(item, "fill") != self.PAPER:
                    out.append(("rect", x0 - m, y0 - m, x1 - m, y1 - m))
            elif kind == "line":
                x0, y0, x1, y1 = self.coords(item)
                out.append(("line", x0 - m, y0 - m, x1 - m, y1 - m, float(self.itemcget(item, "width")), bool(self.itemcget(item, "dash"))))
            elif kind == "text":
                out.append(self._text_primitive(item))
        if getattr(self, "_barcode_box", None):
            modules, x, y, width, height = self._barcode_box
            out.append(("barcode", modules, x - m, y - m, width, height))
        return out

    def _text_primitive(self, item) -> tuple:
        font = tkfont.nametofont(self.itemcget(item, "font"))
        px, bold = abs(int(font.actual("size"))), font.actual("weight") == "bold"
        x, y = self.coords(item)
        m = self.M
        wrap = int(float(self.itemcget(item, "width") or 0))
        anchor, justify = self.itemcget(item, "anchor"), self.itemcget(item, "justify")
        angle = float(self.itemcget(item, "angle") or 0)
        lines = wrap_lines(self.itemcget(item, "text"), font, wrap)
        ascent, linespace = font.metrics("ascent"), font.metrics("linespace")
        widths = [font.measure(line) for line in lines]
        block = max(widths)
        if anchor == "center":  # single rotated line (the VOID stamp): turn it about its centre
            dx, dy = -widths[0] / 2, ascent - linespace / 2
            t = math.radians(angle)
            start = (x + dx * math.cos(t) + dy * math.sin(t), y - dx * math.sin(t) + dy * math.cos(t))
            return ("text", [(start[0] - m, start[1] - m, lines[0])], px, bold, angle)
        left = {"nw": x, "n": x - block / 2, "ne": x - block}[anchor]
        placed = []
        for i, (line, w) in enumerate(zip(lines, widths)):
            shift = {"left": 0, "center": (block - w) / 2, "right": block - w}[justify]
            placed.append((left + shift - m, y + i * linespace + ascent - m, line))
        return ("text", placed, px, bold, 0.0)

    # ---- drawing helpers ----

    def _text(self, x, y, text, px, bold=False, width=None, anchor="nw", justify="left", fill=None, angle=0, tag="") -> int:
        item = self.create_text(
            x, y, text=text, font=self.font(px, bold), fill=fill or self.INK, anchor=anchor,
            width=width, justify=justify, angle=angle, tags=(tag,) if tag else (),
        )
        return self.bbox(item)[3]

    def _fit(self, tag: str, draw, scales=(1.0, 0.92, 0.85, 0.78, 0.7, 0.62)) -> None:
        """Draw a block of text at the largest scale that clears the small print."""
        limit = self.M + self.H - 34
        for scale in scales:
            self.delete(tag)
            draw(scale)
            box = self.bbox(tag)
            if box is None or box[3] <= limit:
                break

    def _paper(self) -> None:
        m, w, h = self.M, self.W, self.H
        self.create_rectangle(m, m, m + w, m + h, fill=self.PAPER, outline=self.PAPER)
        perf = m + self.MAIN_W
        self.create_line(perf, m + 12, perf, m + h - 12, dash=(2, 5), width=2, fill="#777777")
        for y in (m, m + h):  # the punched notches at both ends of the tear line
            self.create_oval(perf - 10, y - 10, perf + 10, y + 10, fill=BG, outline=BG)

    def _main_text(self, c: TicketContent, k: float) -> None:
        """Left column of the customer copy: venue, title, time, day, theater."""
        px = lambda n: max(8, round(n * k))
        x, w = self.M + 30, 372
        y = self.M + 20
        y = self._text(x, y, c.venue, px(15), True, width=w, tag="main") + 6
        title_px = 32 if len(c.title) <= 24 else 26 if len(c.title) <= 40 else 21
        y = self._text(x, y, c.title, px(title_px), True, width=w, tag="main") + 2
        y = self._text(x, y, c.rating_runtime, px(14), width=w, tag="main") + 14
        self._text(x, y, c.time, px(42), True, tag="main")
        side = x + round(205 * k)
        y = self._text(side, y + 2, c.day, px(18), True, width=x + w - side, tag="main") + 2
        self._text(side, y, c.theater, px(19), True, width=x + w - side, tag="main")

    def _right_column(self, c: TicketContent) -> None:
        m = self.M
        width = 210
        rx = m + self.MAIN_W - 26 - width
        ry = self._text(rx, m + 22, f"ADMIT {c.admit}", 20, True) + 4
        for kind, qty in c.items:
            ry = self._text(rx, ry, f"{qty} × {kind}", 16) + 2
        self._barcode(c.barcode_digits, rx, m + 166, width, 60)
        self._text(rx + width / 2, m + 233, c.id_text, 17, True, anchor="n")

    def _small_print(self, c: TicketContent) -> None:
        m = self.M
        self._text(m + 30, m + self.H - 22, "Customer Copy", 11)
        self._text(m + self.MAIN_W - 26, m + self.H - 22, c.sold, 11, anchor="ne")
        self._text(m + self.MAIN_W + 16, m + self.H - 22, "Theater Copy", 10)

    def _barcode(self, digits: str, x: int, y: int, width: int, height: int) -> None:
        modules = code128.encode(digits)
        self._barcode_box = (modules, x, y, width, height)
        unit = 3 if len(modules) * 3 <= width else 2
        left = x + (width - len(modules) * unit) // 2
        start = None
        for i, bit in enumerate(modules + "0"):
            if bit == "1" and start is None:
                start = i
            elif bit == "0" and start is not None:
                self.create_rectangle(
                    left + start * unit, y, left + i * unit, y + height, fill=self.INK, outline=self.INK, tags=("bar",)
                )
                start = None

    def _stub(self, c: TicketContent, k: float) -> None:
        """Theater copy: the same facts, compacted into the last fifth."""
        px = lambda n: max(7, round(n * k))
        m = self.M
        x, w = m + self.MAIN_W + 16, self.STUB_W - 28
        y = m + 20
        y = self._text(x, y, c.venue, px(11), True, width=w, tag="stub") + 5
        y = self._text(x, y, c.title, px(15), True, width=w, tag="stub") + 8
        y = self._text(x, y, c.day, px(13), True, width=w, tag="stub") + 1
        y = self._text(x, y, c.time, px(24), True, width=w, tag="stub")
        y = self._text(x, y, c.theater, px(14), width=w, tag="stub") + 8
        y = self._text(x, y, ", ".join(f"{q} {kind}" for kind, q in c.items), px(12), width=w, tag="stub") + 6
        self._text(x, y, f"ID {c.id_text}", px(13), True, width=w, tag="stub")

    def _void(self) -> None:
        m = self.M
        self._text(m + self.MAIN_W / 2, m + self.H / 2, "VOID - REFUNDED", 50, True, anchor="center", fill=self.VOID, angle=12)
        self._text(m + self.MAIN_W + self.STUB_W / 2, m + self.H / 2, "VOID", 26, True, anchor="center", fill=self.VOID, angle=12)


class TicketDialog(Dialog):
    close_on_enter = True

    def __init__(self, master, sale: Sale, venue: str):
        super().__init__(master, f"Ticket {fmt.tx_id(sale.id)}")
        view = TicketView(self)
        view.pack(padx=24, pady=(24, 8))
        view.show(sale, venue)
        self.button_row([("Close", self.cancel, BTN)])


def show_ticket(master, sale: Sale, venue: str) -> None:
    TicketDialog(master, sale, venue).run()
