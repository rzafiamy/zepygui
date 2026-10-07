"""Rendering (REQ-RND), events (REQ-EVT), routing (REQ-RTE), theming (REQ-THM), dev APIs (REQ-DEV)."""
import asyncio
import time
import unittest

from helpers import Harness, find, find_all, handler_id, tag, text_of

from pygui import App, Event, State, ui


def single_page(fn, path="/", **kw):
    app = App("t")
    app.page("/")(fn)
    return Harness(app, path, **kw)


class RenderTests(unittest.TestCase):
    def test_render_carries_the_tree_and_the_acknowledged_sequence(self):
        """covers: REQ-RND-001"""
        s = State("")
        h = single_page(lambda: ui.input(s))
        self.assertEqual(h.tree["t"], "div")
        h.session.queue.put(("event", handler_id(find(h.tree, tag("input")), "input"), {"value": "x"}, 41))
        self.assertEqual(h.win.next("render")["ack"], 41)
        h.close()

    def test_several_changes_in_one_handler_render_once(self):
        """covers: REQ-RND-002"""
        a, b, c = State(0), State(0), State(0)

        def bump():
            a.set(1)
            b.set(1)
            c.set(1)

        h = single_page(lambda: ui.button(f"{a.value}{b.value}{c.value}", bump))
        h.session.queue.put(("event", handler_id(find(h.tree, tag("button")), "click"), {}, 0))
        renders = h.win.drain("render", wait=0.4)
        self.assertEqual(len(renders), 1)
        self.assertEqual(text_of(renders[0]["tree"]), "111")
        h.close()

    def test_a_failing_page_shows_its_traceback(self):
        """covers: REQ-RND-003"""
        def boom():
            raise ValueError("kaboom")

        h = single_page(boom)
        self.assertIn("kaboom", str(h.tree))
        self.assertIn("This page failed to render", str(h.tree))
        h.close()

    def test_an_unknown_path_shows_not_found(self):
        """covers: REQ-RND-004"""
        h = single_page(lambda: ui.text("home"), path="/nowhere")
        self.assertIn("Page not found", text_of(h.tree))
        h.close()

    def test_window_title_combines_page_and_app_titles(self):
        """covers: REQ-RND-005"""
        app = App("Acme")
        app.page("/", title="Inbox")(lambda: ui.text("x"))
        app.page("/plain")(lambda: ui.text("y"))
        h = Harness(app)
        self.assertEqual(h.win.next("title")["title"], "Inbox · Acme")
        h.session.navigate("/plain")
        self.assertEqual(h.win.next("title")["title"], "Acme")
        h.close()


class EventTests(unittest.TestCase):
    def test_handlers_get_an_argument_only_if_they_accept_one(self):
        """covers: REQ-EVT-001"""
        got = []
        h = single_page(lambda: ui.row(ui.button("a", lambda: got.append("none")),
                                       ui.button("b", lambda e: got.append(e))))
        buttons = h.tree["c"][0]["c"]
        h.session.queue.put(("event", handler_id(buttons[0], "click"), {}, 0))
        h.session.queue.put(("event", handler_id(buttons[1], "click"), {"x": 1}, 0))
        time.sleep(0.2)
        self.assertEqual(got[0], "none")
        self.assertIsInstance(got[1], Event)
        h.close()

    def test_inputs_pass_converted_values(self):
        """covers: REQ-EVT-002"""
        got = []
        h = single_page(lambda: ui.column(
            ui.input(type="number", on_change=got.append), ui.checkbox("c", on_change=got.append),
            ui.slider(1, min=0, max=10, on_change=got.append), ui.input(on_change=got.append)))
        all_inputs = find_all(h.tree, tag("input"))
        num, check, rng, txt = all_inputs
        q = h.session.queue
        for data in ({"value": "3.5"}, {"value": "4"}, {"value": ""}):
            q.put(("event", handler_id(num, "input"), data, 0))
        q.put(("event", handler_id(check, "change"), {"checked": True}, 0))
        q.put(("event", handler_id(rng, "input"), {"value": "7"}, 0))
        q.put(("event", handler_id(txt, "input"), {"value": "hi"}, 0))
        time.sleep(0.3)
        self.assertEqual(got, [3.5, 4, None, True, 7, "hi"])
        h.close()

    def test_select_returns_the_original_option_object(self):
        """covers: REQ-EVT-003"""
        got = []
        h = single_page(lambda: ui.select([("a", "A"), (3, "Three"), (2.5, "Half")], on_change=got.append))
        sel = find(h.tree, tag("select"))
        h.session.queue.put(("event", handler_id(sel, "change"), {"value": "3"}, 0))
        h.session.queue.put(("event", handler_id(sel, "change"), {"value": "2.5"}, 0))
        time.sleep(0.2)
        self.assertEqual(got, [3, 2.5])
        self.assertIsInstance(got[0], int)
        h.close()

    def test_handler_errors_become_toasts_and_the_window_continues(self):
        """covers: REQ-EVT-004"""
        n = State(0)

        def bad():
            raise RuntimeError("nope")

        h = single_page(lambda: ui.row(ui.button("bad", bad), ui.button(str(n.value), lambda: n.set(1))))
        buttons = h.tree["c"][0]["c"]
        h.session.queue.put(("event", handler_id(buttons[0], "click"), {}, 0))
        toast = h.win.next("toast")
        self.assertEqual((toast["kind"], toast["message"]), ("error", "nope"))
        h.event(handler_id(buttons[1], "click"))
        self.assertIn("1", text_of(h.tree))
        h.close()

    def test_async_handlers_do_not_block_the_window(self):
        """covers: REQ-EVT-005"""
        slow, fast = State("slow-pending"), State("fast-pending")

        async def slow_handler():
            await asyncio.sleep(0.4)
            slow.set("slow-done")

        h = single_page(lambda: ui.row(ui.button(slow.value, slow_handler),
                                       ui.button(fast.value, lambda: fast.set("fast-done"))))
        buttons = h.tree["c"][0]["c"]
        h.session.queue.put(("event", handler_id(buttons[0], "click"), {}, 0))
        h.session.queue.put(("event", handler_id(buttons[1], "click"), {}, 0))
        first = text_of(h.win.next("render")["tree"])
        self.assertIn("fast-done", first)
        self.assertIn("slow-pending", first)
        self.assertIn("slow-done", text_of(h.win.next("render", timeout=2)["tree"]))
        h.close()

    def test_debounce_is_sent_with_the_event_spec(self):
        """covers: REQ-EVT-006"""
        h = single_page(lambda: ui.input(State(""), debounce=300))
        self.assertEqual(find(h.tree, tag("input"))["e"]["input"][0]["debounce"], 300)
        h.close()

    def test_on_enter_listens_to_keydown_for_enter_only(self):
        """covers: REQ-EVT-007"""
        h = single_page(lambda: ui.input(on_enter=print))
        self.assertEqual(find(h.tree, tag("input"))["e"]["keydown"][0]["keys"], ["Enter"])
        h.close()

    def test_events_are_processed_in_arrival_order(self):
        """covers: REQ-EVT-008"""
        seen = []
        h = single_page(lambda: ui.input(on_change=seen.append))
        hid = handler_id(find(h.tree, tag("input")), "input")
        for i in range(50):
            h.session.queue.put(("event", hid, {"value": str(i)}, i + 1))
        time.sleep(0.4)
        self.assertEqual(seen, [str(i) for i in range(50)])
        h.close()

    def test_events_for_unknown_handlers_are_ignored(self):
        """covers: REQ-EVT-009"""
        n = State(0)
        h = single_page(lambda: ui.button(str(n.value), lambda: n.set(n.value + 1)))
        h.session.queue.put(("event", "r.9.9:click", {}, 0))
        h.click(tag("button"))
        self.assertEqual(text_of(find(h.tree, tag("button"))), "1")
        h.close()


class RoutingTests(unittest.TestCase):
    def test_static_paths_match_with_or_without_trailing_slash(self):
        """covers: REQ-RTE-001"""
        app = App("t")
        app.page("/about")(lambda: ui.text("about"))
        for path in ("/about", "/about/"):
            h = Harness(app, path)
            self.assertEqual(text_of(h.tree), "about")
            h.close()
        h = Harness(app, "/about/x")
        self.assertIn("Page not found", text_of(h.tree))
        h.close()

    def test_typed_parameters_are_converted(self):
        """covers: REQ-RTE-002"""
        app = App("t")
        app.page("/p/{n:int}/{x:float}/{rest:path}")(lambda n, x, rest: ui.text(repr((n + 1, x * 2, rest))))
        h = Harness(app, "/p/41/1.5/a/b")
        self.assertEqual(text_of(h.tree), "(42, 3.0, 'a/b')")
        h.close()

    def test_pages_receive_only_parameters_they_accept(self):
        """covers: REQ-RTE-003"""
        app = App("t")
        app.page("/u/{uid}/{tab}")(lambda uid: ui.text(uid))
        h = Harness(app, "/u/7/info")
        self.assertEqual(text_of(h.tree), "7")
        h.close()

    def test_navigate_updates_the_client_and_renders_the_target(self):
        """covers: REQ-RTE-004"""
        app = App("t")
        app.page("/")(lambda: ui.button("go", lambda: ui.navigate("/next")))
        app.page("/next")(lambda: ui.text("arrived"))
        h = Harness(app)
        h.session.queue.put(("event", handler_id(find(h.tree, tag("button")), "click"), {}, 0))
        self.assertEqual(h.win.next("nav")["path"], "/next")
        self.assertEqual(text_of(h.win.next("render")["tree"]), "arrived")
        h.close()

    def test_query_string_is_exposed_on_the_session(self):
        """covers: REQ-RTE-005"""
        app = App("t")
        app.page("/s")(lambda: ui.text(repr(ui.session().query)))
        h = Harness(app, "/s?q=hi&tag=a&tag=b")
        self.assertEqual(text_of(h.tree), repr({"q": "hi", "tag": ["a", "b"]}))
        h.close()

    def test_layout_wraps_every_page(self):
        """covers: REQ-RTE-006"""
        app = App("t")
        app.layout(lambda content: ui.div(ui.text("SHELL"), content, cls="shell"))
        app.page("/")(lambda: ui.text("one"))
        app.page("/two")(lambda: ui.text("two"))
        for path, body in (("/", "one"), ("/two", "two")):
            h = Harness(app, path)
            self.assertEqual(h.tree["a"]["class"], "shell")
            self.assertEqual(text_of(h.tree), f"SHELL{body}")
            h.close()


class ThemeTests(unittest.TestCase):
    def test_set_theme_reaches_the_window_and_the_session(self):
        """covers: REQ-THM-002"""
        h = single_page(lambda: ui.button("t", lambda: ui.set_theme("light")), theme="dark")
        h.session.queue.put(("event", handler_id(find(h.tree, tag("button")), "click"), {}, 0))
        self.assertEqual(h.win.next("theme")["theme"], "light")
        time.sleep(0.05)
        self.assertEqual(h.session.theme.value, "light")
        h.close()

    def test_accent_colour_becomes_the_accent_variable(self):
        """covers: REQ-THM-003"""
        page = App("t", accent="#12ab34", radius=7)._index_html()
        self.assertIn("--accent:#12ab34", page)
        self.assertIn("--radius:7px", page)


class DevApiTests(unittest.TestCase):
    def test_exposed_functions_return_results_or_errors(self):
        """covers: REQ-DEV-006"""
        app = App("t")
        app.page("/")(lambda: ui.text("x"))
        app.expose(lambda a, b: a + b, name="add")

        @app.expose
        async def later(x):
            await asyncio.sleep(0.01)
            return x * 2

        h = Harness(app)
        h.session.queue.put(("call", 1, "add", [2, 3]))
        h.session.queue.put(("call", 2, "later", [21]))
        h.session.queue.put(("call", 3, "missing", []))
        # an async function resolves on the shared loop, so results come back by id, not in order
        by_id = {r["id"]: r for r in (h.win.next("result") for _ in range(3))}
        r1, r2, r3 = by_id[1], by_id[2], by_id[3]
        self.assertEqual((r1["ok"], r1["value"]), (True, 5))
        self.assertEqual(r2["value"], 42)
        self.assertFalse(r3["ok"])
        self.assertIn("missing", r3["error"])
        h.close()

    def test_timers_run_periodically_while_the_app_runs(self):
        """covers: REQ-DEV-007"""
        app = App("t")
        ticks = []
        app.timer(0.05)(lambda: ticks.append(1))
        app._startup_hooks()
        time.sleep(0.4)
        app._shutdown_hooks()
        count = len(ticks)
        time.sleep(0.2)
        self.assertGreaterEqual(count, 3)
        self.assertLessEqual(len(ticks), count + 1)


if __name__ == "__main__":
    unittest.main()
