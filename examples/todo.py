"""A polished to-do app: binding, keyed lists, filters, empty states."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # run without installing

import itertools

from zepygui import App, State, ui

app = App("Todos", width=560, height=720, accent="#8b5cf6")

ids = itertools.count(1)
todos = State([
    {"id": next(ids), "text": "Try ZePyGUI", "done": True},
    {"id": next(ids), "text": "Build something beautiful", "done": False},
])
draft = State("")
show = State("all")


def add():
    text = draft.value.strip()
    if text:
        todos.append({"id": next(ids), "text": text, "done": False})
        draft.set("")


def toggle(todo):
    todo["done"] = not todo["done"]
    todos.notify()  # we mutated a dict in place, so tell the UI


def remove(todo):
    todos.remove(todo)
    ui.toast(f"Deleted “{todo['text']}”")


def todo_row(todo):
    return ui.row(
        ui.checkbox(value=todo["done"], on_change=lambda _: toggle(todo)),
        ui.text(todo["text"], cls="done" if todo["done"] else None, style={"flex": 1}),
        ui.icon_button("trash", lambda: remove(todo), tooltip="Delete"),
        cls="todo-row", key=todo["id"],
    )


@app.page("/")
def home():
    visible = [t for t in todos.value
               if show.value == "all" or (show.value == "done") == t["done"]]
    left = sum(not t["done"] for t in todos.value)
    return ui.container(
        ui.column(
            ui.h1("Today"),
            ui.text(f"{left} task{'s' * (left != 1)} left", muted=True),
            gap=1,
        ),
        ui.row(
            ui.input(draft, placeholder="What needs to be done?", on_enter=lambda _: add(), icon="plus",
                     autofocus=True, style={"flex": 1}),
            ui.button("Add", add),
        ),
        ui.segmented({"all": "All", "open": "Open", "done": "Done"}, show, full=True),
        ui.card(*[todo_row(t) for t in visible], padding=2, style={"gap": "2px"}) if visible else
        ui.empty_state("Nothing here", "Add a task above to get started.", icon="check-circle"),
        max_width=560, padding=8, cls="pg-col", style={"gap": "20px"},
    )


app.add_css("""
.todo-row { padding: 8px 10px; border-radius: 8px; transition: background .15s; }
.todo-row:hover { background: var(--surface-2); }
.done { text-decoration: line-through; color: var(--muted); }
""")

app.run()
