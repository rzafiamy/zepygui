"""The smallest ZePyGUI app: a counter."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

from zepygui import App, State, ui

app = App("Hello ZePyGUI", width=520, height=420)
count = State(0)


@app.page("/")
def home():
    return ui.column(
        ui.h1(f"{count.value}"),
        ui.text("times clicked", muted=True),
        ui.row(
            ui.button("Reset", lambda: count.set(0), variant="secondary"),
            ui.button("Click me", lambda: count.set(count.value + 1), icon="plus"),
        ),
        align="center", justify="center", gap=4, style={"height": "100vh"},
    )


app.run()
