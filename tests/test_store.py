import unittest
from datetime import datetime, timedelta

from moviepos import code128
from moviepos.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.theater = self.s.add_theater("Theater 1", 10)
        self.movie = self.s.add_movie("Test Movie", "PG", 100)
        self.start = (datetime.now() + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
        self.s.add_showtimes(self.movie, self.theater, self.start)
        self.show = self.s.showings()[0]

    def tearDown(self):
        self.s.close()

    def test_availability_and_percent(self):
        self.assertEqual((self.show.remaining, self.show.pct_available), (10, 100))
        self.s.sell(self.show.id, {"Adult": 2, "Child": 1}, "card")
        show = self.s.get_showing(self.show.id)
        self.assertEqual((show.sold, show.remaining, show.pct_available), (3, 7, 70))

    def test_cash_change_and_total(self):
        sale = self.s.sell(self.show.id, {"Adult": 2, "Student": 1}, "cash", 5000)
        self.assertEqual(sale.total_cents, 2 * 1250 + 1000)
        self.assertEqual(sale.change_cents, 5000 - 3500)
        self.assertEqual(sale.status, "sold")

    def test_cash_short_is_rejected_and_nothing_recorded(self):
        with self.assertRaises(ValueError):
            self.s.sell(self.show.id, {"Adult": 2}, "cash", 1000)
        self.assertEqual(self.s.recent_sales(), [])

    def test_cannot_oversell(self):
        self.s.sell(self.show.id, {"Adult": 9}, "card")
        with self.assertRaises(ValueError):
            self.s.sell(self.show.id, {"Adult": 2}, "card")
        self.assertEqual(self.s.get_showing(self.show.id).remaining, 1)

    def test_pass_is_free_but_takes_a_seat(self):
        sale = self.s.sell(self.show.id, {"Pass": 2}, "cash")
        self.assertEqual((sale.total_cents, sale.payment_method), (0, "none"))
        self.assertEqual(self.s.get_showing(self.show.id).remaining, 8)

    def test_price_changes_do_not_alter_past_sales(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.s.set_price("Adult", 2000)
        self.assertEqual(self.s.get_sale(sale.id).total_cents, 1250)

    def test_refund_restores_seats_and_cannot_repeat(self):
        sale = self.s.sell(self.show.id, {"Adult": 4}, "card")
        refunded = self.s.refund(sale.id)
        self.assertEqual(refunded.status, "refunded")
        self.assertIsNotNone(refunded.refunded_at)
        self.assertEqual(self.s.get_showing(self.show.id).remaining, 10)
        with self.assertRaises(ValueError):
            self.s.refund(sale.id)
        with self.assertRaises(ValueError):
            self.s.refund(9999)

    def test_transaction_ids_are_unique_and_increasing(self):
        a = self.s.sell(self.show.id, {"Adult": 1}, "card")
        b = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.assertLess(a.id, b.id)

    def test_cannot_lower_capacity_below_sold_seats(self):
        self.s.sell(self.show.id, {"Adult": 6}, "card")
        with self.assertRaises(ValueError):
            self.s.update_theater(self.theater, "Theater 1", 5)
        self.s.update_theater(self.theater, "Theater 1", 6)
        self.assertEqual(self.s.get_showing(self.show.id).capacity, 6)

    def test_overlapping_showtimes_in_same_theater_are_rejected(self):
        with self.assertRaises(ValueError):
            self.s.add_showtimes(self.movie, self.theater, self.start + timedelta(minutes=30))
        self.s.add_showtimes(self.movie, self.theater, self.start + timedelta(minutes=100))

    def test_multi_day_add_is_all_or_nothing(self):
        before = len(self.s.showings())
        with self.assertRaises(ValueError):
            self.s.add_showtimes(self.movie, self.theater, self.start - timedelta(days=1), days=3)
        self.assertEqual(len(self.s.showings()), before)

    def test_sold_showtime_cannot_be_edited_or_deleted(self):
        self.s.sell(self.show.id, {"Adult": 1}, "card")
        with self.assertRaises(ValueError):
            self.s.delete_showtime(self.show.id)
        with self.assertRaises(ValueError):
            self.s.update_showtime(self.show.id, self.movie, self.theater, self.start + timedelta(hours=5))

    def test_referenced_movie_and_theater_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            self.s.delete_movie(self.movie)
        with self.assertRaises(ValueError):
            self.s.delete_theater(self.theater)
        self.s.delete_showtime(self.show.id)
        self.s.delete_movie(self.movie)
        self.s.delete_theater(self.theater)

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):
            self.s.add_theater("Theater 1", 50)
        with self.assertRaises(ValueError):
            self.s.add_movie("Test Movie", "G", 90)

    def test_check_in_defaults_to_whole_party(self):
        sale = self.s.sell(self.show.id, {"Adult": 3, "Child": 1}, "card")
        self.assertEqual((sale.checked_in, sale.not_checked_in), (0, 4))
        done = self.s.check_in(sale.id)
        self.assertEqual((done.checked_in, done.not_checked_in), (4, 0))
        self.assertIsNotNone(done.checked_in_at)
        with self.assertRaises(ValueError):
            self.s.check_in(sale.id)

    def test_partial_check_in_then_the_rest_arrive(self):
        sale = self.s.sell(self.show.id, {"Adult": 4}, "card")
        self.assertEqual(self.s.check_in(sale.id, 3).not_checked_in, 1)
        with self.assertRaises(ValueError):
            self.s.check_in(sale.id, 2)
        self.assertEqual(self.s.check_in(sale.id).checked_in, 4)

    def test_check_in_can_be_corrected_and_undone(self):
        sale = self.s.sell(self.show.id, {"Adult": 4}, "card")
        self.s.check_in(sale.id)
        self.assertEqual(self.s.set_checked_in(sale.id, 2).checked_in, 2)
        undone = self.s.set_checked_in(sale.id, 0)
        self.assertEqual((undone.checked_in, undone.checked_in_at), (0, None))
        with self.assertRaises(ValueError):
            self.s.set_checked_in(sale.id, 5)

    def test_refunded_or_unknown_ticket_cannot_check_in(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.s.refund(sale.id)
        with self.assertRaises(ValueError):
            self.s.check_in(sale.id)
        with self.assertRaises(ValueError):
            self.s.check_in(424242)

    def test_existing_database_is_migrated(self):
        import os, sqlite3, tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
              showtime_id INTEGER NOT NULL, total_cents INTEGER NOT NULL, payment_method TEXT NOT NULL,
              tendered_cents INTEGER NOT NULL, change_cents INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'sold', refunded_at TEXT);
            INSERT INTO transactions(created_at, showtime_id, total_cents, payment_method, tendered_cents, change_cents)
              VALUES ('2026-10-27 10:00:00', 1, 0, 'none', 0, 0);
        """)
        old.close()
        store = Store(path)
        cols = {r["name"] for r in store.db.execute("PRAGMA table_info(transactions)")}
        self.assertTrue({"checked_in", "checked_in_at"} <= cols)
        self.assertEqual(store.db.execute("SELECT checked_in FROM transactions").fetchone()[0], 0)
        store.close()

    def test_store_credit_sale_and_refund(self):
        sale = self.s.sell(self.show.id, {"Adult": 2}, "credit")
        self.assertEqual((sale.payment_method, sale.total_cents, sale.tendered_cents, sale.change_cents), ("credit", 2500, 2500, 0))
        self.assertEqual(self.s.refund(sale.id).payment_method, "credit")
        free = self.s.sell(self.show.id, {"Pass": 1}, "credit")
        self.assertEqual(free.payment_method, "none")  # nothing owed, so nothing to pay with
        with self.assertRaises(ValueError):
            self.s.sell(self.show.id, {"Adult": 1}, "barter")

    def test_database_with_old_payment_check_is_rebuilt_keeping_everything(self):
        import os, sqlite3, tempfile
        path = os.path.join(tempfile.mkdtemp(), "before_credit.db")
        store = Store(path)
        theater = store.add_theater("T", 10)
        movie = store.add_movie("M", "PG", 90)
        store.add_showtimes(movie, theater, datetime.now() + timedelta(days=1))
        show = store.showings()[0]
        sale = store.sell(show.id, {"Adult": 2}, "card")
        store.check_in(sale.id, 1)
        store.close()
        old = sqlite3.connect(path)  # put the previous constraint back, as an older database would have it
        old.executescript("""
            PRAGMA foreign_keys = OFF;
            CREATE TABLE transactions_prev (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, showtime_id INTEGER NOT NULL,
              total_cents INTEGER NOT NULL,
              payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card', 'none')),
              tendered_cents INTEGER NOT NULL, change_cents INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'sold' CHECK (status IN ('sold', 'refunded')),
              refunded_at TEXT, checked_in INTEGER NOT NULL DEFAULT 0, checked_in_at TEXT);
            INSERT INTO transactions_prev SELECT * FROM transactions;
            DROP TABLE transactions;
            ALTER TABLE transactions_prev RENAME TO transactions;
        """)
        old.commit()
        old.close()
        store = Store(path)
        again = store.get_sale(sale.id)
        self.assertEqual((again.payment_method, again.checked_in, [i.qty for i in again.items]), ("card", 1, [2]))
        credit = store.sell(show.id, {"Adult": 1}, "credit")
        self.assertEqual((credit.id, credit.payment_method), (sale.id + 1, "credit"))
        self.assertEqual(store.db.execute("PRAGMA foreign_key_check").fetchall(), [])
        store.close()
        Store(path).close()  # a second start finds nothing to do

    def test_checkin_counts_per_showing(self):
        day = self.start.date()
        self.assertEqual(self.s.checkin_counts(day), [])  # nothing sold yet
        a = self.s.sell(self.show.id, {"Adult": 3}, "card")
        b = self.s.sell(self.show.id, {"Child": 2}, "cash", 2000)
        gone = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.s.check_in(a.id, 2)
        self.s.check_in(gone.id)
        self.s.refund(gone.id)  # refunded tickets count as neither sold nor checked in
        (row,) = self.s.checkin_counts(day)
        self.assertEqual((row.showing.id, row.sold, row.checked_in, row.waiting), (self.show.id, 5, 2, 3))
        self.assertEqual(self.s.checkin_counts(day + timedelta(days=1)), [])
        self.s.check_in(b.id)
        self.assertEqual(self.s.checkin_counts(day)[0].checked_in, 4)

    def test_venue_name_defaults_then_can_be_renamed(self):
        self.assertEqual(self.s.venue_name(), "MOVIE THEATER")
        self.s.set_venue_name("  Starlight   Cinema ")
        self.assertEqual(self.s.venue_name(), "Starlight Cinema")
        with self.assertRaises(ValueError):
            self.s.set_venue_name("   ")
        with self.assertRaises(ValueError):
            self.s.set_venue_name("x" * 41)
        self.assertEqual(self.s.venue_name(), "Starlight Cinema")


class BarcodeTests(unittest.TestCase):
    def test_pattern_table_is_well_formed(self):
        widths = code128._WIDTHS
        self.assertEqual(len(widths), 107)
        self.assertEqual(len(set(widths)), 107)
        for value, w in enumerate(widths):
            self.assertEqual(sum(map(int, w)), 13 if value == 106 else 11, value)

    def test_encoding_shape_and_checksum(self):
        # start C(105) + 00 + 01 + 23 -> checksum (105 + 0*1 + 1*2 + 23*3) % 103 = 73
        bars = code128.encode("000123")
        self.assertEqual(bars, "".join(code128._modules(v) for v in (105, 0, 1, 23, 73, 106)))
        self.assertEqual(len(bars), 11 * 5 + 13)
        self.assertTrue(bars.startswith("11010011100") and bars.endswith("1100011101011"))

    def test_barcode_text_always_even_length_digits(self):
        self.assertEqual(code128.barcode_text(7), "000007")
        self.assertEqual(code128.barcode_text(1234567), "01234567")
        for n in (1, 99999, 123456, 1000000, 98765432):
            self.assertEqual(int(code128.barcode_text(n)), n)
            self.assertEqual(len(code128.barcode_text(n)) % 2, 0)


class ConcessionTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        self.items = {i.name: i.id for i in self.s.list_concessions()}

    def tearDown(self):
        self.s.close()

    def test_menu_is_stocked_once_and_stays_empty_after_deleting_everything(self):
        self.assertIn("Small Popcorn", self.items)
        for item_id in self.items.values():
            self.s.delete_concession(item_id)
        self.s._seed_concessions()
        self.assertEqual(self.s.list_concessions(), [])

    def test_add_edit_delete_and_validation(self):
        new = self.s.add_concession("  Pretzel ", 450)
        self.assertEqual(self.s.list_concessions()[-1].name, "Pretzel")
        self.s.update_concession(new, "Soft Pretzel", 475)
        self.assertEqual(self.s.list_concessions()[-1].price_cents, 475)
        with self.assertRaises(ValueError):
            self.s.add_concession("Soft Pretzel", 100)
        with self.assertRaises(ValueError):
            self.s.add_concession("", 100)
        with self.assertRaises(ValueError):
            self.s.add_concession("Neg", -1)
        with self.assertRaises(ValueError):
            self.s.update_concession(new, "Candy", 100)  # name taken
        self.s.delete_concession(new)
        self.assertNotIn("Soft Pretzel", [i.name for i in self.s.list_concessions()])

    def test_cash_sale_totals_and_change(self):
        sale = self.s.concession_sell({self.items["Small Popcorn"]: 2, self.items["Candy"]: 1}, "cash", 2000)
        self.assertEqual(sale.total_cents, 2 * 550 + 400)
        self.assertEqual((sale.payment_method, sale.tendered_cents, sale.change_cents), ("cash", 2000, 2000 - 1500))
        self.assertEqual([(i.name, i.qty) for i in sale.items], [("Small Popcorn", 2), ("Candy", 1)])
        self.assertEqual(self.s.get_concession_sale(sale.id), sale)

    def test_card_credit_and_free_orders(self):
        pop = self.items["Small Popcorn"]
        self.assertEqual(self.s.concession_sell({pop: 1}, "card").tendered_cents, 550)
        self.assertEqual(self.s.concession_sell({pop: 1}, "credit").change_cents, 0)
        free = self.s.add_concession("Sample", 0)
        self.assertEqual(self.s.concession_sell({free: 1}, "cash").payment_method, "none")

    def test_bad_orders_record_nothing(self):
        pop = self.items["Small Popcorn"]
        for args in (({}, "cash", 100), ({pop: 1}, "cash", 100), ({pop: 1}, "cash", None), ({pop: 1}, "bitcoin", 999), ({9999: 1}, "card", None)):
            with self.assertRaises(ValueError):
                self.s.concession_sell(*args)
        self.assertEqual(self.s.db.execute("SELECT COUNT(*) FROM concession_sales").fetchone()[0], 0)

    def test_past_sales_keep_their_name_and_price(self):
        pop = self.items["Small Popcorn"]
        sale = self.s.concession_sell({pop: 1}, "card")
        self.s.update_concession(pop, "Renamed", 999)
        self.s.delete_concession(pop)
        again = self.s.get_concession_sale(sale.id)
        self.assertEqual((again.items[0].name, again.items[0].unit_price_cents, again.total_cents), ("Small Popcorn", 550, 550))


if __name__ == "__main__":
    unittest.main()
