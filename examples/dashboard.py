"""A complete desktop app: sidebar navigation, live charts, data table, forms, modals, native dialogs."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

import os
import random

from zepygui import App, State, ui

app = App("Northwind", width=1240, height=820, accent="#6366f1")

# ---------------------------------------------------------------- shared state
revenue = State([random.randint(30, 60) for _ in range(12)])
visitors = State(1284)
customers = State([
    {"id": 1, "name": "Ada Lovelace", "email": "ada@analytical.io", "plan": "Pro", "mrr": 249, "status": "Active"},
    {"id": 2, "name": "Grace Hopper", "email": "grace@cobol.dev", "plan": "Enterprise", "mrr": 1200, "status": "Active"},
    {"id": 3, "name": "Alan Turing", "email": "alan@bletchley.uk", "plan": "Starter", "mrr": 29, "status": "Trial"},
    {"id": 4, "name": "Linus Torvalds", "email": "linus@kernel.org", "plan": "Pro", "mrr": 249, "status": "Past due"},
    {"id": 5, "name": "Margaret Hamilton", "email": "margaret@apollo.space", "plan": "Enterprise", "mrr": 980,
     "status": "Active"},
    {"id": 6, "name": "Dennis Ritchie", "email": "dmr@bell-labs.com", "plan": "Starter", "mrr": 29, "status": "Active"},
])
settings = {"notifications": State(True), "weekly": State(False), "density": State("comfortable"),
            "volume": State(60), "name": State("Ada Lovelace"), "email": State("ada@analytical.io")}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
STATUS_COLOR = {"Active": "green", "Trial": "blue", "Past due": "red"}


@app.timer(2.0)
def live_data():
    """Runs in the background: every open window updates by itself."""
    visitors.set(visitors.value + random.randint(-12, 25))
    revenue.set(revenue.value[1:] + [max(10, revenue.value[-1] + random.randint(-8, 10))])


# ---------------------------------------------------------------- layout
@app.layout
def layout(content):
    return ui.shell(
        content,
        sidebar=ui.sidebar(
            ui.nav_item("Overview", "/", icon="home"),
            ui.nav_item("Customers", "/customers", icon="users", badge=len(customers.value)),
            ui.nav_item("Files", "/files", icon="folder"),
            ui.nav_section("Account"),
            ui.nav_item("Settings", "/settings", icon="settings"),
            title="Northwind", logo="zap",
            footer=ui.row(ui.avatar(settings["name"].value, size=32),
                          ui.column(ui.text(settings["name"].value, size="sm", weight=600, truncate=True),
                                    ui.text("Admin", size="xs", muted=True), gap=0, cls="pg-nav-label")),
        ),
        header=ui.header(
            ui.input(placeholder="Search…", icon="search", style={"width": "260px", "margin-right": "auto"}),
            ui.icon_button("bell", lambda: ui.toast("You're all caught up", "success"), tooltip="Notifications"),
            ui.theme_toggle(),
        ),
    )


# ---------------------------------------------------------------- pages
@app.page("/", title="Overview")
def overview():
    total_mrr = sum(c["mrr"] for c in customers.value)
    plans = {}
    for c in customers.value:
        plans[c["plan"]] = plans.get(c["plan"], 0) + 1
    return ui.column(
        ui.row(ui.column(ui.h1("Good morning, Ada"), ui.text("Here's what's happening today.", muted=True), gap=1),
               ui.spacer(),
               ui.button("Export", lambda: export_report(), variant="secondary", icon="download"),
               ui.button("New customer", lambda: ui.navigate("/customers"), icon="plus"), align="end"),
        ui.grid(
            ui.stat("Monthly revenue", f"${total_mrr:,}", delta="+12.5%", icon="dollar", spark=revenue.value),
            ui.stat("Live visitors", f"{visitors.value:,}", delta="+4.1%", icon="activity"),
            ui.stat("Customers", len(customers.value), delta="+2", icon="users"),
            ui.stat("Churn", "1.8%", delta="-0.4%", icon="trending-down"),
            cols=4, gap=4,
        ),
        ui.grid(
            ui.card(ui.line_chart({"Revenue": revenue.value, "Target": [45] * 12}, MONTHS, height=260,
                                  format=lambda v: f"${v}k"),
                    title="Revenue", subtitle="Last 12 months, updates live",
                    actions=ui.badge("Live", "green", dot=True)),
            ui.card(ui.donut(plans, center_label="customers"), title="Plans", subtitle="Distribution by tier"),
            cols="2fr 1fr", gap=4,
        ),
        ui.grid(
            ui.card(ui.bar_chart({"Mon": 32, "Tue": 45, "Wed": 38, "Thu": 52, "Fri": 61, "Sat": 24, "Sun": 18},
                                 height=200, multicolor=True), title="Signups this week"),
            ui.card(
                *[ui.column(ui.row(ui.text(label, size="sm"), ui.spacer(), ui.text(f"{v}%", size="sm", weight=600)),
                            ui.progress(v, size="sm"), gap=1.5)
                  for label, v in [("Storage", 72), ("Bandwidth", 45), ("API quota", 91), ("Seats", 30)]],
                title="Usage", subtitle="Current billing period"),
            cols=2, gap=4,
        ),
        gap=6,
    )


def export_report():
    path = ui.save_file("Export report", "report.csv", types=["csv"])
    if not path:
        return
    with open(path, "w") as f:
        f.write("name,email,plan,mrr,status\n")
        for c in customers.value:
            f.write(f"{c['name']},{c['email']},{c['plan']},{c['mrr']},{c['status']}\n")
    ui.toast(f"Saved {os.path.basename(path)}", "success", title="Export complete")
    ui.notify("Northwind", "Your report has been exported")


@app.page("/customers", title="Customers")
def customers_page():
    query = ui.use_state("")
    dialog = ui.use_state(False)
    form = {"name": ui.use_state(""), "email": ui.use_state(""), "plan": ui.use_state("Starter")}

    def save():
        if not form["name"].value or "@" not in form["email"].value:
            ui.toast("Please enter a name and a valid email", "warning")
            return
        customers.append({"id": max(c["id"] for c in customers.value) + 1, "name": form["name"].value,
                          "email": form["email"].value, "plan": form["plan"].value,
                          "mrr": {"Starter": 29, "Pro": 249, "Enterprise": 990}[form["plan"].value],
                          "status": "Trial"})
        dialog.set(False)
        for s in form.values():
            s.set("" if s is not form["plan"] else "Starter")
        ui.toast("Customer added", "success")

    q = query.value.lower()
    rows = [c for c in customers.value if q in c["name"].lower() or q in c["email"].lower()]
    return ui.column(
        ui.row(ui.column(ui.h1("Customers"), ui.text(f"{len(customers.value)} accounts", muted=True), gap=1),
               ui.spacer(), ui.button("Add customer", lambda: dialog.set(True), icon="plus"), align="end"),
        ui.row(ui.input(query, placeholder="Filter by name or email…", icon="search", clearable=True,
                        style={"width": "320px"})),
        ui.table(rows, [
            {"key": "name", "label": "Customer",
             "format": lambda v, r: ui.row(ui.avatar(v, size=30),
                                           ui.column(ui.text(v, weight=600), ui.text(r["email"], size="xs", muted=True),
                                                     gap=0), gap=3)},
            ("plan", "Plan"),
            {"key": "status", "label": "Status", "format": lambda v: ui.badge(v, STATUS_COLOR[v], dot=True)},
            {"key": "mrr", "label": "MRR", "align": "right", "format": lambda v: f"${v:,}"},
        ], on_row_click=lambda r: ui.toast(f"{r['name']} · {r['plan']} plan", title="Customer"),
            empty="No customers match your search"),
        ui.modal(dialog,
                 ui.input(form["name"], label="Full name", placeholder="Jane Doe", autofocus=True),
                 ui.input(form["email"], label="Email", placeholder="jane@company.com", type="email"),
                 ui.select(["Starter", "Pro", "Enterprise"], form["plan"], label="Plan"),
                 title="New customer",
                 footer=[ui.button("Cancel", lambda: dialog.set(False), variant="ghost"),
                         ui.button("Create customer", save)]),
        gap=6,
    )


@app.page("/files", title="Files")
def files_page():
    picked = ui.use_state([])

    def choose():
        paths = ui.open_file("Choose files", multiple=True)
        if paths:
            picked.set(paths)
            ui.toast(f"{len(paths)} file(s) selected", "success")

    def reveal(path):
        ui.open_path(path, reveal=True)

    return ui.column(
        ui.column(ui.h1("Files"), ui.text("Native file dialogs, straight from Python.", muted=True), gap=1),
        ui.card(
            ui.row(ui.button("Open files…", choose, icon="upload"),
                   ui.button("Choose folder…", lambda: (lambda p: p and ui.toast(p, title="Folder"))(ui.choose_folder()),
                             variant="secondary", icon="folder")),
            ui.table([{"name": os.path.basename(p), "size": os.path.getsize(p), "path": p} for p in picked.value],
                     [("name", "Name"), {"key": "size", "label": "Size", "align": "right",
                                         "format": lambda v: f"{v / 1024:,.1f} KB"}],
                     on_row_click=lambda r: reveal(r["path"]), empty="No files selected yet")
            if picked.value else ui.empty_state("No files yet", "Pick some files to see them here.", icon="file"),
        ),
        gap=6,
    )


@app.page("/settings", title="Settings")
def settings_page():
    s = settings
    return ui.column(
        ui.column(ui.h1("Settings"), ui.text("Manage your account and preferences.", muted=True), gap=1),
        ui.tabs({
            "Profile": lambda: ui.card(
                ui.grid(ui.input(s["name"], label="Name"), ui.input(s["email"], label="Email", type="email"), cols=2),
                ui.textarea(placeholder="Tell us about yourself", label="Bio", rows=3),
                ui.row(ui.spacer(), ui.button("Save changes", lambda: ui.toast("Profile saved", "success"))),
            ),
            "Preferences": lambda: ui.card(
                ui.switch("Push notifications", s["notifications"], description="Get notified about account activity"),
                ui.switch("Weekly digest", s["weekly"], description="A summary every Monday morning"),
                ui.divider(),
                ui.radio_group({"comfortable": "Comfortable", "compact": "Compact"}, s["density"], label="Density",
                               inline=True),
                ui.slider(s["volume"], label="Sound volume", format=lambda v: f"{v}%"),
            ),
            "About": lambda: ui.card(ui.markdown("""
                ### Northwind
                Built with **ZePyGUI**, a native desktop UI framework in pure Python.

                - No dependencies, just the standard library
                - Reactive state: change a value and the UI updates
                - Native window, menus and file dialogs
                """)),
        }, variant="pills"),
        gap=6, style={"max-width": "760px"},
    )


app.run(debug=True)
