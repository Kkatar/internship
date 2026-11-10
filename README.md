# Vilas — Stays & Tables

A classy, professional hotel reservation webapp inspired by [qissa.co.uk](https://www.qissa.co.uk/), built for **Task 4: Hotel Reservation System**.

Search stays, hold a room without paying, watch the live **reserved vs booked** board, pay when you're ready, cancel anytime — and order the feast online (delivery, paid now) or offline (dine-in, pick a date & time).

## Features

- **Search** hotels by name/city with check-in/out dates, guests and category filters (Heritage, Resort, Riverside, Business)
- **5 stays** seeded, incl. **Tandoor Corner**, Kolhapur — 4.1★ · 1,363 Google reviews · ₹200–400 · Mughlai · Crusher Chauk, MH SH 116 · real menu prices (Butter Chicken ₹485, Tandoori Chicken ₹360, Chicken Tangdi Kebab ₹440, Garlic Naan ₹110)
- **Room categorization** — Standard / Deluxe / Suite, each with photo galleries (3D coverflow) and amenities
- **Reserved vs Booked** live counts **visible to every visitor** — reserved = held, unpaid · booked = paid & confirmed · cancelled rooms return to the pool instantly
- **Reservations** — hold a room → simulated payment (card with Luhn check / UPI / wallet) → confirmation with `VIL-XXXXXX` code → cancel anytime
- **Food ordering** — online: delivery address + payment method · offline: dine-in date & time + party size (`ORD-XXXXXX`)
- **Profile** — bookings ledger (booked/reserved/spent/orders), pay or cancel inline, booking details, export bookings as JSON, food orders tab
- **Favourites** — hearts on every stay
- **Auth** — email + password. When `SUPABASE_*` is configured, accounts live in **Supabase Auth** (else PBKDF2 in SQLite). Demo account: `demo@vilas.com` / `demo123` (pre-loaded with reservations in every state + orders in Supabase)
- **Classy 3D scroll experience** — parallax hero, scroll-progress bar, pinned 3D fan, scroll-reveals, counters, marquees (Playfair Display + Jost, all assets local)

## Stack

- **Backend:** Python + Flask, OOP domain layer (`backend/models.py` — `Database`, `User`, `Hotel`, `RoomType`, `Reservation`, `Payment`, `FoodOrder`, `Favourite`, `Exporter`, `AuditLog`)
- **Storage split:** SQLite (`data/vilas.db`) keeps the booking engine — hotels, reservations, payments, occupancy. **Supabase** keeps **auth (Supabase Auth), favourites and food orders** (Postgres tables `vilas_favourites` / `vilas_food_orders`, RLS owner-only) via a stdlib-only REST client (`backend/supabase_client.py`, `backend/sbstore.py`). When the `SUPABASE_*` variables are absent the app falls back to the SQLite implementation, so a fresh clone still runs out of the box.
- **File I/O:** `data/hotels.json` + `data/menu.json` seeds, `data/audit.jsonl` append-only audit log, `exports/*.json` booking downloads
- **Frontend:** Jinja templates + vanilla JS, local fonts & images (offline-safe)

## Connect Supabase (login · favourites · orders)

1. Create a project at supabase.com (or use the connector).
2. Apply the migration (or run the SQL): tables `public.vilas_favourites(user_id uuid → auth.users, hotel_slug text, created_at, PK(user_id, hotel_slug))` and `public.vilas_food_orders(id uuid PK, code text UNIQUE, user_id uuid → auth.users, hotel_slug text, type text, items jsonb, total numeric, status text, address text, payment_method text, paid boolean, dining_date date, dining_time text, guests int, created_at timestamptz)`, both with RLS enabled and owner policies (`auth.uid() = user_id`).
3. Copy `.env.example` to `.env` and fill in:
   - `SUPABASE_URL` — e.g. `https://<ref>.supabase.co`
   - `SUPABASE_ANON_KEY` — anon/publishable key (password grant)
   - `SUPABASE_SERVICE_KEY` — service_role key; **server-side only**, bypasses RLS; never commit it (`.env` is gitignored)
4. Demo users (`demo@vilas.com`/`demo123`, `arjun@vilas.com`/`password123`, `priya@vilas.com`/`password123`) exist in Supabase Auth for this deployment; reservations bridging is by email, so SQLite booking history is preserved.
5. Restart the app — `/api/auth/login` now returns `{"store":"supabase"}`, and `/api/me` returns order/favourite counters from Postgres.

Row Level Security is enabled on both tables; the app accesses them with the service key server-side, scoped by the authenticated UUID.

## Run locally

```bash
pip install -r requirements.txt
python3 backend/seed.py          # create + seed data/vilas.db (idempotent)
python3 app.py                   # serves http://0.0.0.0:5000
```

Configuration via environment (optional):

```bash
export SECRET_KEY="your-random-string"
```

Demo logins (also seeded): `demo@vilas.com / demo123` · `arjun@vilas.com / password123` · `priya@vilas.com / password123`

## Project layout

```
app.py                Flask app — pages + JSON API (/api/*)
backend/models.py     OOP domain layer + SQLite schema
backend/seed.py       idempotent seed (hotels, demo users, occupancy plan)
templates/            Jinja pages (home, hotel, profile, favourites, auth)
static/css|js|img|fonts/  design system, 3D-scroll JS, local assets
data/hotels.json      stays + room categories seed
data/menu.json        menu seed (Tandoor Corner + default)
```

## Notes

- **Payment is simulated** — the card form validates format/Luhn/expiry/CVV and records a fake capture. No real money moves.
- Room/occupancy counts update live across the UI after every reservation, payment and cancellation.
