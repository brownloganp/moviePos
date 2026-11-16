"""SQLite data layer and business rules for the movie POS. No UI code here."""
from __future__ import annotations

import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DT_FMT = "%Y-%m-%d %H:%M"
TS_FMT = "%Y-%m-%d %H:%M:%S"

TICKET_TYPES = ("Adult", "Student", "Child", "Employee", "Pass")
DEFAULT_PRICES = {"Adult": 1250, "Student": 1000, "Child": 800, "Employee": 500, "Pass": 0}
PAYMENT_METHODS = ("cash", "card", "credit")
DEFAULT_VENUE_NAME = "MOVIE THEATER"
MAX_VENUE_NAME = 40
MAX_CONCESSION_NAME = 30
MAX_CONCESSION_PRICE = 99_999  # cents
DEFAULT_CONCESSIONS = (
    ("Small Popcorn", 550), ("Large Popcorn", 750), ("Small Drink", 400), ("Large Drink", 500),
    ("Candy", 400), ("Nachos", 600), ("Hot Dog", 500), ("Bottled Water", 300),
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS theaters (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    capacity INTEGER NOT NULL CHECK (capacity > 0)
);
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    rating TEXT NOT NULL DEFAULT '',
    runtime_min INTEGER NOT NULL DEFAULT 120 CHECK (runtime_min > 0)
);
CREATE TABLE IF NOT EXISTS showtimes (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id),
    theater_id INTEGER NOT NULL REFERENCES theaters(id),
    starts_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_showtimes_start ON showtimes(starts_at);
CREATE TABLE IF NOT EXISTS ticket_types (
    name TEXT PRIMARY KEY,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    showtime_id INTEGER NOT NULL REFERENCES showtimes(id),
    total_cents INTEGER NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card', 'credit', 'none')),
    tendered_cents INTEGER NOT NULL,
    change_cents INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'sold' CHECK (status IN ('sold', 'refunded')),
    refunded_at TEXT,
    checked_in INTEGER NOT NULL DEFAULT 0,
    checked_in_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_transactions_showtime ON transactions(showtime_id);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS transaction_items (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    ticket_type TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    unit_price_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS concession_items (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    sort_order INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS concession_sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    total_cents INTEGER NOT NULL,
    payment_method TEXT NOT NULL CHECK (payment_method IN ('cash', 'card', 'credit', 'none')),
    tendered_cents INTEGER NOT NULL,
    change_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS concession_sale_items (
    id INTEGER PRIMARY KEY,
    sale_id INTEGER NOT NULL REFERENCES concession_sales(id),
    name TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    unit_price_cents INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Movie:
    id: int
    title: str
    rating: str
    runtime_min: int


@dataclass(frozen=True)
class Theater:
    id: int
    name: str
    capacity: int


@dataclass(frozen=True)
class Showing:
    id: int
    movie_id: int
    title: str
    rating: str
    runtime_min: int
    theater_id: int
    theater_name: str
    capacity: int
    starts_at: datetime
    sold: int

    @property
    def remaining(self) -> int:
        return max(self.capacity - self.sold, 0)

    @property
    def pct_available(self) -> int:
        return round(100 * self.remaining / self.capacity) if self.capacity else 0

    @property
    def ends_at(self) -> datetime:
        return self.starts_at + timedelta(minutes=self.runtime_min)


@dataclass(frozen=True)
class SaleItem:
    ticket_type: str
    qty: int
    unit_price_cents: int

    @property
    def line_cents(self) -> int:
        return self.qty * self.unit_price_cents


@dataclass(frozen=True)
class Sale:
    id: int
    created_at: datetime
    showing: Showing
    items: tuple[SaleItem, ...]
    total_cents: int
    payment_method: str
    tendered_cents: int
    change_cents: int
    status: str
    refunded_at: datetime | None
    checked_in: int = 0
    checked_in_at: datetime | None = None

    @property
    def ticket_count(self) -> int:
        return sum(i.qty for i in self.items)

    @property
    def not_checked_in(self) -> int:
        return self.ticket_count - self.checked_in


@dataclass(frozen=True)
class ConcessionItem:
    id: int
    name: str
    price_cents: int


@dataclass(frozen=True)
class ConcessionLine:
    name: str
    qty: int
    unit_price_cents: int

    @property
    def line_cents(self) -> int:
        return self.qty * self.unit_price_cents


@dataclass(frozen=True)
class ConcessionSale:
    id: int
    created_at: datetime
    items: tuple[ConcessionLine, ...]
    total_cents: int
    payment_method: str
    tendered_cents: int
    change_cents: int

    @property
    def item_count(self) -> int:
        return sum(i.qty for i in self.items)


@dataclass(frozen=True)
class ShowCheckins:
    showing: Showing
    checked_in: int

    @property
    def sold(self) -> int:
        return self.showing.sold

    @property
    def waiting(self) -> int:
        return max(self.sold - self.checked_in, 0)


class Store:
    def __init__(self, path: str | Path = ":memory:", read_only: bool = False, setup: bool = True):
        """setup=False skips schema/price initialisation: for short-lived connections to a database
        the POS has already set up (the phone web server opens one per request)."""
        if read_only:
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self.db = sqlite3.connect(uri, uri=True, isolation_level=None)
            self.db.row_factory = sqlite3.Row
            return
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        if not setup:
            return
        self.db.executescript(SCHEMA)
        self._migrate()
        for order, name in enumerate(TICKET_TYPES):
            self.db.execute(
                "INSERT OR IGNORE INTO ticket_types(name, price_cents, sort_order) VALUES (?,?,?)",
                (name, DEFAULT_PRICES[name], order),
            )
        self._seed_concessions()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(transactions)")}
        if "checked_in" not in cols:
            self.db.execute("ALTER TABLE transactions ADD COLUMN checked_in INTEGER NOT NULL DEFAULT 0")
        if "checked_in_at" not in cols:
            self.db.execute("ALTER TABLE transactions ADD COLUMN checked_in_at TEXT")
        table_sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name='transactions'").fetchone()["sql"]
        if "'credit'" not in table_sql:
            self._rebuild_transactions()

    def _rebuild_transactions(self) -> None:
        """SQLite can't change a CHECK constraint in place: copy the table so payment_method may be 'credit'."""
        start = SCHEMA.index("CREATE TABLE IF NOT EXISTS transactions")
        table = SCHEMA[start : SCHEMA.index(";", start)].replace("EXISTS transactions", "EXISTS transactions_new")
        columns = "id, created_at, showtime_id, total_cents, payment_method, tendered_cents, change_cents, status, refunded_at, checked_in, checked_in_at"
        self.db.execute("PRAGMA foreign_keys = OFF")  # dropping the old table would otherwise fail on transaction_items
        try:
            self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("DROP TABLE IF EXISTS transactions_new")
            self.db.execute(table)
            self.db.execute(f"INSERT INTO transactions_new({columns}) SELECT {columns} FROM transactions")
            self.db.execute("DROP TABLE transactions")
            self.db.execute("ALTER TABLE transactions_new RENAME TO transactions")
            self.db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_showtime ON transactions(showtime_id)")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        finally:
            self.db.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _tx(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    # ---- theaters -------------------------------------------------------

    def list_theaters(self) -> list[Theater]:
        rows = self.db.execute("SELECT id, name, capacity FROM theaters ORDER BY name")
        return [Theater(**dict(r)) for r in rows]

    def add_theater(self, name: str, capacity: int) -> int:
        name = self._clean_name(name, "Theater name")
        self._check_capacity(capacity)
        try:
            cur = self.db.execute("INSERT INTO theaters(name, capacity) VALUES (?,?)", (name, capacity))
        except sqlite3.IntegrityError:
            raise ValueError(f'A theater named "{name}" already exists.') from None
        return cur.lastrowid

    def update_theater(self, theater_id: int, name: str, capacity: int) -> None:
        name = self._clean_name(name, "Theater name")
        self._check_capacity(capacity)
        with self._tx():
            now = datetime.now()
            for s in self.showings(theater_id=theater_id, since=now):
                if s.sold > capacity:
                    raise ValueError(
                        f"{s.title} at {s.starts_at:%b %d %H:%M} already has {s.sold} seats sold, "
                        f"so capacity can't be lowered to {capacity}."
                    )
            try:
                self.db.execute(
                    "UPDATE theaters SET name=?, capacity=? WHERE id=?", (name, capacity, theater_id)
                )
            except sqlite3.IntegrityError:
                raise ValueError(f'A theater named "{name}" already exists.') from None

    def delete_theater(self, theater_id: int) -> None:
        if self.db.execute("SELECT 1 FROM showtimes WHERE theater_id=? LIMIT 1", (theater_id,)).fetchone():
            raise ValueError("This theater still has showtimes. Remove them first.")
        self.db.execute("DELETE FROM theaters WHERE id=?", (theater_id,))

    # ---- movies ---------------------------------------------------------

    def list_movies(self) -> list[Movie]:
        rows = self.db.execute("SELECT id, title, rating, runtime_min FROM movies ORDER BY title")
        return [Movie(**dict(r)) for r in rows]

    def add_movie(self, title: str, rating: str, runtime_min: int) -> int:
        title = self._clean_name(title, "Title")
        self._check_runtime(runtime_min)
        try:
            cur = self.db.execute(
                "INSERT INTO movies(title, rating, runtime_min) VALUES (?,?,?)",
                (title, rating.strip(), runtime_min),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f'"{title}" is already in the movie list.') from None
        return cur.lastrowid

    def update_movie(self, movie_id: int, title: str, rating: str, runtime_min: int) -> None:
        title = self._clean_name(title, "Title")
        self._check_runtime(runtime_min)
        try:
            self.db.execute(
                "UPDATE movies SET title=?, rating=?, runtime_min=? WHERE id=?",
                (title, rating.strip(), runtime_min, movie_id),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f'"{title}" is already in the movie list.') from None

    def delete_movie(self, movie_id: int) -> None:
        if self.db.execute("SELECT 1 FROM showtimes WHERE movie_id=? LIMIT 1", (movie_id,)).fetchone():
            raise ValueError("This movie still has showtimes. Remove them first.")
        self.db.execute("DELETE FROM movies WHERE id=?", (movie_id,))

    # ---- ticket prices --------------------------------------------------

    def ticket_prices(self) -> dict[str, int]:
        rows = self.db.execute("SELECT name, price_cents FROM ticket_types ORDER BY sort_order")
        return {r["name"]: r["price_cents"] for r in rows}

    def set_price(self, ticket_type: str, cents: int) -> None:
        if cents < 0:
            raise ValueError("Price can't be negative.")
        cur = self.db.execute("UPDATE ticket_types SET price_cents=? WHERE name=?", (cents, ticket_type))
        if cur.rowcount == 0:
            raise ValueError(f"Unknown ticket type: {ticket_type}")

    # ---- concessions ----------------------------------------------------

    def _seed_concessions(self) -> None:
        """Stock the menu once, so deleting every item later doesn't bring the defaults back."""
        if self.get_setting("concessions_seeded"):
            return
        if not self.db.execute("SELECT 1 FROM concession_items LIMIT 1").fetchone():
            for order, (name, cents) in enumerate(DEFAULT_CONCESSIONS):
                self.db.execute(
                    "INSERT INTO concession_items(name, price_cents, sort_order) VALUES (?,?,?)", (name, cents, order)
                )
        self.set_setting("concessions_seeded", "1")

    def list_concessions(self) -> list[ConcessionItem]:
        rows = self.db.execute("SELECT id, name, price_cents FROM concession_items ORDER BY sort_order, id")
        return [ConcessionItem(**dict(r)) for r in rows]

    def add_concession(self, name: str, price_cents: int) -> int:
        name = self._check_concession(name, price_cents)
        try:
            cur = self.db.execute(
                "INSERT INTO concession_items(name, price_cents, sort_order)"
                " VALUES (?,?,(SELECT COALESCE(MAX(sort_order), -1) + 1 FROM concession_items))",
                (name, price_cents),
            )
        except sqlite3.IntegrityError:
            raise ValueError(f'"{name}" is already on the concessions menu.') from None
        return cur.lastrowid

    def update_concession(self, item_id: int, name: str, price_cents: int) -> None:
        name = self._check_concession(name, price_cents)
        try:
            cur = self.db.execute(
                "UPDATE concession_items SET name=?, price_cents=? WHERE id=?", (name, price_cents, item_id)
            )
        except sqlite3.IntegrityError:
            raise ValueError(f'"{name}" is already on the concessions menu.') from None
        if cur.rowcount == 0:
            raise ValueError("That item no longer exists.")

    def delete_concession(self, item_id: int) -> None:
        """Past sales keep their own copy of the name and price, so an item can always be removed."""
        self.db.execute("DELETE FROM concession_items WHERE id=?", (item_id,))

    @classmethod
    def _check_concession(cls, name: str, price_cents: int) -> str:
        name = cls._clean_name(name, "Name")
        if len(name) > MAX_CONCESSION_NAME:
            raise ValueError(f"Name can be at most {MAX_CONCESSION_NAME} characters.")
        if price_cents < 0:
            raise ValueError("Price can't be negative.")
        if price_cents > MAX_CONCESSION_PRICE:
            raise ValueError(f"Price can be at most ${MAX_CONCESSION_PRICE // 100:,}.")
        return name

    def concession_sell(self, quantities: dict[int, int], method: str, tendered_cents: int | None = None) -> ConcessionSale:
        """Ring up concession items, given as {item id: quantity}, at their current prices."""
        wanted = {item_id: qty for item_id, qty in quantities.items() if qty}
        if not wanted or any(qty < 0 for qty in wanted.values()):
            raise ValueError("Add at least one item.")
        with self._tx():
            menu = {i.id: i for i in self.list_concessions()}
            gone = [i for i in wanted if i not in menu]
            if gone:
                raise ValueError("An item in this order was removed from the menu.")
            total = sum(menu[i].price_cents * q for i, q in wanted.items())
            method, tendered, change = self._settle(total, method, tendered_cents)
            cur = self.db.execute(
                "INSERT INTO concession_sales(created_at, total_cents, payment_method, tendered_cents, change_cents)"
                " VALUES (?,?,?,?,?)",
                (datetime.now().strftime(TS_FMT), total, method, tendered, change),
            )
            sale_id = cur.lastrowid
            for item_id, qty in wanted.items():
                self.db.execute(
                    "INSERT INTO concession_sale_items(sale_id, name, qty, unit_price_cents) VALUES (?,?,?,?)",
                    (sale_id, menu[item_id].name, qty, menu[item_id].price_cents),
                )
        return self.get_concession_sale(sale_id)

    def get_concession_sale(self, sale_id: int) -> ConcessionSale | None:
        row = self.db.execute("SELECT * FROM concession_sales WHERE id=?", (sale_id,)).fetchone()
        if row is None:
            return None
        items = tuple(
            ConcessionLine(r["name"], r["qty"], r["unit_price_cents"])
            for r in self.db.execute(
                "SELECT name, qty, unit_price_cents FROM concession_sale_items WHERE sale_id=? ORDER BY id", (sale_id,)
            )
        )
        return ConcessionSale(
            id=row["id"], created_at=datetime.strptime(row["created_at"], TS_FMT), items=items,
            total_cents=row["total_cents"], payment_method=row["payment_method"],
            tendered_cents=row["tendered_cents"], change_cents=row["change_cents"],
        )

    @staticmethod
    def _settle(total: int, method: str, tendered_cents: int | None) -> tuple[str, int, int]:
        """(method, tendered, change) for a sale of `total` cents paid with `method`."""
        if total == 0:
            return "none", 0, 0
        if method in ("card", "credit"):
            return method, total, 0
        if method == "cash":
            if tendered_cents is None or tendered_cents < total:
                raise ValueError("Cash tendered is less than the total.")
            return "cash", tendered_cents, tendered_cents - total
        raise ValueError("Choose cash, card or store credit.")

    # ---- showtimes ------------------------------------------------------

    _SHOWING_SQL = """
        SELECT s.id, s.movie_id, m.title, m.rating, m.runtime_min,
               s.theater_id, t.name AS theater_name, t.capacity, s.starts_at,
               COALESCE((SELECT SUM(i.qty)
                           FROM transaction_items i
                           JOIN transactions x ON x.id = i.transaction_id
                          WHERE x.showtime_id = s.id AND x.status = 'sold'), 0) AS sold
          FROM showtimes s
          JOIN movies m ON m.id = s.movie_id
          JOIN theaters t ON t.id = s.theater_id
    """

    def showings(
        self,
        *,
        day: date | None = None,
        movie_id: int | None = None,
        theater_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        showing_id: int | None = None,
    ) -> list[Showing]:
        where: list[str] = []
        args: list = []
        if showing_id is not None:
            where.append("s.id = ?")
            args.append(showing_id)
        if movie_id is not None:
            where.append("s.movie_id = ?")
            args.append(movie_id)
        if theater_id is not None:
            where.append("s.theater_id = ?")
            args.append(theater_id)
        if day is not None:
            since = datetime.combine(day, datetime.min.time())
            until = since + timedelta(days=1)
        if since is not None:
            where.append("s.starts_at >= ?")
            args.append(since.strftime(DT_FMT))
        if until is not None:
            where.append("s.starts_at < ?")
            args.append(until.strftime(DT_FMT))
        sql = self._SHOWING_SQL + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY s.starts_at, t.name"
        out = []
        for r in self.db.execute(sql, args):
            d = dict(r)
            d["starts_at"] = datetime.strptime(d["starts_at"], DT_FMT)
            out.append(Showing(**d))
        return out

    def get_showing(self, showing_id: int) -> Showing | None:
        found = self.showings(showing_id=showing_id)
        return found[0] if found else None

    def add_showtimes(self, movie_id: int, theater_id: int, start: datetime, days: int = 1) -> None:
        """Add the same showtime on `days` consecutive days. All or nothing."""
        if days < 1:
            raise ValueError("Days must be at least 1.")
        with self._tx():
            for offset in range(days):
                when = start + timedelta(days=offset)
                self._check_conflict(movie_id, theater_id, when)
                self.db.execute(
                    "INSERT INTO showtimes(movie_id, theater_id, starts_at) VALUES (?,?,?)",
                    (movie_id, theater_id, when.strftime(DT_FMT)),
                )

    def update_showtime(self, showing_id: int, movie_id: int, theater_id: int, start: datetime) -> None:
        with self._tx():
            if self._has_sales(showing_id):
                raise ValueError("Tickets were already sold for this showtime, so it can't be changed.")
            self._check_conflict(movie_id, theater_id, start, exclude_id=showing_id)
            self.db.execute(
                "UPDATE showtimes SET movie_id=?, theater_id=?, starts_at=? WHERE id=?",
                (movie_id, theater_id, start.strftime(DT_FMT), showing_id),
            )

    def delete_showtime(self, showing_id: int) -> None:
        if self._has_sales(showing_id):
            raise ValueError("Tickets were sold for this showtime, so it can't be deleted.")
        self.db.execute("DELETE FROM showtimes WHERE id=?", (showing_id,))

    def _has_sales(self, showing_id: int) -> bool:
        row = self.db.execute("SELECT 1 FROM transactions WHERE showtime_id=? LIMIT 1", (showing_id,))
        return row.fetchone() is not None

    def _check_conflict(self, movie_id: int, theater_id: int, start: datetime, exclude_id: int | None = None):
        movie = self.db.execute("SELECT runtime_min FROM movies WHERE id=?", (movie_id,)).fetchone()
        if movie is None or self.db.execute("SELECT 1 FROM theaters WHERE id=?", (theater_id,)).fetchone() is None:
            raise ValueError("Pick a movie and a theater.")
        end = start + timedelta(minutes=movie["runtime_min"])
        nearby = self.showings(
            theater_id=theater_id, since=start - timedelta(days=1), until=start + timedelta(days=1)
        )
        for other in nearby:
            if other.id == exclude_id:
                continue
            if other.starts_at < end and other.ends_at > start:
                raise ValueError(
                    f"{other.theater_name} is already showing {other.title} "
                    f"{other.starts_at:%a %b %d, %I:%M %p}–{other.ends_at:%I:%M %p}."
                )

    # ---- sales and refunds ----------------------------------------------

    def sell(
        self,
        showing_id: int,
        quantities: dict[str, int],
        method: str,
        tendered_cents: int | None = None,
    ) -> Sale:
        items = {name: qty for name, qty in quantities.items() if qty}
        if not items or any(qty < 0 for qty in items.values()):
            raise ValueError("Select at least one ticket.")
        with self._tx():
            showing = self.get_showing(showing_id)
            if showing is None:
                raise ValueError("That showtime no longer exists.")
            count = sum(items.values())
            if count > showing.remaining:
                raise ValueError(f"Only {showing.remaining} seats are left for this showing.")
            prices = self.ticket_prices()
            unknown = [n for n in items if n not in prices]
            if unknown:
                raise ValueError(f"Unknown ticket type: {unknown[0]}")
            total = sum(prices[n] * q for n, q in items.items())

            method, tendered, change = self._settle(total, method, tendered_cents)

            cur = self.db.execute(
                "INSERT INTO transactions(created_at, showtime_id, total_cents, payment_method,"
                " tendered_cents, change_cents) VALUES (?,?,?,?,?,?)",
                (datetime.now().strftime(TS_FMT), showing_id, total, method, tendered, change),
            )
            sale_id = cur.lastrowid
            for name, qty in items.items():
                self.db.execute(
                    "INSERT INTO transaction_items(transaction_id, ticket_type, qty, unit_price_cents)"
                    " VALUES (?,?,?,?)",
                    (sale_id, name, qty, prices[name]),
                )
        return self.get_sale(sale_id)

    def get_sale(self, sale_id: int) -> Sale | None:
        row = self.db.execute("SELECT * FROM transactions WHERE id=?", (sale_id,)).fetchone()
        if row is None:
            return None
        items = tuple(
            SaleItem(r["ticket_type"], r["qty"], r["unit_price_cents"])
            for r in self.db.execute(
                "SELECT ticket_type, qty, unit_price_cents FROM transaction_items"
                " WHERE transaction_id=? ORDER BY id",
                (sale_id,),
            )
        )
        refunded, admitted_at = row["refunded_at"], row["checked_in_at"]
        return Sale(
            id=row["id"],
            created_at=datetime.strptime(row["created_at"], TS_FMT),
            showing=self.get_showing(row["showtime_id"]),
            items=items,
            total_cents=row["total_cents"],
            payment_method=row["payment_method"],
            tendered_cents=row["tendered_cents"],
            change_cents=row["change_cents"],
            status=row["status"],
            refunded_at=datetime.strptime(refunded, TS_FMT) if refunded else None,
            checked_in=row["checked_in"],
            checked_in_at=datetime.strptime(admitted_at, TS_FMT) if admitted_at else None,
        )

    def recent_sales(self, limit: int = 20) -> list[Sale]:
        ids = [r["id"] for r in self.db.execute("SELECT id FROM transactions ORDER BY id DESC LIMIT ?", (limit,))]
        return [self.get_sale(i) for i in ids]

    def refund(self, sale_id: int) -> Sale:
        """Refund a whole transaction; its seats go back on sale."""
        with self._tx():
            sale = self.get_sale(sale_id)
            if sale is None:
                raise ValueError(f"No transaction with ID {sale_id:06d}.")
            if sale.status == "refunded":
                raise ValueError(f"Transaction {sale_id:06d} was already refunded.")
            self.db.execute(
                "UPDATE transactions SET status='refunded', refunded_at=? WHERE id=?",
                (datetime.now().strftime(TS_FMT), sale_id),
            )
        return self.get_sale(sale_id)

    # ---- check-in -------------------------------------------------------

    def check_in(self, sale_id: int, count: int | None = None) -> Sale:
        """Admit `count` more people from this transaction (default: everyone not yet checked in)."""
        with self._tx():
            sale = self._valid_sale(sale_id)
            if sale.not_checked_in == 0:
                raise ValueError("Everyone on this ticket is already checked in.")
            count = sale.not_checked_in if count is None else count
            if not 1 <= count <= sale.not_checked_in:
                raise ValueError(f"Choose between 1 and {sale.not_checked_in} people.")
            self._write_checked_in(sale_id, sale.checked_in + count)
        return self.get_sale(sale_id)

    def set_checked_in(self, sale_id: int, count: int) -> Sale:
        """Correct the number checked in to an exact value (0 undoes all check-ins)."""
        with self._tx():
            sale = self._valid_sale(sale_id)
            if not 0 <= count <= sale.ticket_count:
                raise ValueError(f"Checked-in count must be between 0 and {sale.ticket_count}.")
            self._write_checked_in(sale_id, count)
        return self.get_sale(sale_id)

    def checkin_counts(self, day: date) -> list[ShowCheckins]:
        """Per showing on `day` that has tickets sold: tickets sold (refunds excluded) and how many are checked in."""
        shows = [s for s in self.showings(day=day) if s.sold]
        if not shows:
            return []
        marks = ",".join("?" * len(shows))
        counts = {
            r["showtime_id"]: r["n"]
            for r in self.db.execute(
                f"SELECT showtime_id, SUM(checked_in) AS n FROM transactions"
                f" WHERE status='sold' AND showtime_id IN ({marks}) GROUP BY showtime_id",
                [s.id for s in shows],
            )
        }
        return [ShowCheckins(s, counts.get(s.id, 0)) for s in shows]

    def _valid_sale(self, sale_id: int) -> Sale:
        sale = self.get_sale(sale_id)
        if sale is None:
            raise ValueError(f"No transaction with ID {sale_id:06d}.")
        if sale.status == "refunded":
            raise ValueError("This ticket was refunded and is not valid.")
        return sale

    def _write_checked_in(self, sale_id: int, count: int) -> None:
        stamp = datetime.now().strftime(TS_FMT) if count else None
        self.db.execute(
            "UPDATE transactions SET checked_in=?, checked_in_at=? WHERE id=?", (count, stamp, sale_id)
        )

    # ---- settings -------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def venue_name(self) -> str:
        """The theater's own name, printed at the top of every ticket."""
        return self.get_setting("venue_name") or DEFAULT_VENUE_NAME

    def set_venue_name(self, name: str) -> None:
        name = self._clean_name(name, "Name")
        if len(name) > MAX_VENUE_NAME:
            raise ValueError(f"Name can be at most {MAX_VENUE_NAME} characters.")
        self.set_setting("venue_name", name)

    def web_key(self) -> str:
        """Secret that phones must present to use the web check-in. Created on first use."""
        key = self.get_setting("web_key")
        if key is None:
            with self._tx():  # re-check inside the lock: the web app and POS may race to create it
                key = self.get_setting("web_key")
                if key is None:
                    key = secrets.token_urlsafe(12)
                    self.set_setting("web_key", key)
        return key

    def reset_web_key(self) -> str:
        """Issue a new key; phones using the old QR code are locked out."""
        key = secrets.token_urlsafe(12)
        self.set_setting("web_key", key)
        return key

    # ---- helpers --------------------------------------------------------

    @staticmethod
    def _clean_name(value: str, label: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError(f"{label} is required.")
        return value

    @staticmethod
    def _check_capacity(capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Capacity must be at least 1 seat.")

    @staticmethod
    def _check_runtime(runtime_min: int) -> None:
        if runtime_min < 1:
            raise ValueError("Runtime must be at least 1 minute.")

    def is_empty(self) -> bool:
        return not (
            self.db.execute("SELECT 1 FROM movies LIMIT 1").fetchone()
            or self.db.execute("SELECT 1 FROM theaters LIMIT 1").fetchone()
        )

    def seed_demo(self) -> None:
        """Sample theaters, movies and a week of showtimes so the app isn't empty on first run."""
        theaters = [("Theater 1", 120), ("Theater 2", 80), ("Theater 3", 150), ("Theater 4", 60)]
        movies = [
            ("The Last Lighthouse", "PG-13", 118),
            ("Galaxy Pups", "G", 92),
            ("Midnight on Elm Street", "R", 105),
            ("Dragon's Gate", "PG", 130),
        ]
        t_ids = [self.add_theater(n, c) for n, c in theaters]
        m_ids = [self.add_movie(t, r, m) for t, r, m in movies]
        today = datetime.combine(date.today(), datetime.min.time())
        schedule = [(11, 0), (13, 45), (16, 30), (19, 15), (21, 45)]
        for day in range(7):
            for slot, (hour, minute) in enumerate(schedule):
                for k, m_id in enumerate(m_ids):
                    start = today + timedelta(days=day, hours=hour, minutes=minute)
                    theater = t_ids[(k + slot) % len(t_ids)]
                    try:
                        self.add_showtimes(m_id, theater, start)
                    except ValueError:
                        pass
