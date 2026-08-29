"""Generic entity layer for FreshBooks Connector: clients, invoices,
expenses, estimates, items, payments, taxes, staffs. Same generic
list/get/create/update/delete shape as QuickBooks/Xero/Sage Intacct
Connector's handlers_entities.py, adapted for FreshBooks' nested
/accounting/account/{account_id}/<service>/<resource> paths and
{"response": {"result": {...}}} wrapper shape (see freshbooks_client.py's
_ENTITY_REGISTRY).
"""
from __future__ import annotations

from imperal_sdk import ActionResult

import freshbooks_client as fc
from app import chat
from handlers_connection import resolve_or_error
from schemas import (
    ListEntitiesParams, EntityList,
    GetEntityParams, EntityDetail,
    CreateEntityParams, UpdateEntityParams, DeleteEntityParams, WriteResult,
)


def _bad_entity(entity: str) -> ActionResult:
    return ActionResult.error(
        f"Unknown entity '{entity}'. Known: {', '.join(fc.known_entities())}",
        code="FRESHBOOKS_VALIDATION_FAILED",
    )


@chat.function(
    "list_entities",
    "List FreshBooks records of any resource type (clients, invoices, expenses, estimates, items, payments, "
    "taxes, staffs) in the connected FreshBooks account.",
    action_type="read", chain_callable=True, data_model=EntityList,
)
async def list_entities(ctx, params: ListEntitiesParams) -> ActionResult:
    """List FreshBooks records of any resource type."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    entry = fc.entity_registry_entry(params.entity)
    if not entry:
        return _bad_entity(params.entity)
    path, _singular_key, plural_key, _id_field = entry
    data = await fc.request(
        ctx, conn, account_id, "GET", path,
        params={"page": params.page, "per_page": params.per_page},
        action=f"list {params.entity}",
    )
    records = fc.unwrap_list(data, plural_key)
    return ActionResult.ok(EntityList(entity=params.entity, count=len(records), records=records))


@chat.function(
    "get_entity",
    "Read one FreshBooks record of any resource type in full by its id.",
    action_type="read", chain_callable=True, data_model=EntityDetail,
)
async def get_entity(ctx, params: GetEntityParams) -> ActionResult:
    """Read one FreshBooks record by id."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    entry = fc.entity_registry_entry(params.entity)
    if not entry:
        return _bad_entity(params.entity)
    path, singular_key, _plural_key, _id_field = entry
    data = await fc.request(
        ctx, conn, account_id, "GET", f"{path}/{params.record_id}",
        action=f"get {params.entity}",
    )
    record = fc.unwrap_single(data, singular_key)
    return ActionResult.ok(EntityDetail(entity=params.entity, record=record))


@chat.function(
    "create_entity",
    "Create a new FreshBooks record of any writable resource type (clients, invoices, expenses, estimates, "
    "items) from a JSON object of its fields.",
    action_type="write", chain_callable=True, data_model=WriteResult,
    event="freshbooks-connector.entity.created", effects=["freshbooks.entity.created"],
)
async def create_entity(ctx, params: CreateEntityParams) -> ActionResult:
    """Create a new FreshBooks record of any writable resource type."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    entry = fc.entity_registry_entry(params.entity)
    if not entry:
        return _bad_entity(params.entity)
    path, singular_key, _plural_key, id_field = entry
    fields = fc.parse_fields_json(params.fields_json)
    if fields is None:
        return ActionResult.error("fields_json must be a valid JSON object.", code="FRESHBOOKS_VALIDATION_FAILED")
    body = {singular_key: fields}
    data = await fc.request(ctx, conn, account_id, "POST", path, json_body=body, action=f"create {params.entity}")
    record = fc.unwrap_single(data, singular_key)
    return ActionResult.ok(WriteResult(ok=True, record_id=str(record.get(id_field, "")), record=record))


@chat.function(
    "update_entity",
    "Update selected fields of an existing FreshBooks record. Only given fields change.",
    action_type="write", chain_callable=True, data_model=WriteResult,
    event="freshbooks-connector.entity.updated", effects=["freshbooks.entity.updated"],
)
async def update_entity(ctx, params: UpdateEntityParams) -> ActionResult:
    """Update selected fields of an existing FreshBooks record."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    entry = fc.entity_registry_entry(params.entity)
    if not entry:
        return _bad_entity(params.entity)
    path, singular_key, _plural_key, id_field = entry
    fields = fc.parse_fields_json(params.fields_json)
    if fields is None:
        return ActionResult.error("fields_json must be a valid JSON object.", code="FRESHBOOKS_VALIDATION_FAILED")
    body = {singular_key: fields}
    data = await fc.request(
        ctx, conn, account_id, "PUT", f"{path}/{params.record_id}", json_body=body,
        action=f"update {params.entity}",
    )
    record = fc.unwrap_single(data, singular_key)
    return ActionResult.ok(WriteResult(ok=True, record_id=params.record_id, record=record))


@chat.function(
    "delete_entity",
    "Permanently delete a FreshBooks record (invoices, expenses, estimates, items). FreshBooks marks most "
    "records as 'deleted' rather than removing them outright, but this is not reversible through the API.",
    action_type="destructive", chain_callable=True, data_model=WriteResult,
    event="freshbooks-connector.entity.deleted", effects=["freshbooks.entity.deleted"],
)
async def delete_entity(ctx, params: DeleteEntityParams) -> ActionResult:
    """Delete a FreshBooks record by id."""
    conn, account_id, err = await resolve_or_error(ctx, params.connection_id, params.account_id)
    if err:
        return err
    entry = fc.entity_registry_entry(params.entity)
    if not entry:
        return _bad_entity(params.entity)
    path, singular_key, _plural_key, _id_field = entry
    body = {singular_key: {"vis_state": 1}}
    await fc.request(
        ctx, conn, account_id, "PUT", f"{path}/{params.record_id}", json_body=body,
        action=f"delete {params.entity}",
    )
    return ActionResult.ok(WriteResult(ok=True, record_id=params.record_id))
