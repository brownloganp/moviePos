"""Colors and fonts. Fonts must be created after the Tk root exists."""
import tkinter.font as tkfont

BG = "#0f141c"
PANEL = "#19212e"
BTN = "#2a3550"
ACCENT = "#2563eb"
GOOD = "#15803d"
WARN = "#b45309"
BAD = "#b91c1c"
DISABLED = "#202734"
DISABLED_FG = "#5b6577"
TEXT = "#f1f5f9"
SUBTLE = "#94a3b8"
ERROR_FG = "#fca5a5"

F: dict[str, tkfont.Font] = {}


def init_fonts() -> None:
    family = "Helvetica"
    specs = {
        "small": (13, "normal"),
        "base": (15, "normal"),
        "btn": (17, "bold"),
        "row": (18, "normal"),
        "h2": (22, "bold"),
        "h1": (30, "bold"),
        "huge": (54, "bold"),
        "key": (22, "bold"),
    }
    for name, (size, weight) in specs.items():
        F[name] = tkfont.Font(family=family, size=size, weight=weight)


def lighten(color: str, amount: float = 0.22) -> str:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"
