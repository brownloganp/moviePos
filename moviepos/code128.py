"""Minimal Code 128 encoder (subset C: digit pairs), which is all the ticket barcode needs."""
from __future__ import annotations

# Element widths (bar, space, bar, space, bar, space) for symbol values 0..106.
# 103-105 are the start codes (A, B, C); 106 is the stop pattern (7 elements).
_WIDTHS = """
212222 222122 222221 121223 121322 131222 122213 122312 132212 221213
221312 231212 112232 122132 122231 113222 123122 123221 223211 221132
221231 213212 223112 312131 311222 321122 321221 312212 322112 322211
212123 212321 232121 111323 131123 131321 112313 132113 132311 211313
231113 231311 112133 112331 132131 113123 113321 133121 313121 211331
231131 213113 213311 213131 311123 311321 331121 312113 312311 332111
314111 221411 431111 111224 111422 121124 121421 141122 141221 112214
112412 122114 122411 142112 142211 241211 221114 413111 241112 134111
111242 121142 121241 114212 124112 124211 411212 421112 421211 212141
214121 412121 111143 111341 131141 114113 114311 411113 411311 113141
114131 311141 411131 211412 211214 211232 2331112
""".split()

START_C = 105
STOP = 106


def _modules(value: int) -> str:
    out, bar = [], True
    for width in _WIDTHS[value]:
        out.append(("1" if bar else "0") * int(width))
        bar = not bar
    return "".join(out)


def barcode_text(number: int) -> str:
    """Digits encoded in the barcode: zero-padded to an even length of at least 6."""
    text = f"{number:06d}"
    return text if len(text) % 2 == 0 else "0" + text


def encode(digits: str) -> str:
    """Return the bar pattern as a string of '1' (bar) and '0' (space) modules, one char per module."""
    if not digits.isdigit() or len(digits) % 2:
        raise ValueError("Code 128 subset C needs an even number of digits.")
    values = [int(digits[i : i + 2]) for i in range(0, len(digits), 2)]
    checksum = (START_C + sum(v * (i + 1) for i, v in enumerate(values))) % 103
    return "".join(_modules(v) for v in [START_C, *values, checksum, STOP])
