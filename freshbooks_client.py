"""Thin HTTP client for the FreshBooks Accounting API + OAuth2 helpers.

Same "fail()-dict + ClientFail exception + generic request() helper" shape
as xero_client.py / quickbooks_client.py, adapted for FreshBooks' own
quirks:

1. Almost every accounting resource is nested under
   /accounting/account/{account_id}/<service>/<resource> -- account_id is
   resolved once via the identity endpoint and stored per connection,
   exactly like Xero's tenant_id.
2. List endpoints wrap results under a nested key, e.g.
   {"response": {"result": {"invoices": [...]}}}.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx


def parse_fields_json(fields_json: str) -> dict | None:
    """Parse a fields_json chat-tool string into a dict, or None if invalid."""
    try:
        data = json.loads(fields_json)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None

AUTHORIZE_URL = "https://auth.freshbooks.com/oauth/authorize"
TOKEN_URL = "https://api.freshbooks.com/auth/oauth/token"
IDENTITY_URL = "https://api.freshbooks.com/auth/api/v1/users/me"
API_BASE = "https://api.freshbooks.com"
SCOPE = "user:profile:read invoices:read invoices:write clients:read clients:write expenses:read expenses:write items:read items:write estimates:read estimates:write payments:read payments:write"

FB_NOT_CONNECTED = "FRESHBOOKS_NOT_CONNECTED"
FB_UNAUTHORIZED = "FRESHBOOKS_UNAUTHORIZED"
FB_FORBIDDEN = "FRESHBOOKS_FORBIDDEN"
FB_NOT_FOUND = "FRESHBOOKS_NOT_FOUND"
FB_RATE_LIMITED = "FRESHBOOKS_RATE_LIMITED"
FB_BACKEND_ERROR = "FRESHBOOKS_BACKEND_ERROR"
FB_VALIDATION_FAILED = "FRESHBOOKS_VALIDATION_FAILED"
FB_RESPONSE_UNEXPECTED = "FRESHBOOKS_RESPONSE_UNEXPECTED"

_MESSAGES = {
    FB_NOT_CONNECTED: "No FreshBooks connection found. Connect FreshBooks first.",
    FB_UNAUTHORIZED: "FreshBooks rejected the request as unauthorized -- the connection may need to be reconnected.",
    FB_FORBIDDEN: "FreshBooks denied access to this resource for the current account/scopes.",
    FB_NOT_FOUND: "That FreshBooks record was not found.",
    FB_RATE_LIMITED: "FreshBooks rate-limited this request. Try again shortly.",
    FB_BACKEND_ERROR: "FreshBooks' API returned an error.",
    FB_VALIDATION_FAILED: "FreshBooks rejected the request as invalid.",
    FB_RESPONSE_UNEXPECTED: "FreshBooks returned an unexpected response shape.",
}


class ClientFail(Exception):
    def __init__(self, payload: dict):
        self.payload = payload
        super().__init__(payload.get("detail", ""))


def fail(code: str, detail: str = "") -> dict:
    return {
        "ok": False,
        "error_code": code,
        "error": _MESSAGES.get(code, "FreshBooks request failed."),
        "detail": detail,
    }


def build_authorize_url(client_id: str, redirect_uri: str, state: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPE,
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code_for_token(ctx, client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    body = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, json=body, headers={"Content-Type": "application/json"})
    if resp.status_code != 200:
        raise ClientFail(fail(FB_UNAUTHORIZED, resp.text[:500]))
    return resp.json()


async def refresh_access_token(ctx, client_id: str, client_secret: str, refresh_token: str) -> dict:
    body = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(TOKEN_URL, json=body, headers={"Content-Type": "application/json"})
    if resp.status_code != 200:
        raise ClientFail(fail(FB_UNAUTHORIZED, resp.text[:500]))
    return resp.json()


async def fetch_identity(ctx, access_token: str) -> dict:
    """GET the identity endpoint -- returns the businesses/accounts this
    OAuth grant covers, each with its own account_id."""
    headers = {"Authorization": f"Bearer {access_token}", "Api-Version": "alpha"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(IDENTITY_URL, headers=headers)
    if resp.status_code != 200:
        raise ClientFail(fail(FB_UNAUTHORIZED, resp.text[:500]))
    return resp.json()


def _headers(access_token: str) -> dict:
    return {
        "Authorization": f"Bearer {access_token}",
        "Api-Version": "alpha",
        "Content-Type": "application/json",
    }


def _check_status(resp: httpx.Response, action: str) -> Any:
    if resp.status_code == 401:
        raise ClientFail(fail(FB_UNAUTHORIZED, f"{action}: {resp.text[:300]}"))
    if resp.status_code == 403:
        raise ClientFail(fail(FB_FORBIDDEN, f"{action}: {resp.text[:300]}"))
    if resp.status_code == 404:
        raise ClientFail(fail(FB_NOT_FOUND, f"{action}: {resp.text[:300]}"))
    if resp.status_code == 429:
        raise ClientFail(fail(FB_RATE_LIMITED, f"{action}: {resp.text[:300]}"))
    if resp.status_code == 400:
        raise ClientFail(fail(FB_VALIDATION_FAILED, f"{action}: {resp.text[:500]}"))
    if resp.status_code >= 500:
        raise ClientFail(fail(FB_BACKEND_ERROR, f"{action}: {resp.text[:300]}"))
    if resp.status_code >= 400:
        raise ClientFail(fail(FB_BACKEND_ERROR, f"{action}: {resp.status_code} {resp.text[:300]}"))
    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        raise ClientFail(fail(FB_RESPONSE_UNEXPECTED, f"{action}: non-JSON response"))


async def request(ctx, conn: dict, account_id: str, method: str, path: str, *, params: dict | None = None,
                   json_body: Any = None, action: str = "request") -> Any:
    access_token = conn.get("access_token", "")
    if not access_token:
        raise ClientFail(fail(FB_NOT_CONNECTED))
    url = f"{API_BASE}{path.format(account_id=account_id)}"
    headers = _headers(access_token)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, headers=headers, params=params, json=json_body)
    return _check_status(resp, action)


# ──────────────────────────────────────────────────────────────────────────
# Entity path/wrapper-key registry -- FreshBooks nests everything under
# /accounting/account/{account_id}/<service>/<resource>, wrapped in
# {"response": {"result": {"<key>": ...}}}.
# ──────────────────────────────────────────────────────────────────────────

_ENTITY_REGISTRY: dict[str, tuple[str, str, str, str]] = {
    # entity_name: (list path template, singular result key, plural result key, id field)
    "clients": ("/accounting/account/{account_id}/users/clients", "client", "clients", "id"),
    "invoices": ("/accounting/account/{account_id}/invoices/invoices", "invoice", "invoices", "invoiceid"),
    "expenses": ("/accounting/account/{account_id}/expenses/expenses", "expense", "expenses", "id"),
    "estimates": ("/accounting/account/{account_id}/estimates/estimates", "estimate", "estimates", "id"),
    "items": ("/accounting/account/{account_id}/items/items", "item", "items", "id"),
    "payments": ("/accounting/account/{account_id}/payments/payments", "payment", "payments", "id"),
    "taxes": ("/accounting/account/{account_id}/taxes/taxes", "tax", "taxes", "id"),
    "staffs": ("/accounting/account/{account_id}/users/staffs", "staff", "staffs", "id"),
}


def entity_registry_entry(entity: str) -> tuple[str, str, str, str] | None:
    return _ENTITY_REGISTRY.get(entity)


def known_entities() -> list[str]:
    return sorted(_ENTITY_REGISTRY.keys())


def unwrap_list(data: dict, plural_key: str) -> list[dict]:
    """Unwrap FreshBooks' {"response": {"result": {"<plural>": [...]}}} shape."""
    if not isinstance(data, dict):
        return []
    result = (data.get("response") or {}).get("result") or {}
    rows = result.get(plural_key, [])
    return rows if isinstance(rows, list) else []


def unwrap_single(data: dict, singular_key: str) -> dict:
    if not isinstance(data, dict):
        return {}
    result = (data.get("response") or {}).get("result") or {}
    rec = result.get(singular_key, {})
    return rec if isinstance(rec, dict) else {}
