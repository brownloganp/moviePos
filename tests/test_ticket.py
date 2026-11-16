import unittest
from datetime import datetime, timedelta

from moviepos import code128
from moviepos.store import Store
from moviepos.ticket import build_ticket


class TicketContentTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        theater = self.s.add_theater("Theater 9", 50)
        movie = self.s.add_movie("Ticket Movie", "PG-13", 125)
        self.s.add_showtimes(movie, theater, (datetime.now() + timedelta(days=1)).replace(hour=19, minute=15))
        self.show = self.s.showings()[0]

    def tearDown(self):
        self.s.close()

    def test_lists_ticket_types_and_counts_only(self):
        sale = self.s.sell(self.show.id, {"Adult": 3, "Child": 1, "Pass": 2}, "cash", 10000)
        c = build_ticket(sale, "Starlight Cinema")
        self.assertEqual(c.items, (("Adult", 3), ("Child", 1), ("Pass", 2)))
        self.assertEqual(c.admit, 6)
        for value in vars(c).values():
            self.assertNotIn("$", str(value))
        self.assertFalse({"total", "price", "tendered", "change"} & {f.lower() for f in vars(c)})

    def test_uses_the_given_venue_name_and_ties_the_barcode_to_the_id(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        c = build_ticket(sale, "Starlight Cinema")
        self.assertEqual(c.venue, "Starlight Cinema")
        self.assertEqual(c.barcode_digits, code128.barcode_text(sale.id))
        self.assertEqual(int(c.barcode_digits), sale.id)
        self.assertEqual((c.title, c.theater, c.time), ("Ticket Movie", "Theater 9", "7:15 PM"))

    def test_refunded_ticket_is_marked_void(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.assertFalse(build_ticket(sale, "X").void)
        self.assertTrue(build_ticket(self.s.refund(sale.id), "X").void)


if __name__ == "__main__":
    unittest.main()
