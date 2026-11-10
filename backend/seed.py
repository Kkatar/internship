"""
First-run seeding: reads data/hotels.json (File I/O) into SQLite, creates the
demo accounts, and fills the board with a believable mix of reserved/booked
rooms so the occupancy ("manage") view is alive from the first page load.
"""
from __future__ import annotations

import datetime as dt
import json

from .models import HOTELS_SEED, AuditLog, Database, FoodOrder, Hotel, User, Reservation

# (booked, reserved) room counts seeded per hotel & category
OCCUPANCY_PLAN = {
    "tandoor-corner": {"Standard": (4, 2), "Deluxe": (3, 1), "Suite": (1, 1)},
    "shahu-palace": {"Standard": (3, 2), "Deluxe": (2, 1), "Suite": (1, 1)},
    "panhala-fort-retreat": {"Standard": (5, 3), "Deluxe": (4, 2), "Suite": (2, 1)},
    "the-riverside-inn": {"Standard": (6, 2), "Deluxe": (3, 2), "Suite": (2, 1)},
    "vasant-villa-resort": {"Standard": (2, 1), "Deluxe": (2, 0), "Suite": (1, 1)},
}

DEMO_ACCOUNTS = [
    ("Demo Guest", "demo@vilas.com", "demo123", "+91 98220 11001"),
    ("Arjun Deshmukh", "arjun@example.com", "password123", "+91 98220 11002"),
    ("Priya Kulkarni", "priya@example.com", "password123", "+91 98220 11003"),
]


def _seed_hotels(db: Database) -> None:
    if db.one("SELECT id FROM hotels LIMIT 1"):
        return
    with open(HOTELS_SEED, encoding="utf-8") as fh:
        data = json.load(fh)
    for h in data["hotels"]:
        hid = db.execute(
            """INSERT INTO hotels
               (slug, name, city, category, tagline, address, phone, email, hours,
                rating, reviews, dine_label, image, description, about, menu_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                h["slug"], h["name"], h["city"], h["category"], h["tagline"],
                h["address"], h["phone"], h["email"], h["hours"],
                h["rating"], h["reviews"], h["dine_label"], h["image"],
                h["description"], h["about"], h.get("menu_key", "default"),
            ),
        )
        for rt in h["room_types"]:
            db.execute(
                """INSERT INTO room_types
                   (hotel_id, name, price, total, images, description, amenities)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    hid, rt["name"], rt["price"], rt["total"],
                    json.dumps(rt["images"]), rt["desc"], json.dumps(rt["amenities"]),
                ),
            )
    AuditLog.write("seed.hotels", count=len(data["hotels"]))


def _seed_accounts(db: Database) -> None:
    for name, email, password, phone in DEMO_ACCOUNTS:
        if not db.one("SELECT id FROM users WHERE email = ?", (email,)):
            User.register(db, name, email, password, phone)


def _uid(db: Database, email: str) -> int:
    return db.one("SELECT id FROM users WHERE email = ?", (email,))["id"]


def _seed_reservations(db: Database) -> None:
    if db.one("SELECT id FROM reservations LIMIT 1"):
        return
    today = dt.date.today()
    emails = [a[1] for a in DEMO_ACCOUNTS]
    n = 0
    for slug, plan in OCCUPANCY_PLAN.items():
        hotel = Hotel.by_slug(db, slug)
        for rt in db.all(
            "SELECT * FROM room_types WHERE hotel_id = ? ORDER BY price", (hotel.id,)
        ):
            booked, reserved = plan.get(rt["name"], (0, 0))
            for status, count in (("booked", booked), ("reserved", reserved)):
                for _ in range(count):
                    check_in = today + dt.timedelta(days=4 + (n % 25))
                    check_out = check_in + dt.timedelta(days=2)
                    user_id = _uid(db, emails[n % len(emails)])
                    res = Reservation.create(
                        db, user_id, slug, rt["id"],
                        check_in.isoformat(), check_out.isoformat(),
                        guests=2, rooms=1,
                    )
                    if status == "booked":
                        db.execute(
                            """UPDATE reservations
                               SET status='booked', payment_method='card',
                                   paid_at=? WHERE id=?""",
                            (res.created_at, res.id),
                        )
                    n += 1

    # The demo guest gets a ready-made story: one pending, one paid, one cancelled
    demo = _uid(db, "demo@vilas.com")
    tandoor = Hotel.by_slug(db, "tandoor-corner")
    rooms = {r["name"]: r["id"] for r in db.all(
        "SELECT id, name FROM room_types WHERE hotel_id = ?", (tandoor.id,)
    )}
    pending = Reservation.create(
        db, demo, "tandoor-corner", rooms["Deluxe"],
        (today + dt.timedelta(days=7)).isoformat(),
        (today + dt.timedelta(days=9)).isoformat(), guests=2, rooms=1,
    )
    paid = Reservation.create(
        db, demo, "tandoor-corner", rooms["Standard"],
        (today + dt.timedelta(days=30)).isoformat(),
        (today + dt.timedelta(days=32)).isoformat(), guests=3, rooms=1,
    )
    db.execute(
        """UPDATE reservations SET status='booked', payment_method='upi', paid_at=?
           WHERE id=?""",
        (paid.created_at, paid.id),
    )
    # one cancelled booking to show the full lifecycle
    panhala = Hotel.by_slug(db, "panhala-fort-retreat")
    suite_id = db.one(
        "SELECT id FROM room_types WHERE hotel_id=? AND name='Suite'", (panhala.id,)
    )["id"]
    check_in = today + dt.timedelta(days=15)
    db.execute(
        """INSERT INTO reservations
           (code, user_id, hotel_id, room_type_id, check_in, check_out, guests,
            rooms, nights, amount, status, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,'cancelled',?)""",
        (
            "VIL-CANCEL1", demo, panhala.id, suite_id,
            check_in.isoformat(), (check_in + dt.timedelta(days=3)).isoformat(),
            2, 1, 3, 9800 * 3, dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    AuditLog.write("seed.reservations", generated=n, demo=3)


def _seed_orders(db: Database) -> None:
    if db.one("SELECT id FROM food_orders LIMIT 1"):
        return
    demo = _uid(db, "demo@vilas.com")
    priya = _uid(db, "priya@example.com")

    # paid delivery order (history)
    order = FoodOrder.create(db, demo, "tandoor-corner", {
        "type": "online",
        "items": [{"id": "tc1", "qty": 1}, {"id": "tc4", "qty": 2}, {"id": "tc8", "qty": 2}],
        "address": "52, Tarabai Park, Kolhapur 416005",
        "payment_method": "card",
        "card": {"number": "4242424242424242", "name": "Demo Guest",
                 "expiry": "12/28", "cvv": "123"},
    })
    db.execute(
        "UPDATE food_orders SET status='delivered', created_at=? WHERE id=?",
        ((dt.datetime.now() - dt.timedelta(days=2)).isoformat(timespec="seconds"),
         order["id"]),
    )

    # upcoming dine-in reservation (date + time, paid at the restaurant)
    FoodOrder.create(db, demo, "tandoor-corner", {
        "type": "offline",
        "items": [{"id": "tc6", "qty": 1}, {"id": "tc7", "qty": 1},
                  {"id": "tc4", "qty": 3}, {"id": "tc8", "qty": 4}],
        "dining_date": (dt.date.today() + dt.timedelta(days=6)).isoformat(),
        "dining_time": "20:00",
        "guests": 4,
    })

    FoodOrder.create(db, priya, "vasant-villa-resort", {
        "type": "online",
        "items": [{"id": "df1", "qty": 1}, {"id": "df4", "qty": 2}],
        "address": "9, Shivaji Peth, Kolhapur 416001",
        "payment_method": "upi",
        "upi": "priya@okaxis",
    })
    AuditLog.write("seed.orders", count=3)


def seed(db: Database) -> None:
    _seed_hotels(db)
    _seed_accounts(db)
    _seed_reservations(db)
    _seed_orders(db)
