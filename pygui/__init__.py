"""PyGUI: beautiful desktop apps in pure Python, with no dependencies.

    from pygui import App, State, ui

    app = App("Hello")
    count = State(0)

    @app.page("/")
    def home():
        return ui.column(
            ui.h1(f"Clicked {count.value} times"),
            ui.button("Click me", on_click=lambda: count.set(count.value + 1)),
        )

    app.run()
"""
from . import rules, ui
from .app import App, Event, Session
from .forms import Field, Form, ValidationError
from .log import Log
from .state import State
from .tasks import Cancelled, CommandError, Task
from .ui import component, use_state

__version__ = "0.1.0"
__all__ = ["App", "State", "Event", "Session", "ui", "component", "use_state", "Log", "Task", "Cancelled",
           "CommandError", "rules", "Field", "Form", "ValidationError"]
