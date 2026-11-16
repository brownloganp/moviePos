import shutil
import unittest
from datetime import datetime, timedelta

from moviepos import receipt
from moviepos import ticket_print as tp
from moviepos.receipt import build_rows, layout
from moviepos.store import Store


class FakeMetrics:
    """Every character is half the font size wide, so wrapping and alignment are predictable."""

    def width(self, text, px, bold):
        return len(text) * px * 0.5

    def ascent(self, px, bold):
        return px * 0.8

    def linespace(self, px, bold):
        return px * 1.2


def pairs(rows):
    return [(r.left, r.right) for r in rows if r.kind == "pair"]


def texts(rows):
    return [r.left for r in rows if r.kind == "text"]


class ReceiptContentTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        theater = self.s.add_theater("Theater 7", 60)
        movie = self.s.add_movie("Receipt Movie", "PG", 100)
        self.s.add_showtimes(movie, theater, (datetime.now() + timedelta(days=1)).replace(hour=19, minute=45))
        self.show = self.s.showings()[0]

    def tearDown(self):
        self.s.close()

    def test_cash_sale_is_itemized_with_subtotal_total_and_change(self):
        sale = self.s.sell(self.show.id, {"Adult": 2, "Child": 1, "Pass": 1}, "cash", 5000)
        rows = build_rows(sale, "Starlight Cinema")
        self.assertEqual(texts(rows)[:2], ["Starlight Cinema", "SALES RECEIPT"])
        p = pairs(rows)
        self.assertIn(("2 × Adult @ $12.50", "$25.00"), p)
        self.assertIn(("1 × Child @ $8.00", "$8.00"), p)
        self.assertIn(("1 × Pass", "Free"), p)
        self.assertIn(("Subtotal", "$33.00"), p)
        self.assertIn(("TOTAL", "$33.00"), p)
        self.assertIn(("Cash received", "$50.00"), p)
        self.assertIn(("Change", "$17.00"), p)
        self.assertIn(("Transaction", f"{sale.id:06d}"), p)
        self.assertIn("Receipt Movie", texts(rows))
        self.assertIn("Theater 7", texts(rows))

    def test_card_and_free_sales_have_no_change_lines(self):
        card = build_rows(self.s.sell(self.show.id, {"Adult": 1}, "card"), "X")
        self.assertIn(("Paid by card", "$12.50"), pairs(card))
        self.assertFalse([p for p in pairs(card) if p[0] in ("Change", "Cash received")])
        free = build_rows(self.s.sell(self.show.id, {"Pass": 2}, "cash"), "X")
        self.assertIn(("TOTAL", "$0.00"), pairs(free))
        self.assertIn("No payment due", texts(free))

    def test_store_credit_receipts(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "credit")
        self.assertIn(("Paid by store credit", "$12.50"), pairs(build_rows(sale, "X")))
        refund = build_rows(self.s.refund(sale.id), "X")
        self.assertIn("Refunded as store credit", texts(refund))

    def test_refund_receipt_shows_negative_amounts_and_how_the_money_goes_back(self):
        sale = self.s.refund(self.s.sell(self.show.id, {"Adult": 2, "Pass": 1}, "card").id)
        rows = build_rows(sale, "Starlight Cinema")
        self.assertEqual(texts(rows)[1], "REFUND RECEIPT")
        p = pairs(rows)
        self.assertIn(("2 × Adult @ $12.50", "-$25.00"), p)
        self.assertIn(("1 × Pass", "Free"), p)
        self.assertIn(("REFUND TOTAL", "-$25.00"), p)
        self.assertIn("Refunded to the original card", texts(rows))
        self.assertTrue([r for r in p if r[0] == "Refunded"] and [r for r in p if r[0] == "Sold"])
        cash = self.s.refund(self.s.sell(self.show.id, {"Adult": 1}, "cash", 2000).id)
        self.assertIn("Cash returned to customer", texts(build_rows(cash, "X")))

    def test_free_refund_has_no_minus_sign(self):
        sale = self.s.refund(self.s.sell(self.show.id, {"Pass": 2}, "cash").id)
        rows = build_rows(sale, "X")
        self.assertIn(("REFUND TOTAL", "$0.00"), pairs(rows))
        self.assertIn("No payment to refund", texts(rows))

    def test_a_sold_ticket_can_be_forced_to_print_as_either_kind(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.assertEqual(texts(build_rows(sale, "X"))[1], "SALES RECEIPT")
        self.assertEqual(texts(build_rows(sale, "X", refund=True))[1], "REFUND RECEIPT")


class ReceiptLayoutTests(unittest.TestCase):
    def rows(self):
        return [
            receipt.Row("text", "Centered", px=40, bold=True, align="center"),
            receipt.Row("rule"),
            receipt.Row("pair", "Left", "Right"),
            receipt.Row("text", "word " * 60),  # must wrap
            receipt.Row("pair", "A very long left side that has to wrap " * 3, "$1.00"),
        ]

    def test_everything_fits_on_the_paper(self):
        ops, height = layout(self.rows(), FakeMetrics(), 576)
        for op in ops:
            if op[0] == "text":
                _, lines, px, bold, _ = op
                for x, y, text in lines:
                    self.assertGreaterEqual(x, receipt.MARGIN - 0.01, text)
                    self.assertLessEqual(x + FakeMetrics().width(text, px, bold), 576 - receipt.MARGIN + 0.01, text)
                    self.assertLess(y, height)
            else:
                self.assertGreaterEqual(op[1], 0)
                self.assertLessEqual(op[3], 576)

    def test_alignment(self):
        ops, _ = layout(self.rows(), FakeMetrics(), 576)
        by_text = {op[1][0][2]: op[1][0] for op in ops if op[0] == "text"}
        x, _, _ = by_text["Centered"]
        self.assertAlmostEqual(x + FakeMetrics().width("Centered", 40, True) / 2, 288, delta=0.01)
        right_x, _, _ = by_text["Right"]
        self.assertAlmostEqual(right_x + FakeMetrics().width("Right", 24, False), 576 - receipt.MARGIN, delta=0.01)
        self.assertEqual(by_text["Left"][0], receipt.MARGIN)
        self.assertEqual(by_text["Left"][1], by_text["Right"][1])  # same baseline

    def test_long_text_wraps_and_pushes_the_paper_longer(self):
        _, short = layout(self.rows()[:3], FakeMetrics(), 576)
        wrapped = [op for op in layout(self.rows(), FakeMetrics(), 576)[0] if op[0] == "text" and op[1][0][2].startswith("word")]
        self.assertGreater(len(wrapped), 1)
        self.assertGreater(layout(self.rows(), FakeMetrics(), 576)[1], short)


@unittest.skipUnless(shutil.which("sips"), "needs macOS sips")
class ReceiptRenderTests(unittest.TestCase):
    def test_upright_page_prints_white_with_black_text(self):
        ops, height = layout([receipt.Row("text", "Hello receipt", px=40, bold=True, align="center")], FakeMetrics(), 576)
        width, rows = tp.decode_job(tp.render_receipt_job(ops, 576, height))
        self.assertEqual((width, len(rows)), (576, height))
        black = sum(map(sum, rows))
        self.assertGreater(black, 300)
        self.assertLess(black, 576 * height * 0.2)
        # text is drawn upright: nothing is in the far-left strip of a centered line
        self.assertEqual(sum(sum(r[:10]) for r in rows), 0)

    def test_receipts_use_the_same_cut_and_framing_as_tickets(self):
        ops, height = layout([receipt.Row("text", "x")], FakeMetrics(), 576)
        job = tp.render_receipt_job(ops, 576, height)
        self.assertTrue(job.startswith(b"\x1b@") and job.endswith(b"\x1dV\x00"))
        self.assertFalse(tp.render_receipt_job(ops, 576, height, cut=False).endswith(b"\x1dV\x00"))


class ConcessionReceiptTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.items = {i.name: i.id for i in self.s.list_concessions()}

    def tearDown(self):
        self.s.close()

    def test_cash_receipt_lists_items_total_and_change(self):
        sale = self.s.concession_sell({self.items["Small Popcorn"]: 2, self.items["Candy"]: 1}, "cash", 2000)
        rows = receipt.build_concession_rows(sale, "Starlight")
        self.assertIn("CONCESSIONS RECEIPT", texts(rows))
        self.assertIn(("Order", receipt.concession_order_id(sale.id)), pairs(rows))
        self.assertIn(("2 × Small Popcorn @ $5.50", "$11.00"), pairs(rows))
        self.assertIn(("TOTAL", "$15.00"), pairs(rows))
        self.assertIn(("Cash received", "$20.00"), pairs(rows))
        self.assertIn(("Change", "$5.00"), pairs(rows))

    def test_card_and_free_receipts(self):
        card = self.s.concession_sell({self.items["Candy"]: 1}, "card")
        self.assertIn(("Paid by card", "$4.00"), pairs(receipt.build_concession_rows(card, "V")))
        free = self.s.add_concession("Sample", 0)
        sale = self.s.concession_sell({free: 3}, "cash")
        rows = receipt.build_concession_rows(sale, "V")
        self.assertIn(("3 × Sample", "Free"), pairs(rows))
        self.assertIn("No payment due", texts(rows))

    @unittest.skipUnless(shutil.which("sips"), "needs macOS sips")
    def test_concession_receipt_renders_like_any_receipt(self):
        sale = self.s.concession_sell({self.items["Candy"]: 1}, "card")
        ops, height = layout(receipt.build_concession_rows(sale, "Starlight"), FakeMetrics(), 576)
        job = tp.render_receipt_job(ops, 576, height)
        self.assertTrue(job.startswith(b"\x1b@") and job.endswith(b"\x1dV\x00"))


if __name__ == "__main__":
    unittest.main()
