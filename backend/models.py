"""
Vilas — Hotel Reservation System
================================
OOP domain layer.

Classes
-------
Database      : thread-safe SQLite gateway (context-managed connections)
Password      : PBKDF2 password hashing helper
User          : guest accounts (register / authenticate / profile stats)
Hotel         : search, detail, and the live "reserved vs booked" board
RoomType      : Standard / Deluxe / Suite categories with availability
Reservation   : hold (reserved) -> pay (booked) -> cancel lifecycle
Payment       : simulated gateway (card / UPI / wallet) with Luhn checks
FoodOrder     : online delivery orders (paid) & offline dine-in orders (date+time)
Favourite     : guest wishlist
AuditLog      : append-only JSONL audit trail          (File I/O)
Exporter      : downloadable JSON booking exports      (File I/O)

Storage
-------
* SQLite  — accounts, hotels, room types, reservations, payments, orders, favourites
* Files   — data/hotels.json + data/menu.json seeds (read on demand),
            data/audit.jsonl (appended on every action), exports/*.json reports

Semantics (per requirements)
----------------------------
* 'reserved' = room held, payment still pending
* 'booked'   = paid & confirmed
* cancelled reservations release their rooms immediately
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")


def _writable_dir(preferred: str, fallback_name: str) -> str:
    """Return ``preferred`` if writable, else a tmp dir (Vercel's FS is read-only)."""
    try:
        os.makedirs(preferred, exist_ok=True)
        probe = os.path.join(preferred, ".write-probe")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return preferred
    except OSError:
        alt = os.path.join(tempfile.gettempdir(), fallback_name)
        os.makedirs(alt, exist_ok=True)
        return alt


EXPORT_DIR = os.environ.get("VILAS_EXPORT_DIR") or _writable_dir(
    os.path.join(BASE_DIR, "exports"), "vilas-exports"
)
_AUDIT_DIR = os.environ.get("VILAS_DATA_DIR") or _writable_dir(DATA_DIR, "vilas-data")
AUDIT_LOG = os.path.join(_AUDIT_DIR, "audit.jsonl")
HOTELS_SEED = os.path.join(DATA_DIR, "hotels.json")
MENU_SEED = os.path.join(DATA_DIR, "menu.json")
DB_PATH = os.environ.get(
    "SQLITE_PATH",
    os.path.join(_writable_dir(DATA_DIR, "vilas-data"), "vilas.db"),
)


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def _luhn(number: str) -> bool:
    """Classic Luhn checksum for simulated card numbers."""
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# --------------------------------------------------------------------------
# Database gateway
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hotels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    city TEXT NOT NULL,
    category TEXT NOT NULL,
    tagline TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL,
    phone TEXT NOT NULL,
    email TEXT NOT NULL,
    hours TEXT NOT NULL,
    rating REAL NOT NULL DEFAULT 0,
    reviews INTEGER NOT NULL DEFAULT 0,
    dine_label TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL,
    description TEXT NOT NULL,
    about TEXT NOT NULL,
    menu_key TEXT NOT NULL DEFAULT 'default'
);
CREATE TABLE IF NOT EXISTS room_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hotel_id INTEGER NOT NULL REFERENCES hotels(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    price REAL NOT NULL,
    total INTEGER NOT NULL,
    images TEXT NOT NULL,
    description TEXT NOT NULL,
    amenities TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    hotel_id INTEGER NOT NULL REFERENCES hotels(id),
    room_type_id INTEGER NOT NULL REFERENCES room_types(id),
    check_in TEXT NOT NULL,
    check_out TEXT NOT NULL,
    guests INTEGER NOT NULL,
    rooms INTEGER NOT NULL,
    nights INTEGER NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved','booked','cancelled')),
    payment_method TEXT,
    created_at TEXT NOT NULL,
    paid_at TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    method TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'captured',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS food_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    hotel_id INTEGER NOT NULL REFERENCES hotels(id),
    type TEXT NOT NULL CHECK (type IN ('online','offline')),
    items TEXT NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL,
    address TEXT,
    payment_method TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    dining_date TEXT,
    dining_time TEXT,
    guests INTEGER,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS favourites (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    hotel_id INTEGER NOT NULL REFERENCES hotels(id) ON DELETE CASCADE,
    PRIMARY KEY (user_id, hotel_id)
);
CREATE INDEX IF NOT EXISTS idx_res_user ON reservations(user_id);
CREATE INDEX IF NOT EXISTS idx_res_room ON reservations(room_type_id);
CREATE INDEX IF NOT EXISTS idx_ord_user ON food_orders(user_id);
"""


# PostgreSQL dialect of the same schema (used when DATABASE_URL is set, e.g.
# Supabase — the only viable persistence on serverless/Vercel).
SCHEMA_PG = """
CREATE TABLE IF NOT EXISTS users (
    id bigint generated by default as identity primary key,
    name text not null,
    email text not null unique,
    password_hash text not null,
    salt text not null,
    phone text not null default '',
    created_at text not null
);
CREATE TABLE IF NOT EXISTS hotels (
    id bigint generated by default as identity primary key,
    slug text not null unique,
    name text not null,
    city text not null,
    category text not null,
    tagline text not null default '',
    address text not null,
    phone text not null,
    email text not null,
    hours text not null,
    rating double precision not null default 0,
    reviews integer not null default 0,
    dine_label text not null default '',
    image text not null,
    description text not null,
    about text not null,
    menu_key text not null default 'default'
);
CREATE TABLE IF NOT EXISTS room_types (
    id bigint generated by default as identity primary key,
    hotel_id bigint not null references public.hotels(id) on delete cascade,
    name text not null,
    price double precision not null,
    total integer not null,
    images text not null,
    description text not null,
    amenities text not null
);
CREATE TABLE IF NOT EXISTS reservations (
    id bigint generated by default as identity primary key,
    code text not null unique,
    user_id bigint not null references users(id),
    hotel_id bigint not null references hotels(id),
    room_type_id bigint not null references room_types(id),
    check_in text not null,
    check_out text not null,
    guests integer not null,
    rooms integer not null,
    nights integer not null,
    amount double precision not null,
    status text not null check (status in ('reserved','booked','cancelled')),
    payment_method text,
    created_at text not null,
    paid_at text
);
CREATE TABLE IF NOT EXISTS payments (
    id bigint generated by default as identity primary key,
    subject text not null,
    subject_id bigint not null,
    amount double precision not null,
    method text not null,
    details text not null default '{}',
    status text not null default 'captured',
    created_at text not null
);
CREATE TABLE IF NOT EXISTS food_orders (
    id bigint generated by default as identity primary key,
    code text not null unique,
    user_id bigint not null references users(id),
    hotel_id bigint not null references hotels(id),
    type text not null check (type in ('online','offline')),
    items text not null,
    total double precision not null,
    status text not null,
    address text,
    payment_method text,
    paid integer not null default 0,
    dining_date text,
    dining_time text,
    guests integer,
    created_at text not null
);
CREATE TABLE IF NOT EXISTS favourites (
    user_id bigint not null references users(id) on delete cascade,
    hotel_id bigint not null references hotels(id) on delete cascade,
    primary key (user_id, hotel_id)
);
CREATE INDEX IF NOT EXISTS idx_res_user ON reservations(user_id);
CREATE INDEX IF NOT EXISTS idx_res_room ON reservations(room_type_id);
CREATE INDEX IF NOT EXISTS idx_ord_user ON food_orders(user_id);
"""


def use_postgres() -> bool:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url.startswith(("postgres://", "postgresql://"))


class Database:
    """Small OOP gateway around SQLite or Postgres.

    Postgres connections are pooled per-process (warm serverless containers
    reuse them); SQLite opens one short-lived connection per call.
    """

    _pools: dict = {}
    _pool_lock = threading.Lock()

    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.url = os.environ.get("DATABASE_URL", "").strip()
        self.dialect = "postgres" if self.url.startswith(("postgres://", "postgresql://")) else "sqlite"

    @classmethod
    def _pool(cls, url: str):
        with cls._pool_lock:
            pool = cls._pools.get(url)
            if pool is None:
                import psycopg2
                from psycopg2 import pool as pg_pool
                from psycopg2.extras import RealDictCursor

                pool = pg_pool.ThreadedConnectionPool(
                    1, 8, url,
                    connect_timeout=12,
                    cursor_factory=RealDictCursor,
                    keepalives=1,
                    keepalives_idle=30,
                    keepalives_interval=10,
                    keepalives_count=5,
                )
                cls._pools[url] = pool
            return pool

    @contextmanager
    def connection(self):
        if self.dialect == "postgres":
            pool = self._pool(self.url)
            conn = pool.getconn()
            try:
                yield conn
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise
            finally:
                pool.putconn(conn)
            return
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def all(self, sql: str, params=()) -> list[dict]:
        with self.connection() as c:
            if self.dialect == "postgres":
                cur = c.cursor()
                cur.execute(self._sql(sql), params)
                return [dict(r) for r in cur.fetchall()]
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        with self.connection() as c:
            if self.dialect == "postgres":
                cur = c.cursor()
                cur.execute(self._sql(sql), params)
                row = cur.fetchone()
                return dict(row) if row else None
            row = c.execute(sql, params).fetchone()
            return dict(row) if row else None

    def execute(self, sql: str, params=()) -> int:
        """Run a write statement; returns the new row id for INSERTs, else rowcount."""
        with self.connection() as c:
            if self.dialect == "postgres":
                cur = c.cursor()
                stmt = self._sql(sql).rstrip().rstrip(";")
                if stmt.upper().startswith("INSERT") and " RETURNING " not in stmt.upper():
                    stmt += " RETURNING id"
                    cur.execute(stmt, params)
                    row = cur.fetchone()
                    return int(row["id"]) if row else 0
                cur.execute(stmt, params)
                return cur.rowcount
            cur = c.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def init_schema(self) -> None:
        with self.connection() as c:
            if self.dialect == "postgres":
                with c.cursor() as cur:
                    cur.execute(SCHEMA_PG)
                return
            c.executescript(SCHEMA)


# --------------------------------------------------------------------------
# File I/O helpers
# --------------------------------------------------------------------------
class AuditLog:
    """Append-only JSONL audit trail written to disk after every action."""

    @staticmethod
    def write(event: str, **data) -> None:
        record = {"ts": now_iso(), "event": event, **data}
        try:
            os.makedirs(_AUDIT_DIR, exist_ok=True)
            with open(AUDIT_LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # the audit trail must never break a request (e.g. read-only FS)


class Password:
    """PBKDF2 password hashing (no external dependencies)."""

    ITERATIONS = 120_000

    @staticmethod
    def hash(password: str) -> tuple[str, str]:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), Password.ITERATIONS
        ).hex()
        return salt, digest

    @staticmethod
    def verify(password: str, salt: str, expected: str) -> bool:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), Password.ITERATIONS
        ).hex()
        return secrets.compare_digest(digest, expected)


# --------------------------------------------------------------------------
# User
# --------------------------------------------------------------------------
class User:
    def __init__(self, db: Database, row: dict):
        self.db = db
        self.id = row["id"]
        self.name = row["name"]
        self.email = row["email"]
        self.phone = row.get("phone") or ""
        self.created_at = row.get("created_at", "")

    # -- factories --------------------------------------------------------
    @classmethod
    def register(cls, db, name, email, password, phone="") -> "User":
        email = (email or "").strip().lower()
        name = (name or "").strip()
        if not name:
            raise ValueError("Please enter your name.")
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Please enter a valid email address.")
        if len(password or "") < 6:
            raise ValueError("Password must be at least 6 characters long.")
        if db.one("SELECT id FROM users WHERE email = ?", (email,)):
            raise ValueError("An account with this email already exists.")
        salt, digest = Password.hash(password)
        uid = db.execute(
            "INSERT INTO users (name, email, password_hash, salt, phone, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (name, email, digest, salt, (phone or "").strip(), now_iso()),
        )
        AuditLog.write("user.register", user_id=uid, email=email)
        return cls.by_id(db, uid)

    @classmethod
    def authenticate(cls, db, email, password) -> "User":
        row = db.one(
            "SELECT * FROM users WHERE email = ?",
            ((email or "").strip().lower(),),
        )
        if not row or not Password.verify(password or "", row["salt"], row["password_hash"]):
            raise ValueError("Email or password is incorrect.")
        return cls(db, row)

    @classmethod
    def by_id(cls, db, user_id) -> "User | None":
        row = db.one("SELECT * FROM users WHERE id = ?", (user_id,))
        return cls(db, row) if row else None

    # -- actions ----------------------------------------------------------
    def update_profile(self, name=None, phone=None) -> None:
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("Name cannot be empty.")
            self.db.execute("UPDATE users SET name = ? WHERE id = ?", (name, self.id))
            self.name = name
        if phone is not None:
            self.db.execute("UPDATE users SET phone = ? WHERE id = ?", (phone.strip(), self.id))
            self.phone = phone.strip()

    def stats(self) -> dict:
        res = self.db.one(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN status='reserved'  THEN 1 ELSE 0 END),0) AS reserved,
                      COALESCE(SUM(CASE WHEN status='booked'    THEN 1 ELSE 0 END),0) AS booked,
                      COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END),0) AS cancelled
               FROM reservations WHERE user_id = ?""",
            (self.id,),
        )
        orders = self.db.one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total),0) AS spent FROM food_orders WHERE user_id = ?",
            (self.id,),
        )
        favs = self.db.one(
            "SELECT COUNT(*) AS n FROM favourites WHERE user_id = ?", (self.id,)
        )
        out = dict(res)
        out["orders"] = orders["n"]
        out["spent"] = round(orders["spent"], 2)
        out["favourites"] = favs["n"]
        return out

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "created_at": self.created_at,
        }


# --------------------------------------------------------------------------
# Hotel & room categories
# --------------------------------------------------------------------------
class Hotel:
    FIELDS = (
        "id", "slug", "name", "city", "category", "tagline", "address", "phone",
        "email", "hours", "rating", "reviews", "dine_label", "image",
        "description", "about", "menu_key",
    )

    def __init__(self, db: Database, row: dict):
        self.db = db
        for key in self.FIELDS:
            setattr(self, key, row.get(key))
        self._occ = None
        self._min_price = None
        self._totals = None

    # -- factories --------------------------------------------------------
    @classmethod
    def by_slug(cls, db, slug: str) -> "Hotel":
        row = db.one("SELECT * FROM hotels WHERE slug = ?", (slug,))
        if not row:
            raise ValueError("Hotel not found.")
        return cls(db, row)

    @classmethod
    def search(cls, db, q: str = "", category: str = "") -> list["Hotel"]:
        sql, conds, params = "SELECT * FROM hotels", [], []
        q = (q or "").strip().lower()
        if q:
            like = f"%{q}%"
            conds.append(
                "(LOWER(name) LIKE ? OR LOWER(city) LIKE ? OR LOWER(tagline) LIKE ?"
                " OR LOWER(category) LIKE ? OR LOWER(address) LIKE ?)"
            )
            params.extend([like] * 5)
        if category and category != "All":
            conds.append("category = ?")
            params.append(category)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY rating DESC, name ASC"
        return [cls(db, r) for r in db.all(sql, tuple(params))]

    @classmethod
    def search_enriched(cls, db, q: str = "", category: str = "") -> list["Hotel"]:
        """Search with min_price + occupancy totals in ONE round trip."""
        where, params = [], []
        q = (q or "").strip().lower()
        if q:
            like = f"%{q}%"
            where.append(
                "(LOWER(h.name) LIKE ? OR LOWER(h.city) LIKE ? OR LOWER(h.tagline) LIKE ?"
                " OR LOWER(h.category) LIKE ? OR LOWER(h.address) LIKE ?)"
            )
            params.extend([like] * 5)
        if category and category != "All":
            where.append("h.category = ?")
            params.append(category)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        rows = db.all(
            f"""SELECT h.*,
                      (SELECT MIN(rt.price) FROM room_types rt WHERE rt.hotel_id = h.id) AS min_price,
                      (SELECT COALESCE(SUM(rt.total), 0) FROM room_types rt WHERE rt.hotel_id = h.id) AS rooms_total,
                      (SELECT COALESCE(SUM(r.rooms), 0) FROM reservations r
                         JOIN room_types rt ON rt.id = r.room_type_id
                        WHERE rt.hotel_id = h.id AND r.status = 'reserved') AS n_reserved,
                      (SELECT COALESCE(SUM(r.rooms), 0) FROM reservations r
                         JOIN room_types rt ON rt.id = r.room_type_id
                        WHERE rt.hotel_id = h.id AND r.status = 'booked')   AS n_booked
               FROM hotels h{clause}
               ORDER BY h.rating DESC, h.name ASC""",
            tuple(params),
        )
        out = []
        for row in rows:
            h = cls(db, row)
            total = int(row.get("rooms_total") or 0)
            reserved = int(row.get("n_reserved") or 0)
            booked = int(row.get("n_booked") or 0)
            h._min_price = row.get("min_price")
            h._totals = {
                "total": total,
                "reserved": reserved,
                "booked": booked,
                "available": max(total - reserved - booked, 0),
            }
            out.append(h)
        return out

    @staticmethod
    def all(db) -> list["Hotel"]:
        return [Hotel(db, r) for r in db.all("SELECT * FROM hotels ORDER BY name")]

    # -- occupancy ("manage") --------------------------------------------
    def occupancy(self) -> list[dict]:
        """Per room category: total / reserved / booked / available rooms."""
        if self._occ is not None:
            return self._occ
        rows = self.db.all(
            """SELECT rt.id, rt.name, rt.price, rt.total,
                      COALESCE(SUM(CASE WHEN r.status='reserved' THEN r.rooms ELSE 0 END),0) AS reserved,
                      COALESCE(SUM(CASE WHEN r.status='booked'   THEN r.rooms ELSE 0 END),0) AS booked
               FROM room_types rt
               LEFT JOIN reservations r
                      ON r.room_type_id = rt.id AND r.status IN ('reserved','booked')
               WHERE rt.hotel_id = ?
               GROUP BY rt.id
               ORDER BY rt.price ASC""",
            (self.id,),
        )
        out = []
        for row in rows:
            row["available"] = max(row["total"] - row["reserved"] - row["booked"], 0)
            out.append(row)
        self._occ = out
        return self._occ

    def totals(self) -> dict:
        if self._totals is not None:
            return self._totals
        occ = self.occupancy()
        self._totals = {
            "total": sum(o["total"] for o in occ),
            "reserved": sum(o["reserved"] for o in occ),
            "booked": sum(o["booked"] for o in occ),
            "available": sum(o["available"] for o in occ),
        }
        return self._totals

    def rooms(self) -> list[dict]:
        rows = self.db.all(
            "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY price ASC", (self.id,)
        )
        occ = {o["id"]: o for o in self.occupancy()}
        rooms = []
        for row in rows:
            o = occ[row["id"]]
            rooms.append({
                "id": row["id"],
                "name": row["name"],
                "price": row["price"],
                "total": row["total"],
                "images": json.loads(row["images"]),
                "desc": row["description"],
                "amenities": json.loads(row["amenities"]),
                "reserved": o["reserved"],
                "booked": o["booked"],
                "available": o["available"],
            })
        return rooms

    def min_price(self):
        if self._min_price is None:
            self._min_price = self.db.one(
                "SELECT MIN(price) AS p FROM room_types WHERE hotel_id = ?", (self.id,)
            )["p"]
        return self._min_price

    def to_dict(self, with_rooms: bool = False) -> dict:
        d = {k: getattr(self, k) for k in self.FIELDS}
        d["min_price"] = self.min_price()
        d["occupancy_totals"] = self.totals()
        if with_rooms:
            d["rooms"] = self.rooms()
        return d

    @staticmethod
    def summary(db) -> list[dict]:
        """Every hotel with per-category counts — the all-user manage board."""
        where = [
            "SELECT h.slug, h.name, h.city, h.image, rt.id AS room_type_id, rt.name AS type,",
            "rt.total,",
            "COALESCE(SUM(r.rooms) FILTER (WHERE r.status='reserved'), 0) AS reserved,",
            "COALESCE(SUM(r.rooms) FILTER (WHERE r.status='booked'), 0) AS booked",
            "FROM hotels h",
            "JOIN room_types rt ON rt.hotel_id = h.id",
            "LEFT JOIN reservations r ON r.room_type_id = rt.id AND r.status IN ('reserved','booked')",
            "GROUP BY h.slug, h.name, h.city, h.image, rt.id, rt.name, rt.price, rt.total",
            "ORDER BY h.name ASC, rt.price ASC",
        ]
        rows = db.all("\n".join(where))
        out, by_slug = [], {}
        for row in rows:
            key = row["slug"]
            entry = by_slug.get(key)
            if entry is None:
                entry = {
                    "slug": row["slug"],
                    "name": row["name"],
                    "city": row["city"],
                    "image": row["image"],
                    "types": [],
                    "totals": {"total": 0, "reserved": 0, "booked": 0, "available": 0},
                }
                by_slug[key] = entry
                out.append(entry)
            available = max(row["total"] - row["reserved"] - row["booked"], 0)
            entry["types"].append({
                "id": row["room_type_id"],
                "name": row["type"],
                "total": row["total"],
                "reserved": row["reserved"],
                "booked": row["booked"],
                "available": available,
            })
            t = entry["totals"]
            t["total"] += row["total"]
            t["reserved"] += row["reserved"]
            t["booked"] += row["booked"]
            t["available"] += available
        return out


# --------------------------------------------------------------------------
# Payment (simulation only — no real money moves)
# --------------------------------------------------------------------------
class Payment:
    METHODS = {"card", "upi", "wallet"}

    @staticmethod
    def capture(method: str, payload: dict) -> dict:
        """Validate a simulated payment and return its display details."""
        method = (method or "").lower()
        if method not in Payment.METHODS:
            raise ValueError("Choose card, UPI or wallet as the payment method.")
        if method == "card":
            number = re.sub(r"\D", "", str(payload.get("number", "")))
            name = str(payload.get("name") or "").strip()
            expiry = str(payload.get("expiry") or "").strip()
            cvv = re.sub(r"\D", "", str(payload.get("cvv", "")))
            if len(number) < 13 or not _luhn(number):
                raise ValueError(
                    "That card number doesn't look right. Tip: use 4242 4242 4242 4242."
                )
            if not name:
                raise ValueError("Enter the name printed on the card.")
            try:
                mm_s, yy_s = expiry.split("/")
                mm, yy = int(mm_s), int(yy_s)
                if not 1 <= mm <= 12 or yy < 0:
                    raise ValueError
                last = calendar.monthrange(2000 + yy, mm)[1]
                if dt.date(2000 + yy, mm, last) < dt.date.today():
                    raise ValueError
            except Exception:
                raise ValueError("Card expiry must be a valid future date in MM/YY.")
            if len(cvv) not in (3, 4):
                raise ValueError("CVV must be 3 or 4 digits.")
            brand = "Visa" if number.startswith("4") else "Card"
            return {"brand": brand, "last4": number[-4:], "name": name}
        if method == "upi":
            vpa = str(payload.get("upi") or "").strip().lower()
            if "@" not in vpa or len(vpa) < 5 or " " in vpa:
                raise ValueError("Enter a valid UPI ID, e.g. yourname@okhdfc.")
            return {"vpa": vpa}
        return {"wallet": str(payload.get("wallet") or "Vilas Wallet")}

    @staticmethod
    def record(db, subject: str, subject_id: int, amount: float, method: str, details: dict) -> int:
        return db.execute(
            """INSERT INTO payments (subject, subject_id, amount, method, details, status, created_at)
               VALUES (?,?,?,?,?, 'captured', ?)""",
            (subject, subject_id, amount, method, json.dumps(details), now_iso()),
        )


# --------------------------------------------------------------------------
# Reservation lifecycle
# --------------------------------------------------------------------------
class Reservation:
    DETAIL_SQL = """
        SELECT r.*,
               h.name AS hotel_name, h.slug AS hotel_slug, h.image AS hotel_image,
               h.city AS hotel_city, h.address AS hotel_address, h.phone AS hotel_phone,
               rt.name AS room_name, rt.images AS room_images, rt.price AS room_price
        FROM reservations r
        JOIN hotels h ON h.id = r.hotel_id
        JOIN room_types rt ON rt.id = r.room_type_id
    """

    def __init__(self, db: Database, row: dict):
        self.db = db
        for k, v in row.items():
            setattr(self, k, v)

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _shape(row: dict) -> dict:
        row = dict(row)
        imgs = json.loads(row.pop("room_images", "[]"))
        row["room_image"] = imgs[0] if imgs else None
        return row

    @classmethod
    def by_id(cls, db, rid: int) -> "Reservation | None":
        row = db.one(cls.DETAIL_SQL + " WHERE r.id = ?", (rid,))
        return cls(db, row) if row else None

    @classmethod
    def by_code(cls, db, code: str) -> "Reservation":
        row = db.one(cls.DETAIL_SQL + " WHERE r.code = ?", (code,))
        if not row:
            raise ValueError("Booking not found.")
        return cls(db, row)

    @staticmethod
    def for_user(db, user_id: int) -> list[dict]:
        rows = db.all(
            Reservation.DETAIL_SQL + " WHERE r.user_id = ? ORDER BY r.created_at DESC",
            (user_id,),
        )
        return [Reservation._shape(r) for r in rows]

    def detail(self) -> dict:
        row = self.db.one(self.DETAIL_SQL + " WHERE r.id = ?", (self.id,))
        return self._shape(row)

    # -- lifecycle --------------------------------------------------------
    @classmethod
    def create(
        cls,
        db,
        user_id: int,
        hotel_slug: str,
        room_type_id,
        check_in: str,
        check_out: str,
        guests=1,
        rooms=1,
    ) -> "Reservation":
        hotel = Hotel.by_slug(db, hotel_slug)
        room = db.one(
            "SELECT * FROM room_types WHERE id = ? AND hotel_id = ?",
            (int(room_type_id), hotel.id),
        )
        if not room:
            raise ValueError("Please choose a valid room category.")
        try:
            d_in = dt.date.fromisoformat(str(check_in))
            d_out = dt.date.fromisoformat(str(check_out))
        except (TypeError, ValueError):
            raise ValueError("Please choose valid check-in and check-out dates.")
        if d_out <= d_in:
            raise ValueError("Check-out must be after check-in.")
        if d_in < dt.date.today():
            raise ValueError("Check-in cannot be in the past.")
        if (d_out - d_in).days > 30:
            raise ValueError("Stays can be booked for up to 30 nights.")
        guests, rooms = int(guests or 1), int(rooms or 1)
        if guests < 1 or guests > 12:
            raise ValueError("Guests must be between 1 and 12.")
        if not 1 <= rooms <= 4:
            raise ValueError("You can reserve up to 4 rooms at once.")

        occ = next((o for o in hotel.occupancy() if o["id"] == int(room_type_id)), None)
        free = occ["available"] if occ else 0
        if free < rooms:
            raise ValueError(
                f"Only {free} room(s) left in {room['name']} — try other dates or category."
            )

        nights = (d_out - d_in).days
        amount = round(float(room["price"]) * rooms * nights, 2)
        code = cls._new_code(db)
        rid = db.execute(
            """INSERT INTO reservations
               (code, user_id, hotel_id, room_type_id, check_in, check_out,
                guests, rooms, nights, amount, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,'reserved',?)""",
            (code, user_id, hotel.id, room["id"], str(check_in), str(check_out),
             guests, rooms, nights, amount, now_iso()),
        )
        AuditLog.write(
            "reservation.held", code=code, user_id=user_id, hotel=hotel.slug,
            room_type=room["name"], rooms=rooms, nights=nights,
            amount=amount, check_in=str(check_in), check_out=str(check_out),
        )
        return cls.by_id(db, rid)

    @staticmethod
    def _new_code(db) -> str:
        for _ in range(25):
            code = "VIL-" + secrets.token_hex(3).upper()
            if not db.one("SELECT 1 FROM reservations WHERE code = ?", (code,)):
                return code
        raise ValueError("Could not allocate a booking code — please retry.")

    def pay(self, method: str, payload: dict) -> dict:
        """Simulated payment: reserved -> booked."""
        if self.status == "cancelled":
            raise ValueError("This reservation was cancelled — book again to continue.")
        if self.status == "booked":
            raise ValueError("This reservation is already paid and confirmed.")
        details = Payment.capture(method, (payload or {}).get("card") or payload or {})
        updated = self.db.execute(
            """UPDATE reservations SET status = 'booked', payment_method = ?, paid_at = ?
               WHERE id = ? AND status = 'reserved'""",
            (method, now_iso(), self.id),
        )
        if not updated:
            raise ValueError("This reservation was just updated — refresh and try again.")
        Payment.record(self.db, "reservation", self.id, float(self.amount), method, details)
        AuditLog.write("reservation.paid", code=self.code, method=method, amount=self.amount)
        return self.detail()

    def cancel(self) -> dict:
        """Cancel: releases the held/confirmed rooms immediately."""
        if self.status == "cancelled":
            raise ValueError("This reservation is already cancelled.")
        was_booked = self.status == "booked"
        self.db.execute(
            "UPDATE reservations SET status = 'cancelled' WHERE id = ?", (self.id,)
        )
        AuditLog.write(
            "reservation.cancelled", code=self.code, amount=self.amount,
            refund_simulated=was_booked,
        )
        return self.detail()


# --------------------------------------------------------------------------
# Food ordering — online (delivery + payment) / offline (dine-in date & time)
# --------------------------------------------------------------------------
class FoodOrder:
    @staticmethod
    def menu(menu_key: str = "default") -> list[dict]:
        """Read the menu file from disk on every call (live File I/O)."""
        with open(MENU_SEED, encoding="utf-8") as fh:
            menus = json.load(fh)
        return menus.get(menu_key) or menus["default"]

    @classmethod
    def _new_code(cls, db) -> str:
        for _ in range(25):
            code = "ORD-" + secrets.token_hex(3).upper()
            if not db.one("SELECT 1 FROM food_orders WHERE code = ?", (code,)):
                return code
        raise ValueError("Could not allocate an order code — please retry.")

    @classmethod
    def create(cls, db, user_id: int, hotel_slug: str, payload: dict) -> dict:
        hotel = Hotel.by_slug(db, hotel_slug)
        otype = (payload or {}).get("type")
        if otype not in ("online", "offline"):
            raise ValueError("Choose delivery (online) or dine-in (offline).")

        raw_items = payload.get("items") or []
        if not raw_items:
            raise ValueError("Your cart is empty — add a dish first.")
        menu = {m["id"]: m for m in cls.menu(hotel.menu_key)}
        items, total = [], 0.0
        for raw in raw_items:
            mid = str(raw.get("id", ""))
            qty = int(raw.get("qty", 0))
            if mid not in menu:
                raise ValueError("An item in your cart is no longer on the menu.")
            if not 1 <= qty <= 20:
                raise ValueError("Quantity per dish must be between 1 and 20.")
            m = menu[mid]
            items.append({"id": mid, "name": m["name"], "price": float(m["price"]), "qty": qty})
            total += float(m["price"]) * qty
        total = round(total, 2)

        if otype == "online":
            address = str(payload.get("address") or "").strip()
            if len(address) < 8:
                raise ValueError("Please enter a full delivery address.")
            method = (payload.get("payment_method") or "card").lower()
            details = Payment.capture(method, payload.get("card") or payload)
            code = cls._new_code(db)
            oid = db.execute(
                """INSERT INTO food_orders
                   (code, user_id, hotel_id, type, items, total, status, address,
                    payment_method, paid, created_at)
                   VALUES (?,?,?,?,?,?,'confirmed',?,?,1,?)""",
                (code, user_id, hotel.id, "online", json.dumps(items), total,
                 address, method, now_iso()),
            )
            Payment.record(db, "order", oid, total, method, details)
            AuditLog.write("order.online", code=code, user_id=user_id,
                           hotel=hotel.slug, total=total, method=method)
            return cls.by_id(db, oid)

        # offline — dine-in: date + time of the visit, paid at the restaurant
        dining_date = payload.get("dining_date")
        dining_time = str(payload.get("dining_time") or "").strip()
        try:
            d = dt.date.fromisoformat(str(dining_date))
        except (TypeError, ValueError):
            raise ValueError("Choose the date you will dine in.")
        if d < dt.date.today():
            raise ValueError("Dine-in date cannot be in the past.")
        if not re.match(r"^\d{2}:\d{2}$", dining_time):
            raise ValueError("Choose a time for your table (HH:MM).")
        guests = int(payload.get("guests") or 2)
        if not 1 <= guests <= 30:
            raise ValueError("Guest count must be between 1 and 30.")
        code = cls._new_code(db)
        oid = db.execute(
            """INSERT INTO food_orders
               (code, user_id, hotel_id, type, items, total, status,
                payment_method, paid, dining_date, dining_time, guests, created_at)
               VALUES (?,?,?,?,?,?,'confirmed','at-restaurant',0,?,?,?,?)""",
            (code, user_id, hotel.id, "offline", json.dumps(items), total,
             str(dining_date), dining_time, guests, now_iso()),
        )
        AuditLog.write("order.offline", code=code, user_id=user_id, hotel=hotel.slug,
                       total=total, dining_date=str(dining_date), dining_time=dining_time)
        return cls.by_id(db, oid)

    DETAIL_SQL = """
        SELECT o.*, h.name AS hotel_name, h.slug AS hotel_slug, h.image AS hotel_image,
               h.city AS hotel_city
        FROM food_orders o JOIN hotels h ON h.id = o.hotel_id
    """

    @classmethod
    def by_id(cls, db, oid: int) -> dict:
        row = db.one(cls.DETAIL_SQL + " WHERE o.id = ?", (oid,))
        if not row:
            raise ValueError("Order not found.")
        row["items"] = json.loads(row["items"])
        return row

    @staticmethod
    def for_user(db, user_id: int) -> list[dict]:
        rows = db.all(
            FoodOrder.DETAIL_SQL + " WHERE o.user_id = ? ORDER BY o.created_at DESC",
            (user_id,),
        )
        for row in rows:
            row["items"] = json.loads(row["items"])
        return rows


# --------------------------------------------------------------------------
# Favourites & export
# --------------------------------------------------------------------------
class Favourite:
    @staticmethod
    def add(db, user_id: int, slug: str) -> None:
        hotel = Hotel.by_slug(db, slug)
        conflict = "ON CONFLICT DO NOTHING" if db.dialect == "postgres" else ""
        verb = "INSERT INTO" if db.dialect == "postgres" else "INSERT OR IGNORE INTO"
        db.execute(
            f"{verb} favourites (user_id, hotel_id) VALUES (?,?) {conflict}".strip(),
            (user_id, hotel.id),
        )
        AuditLog.write("favourite.add", user_id=user_id, hotel=slug)

    @staticmethod
    def remove(db, user_id: int, slug: str) -> None:
        hotel = Hotel.by_slug(db, slug)
        db.execute(
            "DELETE FROM favourites WHERE user_id = ? AND hotel_id = ?",
            (user_id, hotel.id),
        )
        AuditLog.write("favourite.remove", user_id=user_id, hotel=slug)

    @staticmethod
    def slugs(db, user_id: int) -> set:
        rows = db.all(
            "SELECT h.slug FROM favourites f JOIN hotels h ON h.id = f.hotel_id"
            " WHERE f.user_id = ?",
            (user_id,),
        )
        return {r["slug"] for r in rows}

    @staticmethod
    def list(db, user_id: int) -> list[dict]:
        rows = db.all(
            """SELECT h.* FROM favourites f JOIN hotels h ON h.id = f.hotel_id
               WHERE f.user_id = ? ORDER BY h.name""",
            (user_id,),
        )
        out = []
        for row in rows:
            h = Hotel(db, row)
            out.append(h.to_dict())
        return out


class Exporter:
    """Writes a guest's bookings to exports/*.json (File I/O) and returns them."""

    @staticmethod
    def bookings(db, user: User) -> dict:
        data = {
            "exported_at": now_iso(),
            "guest": user.to_dict(),
            "stats": user.stats(),
            "reservations": Reservation.for_user(db, user.id),
            "orders": FoodOrder.for_user(db, user.id),
        }
        os.makedirs(EXPORT_DIR, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"bookings-{user.id}-{stamp}.json"
        with open(os.path.join(EXPORT_DIR, filename), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        AuditLog.write("export.bookings", user_id=user.id, file=filename)
        data["file"] = filename
        return data
