"""Form validation: rules, live errors, a slow server check, and errors coming back from the server."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

from pygui import App, State, ValidationError, rules, ui

app = App("Sign up", width=560, height=820, accent="#10b981")

TAKEN = {"ada@example.com", "grace@example.com"}
accounts = State([])


def create_account(values):
    """Runs in the background (background=True): the form shows a spinner meanwhile."""
    time.sleep(1.2)  # a slow server
    if values["email"].lower() in TAKEN:
        raise ValidationError({"email": "This email is already registered"})
    TAKEN.add(values["email"].lower())
    return values


def created(values):
    accounts.append(values["email"])
    ui.toast(f"Welcome, {values['name']}!", "success")


@app.page("/", title="Sign up")
def home():
    form = ui.use_form(
        name=("", [rules.required(), rules.max_length(40)]),
        email=("", [rules.required(), rules.email()]),
        password=("", [rules.required(), rules.min_length(8),
                       rules.check(lambda v: any(c.isdigit() for c in v), "Include at least one digit")]),
        confirm=("", [rules.required(), rules.matches("password", "Passwords don't match")]),
        age=(None, [rules.required(), rules.number(min=18, max=120, integer=True)]),
        plan=("free", [rules.one_of(["free", "pro", "team"])]),
        terms=(False, [rules.required("Accept the terms to continue")]),
    )
    return ui.container(
        ui.column(ui.h2("Create your account"),
                  ui.text("Try ada@example.com to see an error coming back from the server.", muted=True), gap=1),
        ui.alert(form.error.value, kind="error") if form.error.value else None,
        ui.form(
            ui.input(form.name, label="Name", icon="user", autofocus=True),
            ui.input(form.email, label="Email", type="email", icon="mail"),
            ui.row(
                ui.input(form.password, label="Password", type="password", icon="lock", style={"flex": 1}),
                ui.input(form.confirm, label="Confirm", type="password", style={"flex": 1}),
                align="start",
            ),
            ui.row(
                ui.input(form.age, label="Age", type="number", style={"flex": 1}),
                ui.select({"free": "Free", "pro": "Pro", "team": "Team"}, form.plan, label="Plan",
                          style={"flex": 1}),
                align="start",
            ),
            ui.checkbox("I accept the terms of service", form.terms),
            ui.button("Create account", submit=True, full=True, loading=form.submitting.value),
            on_submit=form.submit(create_account, background=True, on_done=created, reset=True),
        ),
        ui.card(*[ui.text(email) for email in accounts.value], title="Created this session") if accounts.value
        else None,
        max_width=560, padding=8, cls="pg-col", style={"gap": "20px"},
    )


app.run()
