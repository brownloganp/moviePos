import unittest
from datetime import date, datetime, timedelta

from moviepos.customer_display import OrderLine, make_concession_view, make_return_view, make_view
from moviepos.store import Store

NOW = datetime(2026, 10, 28, 16, 45)


class CustomerViewTests(unittest.TestCase):
    def setUp(self):
        self.s = Store(":memory:")
        theater = self.s.add_theater("Theater 3", 40)
        self.movie_id = self.s.add_movie("View Movie", "PG", 95)
        self.s.add_showtimes(self.movie_id, theater, (datetime.now() + timedelta(days=1)).replace(hour=19, minute=15))
        self.show = self.s.showings()[0]
        self.movie = self.s.list_movies()[0]
        self.prices = self.s.ticket_prices()

    def tearDown(self):
        self.s.close()

    def view(self, step, **kw):
        args = dict(on_sell=True, step=step, venue="Starlight", now=NOW, day=date(2026, 10, 29), movie=self.movie,
                    showing=self.show, qty={}, prices=self.prices, method=None, tendered_cents=0, sale=None)
        args.update(kw)
        return make_view(**args)

    def test_feature_step_and_other_tabs_show_the_welcome_screen(self):
        for v in (self.view("movie"), self.view("tickets", on_sell=False), self.view("pay", on_sell=False)):
            self.assertEqual((v.mode, v.venue), ("welcome", "Starlight"))
            self.assertEqual(v.lines, ())
            self.assertIn("Wednesday, October 28", v.clock)
            self.assertIn("4:45 PM", v.clock)

    def test_choosing_a_feature_shows_it_before_a_time_is_picked(self):
        v = self.view("time", showing=None)
        self.assertEqual((v.mode, v.title, v.rating_runtime, v.time), ("feature", "View Movie", "PG · 1h 35m", ""))
        self.assertEqual(v.day, "Thu Oct 29")

    def test_tickets_step_lists_each_type_with_a_running_subtotal(self):
        v = self.view("tickets", qty={"Adult": 2, "Child": 1, "Pass": 0})
        self.assertEqual(v.mode, "order")
        self.assertEqual([(l.label, l.qty, l.unit_cents, l.line_cents) for l in v.lines],
                         [("Adult", 2, 1250, 2500), ("Child", 1, 800, 800)])
        self.assertEqual((v.total_cents, v.time, v.theater), (3300, "7:15 PM", "Theater 3"))
        self.assertEqual(self.view("tickets", qty={}).total_cents, 0)

    def test_subtotal_follows_every_change(self):
        totals = [self.view("tickets", qty={"Adult": n}).total_cents for n in range(4)]
        self.assertEqual(totals, [0, 1250, 2500, 3750])

    def test_cash_payment_shows_received_and_live_change(self):
        qty = {"Adult": 2, "Child": 1}
        v = self.view("pay", qty=qty, method="cash")
        self.assertEqual((v.mode, v.method, v.tendered_cents, v.owed_cents), ("payment", "cash", 0, 3300))
        v = self.view("pay", qty=qty, method="cash", tendered_cents=2000)
        self.assertEqual((v.change_cents, v.owed_cents), (0, 1300))
        v = self.view("pay", qty=qty, method="cash", tendered_cents=5000)
        self.assertEqual((v.change_cents, v.owed_cents), (1700, 0))

    def test_card_and_free_payments(self):
        v = self.view("pay", qty={"Adult": 1}, method="card", tendered_cents=9999)
        self.assertEqual((v.method, v.tendered_cents, v.change_cents), ("card", 0, 0))
        free = self.view("pay", qty={"Pass": 2}, method="cash")
        self.assertEqual((free.method, free.total_cents), ("none", 0))

    def test_store_credit_payment_and_thank_you(self):
        v = self.view("pay", qty={"Adult": 1}, method="credit", tendered_cents=9999)
        self.assertEqual((v.method, v.tendered_cents, v.change_cents), ("credit", 0, 0))
        done = self.view("done", sale=self.s.sell(self.show.id, {"Adult": 1}, "credit"))
        self.assertEqual((done.method, done.change_cents), ("credit", 0))

    def test_thank_you_screen_uses_the_completed_sale(self):
        sale = self.s.sell(self.show.id, {"Adult": 2, "Child": 1}, "cash", 5000)
        v = self.view("done", sale=sale, qty={"Adult": 99})  # in-progress state no longer matters
        self.assertEqual((v.mode, v.total_cents, v.tendered_cents, v.change_cents), ("thanks", 3300, 5000, 1700))
        self.assertEqual([(l.label, l.qty) for l in v.lines], [("Adult", 2), ("Child", 1)])
        card = self.view("done", sale=self.s.sell(self.show.id, {"Adult": 1}, "card"))
        self.assertEqual((card.method, card.change_cents), ("card", 0))

    def return_view(self, sale, stage=None):
        return make_return_view(venue="Starlight", now=NOW, sale=sale, stage=stage)

    def test_returns_tab_is_welcome_until_a_sale_is_loaded(self):
        self.assertEqual(self.return_view(None).mode, "welcome")
        self.assertEqual(self.return_view(None, "confirming").mode, "welcome")

    def test_looked_up_sale_shows_the_original_transaction(self):
        sale = self.s.sell(self.show.id, {"Adult": 2, "Child": 1}, "cash", 5000)
        v = self.return_view(sale)
        self.assertEqual((v.mode, v.tx, v.status, v.total_cents), ("lookup", f"{sale.id:06d}", "", 3300))
        self.assertEqual((v.method, v.tendered_cents, v.change_cents), ("cash", 5000, 1700))
        self.assertEqual([(l.label, l.qty) for l in v.lines], [("Adult", 2), ("Child", 1)])
        self.assertEqual((v.title, v.time, v.theater), ("View Movie", "7:15 PM", "Theater 3"))

    def test_refund_button_switches_to_refund_in_progress_then_complete(self):
        sale = self.s.sell(self.show.id, {"Adult": 1}, "card")
        self.assertEqual(self.return_view(sale, "confirming").mode, "refund")
        refunded = self.s.refund(sale.id)
        v = self.return_view(refunded, "done")
        self.assertEqual((v.mode, v.status, v.total_cents), ("refunded", "Refund complete", 1250))

    def test_looking_up_an_already_refunded_sale_says_when(self):
        sale = self.s.refund(self.s.sell(self.show.id, {"Adult": 1}, "card").id)
        v = self.return_view(sale)
        self.assertEqual(v.mode, "lookup")
        self.assertTrue(v.status.startswith("Refunded"))

    def test_views_compare_equal_when_nothing_changed(self):
        self.assertEqual(self.view("tickets", qty={"Adult": 1}), self.view("tickets", qty={"Adult": 1}))
        self.assertNotEqual(self.view("tickets", qty={"Adult": 1}), self.view("tickets", qty={"Adult": 2}))


class ConcessionViewTests(unittest.TestCase):
    def view(self, step, lines=(), **kw):
        args = dict(venue="Starlight", now=NOW, step=step, lines=tuple(lines), method=None, tendered_cents=0, sale=None)
        args.update(kw)
        return make_concession_view(**args)

    def test_empty_order_shows_the_welcome_screen(self):
        self.assertEqual(self.view("order").mode, "welcome")

    def test_order_and_payment_show_items_without_a_movie(self):
        lines = [OrderLine("Candy", 2, 400), OrderLine("Small Popcorn", 1, 550)]
        order = self.view("order", lines)
        self.assertEqual((order.mode, order.title, order.total_cents, order.concession), ("order", "Concessions", 1350, True))
        self.assertEqual((order.time, order.theater, order.rating_runtime), ("", "", ""))
        pay = self.view("pay", lines, method="cash", tendered_cents=2000)
        self.assertEqual((pay.mode, pay.tendered_cents, pay.change_cents), ("payment", 2000, 650))
        self.assertEqual(self.view("pay", lines, method="card", tendered_cents=2000).tendered_cents, 0)

    def test_thanks_comes_from_the_finished_sale(self):
        s = Store(":memory:")
        try:
            sale = s.concession_sell({s.list_concessions()[0].id: 1}, "cash", 1000)
        finally:
            s.close()
        v = self.view("done", sale=sale)
        self.assertEqual((v.mode, v.method, v.change_cents, v.total_cents), ("thanks", "cash", 450, 550))


if __name__ == "__main__":
    unittest.main()
