"""Rendering cost, memory and scheduling under load (REQ-PRF), large-data components (REQ-CMP)."""
import contextlib
import gc
import io
import threading
import time
import unittest

from helpers import Harness, find, find_all, has_class, tag, text_of

from zepygui import App, State, ui
from zepygui.app import Renderer, Session
from zepygui.ui import Element


def render(page, **kw):
    app = App("t")
    app.page("/")(page)
    return Harness(app, **kw)


def build_time(n):
    app = App("t")
    app.page("/")(lambda: ui.column(*[ui.row(ui.text(str(i)), ui.badge("b"), key=i) for i in range(n)]))
    s = Session(app, "b", "/", "dark")
    try:
        best = float("inf")
        for _ in range(3):
            t = time.perf_counter()
            Renderer(s).build()
            best = min(best, time.perf_counter() - t)
        return best
    finally:
        s.close()


class RenderCostTests(unittest.TestCase):
    def test_render_time_grows_linearly_with_the_number_of_elements(self):
        """covers: REQ-PRF-001"""
        small, large = build_time(2_000), build_time(8_000)
        # 4x the elements: linear is ~4x, the old quadratic detach was ~16x
        self.assertLess(large / small, 7.0, f"{small * 1000:.1f} ms -> {large * 1000:.1f} ms")

    def test_a_render_leaves_no_reference_cycles(self):
        """covers: REQ-PRF-002"""
        app = App("t")
        app.page("/")(lambda: ui.column(*[ui.card(ui.text(str(i)), ui.icon("home")) for i in range(500)]))
        s = Session(app, "c", "/", "dark")
        gc.collect()
        gc.disable()
        gc.set_debug(gc.DEBUG_SAVEALL)  # keep what the collector finds, to inspect it
        try:
            Renderer(s).build()
            gc.collect()
            # other tests' threads may leave garbage of their own meanwhile: only ours counts
            leaked = [o for o in gc.garbage if isinstance(o, Element)]
            self.assertEqual(leaked, [])
        finally:
            gc.set_debug(0)
            gc.garbage.clear()
            gc.enable()
            s.close()

    def test_an_icon_is_sent_as_one_node(self):
        """covers: REQ-PRF-005"""
        h = render(lambda: ui.icon("settings"))
        svg = find(h.tree, tag("svg"))
        self.assertNotIn("c", svg)
        self.assertIn("<path", svg["h"])
        h.close()


class SchedulingTests(unittest.TestCase):
    def test_changes_from_other_threads_queue_at_most_one_render_request(self):
        """covers: REQ-PRF-003"""
        value = State(0)
        h = render(lambda: ui.text(f"v={value.value}"))
        h.session.queue.put(("fn", time.sleep, (0.3,)))  # keep the worker busy while we flood
        time.sleep(0.05)
        for i in range(10_000):
            value.set(i + 1)
        self.assertLessEqual(h.session.queue.qsize(), 1)
        deadline = time.time() + 3
        while time.time() < deadline and "v=10000" not in text_of(h.tree):
            h.tree = h.win.next("render")["tree"]
        self.assertIn("v=10000", text_of(h.tree))
        h.close()

    def test_a_window_renders_at_most_once_per_frame(self):
        """covers: REQ-PRF-004"""
        value = State(0)
        h = render(lambda: ui.text(f"v={value.value}"))
        stop = time.time() + 0.6

        def flood():
            i = 0
            while time.time() < stop:
                i += 1
                value.set(i)

        t = threading.Thread(target=flood)
        t.start()
        t.join()
        renders = h.win.drain("render", wait=0.2)
        self.assertGreater(len(renders), 3)
        self.assertLessEqual(len(renders), int(0.8 * 60) + 2)
        h.close()

    def test_a_slow_handler_is_reported_once(self):
        """covers: REQ-PRF-006"""
        def slow():
            time.sleep(0.3)

        h = render(lambda: ui.button("slow", slow))
        hid = find(h.tree, tag("button"))["e"]["click"][0]["h"]
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            for seq in (1, 2):
                h.event(hid, seq=seq, expect_render=False)
                h.win.next("ack", timeout=3)
        self.assertEqual(err.getvalue().count("blocked its window"), 1)
        self.assertIn("ui.task", err.getvalue())
        h.close()


ROWS = [{"id": i, "name": f"file_{i:06d}"} for i in range(100_000)]


class VirtualTests(unittest.TestCase):
    def scroll_handler(self, tree):
        node = find(tree, lambda n: "scroll" in n.get("e", {}))
        return node["e"]["scroll"][0]

    def test_virtual_table_renders_only_rows_in_view_and_follows_the_scroll(self):
        """covers: REQ-CMP-011, REQ-EVT-011"""
        h = render(lambda: ui.table(ROWS, ["name"], max_height=360, row_height=36))
        body = [r for r in find_all(h.tree, tag("tr")) if not has_class("pg-vspacer")(r)]
        self.assertLess(len(body), 50)
        self.assertIn("file_000000", text_of(h.tree))
        spec = self.scroll_handler(h.tree)
        self.assertTrue(spec.get("throttle"))
        h.event(spec["h"], {"scrollTop": 36 * 50_000}, seq=1)
        self.assertIn("file_050000", text_of(h.tree))
        self.assertNotIn("file_000000", text_of(h.tree))
        spacers = [r for r in find_all(h.tree, tag("tr")) if has_class("pg-vspacer")(r)]
        self.assertEqual(len(spacers), 2)
        h.close()

    def test_tables_switch_to_virtual_above_a_thousand_rows(self):
        """covers: REQ-CMP-013"""
        h = render(lambda: ui.column(ui.table(ROWS[:1000], ["name"]), ui.table(ROWS[:1001], ["name"])))
        small, big = find_all(h.tree, tag("table"))
        self.assertFalse(has_class("pg-virtual")(small))
        self.assertTrue(has_class("pg-virtual")(big))
        h.close()

    def test_virtual_list_renders_only_items_in_view(self):
        """covers: REQ-CMP-011"""
        h = render(lambda: ui.virtual_list(ROWS, lambda r, i: ui.text(f"{i}:{r['name']}"), item_height=40,
                                           height=400))
        items = find_all(h.tree, has_class("pg-vlist-item"))
        self.assertLess(len(items), 40)
        h.event(self.scroll_handler(h.tree)["h"], {"scrollTop": 40 * 99_990}, seq=1)
        self.assertIn("99999:file_099999", text_of(h.tree))
        h.close()

    def test_elements_inside_rows_render_only_in_their_cell(self):
        """covers: REQ-HOK-006"""
        def page():
            rows = [{"id": i, "name": f"n{i}", "tag": ui.badge(f"TAG{i}")} for i in range(3000)]
            return ui.column(ui.h1("T"), ui.table(rows, ["name", "tag"]))

        h = render(page)
        text = text_of(h.tree)
        self.assertIn("TAG0", text)
        self.assertNotIn("TAG2999", text)  # not in view, and not leaked into the page either
        self.assertEqual(text.count("TAG0"), 1)
        h.close()


if __name__ == "__main__":
    unittest.main()
