"""Formatting and parsing helpers shared by the UI."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from decimal import Decimal


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def parse_money(text: str) -> int:
    text = text.strip().lstrip("$")
    if not text or not re.fullmatch(r"\d*\.?\d*", text) or text == ".":
        raise ValueError("Enter a dollar amount, like 12.50.")
    return int((Decimal(text) * 100).quantize(Decimal(1)))


def parse_int(text: str, label: str) -> int:
    if not text.strip().isdigit():
        raise ValueError(f"{label} must be a whole number.")
    return int(text)


def clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def short_day(d: date | datetime) -> str:
    return f"{d:%a %b} {d.day}"


def day_label(d: date) -> str:
    today = date.today()
    if d == today:
        return f"Today · {short_day(d)}"
    if d == today + timedelta(days=1):
        return f"Tomorrow · {short_day(d)}"
    return short_day(d)


def runtime(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def tx_id(n: int) -> str:
    return f"{n:06d}"


def movie_line(rating: str, minutes: int) -> str:
    return f"{rating} · {runtime(minutes)}" if rating else runtime(minutes)
