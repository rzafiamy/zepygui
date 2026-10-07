"""Validation rules for :class:`~pygui.forms.Field` and ``ui.use_form``.

    from pygui import rules
    ui.use_field("", rules.required(), rules.email())
"""
from .forms import (ValidationError, check, email, matches, max_length, min_length, number, one_of, pattern,
                    required, url)

__all__ = ["required", "min_length", "max_length", "pattern", "email", "url", "number", "one_of", "matches",
           "check", "ValidationError"]
