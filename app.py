"""
Vilas — Hotel Reservation System
================================
Flask app: server-rendered pages + JSON API.

Pages:  / (search) · /hotel/<slug> (rooms, availability, dining, about, contact)
        /profile (bookings & orders) · /favourites · /auth (sign in / register)

Storage & OOP live in backend/ (SQLite + File I/O). No real payments happen —
all card/UPI/wallet flows are simulations.
"""
from __future__ import annotations

import os
from functools import wraps

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
)

from backend.models import (
    DB_PATH,
    EXPORT_DIR,
    Database,
    Exporter,
    FoodOrder,
    Favourite,
    Hotel,
    Reservation,
    User,
)
from backend.seed import seed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("SECRET_KEY", "vilas-dev-secret-change-me")

db = Database(DB_PATH)
db.init_schema()
seed(db)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def current_user() -> User | None:
    uid = session.get("uid")
    return User.by_id(db, uid) if uid else None


def unauth():
    return jsonify({"error": "Please sign in to continue."}), 401


def api(fn):
    """Uniform JSON error handling for the API surface."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except Exception:
            app.logger.exception("API failure")
            return jsonify({"error": "Something went wrong on our side."}), 500
    return wrapper


def json_body() -> dict:
    return request.get_json(force=True, silent=True) or {}


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------
@app.route("/")
def page_home():
    return render_template("index.html", active="home")


@app.route("/hotel/<slug>")
def page_hotel(slug):
    try:
        hotel = Hotel.by_slug(db, slug)
    except ValueError:
        abort(404)
    return render_template("hotel.html", active="hotel", slug=slug, hotel_name=hotel.name)


@app.route("/profile")
def page_profile():
    return render_template("profile.html", active="profile")


@app.route("/favourites")
def page_favourites():
    return render_template("favourites.html", active="favourites")


@app.route("/auth")
def page_auth():
    return render_template("auth.html", active="auth")


@app.route("/signout")
def signout():
    session.clear()
    return redirect("/")


# --------------------------------------------------------------------------
# Auth API
# --------------------------------------------------------------------------
@app.post("/api/auth/register")
@api
def api_register():
    p = json_body()
    user = User.register(db, p.get("name"), p.get("email"), p.get("password"), p.get("phone", ""))
    session["uid"] = user.id
    return jsonify({"user": user.to_dict()}), 201


@app.post("/api/auth/login")
@api
def api_login():
    p = json_body()
    user = User.authenticate(db, p.get("email"), p.get("password"))
    session["uid"] = user.id
    return jsonify({"user": user.to_dict()})


@app.post("/api/auth/logout")
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    user = current_user()
    return jsonify({
        "user": user.to_dict() if user else None,
        "stats": user.stats() if user else None,
    })


@app.put("/api/profile")
@api
def api_update_profile():
    user = current_user()
    if not user:
        return unauth()
    p = json_body()
    user.update_profile(p.get("name"), p.get("phone"))
    return jsonify({"user": user.to_dict()})


# --------------------------------------------------------------------------
# Hotels / search / occupancy
# --------------------------------------------------------------------------
@app.get("/api/hotels")
@api
def api_hotels():
    user = current_user()
    favs = Favourite.slugs(db, user.id) if user else set()
    hotels = []
    for h in Hotel.search(db, request.args.get("q", ""), request.args.get("category", "")):
        d = h.to_dict()
        d["favourite"] = h.slug in favs
        hotels.append(d)
    categories = ["All"] + [
        r["category"] for r in db.all("SELECT DISTINCT category FROM hotels ORDER BY category")
    ]
    return jsonify({"hotels": hotels, "categories": categories})


@app.get("/api/hotels/<slug>")
@api
def api_hotel_detail(slug):
    h = Hotel.by_slug(db, slug)
    user = current_user()
    data = h.to_dict(with_rooms=True)
    data["favourite"] = bool(user and slug in Favourite.slugs(db, user.id))
    return jsonify(data)


@app.get("/api/hotels/<slug>/menu")
@api
def api_hotel_menu(slug):
    h = Hotel.by_slug(db, slug)
    return jsonify({
        "name": h.name,
        "dine_label": h.dine_label,
        "hours": h.hours,
        "phone": h.phone,
        "menu": FoodOrder.menu(h.menu_key),
    })


@app.get("/api/occupancy")
@api
def api_occupancy():
    """Live reserved-vs-booked board — open to every visitor."""
    return jsonify({"hotels": Hotel.summary(db)})


# --------------------------------------------------------------------------
# Reservations
# --------------------------------------------------------------------------
@app.post("/api/reservations")
@api
def api_create_reservation():
    user = current_user()
    if not user:
        return unauth()
    p = json_body()
    res = Reservation.create(
        db, user.id, p.get("hotel_slug"), p.get("room_type_id"),
        p.get("check_in"), p.get("check_out"), p.get("guests"), p.get("rooms"),
    )
    return jsonify({"reservation": res.detail()}), 201


@app.get("/api/reservations")
@api
def api_my_reservations():
    user = current_user()
    if not user:
        return unauth()
    return jsonify({"reservations": Reservation.for_user(db, user.id)})


@app.post("/api/reservations/<code>/pay")
@api
def api_pay_reservation(code):
    user = current_user()
    if not user:
        return unauth()
    p = json_body()
    res = Reservation.by_code(db, code)
    if res.user_id != user.id:
        return jsonify({"error": "This booking belongs to another guest."}), 403
    return jsonify({"reservation": res.pay(p.get("method", "card"), p)})


@app.post("/api/reservations/<code>/cancel")
@api
def api_cancel_reservation(code):
    user = current_user()
    if not user:
        return unauth()
    res = Reservation.by_code(db, code)
    if res.user_id != user.id:
        return jsonify({"error": "This booking belongs to another guest."}), 403
    return jsonify({"reservation": res.cancel()})


# --------------------------------------------------------------------------
# Favourites
# --------------------------------------------------------------------------
@app.get("/api/favourites")
@api
def api_favourites():
    user = current_user()
    if not user:
        return unauth()
    return jsonify({"hotels": Favourite.list(db, user.id)})


@app.post("/api/favourites")
@api
def api_add_favourite():
    user = current_user()
    if not user:
        return unauth()
    Favourite.add(db, user.id, json_body().get("slug", ""))
    return jsonify({"ok": True})


@app.delete("/api/favourites/<slug>")
@api
def api_remove_favourite(slug):
    user = current_user()
    if not user:
        return unauth()
    Favourite.remove(db, user.id, slug)
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# Food orders
# --------------------------------------------------------------------------
@app.post("/api/orders")
@api
def api_create_order():
    user = current_user()
    if not user:
        return unauth()
    p = json_body()
    order = FoodOrder.create(db, user.id, p.get("hotel_slug", ""), p)
    return jsonify({"order": order}), 201


@app.get("/api/orders")
@api
def api_my_orders():
    user = current_user()
    if not user:
        return unauth()
    return jsonify({"orders": FoodOrder.for_user(db, user.id)})


# --------------------------------------------------------------------------
# Export (File I/O on the server, JSON download for the guest)
# --------------------------------------------------------------------------
@app.get("/api/export/bookings")
@api
def api_export_bookings():
    user = current_user()
    if not user:
        return unauth()
    data = Exporter.bookings(db, user)
    path = os.path.join(EXPORT_DIR, data["file"])
    return send_file(path, as_attachment=True, download_name=data["file"],
                     mimetype="application/json")


# --------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found."}), 404
    return render_template("index.html", active="home"), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
