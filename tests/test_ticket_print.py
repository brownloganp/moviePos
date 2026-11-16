import random
import shutil
import struct
import subprocess
import unittest
from unittest import mock

from moviepos import ticket_print as tp

HAS_SIPS = shutil.which("sips") is not None


class EscPosTests(unittest.TestCase):
    def rows(self, count, width=576, seed=1):
        rnd = random.Random(seed)
        return [bytes(rnd.getrandbits(1) for _ in range(width)) for _ in range(count)]

    def test_image_survives_encoding_exactly_across_chunks(self):
        for count in (1, 127, 128, 129, 300):
            rows = self.rows(count)
            width, back = tp.decode_job(tp.escpos_job(rows, 576))
            self.assertEqual((width, back), (576, rows), count)

    def test_job_framing(self):
        job = tp.escpos_job(self.rows(3), 576)
        self.assertTrue(job.startswith(b"\x1b@"))  # reset
        self.assertEqual(job[2:6], b"\x1dv0\x00")  # raster bit image, normal size
        self.assertEqual(struct.unpack("<HH", job[6:10]), (72, 3))  # 72 bytes per row, 3 rows
        self.assertTrue(job.endswith(b"\x1dV\x00"))  # full cut
        self.assertIn(b"\x1bJ", job)  # feeds paper past the cutter first
        self.assertFalse(tp.escpos_job(self.rows(1), 576, cut=False).endswith(b"\x1dV\x00"))

    def test_width_must_be_whole_bytes(self):
        with self.assertRaises(ValueError):
            tp.escpos_job([bytes(100)], 100)

    def test_black_is_a_set_bit(self):
        row = bytes([1] * 8 + [0] * 568)
        self.assertEqual(tp.pack_row(row), b"\xff" + b"\x00" * 71)


@unittest.skipUnless(HAS_SIPS, "needs macOS sips")
class RenderingTests(unittest.TestCase):
    def render(self, prims, dots=576):
        job = tp.render_job(prims, dots)
        return tp.decode_job(job)

    def test_blank_ticket_prints_white_not_black(self):
        # sips draws unpainted PDF pages transparent, which reads as black, so the page is painted white
        width, rows = self.render([])
        self.assertEqual((width, len(rows)), (576, 1575))
        self.assertEqual(sum(sum(r) for r in rows), 0)

    def test_ticket_is_turned_a_quarter_turn_clockwise(self):
        # a block at the ticket's top-left corner must land at the TOP-RIGHT of the strip
        width, rows = self.render([("rect", 0, 0, 50, 30)])
        black = [(y, x) for y, r in enumerate(rows) for x, v in enumerate(r) if v]
        ys, xs = [b[0] for b in black], [b[1] for b in black]
        self.assertLessEqual(min(ys), 1)
        self.assertLess(max(ys), 100)  # 50 ticket px * 1.92 dots/px
        self.assertGreater(min(xs), 576 - 62)
        self.assertEqual(max(xs), 575)
        # and one at the ticket's bottom-right lands at the BOTTOM-LEFT
        width, rows = self.render([("rect", 770, 270, 820, 300)])
        black = [(y, x) for y, r in enumerate(rows) for x, v in enumerate(r) if v]
        self.assertGreater(min(b[0] for b in black), 1575 - 100)
        self.assertEqual(min(b[1] for b in black), 0)

    def test_text_prints_and_barcode_bars_are_whole_dots(self):
        width, rows = self.render([("text", [(40, 100, "Hello")], 40, True, 0.0)])
        self.assertGreater(sum(sum(r) for r in rows), 500)
        modules = "11010011100" "10110011100" "11000111010" "1100011101011"
        width, rows = self.render([("barcode", modules, 100, 100, 210, 60)])
        mid = rows[0:0] or [r for r in rows if sum(r)]
        self.assertTrue(mid)
        # every bar and gap along the roll is a whole multiple of the same dot width
        column = [r[300] for r in rows]
        runs, current, count = [], column[0], 0
        for v in column:
            if v == current:
                count += 1
            else:
                runs.append(count)
                current, count = v, 1
        unit = min(r for r in runs[1:-1] if r)
        self.assertTrue(all(r % unit == 0 for r in runs[1:-1] if r), runs)


class SendTests(unittest.TestCase):
    def fake(self, outcomes):
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            code, out, err = outcomes[cmd[0]]
            return subprocess.CompletedProcess(cmd, code, out, err)

        return calls, run

    def test_job_goes_to_the_named_queue_raw(self):
        calls, run = self.fake({"lpstat": (0, "printer POS is idle.", ""), "lp": (0, "request id is POS-7 (1 file(s))", "")})
        with mock.patch("subprocess.run", run):
            reply = tp.send_raw(b"data", "POS", "Ticket 000001")
        self.assertEqual(reply, "request id is POS-7 (1 file(s))")
        lp = calls[1]
        self.assertEqual(lp[:6], ["lp", "-d", "POS", "-o", "raw", "-t"])  # raw: bypass the PostScript driver

    def test_waits_until_cups_no_longer_lists_the_job(self):
        replies = iter(["POS-7  me  100  Thu\nPOS-8  me  100  Thu\n", "POS-8  me  100  Thu\n"])
        calls = []

        def run(cmd, **kw):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, next(replies), "")

        with mock.patch("subprocess.run", run), mock.patch("time.sleep"):
            self.assertTrue(tp.wait_until_printed("POS", "request id is POS-7 (1 file(s))"))
        self.assertEqual(len(calls), 2)  # POS-8 being queued doesn't matter; POS-7 left the list on the second look
        self.assertEqual(calls[0][:4], ["lpstat", "-W", "not-completed", "-o"])

    def test_gives_up_waiting_and_never_blocks_on_unreadable_replies(self):
        stuck = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "POS-7  me  100  Thu\n", "")
        clock = iter(range(0, 1000, 20))
        with mock.patch("subprocess.run", stuck), mock.patch("time.sleep"), mock.patch("time.monotonic", lambda: next(clock)):
            self.assertFalse(tp.wait_until_printed("POS", "request id is POS-7 (1 file(s))", timeout=60))
        self.assertTrue(tp.wait_until_printed("POS", "something unexpected"))  # no job id to watch

    def test_missing_paused_and_refused_printers_give_clear_errors(self):
        _, run = self.fake({"lpstat": (1, "", "not found")})
        with mock.patch("subprocess.run", run), self.assertRaisesRegex(tp.PrintError, "isn't set up"):
            tp.send_raw(b"x", "POS", "t")
        _, run = self.fake({"lpstat": (0, "printer POS disabled since today", "")})
        with mock.patch("subprocess.run", run), self.assertRaisesRegex(tp.PrintError, "paused or turned off"):
            tp.send_raw(b"x", "POS", "t")
        _, run = self.fake({"lpstat": (0, "printer POS is idle", ""), "lp": (1, "", "lp: Forbidden")})
        with mock.patch("subprocess.run", run), self.assertRaisesRegex(tp.PrintError, "Forbidden"):
            tp.send_raw(b"x", "POS", "t")


if __name__ == "__main__":
    unittest.main()
