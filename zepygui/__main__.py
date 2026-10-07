"""Command line: ``python -m zepygui new myapp`` creates a starter app."""
import sys
from pathlib import Path

TEMPLATE = '''from zepygui import App, State, ui

app = App("{title}", width=1000, height=700)
name = State("")


@app.layout
def layout(content):
    return ui.shell(
        content,
        sidebar=ui.sidebar(
            ui.nav_item("Home", "/", icon="home"),
            ui.nav_item("Settings", "/settings", icon="settings"),
            title="{title}",
        ),
        header=ui.header(ui.spacer(), ui.theme_toggle()),
    )


@app.page("/", title="Home")
def home():
    return ui.column(
        ui.h1(f"Hello {{name.value or 'there'}} 👋"),
        ui.card(
            ui.input(name, label="Your name", placeholder="Type here…"),
            ui.button("Say hi", lambda: ui.toast(f"Hi {{name.value or 'friend'}}!", "success"), icon="sparkles"),
            title="Get started", subtitle="Edit {file} and save: the app reloads by itself.",
        ),
        gap=6,
    )


@app.page("/settings", title="Settings")
def settings():
    return ui.card(ui.switch("Notifications", True), ui.slider(50, label="Volume"), title="Settings")


app.run(reload=True)
'''


def main(argv):
    if len(argv) >= 2 and argv[0] == "new":
        target = Path(argv[1])
        file = target / "app.py" if not target.suffix else target
        if file.exists():
            sys.exit(f"{file} already exists")
        file.parent.mkdir(parents=True, exist_ok=True)
        title = file.parent.name.replace("-", " ").replace("_", " ").title() if not target.suffix else "My App"
        file.write_text(TEMPLATE.format(title=title, file=file.name), "utf-8")
        print(f"Created {file}\nRun it with:  python {file}")
        return
    print("usage: python -m zepygui new <folder>")


if __name__ == "__main__":
    main(sys.argv[1:])
