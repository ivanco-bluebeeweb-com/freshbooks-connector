"""Panel UI -- connections list/connect form + the one required "App
settings" entry point, same shape as Xero/QuickBooks Connector's panels.py.

SIDEBAR CONTENT -- NO CARDS ANYWHERE, per ~/UI_INTERFACE_STANDARD.md's
"left sidebar, no decorated cards" rule. Disconnect lives only in the
"App settings" screen (panels_settings.py). The one secondary "App
settings" button is always the LAST element at the bottom of the sidebar.

PER ~/UI_INTERFACE_STANDARD.md (2026-08-21 addendum): every Input carries
its own visible label, the placeholder text is always contextually
specific, the form's own container is stretched to the full width of the
left sidebar, and the form's inner content is stretched to fill that
container. The "How do I set this up?" instructions live ONLY in the help
modal below -- never duplicated as static sidebar text.
"""
from __future__ import annotations

from imperal_sdk import ui

from app import ext
import handlers_connection as h


def _settings_button() -> ui.UINode:
    return ui.Button(
        "App settings", variant="secondary", size="sm", icon="settings", on_click=ui.Call("__panel__freshbooks_settings"),
    )


def _connection_row(c: dict) -> ui.UINode:
    label = c.get("label") or "FreshBooks connection"
    accounts = c.get("accounts", [])
    names = ", ".join(a.get("name", "") for a in accounts) or "—"
    return ui.Stack(direction="v", gap=1, children=[
        ui.Text(label, variant="body"),
        ui.Text(f"Businesses: {names}", variant="caption"),
    ])


def _connections_section(connections: list[dict]) -> ui.UINode:
    if not connections:
        return ui.Text("No FreshBooks accounts connected yet.", variant="caption")
    children: list[ui.UINode] = []
    for i, c in enumerate(connections):
        if i > 0:
            children.append(ui.Divider())
        children.append(_connection_row(c))
    return ui.Stack(direction="v", gap=2, children=children)


def _connect_section() -> ui.UINode:
    return ui.Stack(direction="v", gap=3, align="stretch", children=[
        ui.Button("How do I set this up?", variant="ghost", size="sm",
                  icon="HelpCircle",
                  on_click=ui.Call("__panel__freshbooks_connect_help")),
        ui.Form(
            action="connect_freshbooks",
            submit_label="Get authorize link",
            children=[
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("FreshBooks app Client ID", variant="caption"),
                    ui.Input(param_name="client_id",
                             placeholder="Paste your FreshBooks app's Client ID"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("FreshBooks app Client Secret", variant="caption"),
                    ui.Password(param_name="client_secret",
                                placeholder="Paste your FreshBooks app's Client Secret"),
                ]),
                ui.Stack(direction="v", gap=1, align="stretch", children=[
                    ui.Text("Label (optional)", variant="caption"),
                    ui.Input(param_name="label", placeholder="e.g. Acme Inc FreshBooks"),
                ]),
            ],
        ),
    ])


@ext.panel("freshbooks_connect", slot="left", title="FreshBooks", icon="🧮",
           default_width=320, min_width=260, max_width=420)
async def freshbooks_connect_panel(ctx, **kwargs) -> object:
    connections = await h._load_connections(ctx)

    header = ui.Header(text="FreshBooks", level=2,
                        subtitle="Manage clients, invoices, expenses and estimates from Imperal")

    return ui.Stack(direction="v", gap=4, align="stretch", children=[
        header,
        _connections_section(connections),
        ui.Divider(),
        _connect_section(),
        ui.Divider(),
        _settings_button(),
    ])


@ext.panel("freshbooks_connect_help", slot="center",
           title="How to connect FreshBooks", center_overlay=True)
async def freshbooks_connect_help(ctx, **kwargs) -> object:
    content = ui.Stack(direction="v", gap=3, children=[
        ui.Text("1. Go to my.freshbooks.com/#/developer, sign in, and click \"Create App\"."),
        ui.Text("2. Give it a name, and add a Redirect URI -- you'll get the exact callback URL to paste there after clicking \"Get authorize link\" below."),
        ui.Text("3. Under the app's settings, copy the Client ID and Client Secret."),
        ui.Text("4. Paste the Client ID and Client Secret into the form here and click \"Get authorize link\"."),
        ui.Text("5. Open the link, sign in with FreshBooks, pick a business, and approve access -- the connection finishes itself automatically."),
        ui.Divider(),
        ui.Alert(
            title="Full FreshBooks Accounting coverage",
            message=(
                "Clients, Invoices, Expenses, Estimates, Items, Payments, "
                "Taxes, Staff -- full read/write, plus value-add reports "
                "like revenue overview and overdue invoices -- across every "
                "business your connection covers."
            ),
            type="info",
        ),
        ui.Divider(),
        ui.Link("my.freshbooks.com/#/developer", url="https://my.freshbooks.com/#/developer"),
    ])
    return ui.Stack(direction="v", gap=3, children=[content])
