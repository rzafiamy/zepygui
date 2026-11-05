"""Element tree and its serialisation (REQ-TRE), hooks and components (REQ-HOK)."""
import os
import unittest

from helpers import Harness, find, handler_id, has_class, tag, text_of

from zepygui import App, Log, State, ui


def render(page_fn, **kw):
    app = App("t")
    app.page("/")(page_fn)
    h = Harness(app, **kw)
    return h


class TreeTests(unittest.TestCase):
    def test_nested_calls_and_with_blocks_build_the_same_tree(self):
        """covers: REQ-TRE-001"""
        def nested():
            return ui.card(ui.h3("Title"), ui.row(ui.text("a"), ui.text("b")))

        def with_blocks():
            with ui.card():
                ui.h3("Title")
                with ui.row():
                    ui.text("a")
                    ui.text("b")

        a, b = render(nested), render(with_blocks)
        self.assertEqual(a.tree, b.tree)
        a.close(), b.close()

    def test_on_keywords_register_dom_events(self):
        """covers: REQ-TRE-002"""
        h = render(lambda: ui.el("div", "x", on_mouseenter=lambda: None, on_dblclick=lambda e: None))
        self.assertEqual(set(h.tree["c"][0]["e"]), {"mouseenter", "dblclick"})
        h.close()

    def test_other_keywords_become_attributes(self):
        """covers: REQ-TRE-003"""
        h = render(lambda: ui.el("label", "x", data_user_id=3, for_="email", aria_label="L"))
        self.assertEqual(h.tree["c"][0]["a"], {"data-user-id": 3, "for": "email", "aria-label": "L"})
        h.close()

    def test_numeric_styles_get_px_except_unitless_and_custom_properties(self):
        """covers: REQ-TRE-004"""
        h = render(lambda: ui.div(style={"padding": 12, "opacity": 0.5, "z_index": 2, "--cols": 3, "flex": 1}))
        self.assertEqual(h.tree["c"][0]["a"]["style"], "padding:12px;opacity:0.5;z-index:2;--cols:3;flex:1")
        h.close()

    def test_none_and_booleans_render_nothing(self):
        """covers: REQ-TRE-005"""
        h = render(lambda: ui.div(None, True, False, "kept"))
        self.assertEqual(h.tree["c"][0]["c"], ["kept"])
        h.close()

    def test_states_render_their_current_value(self):
        """covers: REQ-TRE-006"""
        s = State("v1")
        h = render(lambda: ui.div(s, title=s))
        self.assertEqual((h.tree["c"][0]["c"], h.tree["c"][0]["a"]["title"]), (["v1"], "v1"))
        s.set("v2")
        tree = h.win.next("render")["tree"]
        self.assertEqual(tree["c"][0]["c"], ["v2"])
        h.close()

    def test_keys_are_sent_to_the_client(self):
        """covers: REQ-TRE-007"""
        h = render(lambda: ui.div(*[ui.span(n, key=f"k{n}") for n in range(3)]))
        self.assertEqual([c["k"] for c in h.tree["c"][0]["c"]], ["k0", "k1", "k2"])
        h.close()

    def test_fragments_add_no_wrapper(self):
        """covers: REQ-TRE-008"""
        h = render(lambda: ui.div(ui.fragment(ui.span("a"), ui.span("b"))))
        self.assertEqual([c["t"] for c in h.tree["c"][0]["c"]], ["span", "span"])
        h.close()


class HookTests(unittest.TestCase):
    def test_use_state_survives_rerenders(self):
        """covers: REQ-HOK-001"""
        def page():
            n = ui.use_state(0)
            return ui.button(str(n.value), lambda: n.set(n.value + 1))

        h = render(page)
        h.click(tag("button"))
        h.click(tag("button"))
        self.assertEqual(text_of(find(h.tree, tag("button"))), "2")
        h.close()

    def test_component_instances_have_independent_state(self):
        """covers: REQ-HOK-002"""
        @ui.component
        def Counter(label):
            n = ui.use_state(0)
            return ui.button(f"{label}:{n.value}", lambda: n.set(n.value + 1))

        h = render(lambda: ui.row(Counter("a"), Counter("b")))
        h.event(handler_id(h.tree["c"][0]["c"][1], "click"))
        self.assertEqual([text_of(b) for b in h.tree["c"][0]["c"]], ["a:0", "b:1"])
        h.close()

    def test_use_state_outside_a_render_raises(self):
        """covers: REQ-HOK-003"""
        with self.assertRaises(RuntimeError):
            ui.use_state(0)

    def test_callable_default_is_evaluated_once(self):
        """covers: REQ-HOK-004"""
        calls = []

        def make():
            calls.append(1)
            return 5

        flag = State(0)

        def page():
            v = ui.use_state(make)
            return ui.text(f"{v.value}-{flag.value}")

        h = render(page)
        flag.set(1)
        h.win.next("render")
        self.assertEqual(len(calls), 1)
        h.close()

    def test_state_of_unmounted_components_is_discarded(self):
        """covers: REQ-HOK-005"""
        show = State(True)

        @ui.component
        def Child():
            ui.use_state("x")
            return ui.text("child")

        h = render(lambda: ui.div(Child() if show.value else None))
        self.assertEqual(len(h.session.hooks), 1)
        show.set(False)
        h.win.next("render")
        self.assertEqual(len(h.session.hooks), 0)
        h.close()

    def test_elements_passed_to_components_do_not_leak_where_created(self):
        """covers: REQ-HOK-006"""
        @ui.component
        def Ignore(content):
            return ui.text("shown")

        def page():
            with ui.column():
                Ignore(ui.text("LEAK"))

        h = render(page)
        self.assertNotIn("LEAK", text_of(h.tree))
        self.assertIn("shown", text_of(h.tree))
        h.close()


class ComponentTests(unittest.TestCase):
    def test_modal_renders_nothing_while_closed(self):
        """covers: REQ-CMP-002"""
        open_ = State(False)
        h = render(lambda: ui.column(ui.modal(open_, ui.text("SECRET"), footer=ui.button("ok"))))
        self.assertNotIn("SECRET", text_of(h.tree))
        open_.set(True)
        self.assertIn("SECRET", text_of(h.win.next("render")["tree"]))
        h.close()

    def test_tabs_render_only_the_active_tab(self):
        """covers: REQ-CMP-003"""
        h = render(lambda: ui.tabs({"One": ui.text("first"), "Two": lambda: ui.text("second")}))
        self.assertIn("first", text_of(h.tree))
        self.assertNotIn("second", text_of(h.tree))
        h.click(lambda n: n.get("t") == "button" and text_of(n) == "Two")
        self.assertIn("second", text_of(h.tree))
        self.assertNotIn("first", text_of(h.tree))
        h.close()

    def test_table_sorts_ascending_descending_then_unsorted(self):
        """covers: REQ-CMP-004"""
        rows = [{"name": "b", "n": 2}, {"name": "c", "n": 3}, {"name": "a", "n": 1}]
        h = render(lambda: ui.table(rows, ["name", "n"]))

        def names():
            return [text_of(tr["c"][0]) for tr in find(h.tree, tag("tbody"))["c"]]

        header = lambda n: n.get("t") == "th" and "Name" in text_of(n)  # noqa: E731
        h.click(header)
        self.assertEqual(names(), ["a", "b", "c"])
        h.click(header)
        self.assertEqual(names(), ["c", "b", "a"])
        h.click(header)
        self.assertEqual(names(), ["b", "c", "a"])
        h.close()

    def test_two_parameter_formatters_receive_the_row(self):
        """covers: REQ-CMP-005"""
        rows = [{"name": "Ada", "email": "ada@x.io"}]
        h = render(lambda: ui.table(rows, [{"key": "name", "format": lambda v, r: f"{v} <{r['email']}>"}]))
        self.assertIn("Ada <ada@x.io>", text_of(h.tree))
        h.close()

    def test_nav_item_is_active_on_its_path_and_below(self):
        """covers: REQ-CMP-006"""
        def page():
            return ui.div(ui.nav_item("Home", "/", key="h"), ui.nav_item("Users", "/users", key="u"))

        app = App("t")
        app.page("/users/{uid}")(lambda uid: page())
        h = Harness(app, "/users/7")
        active = [n["k"] for n in h.tree["c"][0]["c"] if "active" in n["a"]["class"]]
        self.assertEqual(active, ["u"])
        h.close()

    def test_charts_show_an_empty_state_without_data(self):
        """covers: REQ-CMP-007"""
        h = render(lambda: ui.column(ui.line_chart([]), ui.bar_chart({})))
        self.assertEqual(text_of(h.tree).count("No data"), 2)
        h.close()

    def test_bound_input_updates_its_state(self):
        """covers: REQ-CMP-008"""
        name = State("")
        h = render(lambda: ui.column(ui.input(name), ui.text(f"Hello {name.value}")))
        h.event(handler_id(find(h.tree, tag("input")), "input"), {"value": "Ada"}, seq=1)
        self.assertEqual(name.value, "Ada")
        self.assertIn("Hello Ada", text_of(h.tree))
        self.assertEqual(find(h.tree, tag("input"))["a"]["value"], "Ada")
        h.close()

    def test_theme_toggle_shows_the_theme_it_switches_to(self):
        """covers: REQ-CMP-009"""
        sun = ui.ICONS["sun"][1]
        h = render(lambda: ui.theme_toggle(), theme="dark")
        self.assertIn(sun, str(h.tree))
        h.close()
        h = render(lambda: ui.theme_toggle(), theme="light")
        self.assertNotIn(sun, str(h.tree))
        h.close()

    def test_every_public_component_renders(self):
        """covers: REQ-CMP-001"""
        minimal = {
            "column": lambda: ui.column("x"), "row": lambda: ui.row("x"), "grid": lambda: ui.grid("x"),
            "container": lambda: ui.container("x"), "spacer": ui.spacer, "divider": lambda: ui.divider("or"),
            "card": lambda: ui.card("x", title="T", actions=ui.badge("b")), "scroll_area": lambda: ui.scroll_area("x"),
            "shell": lambda: ui.shell("x", sidebar=ui.sidebar(title="S"), header=ui.header(title="H")),
            "sidebar": lambda: ui.sidebar(title="S"), "nav_item": lambda: ui.nav_item("n", "/"),
            "nav_section": lambda: ui.nav_section("s"), "header": lambda: ui.header(title="H"),
            "h1": lambda: ui.h1("x"), "h2": lambda: ui.h2("x"), "h3": lambda: ui.h3("x"), "h4": lambda: ui.h4("x"),
            "text": lambda: ui.text("x"), "code": lambda: ui.code("x"), "code_block": lambda: ui.code_block("x"),
            "link": lambda: ui.link("x", to="/"), "markdown": lambda: ui.markdown("# x"), "kbd": lambda: ui.kbd("K"),
            "button": lambda: ui.button("x", icon="plus"), "icon_button": lambda: ui.icon_button("x", tooltip="t"),
            "input": lambda: ui.input(State("")), "textarea": lambda: ui.textarea(State("")),
            "checkbox": lambda: ui.checkbox("c", State(True)), "switch": lambda: ui.switch("s", State(False)),
            "slider": lambda: ui.slider(State(5)), "select": lambda: ui.select(["a"], State("a")),
            "radio_group": lambda: ui.radio_group(["a", "b"], State("a")),
            "segmented": lambda: ui.segmented(["a", "b"], State("a")), "form": lambda: ui.form(on_submit=print),
            "icon": lambda: ui.icon("home"), "badge": lambda: ui.badge("b"), "avatar": lambda: ui.avatar("A B"),
            "progress": lambda: ui.progress(40, show_value=True), "spinner": ui.spinner,
            "alert": lambda: ui.alert("a", title="t"), "stat": lambda: ui.stat("s", 1, delta="+1", spark=[1, 2]),
            "image": lambda: ui.image("x.png"), "table": lambda: ui.table([{"a": 1}]),
            "tabs": lambda: ui.tabs({"a": "x"}), "accordion": lambda: ui.accordion({"q": "a"}),
            "modal": lambda: ui.modal(State(True), "x", title="m"), "tooltip": lambda: ui.tooltip("x", "tip"),
            "empty_state": lambda: ui.empty_state("e"), "theme_toggle": ui.theme_toggle,
            "line_chart": lambda: ui.line_chart({"a": [1, 2], "b": [2, 1]}),
            "bar_chart": lambda: ui.bar_chart({"a": 1}), "donut": lambda: ui.donut({"a": 1, "b": 2}),
            "sparkline": lambda: ui.sparkline([1, 3, 2]),
            "virtual_list": lambda: ui.virtual_list(list(range(100)), lambda i: ui.text(str(i))),
            "log_view": lambda: ui.log_view(Log()),
            "file_browser": lambda: ui.file_browser(os.path.dirname(__file__), height=300),
            "file_dialog": lambda: ui.file_dialog(State(True), start=os.path.dirname(__file__)),
            "file_icon": lambda: ui.file_icon("a.pdf", 32), "breadcrumbs": lambda: ui.breadcrumbs(["a", "b"]),
        }
        not_components = {"Element", "component", "use_state", "use_form", "use_field", "el", "div", "span", "fragment", "html", "session",
                          "register_icon", "toast", "navigate", "run_js", "set_title", "set_theme", "toggle_theme",
                          "copy", "background", "open_file", "save_file", "choose_folder", "notify", "open_url",
                          "open_path", "task", "run_command", "file_url"}
        self.assertEqual(set(ui.__all__) - not_components, set(minimal), "a component is missing from this test")
        h = render(lambda: ui.div(*[fn() for fn in minimal.values()]))
        self.assertGreater(len(h.tree["c"][0]["c"]), len(minimal) - 5)
        self.assertIsNotNone(find(h.tree, has_class("pg-donut")))
        h.close()


if __name__ == "__main__":
    unittest.main()
