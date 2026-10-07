"""Reactive state (REQ-STA)."""
import gc
import threading
import unittest

from helpers import Harness, text_of

from zepygui import App, State, ui
from zepygui.state import _local


class Subscriber:
    def __init__(self):
        self.count = 0

    def invalidate(self):
        self.count += 1


def subscribe(state):
    sub = Subscriber()
    _local.rendering = sub
    try:
        state.value
    finally:
        _local.rendering = None
    return sub


class StateTests(unittest.TestCase):
    def test_new_value_notifies_subscribers(self):
        """covers: REQ-STA-001"""
        s = State(1)
        sub = subscribe(s)
        s.set(2)
        s.value = [1]
        s.set([1])  # equal but a different mutable object
        self.assertEqual(sub.count, 3)

    def test_equal_immutable_value_does_not_notify(self):
        """covers: REQ-STA-002"""
        s = State("a")
        sub = subscribe(s)
        s.set("a")
        s.value = "a"
        self.assertEqual(sub.count, 0)

    def test_reading_subscribes_only_during_a_render(self):
        """covers: REQ-STA-003, REQ-STA-004"""
        s = State(0)
        s.value  # no render running: nothing subscribes
        self.assertEqual(len(s._subs), 0)
        sub = subscribe(s)
        self.assertIn(sub, s._subs)

    def test_list_helpers_notify_after_mutating(self):
        """covers: REQ-STA-005"""
        s = State([3, 1])
        sub = subscribe(s)
        s.append(4)
        s.extend([5])
        s.insert(0, 0)
        s.remove(1)
        s.pop()
        s[0] = 9
        del s[0]
        self.assertEqual(s.value, [3, 4])
        s.clear()
        self.assertEqual(sub.count, 8)

    def test_notify_rerenders_without_changing_the_value(self):
        """covers: REQ-STA-006"""
        data = {"n": 1}
        s = State(data)
        sub = subscribe(s)
        data["n"] = 2
        s.notify()
        self.assertEqual(sub.count, 1)
        self.assertIs(s.value, data)

    def test_change_from_a_background_thread_rerenders_the_window(self):
        """covers: REQ-STA-007"""
        app = App("t")
        s = State("before")

        @app.page("/")
        def home():
            return ui.text(s.value)

        h = Harness(app)
        t = threading.Thread(target=lambda: s.set("after"))
        t.start()
        t.join()
        self.assertEqual(text_of(h.win.next("render")["tree"]), "after")
        h.close()

    def test_subscriptions_do_not_keep_windows_alive(self):
        """covers: REQ-STA-008"""
        s = State(0)
        sub = subscribe(s)
        del sub
        gc.collect()
        self.assertEqual(len(s._subs), 0)


if __name__ == "__main__":
    unittest.main()
