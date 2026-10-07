"""Streaming log buffers (REQ-LOG)."""
import threading
import time
import unittest

from helpers import Harness

from zepygui import App, Log, ui


def view(log):
    app = App("t")
    app.page("/")(lambda: ui.log_view(log))
    return Harness(app)


def collect(h, until, timeout=5.0):
    """Rebuild the client's copy of the log from the messages, the way client.js does."""
    lines, msgs, deadline = [], 0, time.time() + timeout
    start = 0
    while time.time() < deadline and len(lines) < until:
        m = h.win.next("log", timeout=max(0.05, deadline - time.time()))
        msgs += 1
        if m["reset"]:
            start, lines = m["start"], list(m["lines"])
        else:
            lines += m["lines"]
    return start, lines, msgs


class LogTests(unittest.TestCase):
    def test_each_line_reaches_the_window_once_in_order_in_batches(self):
        """covers: REQ-LOG-001"""
        log = Log()
        h = view(log)

        def produce():
            for i in range(20_000):
                log.append(f"line {i}")

        threading.Thread(target=produce).start()
        _, lines, msgs = collect(h, 20_000)
        self.assertEqual(lines, [f"line {i}" for i in range(20_000)])
        self.assertLess(msgs, 2_000)  # batched, not one message per line
        h.close()

    def test_a_log_keeps_at_most_max_lines(self):
        """covers: REQ-LOG-002"""
        log = Log(max_lines=100)
        log.extend(str(i) for i in range(1_000))
        self.assertEqual(len(log), 100)
        self.assertEqual(log.lines()[0], "900")
        self.assertEqual(log.lines(last=2), ["998", "999"])
        h = view(log)
        start, lines, _ = collect(h, 100)
        self.assertEqual((start, lines[0], len(lines)), (900, "900", 100))
        h.close()

    def test_clear_empties_open_views(self):
        """covers: REQ-LOG-003"""
        log = Log()
        log.extend(["a", "b"])
        h = view(log)
        collect(h, 2)
        log.clear()
        m = h.win.next("log")
        self.assertTrue(m["reset"])
        self.assertEqual(m["lines"], [])
        log.append("c")
        self.assertEqual(h.win.next("log")["lines"], ["c"])
        h.close()

    def test_a_reconnected_window_receives_the_lines_again(self):
        """covers: REQ-LOG-004"""
        log = Log()
        log.extend(["a", "b", "c"])
        h = view(log)
        collect(h, 3)
        h.session.detach()
        h.session.attach(h.win)
        start, lines, _ = collect(h, 3)
        self.assertEqual(lines, ["a", "b", "c"])
        h.close()

    def test_a_log_is_a_writable_text_stream(self):
        """covers: REQ-LOG-006"""
        log = Log()
        print("hello", "world", file=log)
        log.write("par")
        log.write("tial\nnext ")
        self.assertEqual(log.lines(), ["hello world", "partial"])
        log.write("line\n")
        self.assertEqual(log.lines()[-1], "next line")


if __name__ == "__main__":
    unittest.main()
