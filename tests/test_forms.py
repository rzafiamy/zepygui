"""Input and form validation (REQ-VAL)."""
import threading
import time
import unittest

from helpers import Harness, find, find_all, has_class, tag, text_of

from zepygui import App, Field, Form, State, ValidationError, rules, ui


def render(page):
    app = App("t")
    app.page("/")(page)
    return Harness(app)


def errors(tree):
    return [text_of(n) for n in find_all(tree, has_class("pg-error-text"))]


class RuleTests(unittest.TestCase):
    def test_rules_accept_valid_and_empty_values_and_name_the_problem(self):
        """covers: REQ-VAL-001"""
        cases = [
            (rules.required(), "", "This field is required"), (rules.required(), "  ", "This field is required"),
            (rules.required(), None, "This field is required"), (rules.required(), False, "This field is required"),
            (rules.required(), "x", None), (rules.email(), "a@b.co", None), (rules.email(), "a@b", "Enter a valid email address"),
            (rules.min_length(3), "ab", "Use at least 3 characters"), (rules.max_length(2), "abc", "Use at most 2 characters"),
            (rules.number(min=18, integer=True), 17, "Enter a whole number of at least 18"),
            (rules.number(min=18, integer=True), 18.5, "Enter a whole number of at least 18"),
            (rules.number(max=5), 5, None), (rules.url(), "https://x.org/a", None), (rules.url(), "ftp://x", "Enter a valid URL (http:// or https://)"),
            (rules.pattern(r"[A-Z]{3}"), "ABC", None), (rules.one_of(["a", "b"]), "c", "Choose one of the options"),
            (rules.check(lambda v: v % 2 == 0, "Even please"), 3, "Even please"),
        ]
        for rule, value, expected in cases:
            self.assertEqual(rule(value, {}), expected, (value, expected))
        for rule in (rules.email(), rules.min_length(3), rules.number(min=1), rules.pattern("x")):
            self.assertIsNone(rule("", {}))
            self.assertIsNone(rule(None, {}))

    def test_matches_compares_with_another_field(self):
        """covers: REQ-VAL-010"""
        form = Form(password=("secret12", []), confirm=("secret1", [rules.matches("password", "No match")]))
        self.assertEqual(form.confirm.error, "No match")
        form.confirm.set("secret12")
        self.assertIsNone(form.confirm.error)


class FieldTests(unittest.TestCase):
    def test_errors_appear_after_leaving_the_field_then_follow_the_value(self):
        """covers: REQ-VAL-002"""
        def page():
            email = ui.use_field("", rules.required(), rules.email())
            return ui.input(email, label="Email")

        h = render(page)
        self.assertEqual(errors(h.tree), [])
        inp = find(h.tree, tag("input"))
        h.event(inp["e"]["blur"][0]["h"], seq=1)
        self.assertEqual(errors(h.tree), ["This field is required"])
        h.event(inp["e"]["input"][0]["h"], {"value": "ada@"}, seq=2)
        self.assertEqual(errors(h.tree), ["Enter a valid email address"])
        h.event(inp["e"]["input"][0]["h"], {"value": "ada@example.com"}, seq=3)
        self.assertEqual(errors(h.tree), [])
        h.close()

    def test_inputs_bind_a_field_and_mark_it_required(self):
        """covers: REQ-VAL-007"""
        name = Field("Ada", [rules.required()])
        agree = Field(False, [rules.required("Please accept")])
        size = Field(None, [rules.required()])
        h = render(lambda: ui.column(ui.input(name, label="Name"), ui.textarea(name, label="Bio"),
                                     ui.select(["S", "M"], size, label="Size"), ui.checkbox("Agree", agree)))
        self.assertEqual(find(h.tree, tag("input"))["a"]["value"], "Ada")
        self.assertEqual(find(h.tree, tag("input"))["a"]["aria-required"], "true")
        self.assertEqual(len(find_all(h.tree, has_class("pg-required"))), 3)
        agree.touch()
        size.touch()
        h.tree = h.win.next("render")["tree"]
        self.assertEqual(sorted(errors(h.tree)), ["Please accept", "This field is required"])
        h.close()

    def test_editing_a_field_clears_its_server_error(self):
        """covers: REQ-VAL-006"""
        form = Form(email=("a@b.co", [rules.email()]))
        form.set_errors({"email": "Already registered"})
        h = render(lambda: ui.input(form.email))
        self.assertEqual(errors(h.tree), ["Already registered"])
        h.event(find(h.tree, tag("input"))["e"]["input"][0]["h"], {"value": "c@d.co"}, seq=1)
        self.assertEqual(errors(h.tree), [])
        h.close()


class FormTests(unittest.TestCase):
    def signup(self, handler, **submit_kw):
        holder = {}

        def page():
            form = ui.use_form(email=("", [rules.required(), rules.email()]), age=(None, [rules.number(min=18)]))
            holder["form"] = form
            return ui.form(ui.input(form.email), ui.input(form.age, type="number"),
                           ui.text(form.error.value or ""), ui.text("busy" if form.submitting.value else "idle"),
                           on_submit=form.submit(handler, **submit_kw))

        h = render(page)
        return h, holder

    def submit(self, h, expect_render=True):
        return h.event(find(h.tree, tag("form"))["e"]["submit"][0]["h"], {"form": {}}, seq=0,
                       expect_render=expect_render)

    def test_submit_shows_every_error_and_does_not_call_the_handler(self):
        """covers: REQ-VAL-003"""
        calls = []
        h, holder = self.signup(calls.append)
        self.submit(h)
        self.assertEqual(errors(h.tree), ["This field is required"])
        self.assertEqual(calls, [])
        form = holder["form"]
        form.email.set("ada@example.com")
        form.age.set(30)
        h.tree = h.win.next("render")["tree"]
        self.submit(h, expect_render=False)
        time.sleep(0.1)
        self.assertEqual(calls, [{"email": "ada@example.com", "age": 30}])
        h.close()

    def test_validation_errors_from_the_handler_go_to_their_fields(self):
        """covers: REQ-VAL-004"""
        def save(values):
            raise ValidationError({"email": "Already registered"})

        h, holder = self.signup(save)
        holder["form"].email.set("ada@example.com")
        h.tree = h.win.next("render")["tree"]
        self.submit(h)
        self.assertEqual(errors(h.tree), ["Already registered"])

        def down(values):
            raise ValidationError("Server unavailable")

        h2, holder2 = self.signup(down)
        holder2["form"].email.set("ada@example.com")
        h2.tree = h2.win.next("render")["tree"]
        self.submit(h2)
        self.assertIn("Server unavailable", text_of(h2.tree))
        h.close()
        h2.close()

    def test_background_submit_marks_the_form_busy_until_done(self):
        """covers: REQ-VAL-005"""
        gate, saved = threading.Event(), []

        def save(values):
            gate.wait(5)
            saved.append(values["email"])

        h, holder = self.signup(save, background=True, reset=True)
        holder["form"].email.set("ada@example.com")
        h.tree = h.win.next("render")["tree"]
        self.submit(h)
        self.assertIn("busy", text_of(h.tree))
        gate.set()
        deadline = time.time() + 3
        while "idle" not in text_of(h.tree) and time.time() < deadline:
            h.tree = h.win.next("render")["tree"]
        self.assertEqual(saved, ["ada@example.com"])
        self.assertEqual(holder["form"].email.value, "")  # reset=True
        h.close()

    def test_forms_turn_off_native_browser_validation(self):
        """covers: REQ-VAL-008"""
        h = render(lambda: ui.form(ui.input(State(""))))
        self.assertTrue(find(h.tree, tag("form"))["a"]["novalidate"])
        h.close()


if __name__ == "__main__":
    unittest.main()
