"""Thin Supabase REST client — stdlib only (no external dependencies).

Used for the three features delegated to Supabase:
  * Auth          — GoTrue (email + password, admin signup, token grant)
  * Favourites    — PostgREST table ``vilas_favourites`` (RLS: owner-only)
  * Food orders   — PostgREST table ``vilas_food_orders`` (RLS: owner-only)

Configuration comes from the environment (or a local ``.env`` — see README):
  SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_KEY

The service key is used server-side only and bypasses RLS; the anon key is used
for the password grant. Neither key is ever sent to the browser.
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request


class SupabaseError(Exception):
    """Raised when Supabase rejects a call. ``message`` is user-safe."""


def _cfg():
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON_KEY") or ""
    service = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    return url, anon, service


def is_configured() -> bool:
    url, anon, service = _cfg()
    return bool(url and anon and service)


def _request(method, path, *, token, apikey, params=None, body=None, headers=None):
    url, _, _ = _cfg()
    qs = f"?{urllib.parse.urlencode(params)}" if params else ""
    req = urllib.request.Request(url + path + qs, method=method)
    req.add_header("apikey", apikey)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=12) as resp:
            raw = resp.read().decode("utf-8") or "null"
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "ignore") or "{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"message": raw}
        return exc.code, payload
    except urllib.error.URLError as exc:
        raise SupabaseError(
            "Supabase is unreachable — check SUPABASE_URL and your network."
        ) from exc


def _error_message(payload, default):
    if isinstance(payload, dict):
        for key in ("msg", "message", "error_description", "error"):
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("message") or value.get("msg")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return default


# --------------------------------------------------------------------------
# Auth (GoTrue)
# --------------------------------------------------------------------------
def auth_signup(name, email, password, phone=""):
    """Create an email-confirmed user (service key). Returns the user object."""
    _, _, service = _cfg()
    code, payload = _request(
        "POST", "/auth/v1/admin/users", token=service, apikey=service,
        body={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"name": name, "phone": phone},
        },
    )
    if code >= 400:
        msg = _error_message(payload, "Could not create the account.")
        low = msg.lower()
        if "already" in low or "exists" in low or "duplicate" in low:
            msg = "An account with this email already exists — try signing in."
        raise SupabaseError(msg)
    return payload


def auth_login(email, password):
    """Password grant (anon key). Returns the token response incl. ``user``."""
    _, anon, _ = _cfg()
    code, payload = _request(
        "POST", "/auth/v1/token", token=anon, apikey=anon,
        params={"grant_type": "password"},
        body={"email": email, "password": password},
    )
    if code >= 400:
        raise SupabaseError("Invalid email or password.")
    if not isinstance(payload, dict) or "user" not in payload:
        raise SupabaseError("Supabase returned an unexpected sign-in response.")
    return payload


# --------------------------------------------------------------------------
# PostgREST
# --------------------------------------------------------------------------
def rest(method, table, *, params=None, body=None, prefer=None):
    _, _, service = _cfg()
    headers = {"Prefer": prefer} if prefer else None
    code, payload = _request(
        method, f"/rest/v1/{table}", token=service, apikey=service,
        params=params, body=body, headers=headers,
    )
    if code >= 400:
        raise SupabaseError(_error_message(payload, f"Supabase {table} error ({code})."))
    return payload


def select(table, params):
    return rest("GET", table, params=params)


def insert(table, rows, on_conflict=None):
    prefer = "return=representation,resolution=ignore-duplicates"
    params = {"on_conflict": on_conflict} if on_conflict else None
    return rest("POST", table, params=params, body=rows, prefer=prefer)


def delete(table, params):
    return rest("DELETE", table, params=params, prefer="return=minimal")
