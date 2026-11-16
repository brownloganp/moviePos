"""Print the ticket on an 80mm ESC/POS receipt printer, turned on its side.

The ticket is landscape. To use the full paper width it is rotated a quarter turn so its short side runs
across the paper and its long side runs along the roll. Pipeline:

  laid-out ticket (ticket.TicketView.primitives)  ->  PDF page, rotated, 1 point = 1 printer dot
  ->  macOS `sips` rasterizes it  ->  1-bit rows  ->  ESC/POS raster commands  ->  `lp -o raw`

The printer's CUPS queue here uses a generic PostScript driver, which a thermal printer can't read, so the
job is sent raw (bypassing the driver) with the printer's own commands.
"""
from __future__ import annotations

import math
import os
import queue as queue_mod
import re
import struct
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PRINTER = "STMicroelectronics_POS80_Printer_USB"
DEFAULT_DOTS = 576  # printable width of an 80mm printer at 203 dpi
BLACK_BELOW = 150  # grey level (0 black .. 255 white) under which a dot is printed
CHUNK_ROWS = 128  # rows per ESC/POS raster command
FEED_DOTS = 110  # blank paper fed after the ticket so the cutter doesn't slice the stub

SETTLE_SECONDS = 3.0  # minimum pause after a job leaves CUPS: the printer is still cutting its buffer
PRINT_DOTS_PER_SECOND = 150  # deliberately slow estimate of how fast the printer lays down a bitmap
DONE_TIMEOUT = 60  # seconds to wait for CUPS to report a job finished

TICKET_W, TICKET_H = 820, 300  # ticket size in preview pixels (TicketView.W / H)


class PrintError(Exception):
    """Something went wrong; the message is shown to the cashier."""


# ---------------------------------------------------------------------------- PDF

def _pdf_text(text: str) -> bytes:
    raw = text.encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(primitives: list[tuple], dots: int = DEFAULT_DOTS) -> tuple[bytes, int, int]:
    """Draw the ticket rotated a quarter turn clockwise onto a page `dots` wide. Returns (pdf, width, height).

    Ticket (x right, y down) -> page: ticket-left becomes the top of the page, ticket-top the right edge.
    One PDF point is one printer dot.
    """
    s = dots / TICKET_H
    length = math.ceil(TICKET_W * s)

    def point(x: float, y: float) -> tuple[float, float]:
        return (TICKET_H - y) * s, length - x * s

    ops: list[bytes] = [b"1 1 1 rg 0 0 %d %d re f" % (dots, length), b"0 0 0 rg 0 0 0 RG"]  # sips draws transparent paper otherwise

    for prim in primitives:
        kind = prim[0]
        if kind == "rect":
            (a, b), (c, d) = point(*prim[1:3]), point(*prim[3:5])
            ops.append(b"%.2f %.2f %.2f %.2f re f" % (min(a, c), min(b, d), abs(c - a), abs(d - b)))
        elif kind == "line":
            _, x0, y0, x1, y1, width, dashed = prim
            (a, b), (c, d) = point(x0, y0), point(x1, y1)
            dash = b"[8 14] 0 d" if dashed else b"[] 0 d"
            ops.append(b"%.2f w %s %.2f %.2f m %.2f %.2f l S" % (max(width * s, 1), dash, a, b, c, d))
        elif kind == "barcode":
            _, modules, x, y, width, height = prim
            unit = max(1, int(width * s // len(modules)))  # whole dots per bar: every bar prints the same width
            first = (x + width / 2) * s - len(modules) * unit / 2  # distance from the top of the roll
            lo, hi = round((TICKET_H - (y + height)) * s), round((TICKET_H - y) * s)  # extent across the paper
            run = None
            for i, bit in enumerate(modules + "0"):
                if bit == "1" and run is None:
                    run = i
                elif bit == "0" and run is not None:
                    top, bottom = round(first + run * unit), round(first + i * unit)
                    ops.append(b"%d %d %d %d re f" % (lo, length - bottom, hi - lo, bottom - top))
                    run = None
        elif kind == "text":
            _, lines, px, bold, angle = prim
            t = math.radians(angle)
            a, b, c, d = math.sin(t), -math.cos(t), math.cos(t), math.sin(t)  # a quarter turn plus the text's own angle
            for x, y, text in lines:
                if text.strip():
                    e, f = point(x, y)
                    ops.append(
                        b"BT /%s %.2f Tf %.4f %.4f %.4f %.4f %.2f %.2f Tm (" % (b"F2" if bold else b"F1", px * s, a, b, c, d, e, f)
                        + _pdf_text(text) + b") Tj ET"
                    )

    return _assemble(b"\n".join(ops), dots, length), dots, length


def _assemble(body: bytes, dots: int, length: int) -> bytes:
    """Wrap page content in a one-page PDF (Helvetica as F1, Helvetica-Bold as F2)."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> >>" % (dots, length),
        b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


def build_receipt_pdf(ops: list[tuple], dots: int, height: int) -> bytes:
    """Draw an upright receipt (ops from receipt.layout, in paper dots with y down) onto a page of that size."""
    body = [b"1 1 1 rg 0 0 %d %d re f" % (dots, height), b"0 0 0 rg 0 0 0 RG"]
    for op in ops:
        if op[0] == "line":
            _, x0, y0, x1, y1, width, dashed = op
            dash = b"[3 6] 0 d" if dashed else b"[] 0 d"
            body.append(b"%.2f w %s %.2f %.2f m %.2f %.2f l S" % (width, dash, x0, height - y0, x1, height - y1))
        elif op[0] == "text":
            _, lines, px, bold, _angle = op
            for x, y, text in lines:
                if text.strip():
                    body.append(
                        b"BT /%s %d Tf 1 0 0 1 %.2f %.2f Tm (" % (b"F2" if bold else b"F1", px, x, height - y)
                        + _pdf_text(text) + b") Tj ET"
                    )
    return _assemble(b"\n".join(body), dots, height)


# ---------------------------------------------------------------------------- raster

def rasterize(pdf: bytes) -> tuple[int, list[bytes]]:
    """Render the PDF with macOS sips. Returns (width, rows) where each row is one byte per dot: 1 = black."""
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp) / "ticket.pdf", Path(tmp) / "ticket.bmp"
        src.write_bytes(pdf)
        try:
            run = subprocess.run(["sips", "-s", "format", "bmp", str(src), "--out", str(dst)], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PrintError(f"Can't draw the ticket for printing ({e}).") from e
        if run.returncode != 0 or not dst.exists():
            raise PrintError("Can't draw the ticket for printing (macOS 'sips' failed).")
        return read_bmp(dst.read_bytes())


def read_bmp(data: bytes) -> tuple[int, list[bytes]]:
    """Parse the 24- or 32-bit BMP sips produces into rows of 0/1 bytes (1 = black)."""
    if data[:2] != b"BM":
        raise PrintError("Unexpected image format from the renderer.")
    offset = struct.unpack("<I", data[10:14])[0]
    width, height, _planes, bpp, compression = struct.unpack("<iiHHI", data[18:34])
    if bpp not in (24, 32) or compression not in (0, 3):
        raise PrintError(f"Unexpected image format from the renderer ({bpp} bits).")
    green = 1  # BGR / BGRA: the green byte is second
    if bpp == 32 and compression == 3:
        green = (struct.unpack("<I", data[58:62])[0].bit_length() - 1) // 8
    step = bpp // 8
    stride = (width * bpp + 31) // 32 * 4  # rows are padded to 4 bytes
    blackness = bytes(1 if level < BLACK_BELOW else 0 for level in range(256))
    rows = []
    for y in range(abs(height)):
        start = offset + y * stride
        rows.append(data[start + green : start + width * step : step].translate(blackness))
    if height > 0:  # bottom-up BMP
        rows.reverse()
    return width, rows


# ---------------------------------------------------------------------------- ESC/POS

def pack_row(dots: bytes) -> bytes:
    bits = dots.translate(bytes.maketrans(b"\x00\x01", b"01")).decode("ascii")
    return int(bits, 2).to_bytes(len(dots) // 8, "big")


def escpos_job(rows: list[bytes], width: int, cut: bool = True) -> bytes:
    """Initialise, print the bitmap in chunks (GS v 0), feed past the cutter, and cut."""
    if width % 8:
        raise ValueError("Printer width must be a multiple of 8 dots.")
    per_row = width // 8
    job = bytearray(b"\x1b@")  # ESC @ : reset
    for start in range(0, len(rows), CHUNK_ROWS):
        chunk = rows[start : start + CHUNK_ROWS]
        job += b"\x1dv0\x00" + struct.pack("<HH", per_row, len(chunk))
        job += b"".join(pack_row(r) for r in chunk)
    feed = FEED_DOTS
    while feed > 0:
        job += b"\x1bJ" + bytes([min(feed, 255)])  # ESC J n : feed n dots
        feed -= 255
    if cut:
        job += b"\x1dV\x00"  # GS V 0 : full cut
    return bytes(job)


def render_job(primitives: list[tuple], dots: int = DEFAULT_DOTS, cut: bool = True) -> bytes:
    pdf, width, _height = build_pdf(primitives, dots)
    width, rows = rasterize(pdf)
    return escpos_job(rows, width, cut)


def render_receipt_job(ops: list[tuple], dots: int, height: int, cut: bool = True) -> bytes:
    width, rows = rasterize(build_receipt_pdf(ops, dots, height))
    return escpos_job(rows, width, cut)


def decode_job(job: bytes) -> tuple[int, list[bytes]]:
    """Inverse of escpos_job for the image part (used to verify output and in tests)."""
    rows, width, i = [], 0, 0
    while i < len(job):
        if job[i : i + 4] == b"\x1dv0\x00":
            per_row, count = struct.unpack("<HH", job[i + 4 : i + 8])
            width = per_row * 8
            i += 8
            for _ in range(count):
                bits = bin(int.from_bytes(job[i : i + per_row], "big") | (1 << (per_row * 8)))[3:]
                rows.append(bits.encode().translate(bytes.maketrans(b"01", b"\x00\x01")))
                i += per_row
        else:
            i += 1
    return width, rows


# ---------------------------------------------------------------------------- sending

def send_raw(job: bytes, printer: str, title: str) -> str:
    """Hand the bytes to CUPS untouched. Returns CUPS' confirmation (the job id)."""
    try:
        status = subprocess.run(["lpstat", "-p", printer], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PrintError(f"Can't reach the print system ({e}).") from e
    if status.returncode != 0:
        raise PrintError(f'The printer "{printer}" isn\'t set up on this computer.')
    if "disabled" in status.stdout:
        raise PrintError("The printer is paused or turned off. Check the cable and power, then print again.")
    fd, path = tempfile.mkstemp(suffix=".escpos")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(job)
        run = subprocess.run(["lp", "-d", printer, "-o", "raw", "-t", title, path], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise PrintError(f"Couldn't send the ticket to the printer ({e}).") from e
    finally:
        os.unlink(path)
    if run.returncode != 0:
        raise PrintError("The print system refused the ticket: " + (run.stderr.strip() or "unknown error"))
    return run.stdout.strip()


def wait_until_printed(printer: str, reply: str, timeout: float = DONE_TIMEOUT) -> bool:
    """Block until CUPS has handed the whole job to the printer. False if it is still queued after `timeout`."""
    match = re.search(r"request id is (\S+)", reply)
    if not match:
        return True
    job, deadline = match.group(1), time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            out = subprocess.run(
                ["lpstat", "-W", "not-completed", "-o", printer], capture_output=True, text=True, timeout=15
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            return True  # can't tell: don't hold up the cashier
        if not any(line.split()[:1] == [job] for line in out.splitlines()):
            return True
        time.sleep(0.25)
    return False


@dataclass(frozen=True)
class PrintResult:
    ok: bool
    message: str


class TkMetrics:
    """Text measurements from Tk's Helvetica, which is the font the PDF draws with (one pixel = one dot)."""

    def __init__(self):
        import tkinter.font as tkfont

        self._tkfont, self._fonts = tkfont, {}

    def _font(self, px: int, bold: bool):
        if (px, bold) not in self._fonts:
            self._fonts[(px, bold)] = self._tkfont.Font(family="Helvetica", size=-px, weight="bold" if bold else "normal")
        return self._fonts[(px, bold)]

    def width(self, text: str, px: int, bold: bool) -> float:
        return self._font(px, bold).measure(text)

    def ascent(self, px: int, bold: bool) -> float:
        return self._font(px, bold).metrics("ascent")

    def linespace(self, px: int, bold: bool) -> float:
        return self._font(px, bold).metrics("linespace")


class TicketPrinter:
    """Prints tickets and receipts in the background. Results come back on the Tk thread via the callback."""

    def __init__(self, root, printer: str = DEFAULT_PRINTER, dots: int = DEFAULT_DOTS, cut: bool = True):
        from .ticket import TicketView  # imported here: the view needs Tk

        self.root, self.printer, self.dots, self.cut = root, printer, dots, cut
        self._view = TicketView(root)  # never shown: only used to lay the ticket out
        self._metrics = TkMetrics()
        self._done: queue_mod.Queue = queue_mod.Queue()
        self._jobs: queue_mod.Queue = queue_mod.Queue()
        threading.Thread(target=self._run, daemon=True, name="ticket-printer").start()
        self.root.after(200, self._poll)

    def print_sale(self, sale, venue: str, on_done=None) -> None:
        """The sideways ticket."""
        self._view.show(sale, venue)
        primitives = self._view.primitives()  # laid out here, on the Tk thread
        name = f"Ticket {sale.id:06d}"
        self._spawn(lambda: render_job(primitives, self.dots, self.cut), name, on_done)

    def print_receipt(self, sale, venue: str, on_done=None) -> None:
        """The itemized, upright receipt: a refund receipt if the sale was refunded."""
        from .receipt import build_rows, layout

        ops, height = layout(build_rows(sale, venue), self._metrics, self.dots)  # laid out on the Tk thread
        name = f"{'Refund receipt' if sale.status == 'refunded' else 'Receipt'} {sale.id:06d}"
        self._spawn(lambda: render_receipt_job(ops, self.dots, height, self.cut), name, on_done)

    def print_concession_receipt(self, sale, venue: str, on_done=None) -> None:
        """The receipt for a concessions order."""
        from .receipt import build_concession_rows, concession_order_id, layout

        ops, height = layout(build_concession_rows(sale, venue), self._metrics, self.dots)
        name = f"Concessions receipt {concession_order_id(sale.id)}"
        self._spawn(lambda: render_receipt_job(ops, self.dots, height, self.cut), name, on_done)

    def _spawn(self, make_job, name: str, on_done) -> None:
        self._jobs.put((make_job, name, on_done))

    def _run(self) -> None:
        """One job at a time: a second job's bytes must never reach the printer while it is still busy with the
        first, or the printer can lose its place and print the image data as text."""
        while True:
            make_job, name, on_done = self._jobs.get()
            self._work(make_job, name, on_done)

    def _work(self, make_job, name: str, on_done) -> None:
        settle = 0.0
        try:
            job = make_job()
            reply = send_raw(job, self.printer, name)
            # A short job fits entirely in the printer's buffer, so CUPS reports it done long before the paper has
            # finished moving. Hold the next job back for as long as this one takes to print, or the printer
            # receives it mid-print, loses its place and prints the start of it as text.
            settle = SETTLE_SECONDS + (len(job) // (self.dots // 8)) / PRINT_DOTS_PER_SECOND
            if wait_until_printed(self.printer, reply):
                result = PrintResult(True, f"{name} sent to the printer")
            else:
                result = PrintResult(False, f"{name} is still waiting in the printer queue. Check the paper and power.")
        except PrintError as e:
            result = PrintResult(False, str(e))
        except Exception as e:  # never let a printing bug kill the sale screen
            result = PrintResult(False, f"Unexpected printing error: {e}")
        self._done.put((on_done, result))
        if settle:
            time.sleep(settle)

    def _poll(self) -> None:
        try:
            while True:
                on_done, result = self._done.get_nowait()
                if on_done:
                    on_done(result)
        except queue_mod.Empty:
            pass
        self.root.after(200, self._poll)
