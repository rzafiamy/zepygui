"""Input and form validation.

    from pygui import ui, rules

    @app.page("/signup")
    def signup():
        form = ui.use_form(
            email=("", [rules.required(), rules.email()]),
            password=("", [rules.required(), rules.min_length(8)]),
            confirm=("", [rules.matches("password", "Passwords don't match")]),
            age=(None, [rules.number(min=18, integer=True)]),
        )
        return ui.form(
            ui.input(form.email, label="Email"),
            ui.input(form.password, type="password", label="Password"),
            ui.input(form.confirm, type="password", label="Confirm password"),
            ui.input(form.age, type="number", label="Age"),
            ui.button("Create account", submit=True, loading=form.submitting.value),
            on_submit=form.submit(create_account, background=True),
        )

A field shows its error once the user has left it (or tried to submit), then updates live
as they type. ``form.submit(fn)`` calls ``fn(values)`` only when every field is valid; ``fn``
may raise :class:`ValidationError` to put server-side errors (``"email already used"``) back
on the fields.
"""
from __future__ import annotations

import re

from .state import State, invoke

__all__ = ["Field", "Form", "ValidationError", "required", "min_length", "max_length", "pattern", "email",
           "url", "number", "one_of", "matches", "check"]


class ValidationError(Exception):
    """Raise from a submit handler: ``ValidationError({"email": "Already registered"})``
    marks fields, ``ValidationError("Server unavailable")`` sets ``form.error``."""

    def __init__(self, errors):
        super().__init__(errors if isinstance(errors, str) else "; ".join(f"{k}: {v}" for k, v in errors.items()))
        self.errors = errors


# ----------------------------------------------------------------------------- rules
def _empty(v):
    return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, (list, tuple, set, dict)) and not v)


class Rule:
    """A validation rule: ``rule(value, values)`` returns an error message or ``None``."""

    required = False

    def __init__(self, fn, message):
        self.fn, self.message = fn, message

    def __call__(self, value, values=None):
        if _empty(value):
            return None  # only `required` objects to an empty value
        try:
            ok = self.fn(value, values or {})
        except (TypeError, ValueError):
            ok = False
        return None if ok else self.message


class _Required(Rule):
    required = True

    def __call__(self, value, values=None):
        return self.message if _empty(value) or value is False else None


def required(message="This field is required"):
    """Not empty (and, for a checkbox, checked)."""
    return _Required(None, message)


def min_length(n, message=None):
    return Rule(lambda v, _: len(v) >= n, message or f"Use at least {n} characters")


def max_length(n, message=None):
    return Rule(lambda v, _: len(v) <= n, message or f"Use at most {n} characters")


def pattern(regex, message="Invalid format"):
    rx = re.compile(regex)
    return Rule(lambda v, _: rx.fullmatch(str(v)) is not None, message)


_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_URL = re.compile(r"https?://[^\s/$.?#][^\s]*", re.IGNORECASE)


def email(message="Enter a valid email address"):
    return Rule(lambda v, _: _EMAIL.fullmatch(str(v).strip()) is not None, message)


def url(message="Enter a valid URL (http:// or https://)"):
    return Rule(lambda v, _: _URL.fullmatch(str(v).strip()) is not None, message)


def number(min=None, max=None, integer=False, message=None):  # noqa: A002 - mirrors ui.slider
    """A number (``ui.input(type="number")`` gives ``None`` for text that is not one)."""
    def ok(v, _):
        if isinstance(v, bool):
            return False
        n = float(v)
        return (not integer or n.is_integer()) and (min is None or n >= min) and (max is None or n <= max)

    if message is None:
        kind = "a whole number" if integer else "a number"
        if min is not None and max is not None:
            message = f"Enter {kind} from {min} to {max}"
        elif min is not None:
            message = f"Enter {kind} of at least {min}"
        elif max is not None:
            message = f"Enter {kind} of at most {max}"
        else:
            message = f"Enter {kind}"
    return Rule(ok, message)


def one_of(options, message="Choose one of the options"):
    allowed = list(options)
    return Rule(lambda v, _: v in allowed, message)


def matches(field, message="The values don't match"):
    """Equal to another field of the same form (password confirmation)."""
    return Rule(lambda v, values: v == values.get(field), message)


def check(predicate, message="Invalid value"):
    """A custom rule: ``predicate(value)`` or ``predicate(value, values)`` returns truthy when valid."""
    from .state import _arity
    two = _arity(predicate, 2) >= 2
    return Rule(lambda v, values: predicate(v, values) if two else predicate(v), message)


# ----------------------------------------------------------------------------- fields
class Field:
    """A value with validation rules. Pass it to an input as ``value``:
    ``ui.input(field, label="Email")`` binds the value and shows the error."""

    def __init__(self, default=None, rules=(), *, name=None, form=None):
        self.name = name
        self.default = default
        self.rules = list(rules)
        self.state = State(default)
        self.touched = State(False)
        self.server_error = State(None)
        self._form = form

    @property
    def value(self):
        return self.state.value

    @value.setter
    def value(self, v):
        self.state.set(v)

    def set(self, v):
        self.state.set(v)

    @property
    def required(self):
        return any(r.required for r in self.rules if isinstance(r, Rule))

    def validate(self):
        """The first error message for the current value, or ``None``."""
        if self.server_error.value:
            return self.server_error.value
        value = self.state.value
        values = self._form._values(live=True) if self._form is not None else {}
        for rule in self.rules:
            msg = rule(value, values)
            if msg:
                return msg
        return None

    @property
    def error(self):
        return self.validate()

    @property
    def valid(self):
        return self.validate() is None

    @property
    def visible_error(self):
        """The error, once the user has left the field or tried to submit the form."""
        shown = self.touched.value or (self._form is not None and self._form.submitted.value)
        return self.validate() if shown else None

    def touch(self):
        self.touched.set(True)

    def _changed(self):
        if self.server_error._value is not None:
            self.server_error.set(None)

    def reset(self):
        self.state.set(self.default)
        self.touched.set(False)
        self.server_error.set(None)

    def __repr__(self):
        return f"<Field {self.name or ''} {self.state._value!r}>"


class Form:
    """A group of named :class:`Field`\\ s. Access fields as attributes or items.

    ``Form(email=("", [rules.required()]), remember=False)`` — each value is a
    ``(default, rules)`` pair, a :class:`Field`, or just a default.
    """

    def __init__(self, fields=None, **kw):
        spec = dict(fields or {}, **kw)
        self.fields = {}
        for name, item in spec.items():
            if isinstance(item, Field):
                field = item
                field.name, field._form = name, self
            elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], (list, tuple)):
                field = Field(item[0], item[1], name=name, form=self)
            else:
                field = Field(item, (), name=name, form=self)
            self.fields[name] = field
        self.submitted = State(False)
        self.submitting = State(False)
        self.error = State(None)  # a form-level message (from ValidationError("..."))

    def __getattr__(self, name):
        fields = self.__dict__.get("fields")
        if fields is not None and name in fields:
            return fields[name]
        raise AttributeError(name)

    def __getitem__(self, name):
        return self.fields[name]

    def _values(self, live=False):
        return {n: (f.state.value if live else f.state._value) for n, f in self.fields.items()}

    def values(self):
        """``{name: value}`` of every field."""
        return self._values()

    def errors(self):
        """``{name: message}`` for every invalid field."""
        return {n: e for n, e in ((n, f.validate()) for n, f in self.fields.items()) if e}

    @property
    def valid(self):
        return not self.errors()

    def validate(self):
        """Show every field's error; return ``True`` when the form is valid."""
        self.submitted.set(True)
        return self.valid

    def set_errors(self, errors):
        """Put messages on fields (``{"email": "Already registered"}``) or on the form (a string)."""
        if isinstance(errors, str):
            self.error.set(errors)
            return
        for name, msg in errors.items():
            if name in self.fields:
                self.fields[name].server_error.set(msg)
                self.fields[name].touch()
            else:
                self.error.set(msg)

    def reset(self):
        for f in self.fields.values():
            f.reset()
        self.submitted.set(False)
        self.error.set(None)

    def submit(self, fn, *, background=False, on_done=None, reset=False):
        """A handler for ``ui.form(on_submit=...)`` or a button: validates, then calls
        ``fn(values)``.

        ``background=True`` runs ``fn`` as a :func:`ui.task` while ``form.submitting`` is
        ``True`` (for slow saves). ``on_done(result)`` runs after success; ``reset=True``
        clears the form then. ``fn`` may raise :class:`ValidationError`.
        """
        def finish(result):
            self.submitting.set(False)
            if reset:
                self.reset()
            if on_done is not None:
                invoke(on_done, result)

        def failed(exc):
            self.submitting.set(False)
            if isinstance(exc, ValidationError):
                self.set_errors(exc.errors)
            else:
                self.error.set(str(exc) or type(exc).__name__)

        def handler(*_):
            self.error.set(None)
            if not self.validate() or self.submitting._value:
                return
            values = self.values()
            if background:
                from .tasks import start
                self.submitting.set(True)
                start(fn, values, on_done=finish, on_error=failed)
                return
            try:
                result = invoke(fn, values)
            except ValidationError as exc:
                failed(exc)
            else:
                finish(result)

        return handler
