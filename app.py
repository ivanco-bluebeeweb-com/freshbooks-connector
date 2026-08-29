"""Extension declaration, secrets, lifecycle hooks.

WHY BYOK, same reasoning as every other connector this session -- the
user's own FreshBooks business data (clients, invoices, expenses) lives
inside THEIR OWN FreshBooks account.

WHY OAUTH2 AUTHORIZATION CODE, NOT API KEY (confirmed against
developer.freshbooks.com/getting-started/, 2026-08-29): FreshBooks only
supports OAuth2 for the accounting API -- no static API key option.

WHY THE USER BRINGS THEIR OWN FRESHBOOKS APP (client_id/client_secret),
same pattern as Xero/QuickBooks/Clio Connector, not a single Imperal-owned
OAuth app: a single Imperal-owned FreshBooks app usable by every Imperal
user would need FreshBooks' own app review and one fixed redirect_uri
hosted centrally. Instead each user registers their own free app at
my.freshbooks.com/#/developer, gets their own client_id/client_secret, and
points its redirect URI at Imperal's OAuth callback for this connector.

WHY account_id IS STORED PER CONNECTION, SAME ROLE AS XERO'S tenant_id.
FreshBooks scopes almost every accounting endpoint under
/accounting/account/{account_id}/... -- the account_id is fetched once
from the identity endpoint (auth/api/v1/users/me) right after token
exchange and stored alongside the tokens. A single OAuth grant can cover
several businesses/accounts; we store the full list and let entity/report
tools target one via an explicit account_id, defaulting to the
connection's first/primary account if omitted. See PREPARATION.md.
"""
from __future__ import annotations

from imperal_sdk import ChatExtension, Extension

ext = Extension(
    "freshbooks-connector",
    version="0.1.0",
    display_name="FreshBooks",
    icon="icon.svg",
    capabilities=["freshbooks:read", "freshbooks:write"],
    description=(
        "Connect your own FreshBooks account(s) (OAuth2) to manage clients, invoices, "
        "expenses, estimates, items, and payments -- full read/write plus value-add "
        "revenue overview and overdue-invoice reports."
    ),
)

chat = ChatExtension(
    ext,
    tool_name="freshbooks",
    description=(
        "FreshBooks Connector -- connect your FreshBooks account(s) via OAuth2, then "
        "manage clients, invoices, expenses, estimates, items, and payments, run "
        "value-add revenue/overdue reports, and check account info -- across one or "
        "more accounts under the same connection."
    ),
)

# Credentials never flow through the LLM beyond this one setup call.
# `connect_freshbooks` collects the user's own FreshBooks app
# client_id/client_secret plus a friendly label; the callback webhook does
# the code-for-token exchange server-side, fetches the granted account
# list from auth/api/v1/users/me, and stores everything in the
# Vault-encrypted secret below.
ext.secret(
    "freshbooks_connections",
    (
        "JSON array of connected FreshBooks OAuth grants: client_id/"
        "client_secret (your own FreshBooks app), access_token, "
        "refresh_token, expiry timestamps, the list of granted accounts "
        "(account_id, name, business_uuid), default_account_id, and "
        "label. Managed through connect_freshbooks / disconnect_freshbooks "
        "-- you should not need to edit this directly."
    ),
    required=True,
    write_mode="both",
    max_bytes=65536,
    rotation_hint_days=90,
)(lambda: None)

ext.secret(
    "freshbooks_pending",
    (
        "JSON array of in-flight FreshBooks OAuth connection attempts "
        "(client_id/client_secret captured at connect_freshbooks time, "
        "keyed by a pending id used as the OAuth `state`), consumed and "
        "removed by the callback webhook once the code-for-token exchange "
        "completes. write_mode='extension': only connector code writes "
        "this, never the Panel UI directly."
    ),
    required=False,
    write_mode="extension",
    max_bytes=16384,
)(lambda: None)


@ext.health_check
async def health_check(ctx) -> dict:
    """Fast configuration health; no third-party call -- just confirms at
    least one FreshBooks connection (with at least one account) is
    stored, same shape as Xero Connector's health_check."""
    import json as _json
    raw = await ctx.secrets.get("freshbooks_connections")
    try:
        conns = _json.loads(raw) if raw else []
    except Exception:
        conns = []
    account_count = sum(len(c.get("accounts", [])) for c in conns) if isinstance(conns, list) else 0
    return {
        "healthy": True,
        "detail": (
            f"{account_count} FreshBooks account{'s' if account_count != 1 else ''} connected."
            if account_count else "Not connected yet -- run connect_freshbooks."
        ),
    }
