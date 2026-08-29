"""Value-add reports for FreshBooks Connector -- revenue overview and
overdue invoices, same "aggregate raw records into one glance" shape as
every other connector's handlers_reports.py this session.
"""
from __future__ import annotations

import datetime as _dt

from imperal_sdk import ActionResult

import freshbooks_client as fc
from app import chat
from handlers_connection import resolve_or_error
from schemas import (
    GetRevenueOverviewParams, RevenueOverviewReport,
    GetOverdueInvoicesParams, OverdueInvoicesReport, OverdueInvoice,
)


@chat.function(
    "get_revenue_overview",
    "Value-add report: scan recent FreshBooks invoices and summarize total invoiced/paid/outstanding "
    "amounts, broken down by status.",
    action_type="read", chain_callable=True, data_model=RevenueOverviewReport,
)
async def get_revenue_overview(ctx, params: GetRevenueOverviewParams) -> ActionResult:
    """Scan recent invoices and bucket totals by status."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    path, _singular_key, plural_key, _id_field = fc.entity_registry_entry("invoices")
    data = await fc.request(
        ctx, conn, account_id, "GET", path,
        params={"page": 1, "per_page": params.limit},
        action="list invoices for revenue overview",
    )
    invoices = fc.unwrap_list(data, plural_key)
    total_invoiced = 0.0
    total_paid = 0.0
    by_status: dict[str, int] = {}
    for inv in invoices:
        amount = inv.get("amount", {}) or {}
        paid = inv.get("paid", {}) or {}
        total_invoiced += float(amount.get("amount", 0) or 0)
        total_paid += float(paid.get("amount", 0) or 0)
        status = str(inv.get("v3_status") or inv.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
    return ActionResult.ok(RevenueOverviewReport(
        invoice_count=len(invoices),
        total_invoiced=round(total_invoiced, 2),
        total_paid=round(total_paid, 2),
        total_outstanding=round(total_invoiced - total_paid, 2),
        by_status=by_status,
    ))


@chat.function(
    "get_overdue_invoices",
    "Value-add report: flag every unpaid FreshBooks invoice overdue by at least a given number of days.",
    action_type="read", chain_callable=True, data_model=OverdueInvoicesReport,
)
async def get_overdue_invoices(ctx, params: GetOverdueInvoicesParams) -> ActionResult:
    """Scan recent invoices and flag ones past their due date."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    path, _singular_key, plural_key, _id_field = fc.entity_registry_entry("invoices")
    data = await fc.request(
        ctx, conn, account_id, "GET", path,
        params={"page": 1, "per_page": params.limit},
        action="list invoices for overdue report",
    )
    invoices = fc.unwrap_list(data, plural_key)
    today = _dt.date.today()
    flagged: list[OverdueInvoice] = []
    total_overdue = 0.0
    for inv in invoices:
        status = str(inv.get("v3_status") or inv.get("status") or "").lower()
        if status in ("paid", "draft", "cancelled", "disputed"):
            continue
        due_date_str = inv.get("due_date") or ""
        if not due_date_str:
            continue
        try:
            due_date = _dt.date.fromisoformat(due_date_str[:10])
        except ValueError:
            continue
        days_overdue = (today - due_date).days
        if days_overdue < params.min_days_overdue:
            continue
        amount = inv.get("amount", {}) or {}
        paid = inv.get("paid", {}) or {}
        amount_due = round(float(amount.get("amount", 0) or 0) - float(paid.get("amount", 0) or 0), 2)
        if amount_due <= 0:
            continue
        total_overdue += amount_due
        flagged.append(OverdueInvoice(
            invoice_id=str(inv.get("invoiceid") or inv.get("id") or ""),
            client_name=inv.get("organization") or "",
            amount_due=amount_due,
            due_date=due_date_str[:10],
            days_overdue=days_overdue,
        ))
    flagged.sort(key=lambda r: r.days_overdue, reverse=True)
    return ActionResult.ok(OverdueInvoicesReport(
        count=len(flagged), total_overdue_amount=round(total_overdue, 2), invoices=flagged,
    ))
