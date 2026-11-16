"""Phone ticket-taker web app: a tiny HTTP server (standard library only) over the POS database.

The POS starts it automatically. It can also run alone:  python3 -m moviepos.web
Every API call needs the access key that is embedded in the QR code (see Store.web_key).
"""
from __future__ import annotations

import argparse
import hmac
import json
import socket
import sys
import threading
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import fmt, qr
from .store import Sale, ShowCheckins, Store

PAGE = Path(__file__).with_name("static") / "ticket_taker.html"
DEFAULT_PORT = 8080
MAX_BODY = 4096
MAX_ID = 10**12


def lan_ip() -> str:
    """Best guess at this machine's address on the local network."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # UDP: nothing is actually sent
            return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"


def sale_json(sale: Sale) -> dict:
    show = sale.showing
    return {
        "id": sale.id,
        "idText": fmt.tx_id(sale.id),
        "status": sale.status,
        "title": show.title,
        "day": fmt.short_day(show.starts_at),
        "time": fmt.clock(show.starts_at),
        "theater": show.theater_name,
        "isToday": show.starts_at.date() == date.today(),
        "ended": datetime.now() > show.ends_at,
        "items": [{"type": i.ticket_type, "qty": i.qty} for i in sale.items],
        "ticketCount": sale.ticket_count,
        "checkedIn": sale.checked_in,
        "notCheckedIn": sale.not_checked_in,
        "checkedInAt": fmt.clock(sale.checked_in_at) if sale.checked_in_at else None,
    }


def checkins_json(day: date, rows: list[ShowCheckins]) -> dict:
    return {
        "day": day.isoformat(),
        "dayLabel": fmt.day_label(day),
        "isToday": day == date.today(),
        "sold": sum(r.sold for r in rows),
        "checkedIn": sum(r.checked_in for r in rows),
        "shows": [
            {
                "id": r.showing.id, "title": r.showing.title, "time": fmt.clock(r.showing.starts_at),
                "theater": r.showing.theater_name, "sold": r.sold, "checkedIn": r.checked_in,
            }
            for r in rows
        ],
    }


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        # Phones routinely drop or reset connections (screen lock, Wi-Fi roaming, closing Safari). Not worth a traceback.
        if isinstance(sys.exc_info()[1], (ConnectionError, TimeoutError)):
            return
        super().handle_error(request, client_address)


class _Handler(BaseHTTPRequestHandler):
    server_version = "MoviePOS"
    protocol_version = "HTTP/1.1"
    timeout = 30  # drop idle keep-alive connections instead of holding a thread forever

    def log_message(self, *args) -> None:  # keep the POS terminal quiet
        pass

    # ---- plumbing ----

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _authorized(self, store: Store) -> bool:
        expected = store.get_setting("web_key")
        given = self.headers.get("X-Access-Key", "")
        return bool(expected) and hmac.compare_digest(expected.encode(), given.encode())

    def _ticket_id(self, raw) -> int | None:
        try:
            value = int(str(raw))
        except (TypeError, ValueError):
            return None
        return value if 0 < value < MAX_ID else None

    def _read_json(self) -> dict | None:
        """Always consume the body so a keep-alive connection stays in sync, even when we reject the call."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 <= length <= MAX_BODY:
            self.close_connection = True
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def _open(self) -> Store:
        return Store(self.server.db_path, setup=False)

    # ---- routes ----

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/":
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/ping":
            with closing(self._open()) as store:
                ok = self._authorized(store)
            self._json(200, {"ok": True}) if ok else self._error(401, "Access key rejected.")
        elif url.path == "/api/ticket":
            self._lookup(parse_qs(url.query).get("id", [""])[0])
        elif url.path == "/api/checkins":
            self._checkins(parse_qs(url.query).get("day", [""])[0])
        else:
            self._error(404, "Not found.")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/api/checkin", "/api/undo"):
            return self._error(404, "Not found.")
        body = self._read_json()
        with closing(self._open()) as store:
            if not self._authorized(store):
                return self._error(401, "Access key rejected.")
            ticket_id = self._ticket_id(body.get("id")) if body else None
            if ticket_id is None:
                return self._error(400, "Enter a ticket ID.")
            try:
                if path == "/api/undo":
                    sale = store.set_checked_in(ticket_id, 0)
                else:
                    count = body.get("count")
                    if count is not None and (not isinstance(count, int) or isinstance(count, bool)):
                        return self._error(400, "Count must be a whole number.")
                    sale = store.check_in(ticket_id, count)
            except ValueError as e:
                return self._error(400, str(e))
        self._json(200, {"ticket": sale_json(sale)})

    def _checkins(self, raw_day: str) -> None:
        with closing(self._open()) as store:
            if not self._authorized(store):
                return self._error(401, "Access key rejected.")
            try:
                day = date.fromisoformat(raw_day) if raw_day else date.today()
            except ValueError:
                return self._error(400, "Day must look like 2026-10-29.")
            rows = store.checkin_counts(day)
        self._json(200, checkins_json(day, rows))

    def _lookup(self, raw_id: str) -> None:
        ticket_id = self._ticket_id(raw_id)
        with closing(self._open()) as store:
            if not self._authorized(store):
                return self._error(401, "Access key rejected.")
            if ticket_id is None:
                return self._error(400, "Enter a ticket ID.")
            sale = store.get_sale(ticket_id)
        if sale is None:
            self._error(404, f"No ticket with ID {fmt.tx_id(ticket_id)}.")
        else:
            self._json(200, {"ticket": sale_json(sale)})


class WebServer:
    def __init__(self, db_path: str | Path, port: int = DEFAULT_PORT, host: str = "0.0.0.0"):
        self.httpd = _Server((host, port), _Handler)
        self.httpd.db_path = str(db_path)
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.1), daemon=True, name="phone-web"
        )

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@dataclass
class PhoneAccess:
    """What the POS needs to show the QR code."""

    store: Store
    host: str
    port: int
    server: WebServer | None = None
    error: str = ""

    @property
    def running(self) -> bool:
        return self.server is not None

    def url(self) -> str:
        return f"http://{self.host}:{self.port}/?key={self.store.web_key()}"

    def stop(self) -> None:
        if self.server:
            self.server.stop()


def start_phone_access(
    store: Store, db_path: str | Path, port: int = DEFAULT_PORT, host: str | None = None, attempts: int = 10
) -> PhoneAccess:
    """Create the access key and start the server. If the port is taken (say, by a POS that is still
    closing), try the next few; the QR code always carries whichever port worked. Never raises."""
    store.web_key()
    access = PhoneAccess(store, host or lan_ip(), port)
    candidates = [0] if port == 0 else range(port, port + max(attempts, 1))
    last_error = ""
    for candidate in candidates:
        try:
            access.server = WebServer(db_path, candidate)
        except OSError as e:
            last_error = e.strerror or str(e)
            continue
        access.port = access.server.port
        access.server.start()
        return access
    access.error = f"Couldn't start the phone web app on port {port}: {last_error}"
    return access


def terminal_qr(text: str) -> str:
    matrix = qr.encode(text)
    quiet = [[False] * (len(matrix) + 4) for _ in range(2)]
    rows = quiet + [[False, False] + row + [False, False] for row in matrix] + quiet
    return "\n".join("".join("  " if cell else "██" for cell in row) for row in rows)


def main() -> None:
    default_db = Path(__file__).resolve().parent.parent / "moviepos.db"
    parser = argparse.ArgumentParser(description="Phone ticket-taker web app (standalone)")
    parser.add_argument("--db", default=str(default_db), help="POS database (default: ./moviepos.db)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", help="address phones should use (default: auto-detected LAN address)")
    args = parser.parse_args()
    if not Path(args.db).is_file():
        sys.exit(f"Database not found: {args.db}\nStart the POS once (python3 -m moviepos) to create it.")
    store = Store(args.db)
    access = start_phone_access(store, args.db, args.port, args.host)
    if not access.running:
        sys.exit(access.error)
    url = access.url()
    print(terminal_qr(url))
    print(f"\nOpen on the phone:  {url}\nPress Ctrl+C to stop.")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        access.stop()
        store.close()


if __name__ == "__main__":
    main()
