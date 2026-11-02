"""Incremental renders: patches against the tree the window shows (REQ-DIF)."""
import json
import random
import unittest

from helpers import Harness, find, has_class, text_of

from zepygui import App, State, ui
from zepygui.diff import apply, diff


def rand_tree(rng, depth=0):
    if depth > 3 or rng.random() < 0.25:
        return rng.choice(["a", "b", "c", "hello"])
    node = {"t": rng.choice(["div", "span", "p"])}
    if rng.random() < 0.4:
        node["k"] = str(rng.randint(0, 6))
    if rng.random() < 0.5:
        node["a"] = {"class": rng.choice(["x", "y"])}
    kids = [rand_tree(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    if kids:
        node["c"] = kids
    return node


def mutate(rng, tree):
    t = json.loads(json.dumps(tree))
    def walk(n):
        if isinstance(n, dict) and "c" in n:
            c = n["c"]
            r = rng.random()
            if r < 0.2 and c:
                c.pop(rng.randrange(len(c)))
            elif r < 0.4:
                c.insert(rng.randint(0, len(c)), rand_tree(rng, 2))
            elif r < 0.5 and len(c) > 1:
                rng.shuffle(c)
            for x in c:
                walk(x)
        if isinstance(n, dict) and rng.random() < 0.2:
            n["a"] = {"class": "z"}
    walk(t)
    return t


class DiffTests(unittest.TestCase):
    def test_applying_the_patch_rebuilds_the_new_tree(self):
        """covers: REQ-DIF-001"""
        rng = random.Random(7)
        for _ in range(3000):
            old = rand_tree(rng)
            new = mutate(rng, old)
            self.assertEqual(apply(old, diff(old, new)), new)

    def test_unchanged_subtrees_become_indices(self):
        """covers: REQ-DIF-002"""
        old = {"t": "div", "c": [{"t": "p", "c": ["big"]}, "x"]}
        new = {"t": "div", "c": [{"t": "p", "c": ["big"]}, "y"]}
        self.assertEqual(diff(old, new), {"t": "div", "o": 0, "d": 1, "c": [0, "y"]})
        self.assertEqual(diff(old, old), 0)

    def test_keyed_children_keep_their_node_when_reordered(self):
        """covers: REQ-DIF-003"""
        a, b = {"t": "li", "k": "a", "c": ["A"]}, {"t": "li", "k": "b", "c": ["B"]}
        patch = diff({"t": "ul", "c": [a, b]}, {"t": "ul", "c": [b, a]})
        self.assertEqual(patch["c"], [1, 0])

    def test_a_window_receives_a_small_patch_after_a_small_change(self):
        """covers: REQ-DIF-004"""
        q = State("")
        rows = [{"id": i, "name": f"row {i}"} for i in range(2000)]
        app = App("t")
        app.page("/")(lambda: ui.column(ui.text(f"q={q.value}"), ui.table(rows, ["name"], virtual=False)))
        h = Harness(app)
        full = len(json.dumps(h.tree))
        q.set("abc")
        m = h.win.next("render")
        self.assertTrue(m.get("diff"))
        self.assertLess(len(json.dumps(m["patch"])), full / 50)
        self.assertEqual(text_of(find(m["tree"], has_class("pg-text"))), "q=abc")
        h.close()

    def test_a_reconnecting_window_gets_a_full_tree(self):
        """covers: REQ-DIF-005"""
        app = App("t")
        app.page("/")(lambda: ui.text("hi"))
        h = Harness(app)
        h.session.attach(h.win)
        m = h.win.next("render")
        self.assertFalse(m.get("diff"))
        h.close()

    def test_resync_requests_a_full_tree(self):
        """covers: REQ-DIF-006"""
        n = State(0)
        app = App("t")
        app.page("/")(lambda: ui.text(str(n.value)))
        h = Harness(app)
        h.session.queue.put(("resync",))
        m = h.win.next("render")
        self.assertFalse(m.get("diff"))
        h.close()


if __name__ == "__main__":
    unittest.main()
