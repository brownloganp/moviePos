import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from moviepos.board import group_by_movie, visible_showings
from moviepos.store import Showing, Store


def show(starts_at, sold=0, capacity=10, title="Movie", movie_id=1, theater="Theater 1"):
    return Showing(1, movie_id, title, "PG", 100, 1, theater, capacity, starts_at, sold)


class VisibleShowingsTests(unittest.TestCase):
    now = datetime(2026, 10, 28, 15, 0)

    def titles(self, offsets_min):
        shows = [show(self.now + timedelta(minutes=m), title=str(m)) for m in offsets_min]
        return [s.title for s in visible_showings(shows, self.now)]

    def test_future_shows_today_are_visible(self):
        self.assertEqual(self.titles([1, 60, 300]), ["1", "60", "300"])

    def test_started_less_than_15_minutes_ago_is_visible(self):
        self.assertEqual(self.titles([0, -1, -14]), ["0", "-1", "-14"])

    def test_started_15_minutes_ago_or_more_is_hidden(self):
        self.assertEqual(self.titles([-15, -16, -120]), [])

    def test_other_days_are_hidden(self):
        tomorrow = self.now + timedelta(days=1)
        yesterday = self.now - timedelta(days=1)
        self.assertEqual(visible_showings([show(tomorrow), show(yesterday)], self.now), [])

    def test_sold_out_shows_are_still_listed(self):
        full = show(self.now + timedelta(hours=1), sold=10)
        self.assertEqual(visible_showings([full], self.now), [full])
        self.assertEqual(full.remaining, 0)


class GroupByMovieTests(unittest.TestCase):
    base = datetime(2026, 10, 28, 15, 0)

    def at(self, minutes):
        return self.base + timedelta(minutes=minutes)

    def test_one_group_per_movie_sorted_by_title_with_times_in_order(self):
        shows = [
            show(self.at(120), title="zebra", movie_id=2),
            show(self.at(90), title="Alpha", movie_id=1),
            show(self.at(30), title="Alpha", movie_id=1),
        ]
        groups = group_by_movie(shows)
        self.assertEqual([g.title for g in groups], ["Alpha", "zebra"])
        self.assertEqual([s.starts_at for s in groups[0].slots], [self.at(30), self.at(90)])

    def test_only_sold_out_times_are_marked(self):
        shows = [show(self.at(30), sold=10), show(self.at(90), sold=3)]
        self.assertEqual([s.sold_out for s in group_by_movie(shows)[0].slots], [True, False])

    def test_same_time_on_two_screens_is_one_square_sold_out_only_if_both_are(self):
        both_full = [show(self.at(30), sold=10, theater="A"), show(self.at(30), sold=10, theater="B")]
        one_open = [show(self.at(30), sold=10, theater="A"), show(self.at(30), sold=2, theater="B")]
        self.assertEqual([(len(g.slots), g.slots[0].sold_out) for g in group_by_movie(both_full)], [(1, True)])
        self.assertEqual([(len(g.slots), g.slots[0].sold_out) for g in group_by_movie(one_open)], [(1, False)])

    def test_empty(self):
        self.assertEqual(group_by_movie([]), [])


class ReadOnlyStoreTests(unittest.TestCase):
    def test_board_connection_can_read_but_never_write(self):
        path = os.path.join(tempfile.mkdtemp(), "pos.db")
        writer = Store(path)
        writer.seed_demo()
        reader = Store(path, read_only=True)
        self.assertGreater(len(reader.showings()), 0)
        with self.assertRaises(sqlite3.OperationalError):
            reader.db.execute("DELETE FROM showtimes")
        reader.close()
        writer.close()

    def test_read_only_does_not_create_a_missing_database(self):
        path = os.path.join(tempfile.mkdtemp(), "missing.db")
        with self.assertRaises(sqlite3.OperationalError):
            Store(path, read_only=True)
        self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
