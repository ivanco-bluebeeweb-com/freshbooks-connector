"""Pydantic params/result models for FreshBooks Connector.

All params models are module-scope (V17 federal invariant, same rule as
every other connector this session's schemas.py).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class NoParams(BaseModel):
    """Explicit empty params model -- V17 disallows untyped handlers."""
    pass


class AccountScoped(BaseModel):
    connection_id: str = Field(
        "",
        description="Which connected FreshBooks account grant to use (see list_connections). Omit if only one is connected.",
    )
    account_id: str = Field(
        "",
        description="Which FreshBooks business account to target, if the connection covers several. Omit to use the default account.",
    )


# ──────────────────────────────────────────────────────────────────────────
# Connection -- OAuth2 authorization code, like Xero/QuickBooks
# ──────────────────────────────────────────────────────────────────────────


class ConnectFreshbooksParams(BaseModel):
    client_id: str = Field("", description="Your FreshBooks app's Client ID (my.freshbooks.com/#/developer).")
    client_secret: str = Field("", description="Your FreshBooks app's Client Secret.")
    redirect_uri: str = Field("", description="The redirect URI registered on your FreshBooks app.")
    label: str = Field("", description="Optional friendly label for this connection, e.g. 'Acme Inc FreshBooks'.")


class ConnectFreshbooksResult(BaseModel):
    authorize_url: str = ""
    pending_id: str = ""


class ProviderAccount(BaseModel):
    account_id: str = ""
    name: str = ""
    business_uuid: str = ""


class ProviderConnection(BaseModel):
    id: str = ""
    label: str = ""
    accounts: list[ProviderAccount] = Field(default_factory=list)
    default_account_id: str = ""


class ProviderConnectionList(BaseModel):
    connections: list[ProviderConnection] = Field(default_factory=list)


class DisconnectFreshbooksParams(BaseModel):
    connection_id: str = Field(description="Which connection to disconnect (see list_connections).")


class DeleteResult(BaseModel):
    deleted: bool = False
    id: str = ""


# ──────────────────────────────────────────────────────────────────────────
# Generic entity layer
# ──────────────────────────────────────────────────────────────────────────


class ListEntitiesParams(AccountScoped):
    entity: str = Field(description="Resource type: clients, invoices, expenses, estimates, items, payments, taxes, staffs.")
    page: int = Field(1, ge=1, description="Page number, 1-based.")
    per_page: int = Field(30, ge=1, le=100, description="Records per page.")


class EntityList(BaseModel):
    entity: str = ""
    count: int = 0
    records: list[dict] = Field(default_factory=list)


class GetEntityParams(AccountScoped):
    entity: str = Field(description="Resource type, same values as list_entities.")
    record_id: str = Field(description="The record's FreshBooks id.")


class EntityDetail(BaseModel):
    entity: str = ""
    record: dict = Field(default_factory=dict)


class CreateEntityParams(AccountScoped):
    entity: str = Field(description="Resource type to create: clients, invoices, expenses, estimates, items.")
    fields_json: str = Field(description="JSON object of the fields for the new record, using FreshBooks' own field names.")


class UpdateEntityParams(AccountScoped):
    entity: str = Field(description="Resource type to update, same values as list_entities.")
    record_id: str = Field(description="The record's FreshBooks id.")
    fields_json: str = Field(description="JSON object of the fields to change. Only given fields change.")


class DeleteEntityParams(AccountScoped):
    entity: str = Field(description="Resource type to delete: invoices, expenses, estimates, items.")
    record_id: str = Field(description="The record's FreshBooks id.")


class WriteResult(BaseModel):
    ok: bool = False
    record_id: str = ""
    record: dict = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Value-add reports
# ──────────────────────────────────────────────────────────────────────────


class GetRevenueOverviewParams(AccountScoped):
    limit: int = Field(100, ge=1, le=100, description="Number of recent invoices to scan for the overview.")


class RevenueOverviewReport(BaseModel):
    invoice_count: int = 0
    total_invoiced: float = 0.0
    total_paid: float = 0.0
    total_outstanding: float = 0.0
    by_status: dict[str, int] = Field(default_factory=dict)


class GetOverdueInvoicesParams(AccountScoped):
    min_days_overdue: int = Field(1, ge=0, description="Minimum number of days past due date to flag.")
    limit: int = Field(100, ge=1, le=100, description="Number of recent invoices to scan.")


class OverdueInvoice(BaseModel):
    invoice_id: str = ""
    client_name: str = ""
    amount_due: float = 0.0
    due_date: str = ""
    days_overdue: int = 0


class OverdueInvoicesReport(BaseModel):
    count: int = 0
    total_overdue_amount: float = 0.0
    invoices: list[OverdueInvoice] = Field(default_factory=list)
