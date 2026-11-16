"""Keyboard helpers shared by every screen and dialog."""
from __future__ import annotations

import sys

ENTER = ("Return", "KP_Enter")

_NAMED = {
    "space": " ", "period": ".", "comma": ",", "minus": "-", "plus": "+", "equal": "=", "apostrophe": "'",
    "colon": ":", "exclam": "!", "question": "?", "ampersand": "&", "slash": "/",
    "KP_Add": "+", "KP_Subtract": "-", "KP_Decimal": ".",
}


def key_char(event) -> str:
    """The printable character a key press produces ('' for keys like Tab or arrows)."""
    ch = event.char
    if ch and ch.isprintable():
        return ch
    key = event.keysym
    if key.startswith("KP_") and key[3:].isdigit():
        return key[3:]
    if len(key) == 1:
        return key
    return _NAMED.get(key, "")


def has_modifier(event) -> bool:
    """Ctrl (or Command on a Mac) is held, so this is a shortcut for the system, not typing."""
    state = event.state if isinstance(event.state, int) else 0
    return bool(state & 0x4) or (sys.platform == "darwin" and bool(state & 0x8))


def shift_held(event) -> bool:
    return isinstance(event.state, int) and bool(event.state & 0x1)
