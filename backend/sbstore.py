"""Supabase-backed stores for the three features delegated to Supabase:
favourites, food orders, and the matching stat counters.

Identity model
--------------
Supabase Auth users are identified by a UUID (``sb_uid``, kept in the Flask
session). Reservations / payments / occupancy / hotels stay in SQLite, whose
integer ``users.id`` the rest of the app already uses. Login therefore does a
bridge: on every Supabase sign-in we find-or-create the SQLite user with the
same email (keeping their booking history) and keep ``user_id`` in the session
alongside ``sb_uid``.

Hotel metadata for Supabase-side rows is resolved from the SQLite catalogue
(which itself is seeded from ``data/hotels.json``), so the API response shape
is byte-compatible with the previous SQLite implementation.
"""

import datetime as dt
import json
import re
import secrets

from . import supabase_client as sb
from .models import AuditLog, Hotel, Payment, now_iso

FAVOURITES = "vilas_favourites"
ORDERS = "vilas_food_orders"


def enabled() -> bool:
    return sb.is_configured()


# --------------------------------------------------------------------------
# Identity bridge (Supabase Auth user  <->  SQLite users row)
# --------------------------------------------------------------------------
def ensure_sqlite_user(db, sb_user: dict) -> int:
    """Return the integer SQLite user id for a Supabase user (find or create)."""
    email = (sb_user.get("email") or "").strip().lower()
    meta = sb_user.get("user_metadata") or {}
    name = (meta.get("name") or email.split("@")[0] or "Guest").strip()
    phone = (meta.get("phone") or "").strip()
    row = db.one("SELECT id FROM users WHERE email = ?", (email,))
    if row:
        return row["id"]
    placeholder = secrets.token_hex(32)  # password hash never used in Supabase mode
    return db.execute(
        "INSERT INTO users (name, email, password_hash, salt, phone, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (name, email, placeholder, placeholder, phone, now_iso()),
    )


# --------------------------------------------------------------------------
# Favourites
# --------------------------------------------------------------------------
def fav_add(db, uid, slug):
    Hotel.by_slug(db, slug)  # raises ValueError for unknown hotels
    sb.insert(FAVOURITES, [{"user_id": uid, "hotel_slug": slug}],
              on_conflict="user_id,hotel_slug")
    AuditLog.write("favourite.add", user_id=uid, hotel=slug, store="supabase")


def fav_remove(uid, slug):
    sb.delete(FAVOURITES, {"user_id": f"eq.{uid}", "hotel_slug": f"eq.{slug}"})
    AuditLog.write("favourite.remove", user_id=uid, hotel=slug, store="supabase")


def fav_slugs(uid):
    rows = sb.select(FAVOURITES, {
        "user_id": f"eq.{uid}",
        "select": "hotel_slug",
        "order": "created_at.asc",
    })
    return [r["hotel_slug"] for r in rows or []]


def fav_list(db, uid):
    out = []
    for slug in set(fav_slugs(uid)):
        try:
            out.append(Hotel.by_slug(db, slug).to_dict())
        except ValueError:
            continue  # hotel no longer in the catalogue
    out.sort(key=lambda h: h["name"])
    return out


def fav_count(uid):
    rows = sb.select(FAVOURITES, {"user_id": f"eq.{uid}", "select": "hotel_slug"})
    return len(rows or [])


# --------------------------------------------------------------------------
# Food orders
# --------------------------------------------------------------------------
def _hotel(db, slug):
    return Hotel.by_slug(db, slug)  # raises ValueError when unknown


def _enrich(db, slug):
    try:
        h = _hotel(db, slug)
    except ValueError:
        return {"hotel_name": slug, "hotel_slug": slug, "hotel_image": "", "hotel_city": ""}
    return {
        "hotel_name": h.name,
        "hotel_slug": h.slug,
        "hotel_image": h.image,
        "hotel_city": h.city,
    }


def _shape(db, row):
    row = dict(row)
    items = row.get("items")
    if isinstance(items, str):
        items = json.loads(items or "[]")
    row["items"] = items or []
    row["total"] = float(row.get("total") or 0)
    row["paid"] = bool(row.get("paid"))
    if row.get("created_at"):
        row["created_at"] = str(row["created_at"])
    row.update(_enrich(db, row.get("hotel_slug") or ""))
    return row


def _new_code():
    for _ in range(25):
        code = "ORD-" + secrets.token_hex(3).upper()
        existing = sb.select(ORDERS, {"code": f"eq.{code}", "select": "code"})
        if not existing:
            return code
    raise ValueError("Could not allocate an order code — please retry.")


def _validate_items(hotel_menu_key, raw_items):
    menu = {m["id"]: m for m in _menu(hotel_menu_key)}
    items, total = [], 0.0
    for raw in raw_items or []:
        mid = str((raw or {}).get("id", ""))
        qty = int((raw or {}).get("qty", 0))
        if mid not in menu:
            raise ValueError("An item in your cart is no longer on the menu.")
        if not 1 <= qty <= 20:
            raise ValueError("Quantity per dish must be between 1 and 20.")
        m = menu[mid]
        items.append({"id": mid, "name": m["name"], "price": float(m["price"]), "qty": qty})
        total += float(m["price"]) * qty
    if not items:
        raise ValueError("Your cart is empty — add a dish first.")
    return items, round(total, 2)


def _menu(menu_key):
    from .models import FoodOrder  # reused so the menu stays file-backed
    return FoodOrder.menu(menu_key or "default")


def order_create(db, uid, hotel_slug, payload):
    payload = payload or {}
    hotel = _hotel(db, hotel_slug)
    otype = payload.get("type")
    if otype not in ("online", "offline"):
        raise ValueError("Choose delivery (online) or dine-in (offline).")

    items, total = _validate_items(hotel.menu_key, payload.get("items"))
    base = {
        "code": _new_code(),
        "user_id": uid,
        "hotel_slug": hotel.slug,
        "type": otype,
        "items": items,
        "total": total,
        "status": "confirmed",
    }

    if otype == "online":
        address = str(payload.get("address") or "").strip()
        if len(address) < 8:
            raise ValueError("Please enter a full delivery address.")
        method = (payload.get("payment_method") or "card").lower()
        payment = Payment.capture(method, payload.get("card") or payload)
        base.update({
            "address": address,
            "payment_method": method,
            "paid": True,
        })
        row = base
        inserted = sb.insert(ORDERS, [row])
        AuditLog.write("order.online", code=row["code"], user_id=uid,
                       hotel=hotel.slug, total=total, method=method,
                       auth=(payment or {}).get("auth_code"), store="supabase")
    else:
        dining_date = payload.get("dining_date")
        dining_time = str(payload.get("dining_time") or "").strip()
        try:
            day = dt.date.fromisoformat(str(dining_date))
        except (TypeError, ValueError):
            raise ValueError("Choose the date you will dine in.")
        if day < dt.date.today():
            raise ValueError("Dine-in date cannot be in the past.")
        if not re.match(r"^\d{2}:\d{2}$", dining_time):
            raise ValueError("Choose a time for your table (HH:MM).")
        guests = int(payload.get("guests") or 2)
        if not 1 <= guests <= 30:
            raise ValueError("Guest count must be between 1 and 30.")
        base.update({
            "dining_date": str(dining_date),
            "dining_time": dining_time,
            "guests": guests,
            "payment_method": "at-restaurant",
            "paid": False,
        })
        row = base
        inserted = sb.insert(ORDERS, [row])
        AuditLog.write("order.offline", code=row["code"], user_id=uid,
                       hotel=hotel.slug, total=total, dining_date=str(dining_date),
                       dining_time=dining_time, store="supabase")

    created = (inserted or [row])[0]
    return _shape(db, created)


def orders_for_user(db, uid):
    rows = sb.select(ORDERS, {
        "user_id": f"eq.{uid}",
        "select": "*",
        "order": "created_at.desc",
    })
    return [_shape(db, row) for row in rows or []]


def orders_stats(db, uid):
    rows = sb.select(ORDERS, {"user_id": f"eq.{uid}", "select": "total"})
    totals = [float(r.get("total") or 0) for r in rows or []]
    return {"orders": len(totals), "spent": round(sum(totals), 2)}


def merge_stats(db, stats, uid):
    """Overlay Supabase-backed counters onto the SQLite reservation stats."""
    orders = orders_stats(db, uid)
    stats["orders"] = orders["orders"]
    stats["spent"] = orders["spent"]
    stats["favourites"] = fav_count(uid)
    return stats
