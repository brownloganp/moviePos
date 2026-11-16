import http.client
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta

from moviepos.store import Store
from moviepos.web import PhoneAccess, WebServer, sale_json, start_phone_access


class WebTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "pos.db")
        self.store = Store(self.path)
        theater = self.store.add_theater("Theater 1", 20)
        movie = self.store.add_movie("Web Movie", "PG", 100)
        self.store.add_showtimes(movie, theater, datetime.now() + timedelta(days=1))
        self.show = self.store.showings()[0]
        self.sale = self.store.sell(self.show.id, {"Adult": 3, "Child": 1}, "card")
        self.key = self.store.web_key()
        self.server = WebServer(self.path, port=0, host="127.0.0.1")
        self.server.start()
        self.conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=5)

    def tearDown(self):
        self.conn.close()
        self.server.stop()
        self.store.close()

    def call(self, method, path, body=None, key="__use__", raw_body=None):
        headers = {}
        key = self.key if key == "__use__" else key
        if key is not None:
            headers["X-Access-Key"] = key
        data = raw_body
        if body is not None:
            data = json.dumps(body)
            headers["Content-Type"] = "application/json"
        self.conn.request(method, path, body=data, headers=headers)
        resp = self.conn.getresponse()
        text = resp.read()
        return resp.status, (json.loads(text) if resp.getheader("Content-Type", "").startswith("application/json") else text)

    def test_page_is_served_without_a_key(self):
        status, body = self.call("GET", "/", key=None)
        self.assertEqual(status, 200)
        self.assertIn(b"Ticket Taker", body)

    def test_api_requires_the_right_key(self):
        for key in (None, "", "wrong", self.key + "x"):
            self.assertEqual(self.call("GET", f"/api/ticket?id={self.sale.id}", key=key)[0], 401, key)
            self.assertEqual(self.call("POST", "/api/checkin", {"id": self.sale.id}, key=key)[0], 401, key)
        self.assertEqual(self.store.get_sale(self.sale.id).checked_in, 0)
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)

    def test_resetting_the_key_locks_out_old_links(self):
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)
        new_key = self.store.reset_web_key()
        self.assertEqual(self.call("GET", "/api/ping")[0], 401)
        self.assertEqual(self.call("GET", "/api/ping", key=new_key)[0], 200)

    def test_lookup(self):
        status, body = self.call("GET", f"/api/ticket?id={self.sale.id}")
        t = body["ticket"]
        self.assertEqual((status, t["idText"], t["title"], t["ticketCount"], t["notCheckedIn"]), (200, f"{self.sale.id:06d}", "Web Movie", 4, 4))
        self.assertFalse(t["isToday"])
        self.assertEqual(t["items"], [{"type": "Adult", "qty": 3}, {"type": "Child", "qty": 1}])
        self.assertEqual(self.call("GET", "/api/ticket?id=000001")[0], 200)  # leading zeros from the barcode
        self.assertEqual(self.call("GET", "/api/ticket?id=987654")[0], 404)
        for bad in ("", "abc", "0", "-3", "1" + "0" * 15):
            self.assertEqual(self.call("GET", f"/api/ticket?id={bad}")[0], 400, bad)

    def test_checkin_counts(self):
        day = self.show.starts_at.date().isoformat()
        status, body = self.call("GET", f"/api/checkins?day={day}")
        self.assertEqual((status, body["sold"], body["checkedIn"], body["isToday"]), (200, 4, 0, False))
        self.assertEqual(
            body["shows"], [{"id": self.show.id, "title": "Web Movie", "time": body["shows"][0]["time"],
                             "theater": "Theater 1", "sold": 4, "checkedIn": 0}],
        )
        self.call("POST", "/api/checkin", {"id": self.sale.id, "count": 3})
        self.assertEqual(self.call("GET", f"/api/checkins?day={day}")[1]["checkedIn"], 3)
        status, today = self.call("GET", "/api/checkins")  # no day: today, when the sale is for tomorrow
        self.assertEqual((status, today["isToday"], today["shows"]), (200, True, []))
        self.assertEqual(self.call("GET", "/api/checkins?day=not-a-date")[0], 400)
        self.assertEqual(self.call("GET", f"/api/checkins?day={day}", key="wrong")[0], 401)
        self.assertEqual(self.call("GET", f"/api/checkins?day={day}", key=None)[0], 401)

    def test_check_in_all_partial_and_undo(self):
        sid = self.sale.id
        status, body = self.call("POST", "/api/checkin", {"id": sid, "count": 3})
        self.assertEqual((status, body["ticket"]["checkedIn"], body["ticket"]["notCheckedIn"]), (200, 3, 1))
        status, body = self.call("POST", "/api/checkin", {"id": sid, "count": 2})
        self.assertEqual(status, 400)
        self.assertIn("between 1 and 1", body["error"])
        status, body = self.call("POST", "/api/checkin", {"id": sid})  # no count = everyone left
        self.assertEqual((status, body["ticket"]["checkedIn"]), (200, 4))
        self.assertIsNotNone(body["ticket"]["checkedInAt"])
        self.assertEqual(self.call("POST", "/api/checkin", {"id": sid})[0], 400)  # already all in
        status, body = self.call("POST", "/api/undo", {"id": sid})
        self.assertEqual((status, body["ticket"]["checkedIn"]), (200, 0))
        self.assertEqual(self.store.get_sale(sid).checked_in, 0)

    def test_refunded_and_unknown_tickets_cannot_check_in(self):
        self.store.refund(self.sale.id)
        status, body = self.call("POST", "/api/checkin", {"id": self.sale.id})
        self.assertEqual(status, 400)
        self.assertIn("refunded", body["error"])
        self.assertEqual(self.call("GET", f"/api/ticket?id={self.sale.id}")[1]["ticket"]["status"], "refunded")
        self.assertEqual(self.call("POST", "/api/checkin", {"id": 424242})[0], 400)

    def test_bad_requests(self):
        sid = self.sale.id
        self.assertEqual(self.call("POST", "/api/checkin", {"id": sid, "count": "2"})[0], 400)
        self.assertEqual(self.call("POST", "/api/checkin", {"id": sid, "count": True})[0], 400)
        self.assertEqual(self.call("POST", "/api/checkin", {"id": sid, "count": 0})[0], 400)
        self.assertEqual(self.call("POST", "/api/checkin", raw_body="not json")[0], 400)
        self.assertEqual(self.call("POST", "/api/checkin", ["list"])[0], 400)
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("POST", "/api/other", {})[0], 404)
        self.assertEqual(self.store.get_sale(sid).checked_in, 0)

    def test_rejected_post_does_not_break_the_next_request_on_the_same_connection(self):
        self.assertEqual(self.call("POST", "/api/checkin", {"id": self.sale.id}, key="wrong")[0], 401)
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)

    def test_oversized_body_is_rejected(self):
        status, _ = self.call("POST", "/api/checkin", raw_body="x" * 10000)
        self.assertEqual(status, 400)

    def test_dropped_connections_do_not_spam_the_terminal(self):
        import contextlib, io, socket, struct, time
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            for _ in range(3):
                raw = socket.create_connection(("127.0.0.1", self.server.port), timeout=5)
                raw.sendall(b"GET /api/ping HTTP/1.1\r\nHost: x\r\n")  # request never finished
                raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                raw.close()  # RST, like a phone that went away
            time.sleep(0.5)
        self.assertEqual(captured.getvalue(), "")
        self.assertEqual(self.call("GET", "/api/ping")[0], 200)  # and the server is still fine

    def test_json_never_contains_internal_fields(self):
        data = sale_json(self.store.get_sale(self.sale.id))
        self.assertNotIn("tendered", json.dumps(data).lower())


class PhoneAccessTests(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "pos.db")
        self.store = Store(self.path)
        self.started = []

    def tearDown(self):
        for access in self.started:
            access.stop()
        self.store.close()

    def start(self, **kw):
        access = start_phone_access(self.store, self.path, host="192.0.2.7", **kw)
        self.started.append(access)
        return access

    def test_url_carries_the_key_and_the_real_port(self):
        access = self.start(port=0)
        self.assertTrue(access.running)
        self.assertEqual(access.url(), f"http://192.0.2.7:{access.port}/?key={self.store.web_key()}")

    def test_a_busy_port_falls_back_to_the_next_one_and_the_qr_follows(self):
        first = self.start(port=0)
        second = self.start(port=first.port)  # first.port is taken
        self.assertTrue(second.running)
        self.assertNotEqual(second.port, first.port)
        self.assertIn(f":{second.port}/", second.url())

    def test_gives_up_with_a_message_when_no_port_is_free(self):
        first = self.start(port=0)
        stuck = self.start(port=first.port, attempts=1)
        self.assertFalse(stuck.running)
        self.assertIn(str(first.port), stuck.error)


if __name__ == "__main__":
    unittest.main()
