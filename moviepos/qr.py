"""Small QR Code encoder: byte mode, error-correction level M, versions 1-10 (up to 213 bytes).

Enough for a URL. Returns the module matrix; drawing is up to the caller.
"""
from __future__ import annotations

# Level M only. Index = version (index 0 unused).
_ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
_NUM_BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
_MAX_VERSION = 10
_FORMAT_BITS_M = 0  # level M indicator in the format string


def _bit(value: int, i: int) -> bool:
    return (value >> i) & 1 != 0


def _raw_modules(ver: int) -> int:
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        n -= (25 * align - 10) * align - 55
        if ver >= 7:
            n -= 36
    return n


def _data_codewords(ver: int) -> int:
    return _raw_modules(ver) // 8 - _ECC_PER_BLOCK[ver] * _NUM_BLOCKS[ver]


def _gf_mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _gf_mul(coef, factor)
    return result


def _build_codewords(text: bytes, ver: int) -> list[int]:
    bits: list[int] = []

    def put(value: int, count: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(count)))

    put(0b0100, 4)  # byte mode
    put(len(text), 8 if ver <= 9 else 16)
    for b in text:
        put(b, 8)
    capacity_bits = _data_codewords(ver) * 8
    put(0, min(4, capacity_bits - len(bits)))
    put(0, -len(bits) % 8)
    data = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(data) < _data_codewords(ver):
        data.append(pad)
        pad ^= 0xEC ^ 0x11

    blocks_n, ecc_len = _NUM_BLOCKS[ver], _ECC_PER_BLOCK[ver]
    raw = _raw_modules(ver) // 8
    short_blocks = blocks_n - raw % blocks_n
    short_len = raw // blocks_n
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(blocks_n):
        dat = data[k : k + short_len - ecc_len + (0 if i < short_blocks else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, divisor)
        if i < short_blocks:
            dat = dat + [0]  # placeholder so every block has equal length when interleaving
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_blocks:
                out.append(block[i])
    return out


class _Matrix:
    def __init__(self, ver: int):
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]
        self._draw_function_patterns()

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fn[y][x] = True

    def _draw_function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self._alignment_positions()
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        self._draw_version()

    def _alignment_positions(self) -> list[int]:
        if self.ver == 1:
            return []
        count = self.ver // 7 + 2
        step = (self.ver * 4 + count * 2 + 1) // (count * 2 - 2) * 2
        return [6] + [self.size - 7 - i * step for i in reversed(range(count - 1))]

    def draw_format(self, mask: int) -> None:
        n = self.size
        data = _FORMAT_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        for i in range(6):
            self._set(8, i, _bit(bits, i))
        self._set(8, 7, _bit(bits, 6))
        self._set(8, 8, _bit(bits, 7))
        self._set(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self._set(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self._set(n - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, _bit(bits, i))
        self._set(8, n - 8, True)

    def _draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        for i in range(18):
            a, b = self.size - 11 + i % 3, i // 3
            self._set(a, b, _bit(bits, i))
            self._set(b, a, _bit(bits, i))

    def place(self, codewords: list[int]) -> None:
        n, i = self.size, 0
        for right in range(n - 1, 0, -2):
            if right == 6:
                right = 5
            for vert in range(n):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = n - 1 - vert if upward else vert
                    if not self.fn[y][x] and i < len(codewords) * 8:
                        self.m[y][x] = _bit(codewords[i >> 3], 7 - (i & 7))
                        i += 1

    def mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                invert = (
                    (x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0,
                    (x // 3 + y // 2) % 2 == 0, x * y % 2 + x * y % 3 == 0,
                    (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0,
                )[mask]
                if invert and not self.fn[y][x]:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self) -> int:
        n, m = self.size, self.m
        score = 0
        lines = [row for row in m] + [[m[y][x] for y in range(n)] for x in range(n)]
        for line in lines:
            run = 1
            for a, b in zip(line, line[1:]):
                run = run + 1 if a == b else 1
                if run == 5:
                    score += 3
                elif run > 5:
                    score += 1
            text = "".join("1" if v else "0" for v in line)
            for pattern in ("10111010000", "00001011101"):
                start = text.find(pattern)
                while start != -1:
                    score += 40
                    start = text.find(pattern, start + 1)
        for y in range(n - 1):
            for x in range(n - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in m)
        total = n * n
        score += ((abs(dark * 20 - total * 10) + total - 1) // total - 1) * 10
        return score


def encode(text: str) -> list[list[bool]]:
    """Return the QR module matrix (True = dark), without the quiet zone."""
    data = text.encode("utf-8")
    for ver in range(1, _MAX_VERSION + 1):
        capacity_bits = _data_codewords(ver) * 8
        if 4 + (8 if ver <= 9 else 16) + 8 * len(data) <= capacity_bits:
            break
    else:
        raise ValueError(f"Text is too long for a QR code here ({len(data)} bytes; max 213).")
    codewords = _build_codewords(data, ver)
    best, best_score = None, None
    for mask in range(8):
        matrix = _Matrix(ver)
        matrix.place(codewords)
        matrix.mask(mask)
        matrix.draw_format(mask)
        score = matrix.penalty()
        if best_score is None or score < best_score:
            best, best_score = matrix, score
    return best.m
