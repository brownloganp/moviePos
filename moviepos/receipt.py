"""Itemized receipt for a sale or a refund: a normal upright receipt, not the sideways ticket.

build_rows() decides what is printed (no drawing, easy to test); layout() places it on the paper.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol

from . import fmt
from .store import ConcessionSale, Sale

DOTS = 576
MARGIN = 20


@dataclass(frozen=True)
class Row:
    kind: str  # text | pair | rule | gap
    left: str = ""
    right: str = ""
    px: int = 24
    bold: bool = False
    align: str = "left"  # text rows: left | center
    space: int = 0  # extra blank dots after the row


class Metrics(Protocol):
    def width(self, text: str, px: int, bold: bool) -> float: ...
    def ascent(self, px: int, bold: bool) -> float: ...
    def linespace(self, px: int, bold: bool) -> float: ...


def _stamp(when: datetime) -> str:
    return f"{fmt.short_day(when)}, {when.year}  {fmt.clock(when)}"


def build_rows(sale: Sale, venue: str, refund: bool | None = None) -> list[Row]:
    """The receipt lines. A refunded sale prints as a refund receipt unless `refund=False` is forced."""
    refund = sale.status == "refunded" if refund is None else refund
    show = sale.showing
    sign = "-" if refund and sale.total_cents else ""
    rows = [
        Row("text", venue, px=40, bold=True, align="center"),
        Row("text", "REFUND RECEIPT" if refund else "SALES RECEIPT", px=26, bold=True, align="center", space=6),
        Row("rule"),
        Row("pair", "Transaction", fmt.tx_id(sale.id), bold=True),
    ]
    if refund and sale.refunded_at:
        rows += [Row("pair", "Sold", _stamp(sale.created_at)), Row("pair", "Refunded", _stamp(sale.refunded_at))]
    else:
        rows.append(Row("pair", "Date", _stamp(sale.created_at)))
    rows += [
        Row("rule"),
        Row("text", show.title, px=28, bold=True),
        Row("text", f"{fmt.short_day(show.starts_at)}  ·  {fmt.clock(show.starts_at)}"),
        Row("text", show.theater_name),
        Row("rule"),
    ]
    for item in sale.items:
        if item.unit_price_cents:
            rows.append(Row("pair", f"{item.qty} × {item.ticket_type} @ {fmt.money(item.unit_price_cents)}", sign + fmt.money(item.line_cents)))
        else:
            rows.append(Row("pair", f"{item.qty} × {item.ticket_type}", "Free"))
    total = sign + fmt.money(sale.total_cents)
    rows += [Row("rule"), Row("pair", "Subtotal", total)]
    if refund:
        rows.append(Row("pair", "REFUND TOTAL", total, px=30, bold=True, space=6))
        method = {
            "cash": "Cash returned to customer", "card": "Refunded to the original card",
            "credit": "Refunded as store credit", "none": "No payment to refund",
        }
        rows.append(Row("text", method[sale.payment_method]))
        rows.append(Row("text", "These tickets are no longer valid."))
    else:
        rows.append(Row("pair", "TOTAL", total, px=30, bold=True, space=6))
        if sale.payment_method == "cash":
            rows += [
                Row("pair", "Cash received", fmt.money(sale.tendered_cents)),
                Row("pair", "Change", fmt.money(sale.change_cents), px=28, bold=True),
            ]
        elif sale.payment_method == "card":
            rows.append(Row("pair", "Paid by card", fmt.money(sale.total_cents)))
        elif sale.payment_method == "credit":
            rows.append(Row("pair", "Paid by store credit", fmt.money(sale.total_cents)))
        else:
            rows.append(Row("text", "No payment due"))
    rows += [Row("rule"), Row("text", "We hope to see you again." if refund else "Thank you!", px=26, bold=True, align="center")]
    return rows


def concession_order_id(sale_id: int) -> str:
    return f"C{fmt.tx_id(sale_id)}"


def build_concession_rows(sale: ConcessionSale, venue: str) -> list[Row]:
    """The receipt lines for a concessions order."""
    rows = [
        Row("text", venue, px=40, bold=True, align="center"),
        Row("text", "CONCESSIONS RECEIPT", px=26, bold=True, align="center", space=6),
        Row("rule"),
        Row("pair", "Order", concession_order_id(sale.id), bold=True),
        Row("pair", "Date", _stamp(sale.created_at)),
        Row("rule"),
    ]
    for item in sale.items:
        if item.unit_price_cents:
            rows.append(Row("pair", f"{item.qty} × {item.name} @ {fmt.money(item.unit_price_cents)}", fmt.money(item.line_cents)))
        else:
            rows.append(Row("pair", f"{item.qty} × {item.name}", "Free"))
    total = fmt.money(sale.total_cents)
    rows += [Row("rule"), Row("pair", "TOTAL", total, px=30, bold=True, space=6)]
    if sale.payment_method == "cash":
        rows += [
            Row("pair", "Cash received", fmt.money(sale.tendered_cents)),
            Row("pair", "Change", fmt.money(sale.change_cents), px=28, bold=True),
        ]
    elif sale.payment_method == "card":
        rows.append(Row("pair", "Paid by card", total))
    elif sale.payment_method == "credit":
        rows.append(Row("pair", "Paid by store credit", total))
    else:
        rows.append(Row("text", "No payment due"))
    rows += [Row("rule"), Row("text", "Thank you!", px=26, bold=True, align="center")]
    return rows


def layout(rows: list[Row], metrics: Metrics, dots: int = DOTS, margin: int = MARGIN) -> tuple[list[tuple], int]:
    """Place the rows top to bottom. Returns drawing ops in paper dots and the paper height needed.

    ops: ("text", [(x, baseline_y, text)], px, bold, 0.0) and ("line", x0, y0, x1, y1, width, dashed)
    """
    content = dots - 2 * margin
    ops: list[tuple] = []
    y = 26.0

    def wrap(text: str, px: int, bold: bool, limit: float) -> list[str]:
        lines: list[str] = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split(" "):
                trial = f"{current} {word}" if current else word
                if metrics.width(trial, px, bold) <= limit:
                    current = trial
                    continue
                if current:
                    lines.append(current)
                while metrics.width(word, px, bold) > limit and len(word) > 1:
                    cut = len(word)
                    while cut > 1 and metrics.width(word[:cut], px, bold) > limit:
                        cut -= 1
                    lines.append(word[:cut])
                    word = word[cut:]
                current = word
            lines.append(current)
        return lines

    for row in rows:
        if row.kind == "rule":
            ops.append(("line", margin, y + 8, dots - margin, y + 8, 2.0, True))
            y += 22
            continue
        step = metrics.linespace(row.px, row.bold) + 4
        ascent = metrics.ascent(row.px, row.bold)
        if row.kind == "text":
            for line in wrap(row.left, row.px, row.bold, content):
                w = metrics.width(line, row.px, row.bold)
                x = margin + (content - w) / 2 if row.align == "center" else margin
                ops.append(("text", [(x, y + ascent, line)], row.px, row.bold, 0.0))
                y += step
        elif row.kind == "pair":
            right_w = metrics.width(row.right, row.px, row.bold)
            lines = wrap(row.left, row.px, row.bold, content - right_w - 18)
            ops.append(("text", [(dots - margin - right_w, y + ascent, row.right)], row.px, row.bold, 0.0))
            for line in lines:
                ops.append(("text", [(margin, y + ascent, line)], row.px, row.bold, 0.0))
                y += step
        y += row.space
    return ops, int(y + 18)
