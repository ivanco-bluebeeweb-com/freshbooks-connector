"""Connection management for FreshBooks Connector: connect/disconnect/list,
OAuth callback webhook, proactive token refresh -- same shape as
Xero Connector's handlers_connection.py (JSON array under one secret, plus
a pending-connections secret keyed by OAuth `state`).

WHY THE FLOW IS SPLIT connect_freshbooks (tool) + handle_oauth_callback
(webhook), SAME REASONING AS XERO/QUICKBOOKS CONNECTOR: FreshBooks only
offers Authorization Code Grant -- there is no way to validate credentials
without a real user browser redirect and consent.

FRESHBOOKS-SPECIFIC: right after the token exchange we call GET
auth/api/v1/users/me to discover every business account this OAuth grant
now covers (business_memberships[].business.account_id), and store the
full list on the connection record. Entity/report tools accept an
optional account_id override, defaulting to the first account.
"""
from __future__ import annotations

import json
import time as _time
import uuid

from imperal_sdk import ActionResult

import freshbooks_client as fc
from app import ext, chat
from schemas import (
    NoParams,
    ConnectFreshbooksParams, ConnectFreshbooksResult,
    ProviderConnection, ProviderConnectionList, ProviderAccount,
    DisconnectFreshbooksParams, DeleteResult,
)

_SECRET_NAME = "freshbooks_connections"
_PENDING_SECRET = "freshbooks_pending"


async def _load_connections(ctx) -> list[dict]:
    raw = await ctx.secrets.get(_SECRET_NAME)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


async def _save_connections(ctx, connections: list[dict]) -> None:
    await ctx.secrets.set(_SECRET_NAME, json.dumps(connections))


async def resolve_connection(ctx, connection_id: str = "") -> dict | None:
    connections = await _load_connections(ctx)
    if not connections:
        return None
    if connection_id:
        for c in connections:
            if c.get("id") == connection_id:
                return c
        return None
    return connections[0]


def resolve_account_id(conn: dict, account_id: str = "") -> str:
    if account_id:
        return account_id
    return conn.get("default_account_id", "")



async def ensure_fresh_token(ctx, conn: dict) -> dict:
    """Proactively refresh the access_token if it's within 60s of expiry
    (FreshBooks access tokens live 12 hours)."""
    expires_at = int(conn.get("expires_at", 0) or 0)
    if expires_at and expires_at - int(_time.time()) > 60:
        return conn
    refresh_token = conn.get("refresh_token", "")
    if not refresh_token:
        return conn
    try:
        result = await fc.refresh_access_token(ctx, conn["client_id"], conn["client_secret"], refresh_token)
    except fc.ClientFail:
        return conn
    conn["access_token"] = result["access_token"]
    conn["refresh_token"] = result.get("refresh_token", refresh_token)
    conn["expires_at"] = int(_time.time()) + int(result.get("expires_in", 43200))
    connections = await _load_connections(ctx)
    for i, c in enumerate(connections):
        if c.get("id") == conn.get("id"):
            connections[i] = conn
            break
    await _save_connections(ctx, connections)
    return conn


def _connection_to_entity(c: dict) -> ProviderConnection:
    return ProviderConnection(
        id=c.get("id", ""),
        label=c.get("label") or "FreshBooks connection",
        default_account_id=c.get("default_account_id", ""),
        accounts=[ProviderAccount(**a) for a in c.get("accounts", [])],
    )


async def resolve_or_error(ctx, connection_id: str = "", account_id: str = ""):
    conn = await resolve_connection(ctx, connection_id)
    if not conn:
        return None, None, ActionResult.error(
            "No FreshBooks connection found. Connect one with connect_freshbooks first "
            "and open the returned authorize_url to finish the one-time login.",
            code="FRESHBOOKS_NOT_CONNECTED",
        )
    conn = await ensure_fresh_token(ctx, conn)
    resolved_account = resolve_account_id(conn, account_id)
    if not resolved_account:
        return None, None, ActionResult.error(
            "This FreshBooks connection has no business account on record. Reconnect with connect_freshbooks.",
            code="FRESHBOOKS_NOT_CONNECTED",
        )
    return conn, resolved_account, None


@chat.function(
    "connect_freshbooks",
    "Start connecting your FreshBooks account(s): register your FreshBooks app's Client ID/Client Secret, "
    "then get back a one-time browser authorize_url. Open it, sign in with FreshBooks, pick the business(es) "
    "to grant access to, and approve -- FreshBooks redirects back here automatically and the connection "
    "finishes itself, no further action needed.",
    action_type="write",
    chain_callable=True,
    data_model=ConnectFreshbooksResult,
    event="freshbooks-connector.connect",
    effects=["freshbooks.connection.pending"],
)
async def connect_freshbooks(ctx, params: ConnectFreshbooksParams) -> ActionResult:
    """Register the user's own FreshBooks app credentials and hand back a
    one-time browser authorize_url."""
    if not params.client_id.strip() or not params.client_secret.strip():
        return ActionResult.error(
            "Both the FreshBooks app's Client ID and Client Secret are required.",
            code="FRESHBOOKS_VALIDATION_FAILED",
        )
    pending_id = str(uuid.uuid4())
    redirect_uri = params.redirect_uri.strip() or ctx.webhook_url("callback")
    pending = {
        "id": pending_id,
        "label": params.label.strip(),
        "client_id": params.client_id.strip(),
        "client_secret": params.client_secret.strip(),
        "redirect_uri": redirect_uri,
    }
    all_pending = await _load_pending(ctx)
    all_pending.append(pending)
    await _save_pending(ctx, all_pending)
    authorize_url = fc.build_authorize_url(params.client_id.strip(), redirect_uri, pending_id)
    return ActionResult.success(ConnectFreshbooksResult(authorize_url=authorize_url, pending_id=pending_id), summary="Freshbooks connected.")


@ext.webhook("callback")
async def handle_oauth_callback(ctx, headers, body, query_params):
    """FreshBooks' OAuth redirect target: exchanges `code` for tokens,
    discovers every business account this grant covers via the identity
    endpoint, and finishes the pending connection started by
    connect_freshbooks."""
    error = query_params.get("error")
    state = query_params.get("state", "")
    code = query_params.get("code", "")
    if error:
        return {"status_code": 200, "body": f"FreshBooks authorization failed: {error}. Close this tab and try connect_freshbooks again."}
    if not state or not code:
        return {"status_code": 400, "body": "Missing code/state."}
    all_pending = await _load_pending(ctx)
    pending = next((p for p in all_pending if p.get("id") == state), None)
    if not pending:
        return {"status_code": 400, "body": "Unknown or expired connection request. Run connect_freshbooks again."}
    try:
        result = await fc.exchange_code_for_token(
            ctx, pending["client_id"], pending["client_secret"], code, pending["redirect_uri"],
        )
    except fc.ClientFail as exc:
        return {"status_code": 200, "body": f"Could not finish connecting FreshBooks: {exc.payload.get('error', 'unknown error')}. Close this tab and try connect_freshbooks again."}
    access_token = result["access_token"]
    try:
        identity = await fc.fetch_identity(ctx, access_token)
    except fc.ClientFail:
        identity = {}
    memberships = (identity.get("response", {}).get("business_memberships", []) or [])
    accounts = [
        {
            "account_id": m.get("business", {}).get("account_id", ""),
            "name": m.get("business", {}).get("name", ""),
            "business_uuid": m.get("business", {}).get("id", ""),
        }
        for m in memberships
        if m.get("business", {}).get("account_id")
    ]
    conn = {
        "id": str(uuid.uuid4()),
        "label": pending.get("label", ""),
        "client_id": pending["client_id"],
        "client_secret": pending["client_secret"],
        "access_token": access_token,
        "refresh_token": result["refresh_token"],
        "expires_at": int(_time.time()) + int(result.get("expires_in", 43200)),
        "accounts": accounts,
        "default_account_id": accounts[0]["account_id"] if accounts else "",
    }
    all_pending = [p for p in all_pending if p.get("id") != state]
    await _save_pending(ctx, all_pending)
    connections = await _load_connections(ctx)
    connections.append(conn)
    await _save_connections(ctx, connections)
    return {"status_code": 200, "body": "FreshBooks connected! You can close this tab and go back to Imperal."}


@chat.function(
    "list_connections",
    "List the connected FreshBooks accounts.",
    action_type="read", chain_callable=True, data_model=ProviderConnectionList,
)
async def list_connections(ctx, params: NoParams) -> ActionResult:
    """List the connected FreshBooks accounts."""
    connections = await _load_connections(ctx)
    return ActionResult.success(ProviderConnectionList(connections=[_connection_to_entity(c) for c in connections]), summary="Connections listed.")


async def _load_pending(ctx) -> list[dict]:
    raw = await ctx.secrets.get(_PENDING_SECRET)
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return data if isinstance(data, list) else []


async def _save_pending(ctx, pending: list[dict]) -> None:
    await ctx.secrets.set(_PENDING_SECRET, json.dumps(pending))


@chat.function(
    "disconnect_freshbooks",
    "Disconnect a FreshBooks connection: deletes the saved connection (and every account it covered). "
    "Nothing in FreshBooks itself is changed.",
    action_type="destructive",
    chain_callable=True,
    data_model=DeleteResult,
    event="freshbooks-connector.disconnect",
    effects=["freshbooks.connection.removed"],
)
async def disconnect_freshbooks(ctx, params: DisconnectFreshbooksParams) -> ActionResult:
    """Delete one saved FreshBooks connection by id."""
    connections = await _load_connections(ctx)
    remaining = [c for c in connections if c.get("id") != params.connection_id]
    if len(remaining) == len(connections):
        return ActionResult.error("No such FreshBooks connection.", code="FRESHBOOKS_NOT_CONNECTED")
    await _save_connections(ctx, remaining)
    return ActionResult.success(DeleteResult(deleted=True, id=params.connection_id), summary="Freshbooks disconnected.")
