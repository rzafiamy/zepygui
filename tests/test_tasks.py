"""Background work: tasks, processes, commands and the shared event loop (REQ-TSK)."""
import asyncio
import multiprocessing
import sys
import threading
import time
import unittest

from helpers import Harness, find, tag

from pygui import App, CommandError, ui
from pygui.state import current_session


def render(page):
    app = App("t")
    app.page("/")(page)
    return Harness(app)


def square(x):  # top level: process pools pickle functions by name
    import os
    return x * x, os.getpid()


def run_app_in_child(q):
    from pygui import App as ChildApp
    q.put(ChildApp("child").run())


class TaskTests(unittest.TestCase):
    def test_a_task_runs_in_the_background_and_returns_at_once(self):
        """covers: REQ-TSK-001"""
        gate = threading.Event()
        t = time.perf_counter()
        task = ui.task(gate.wait, 5)
        self.assertLess(time.perf_counter() - t, 0.1)
        self.assertIn(task.status.value, ("pending", "running"))
        gate.set()
        self.assertTrue(task.wait(2))
        self.assertEqual(task.status.value, "done")

    def test_callbacks_run_on_the_window_thread(self):
        """covers: REQ-TSK-002"""
        seen = {}
        done = threading.Event()

        def start():
            def ok(result):
                seen["thread"] = threading.current_thread()
                seen["session"] = current_session()
                seen["result"] = result
                done.set()
            ui.task(lambda: 41 + 1, on_done=ok)

        h = render(lambda: ui.button("go", start))
        h.event(_click(h), expect_render=False)
        self.assertTrue(done.wait(2))
        self.assertIs(seen["thread"], h.session.worker)
        self.assertIs(seen["session"], h.session)
        self.assertEqual(seen["result"], 42)

        failed = threading.Event()
        errors = []

        def boom():
            raise ValueError("nope")

        def start_failing():
            ui.task(boom, on_error=lambda e: (errors.append((e, threading.current_thread())), failed.set()))

        h2 = render(lambda: ui.button("go", start_failing))
        h2.event(_click(h2), expect_render=False)
        self.assertTrue(failed.wait(2))
        self.assertIsInstance(errors[0][0], ValueError)
        self.assertIs(errors[0][1], h2.session.worker)
        h.close()
        h2.close()

    def test_a_task_parameter_receives_the_task_and_reports_progress(self):
        """covers: REQ-TSK-003"""
        def work(n, task):
            for i in range(n):
                task.report((i + 1) / n, f"item {i + 1}")
            return n

        task = ui.task(work, 4)
        self.assertEqual(task.wait(2), 4)
        self.assertEqual(task.progress.value, 1.0)
        self.assertEqual(task.message.value, "item 4")

    def test_cancelling_stops_pending_and_running_tasks(self):
        """covers: REQ-TSK-004"""
        started = threading.Event()

        def loop(task):
            started.set()
            while True:
                task.check()
                time.sleep(0.01)

        running = ui.task(loop)
        self.assertTrue(started.wait(2))
        running.cancel()
        self.assertTrue(running._finished.wait(2))
        self.assertEqual(running.status.value, "cancelled")

        ran = []
        blockers = [ui.task(time.sleep, 0.3) for _ in range(40)]  # fill the pool
        pending = ui.task(lambda: ran.append(1))
        pending.cancel()
        for b in blockers:
            b.wait(5)
        time.sleep(0.1)
        self.assertEqual(pending.status.value, "cancelled")
        self.assertEqual(ran, [])

        async def forever():
            await asyncio.sleep(10)

        coro = ui.task(forever)
        time.sleep(0.05)
        coro.cancel()
        coro._finished.wait(2)
        self.assertEqual(coro.status.value, "cancelled")

    def test_an_unhandled_task_error_becomes_a_toast(self):
        """covers: REQ-TSK-005"""
        def boom():
            raise RuntimeError("disk full")

        h = render(lambda: ui.button("go", lambda: ui.task(boom)))
        h.event(_click(h), expect_render=False)
        toast = h.win.next("toast", timeout=3)
        self.assertEqual((toast["kind"], toast["title"], toast["message"]), ("error", "RuntimeError", "disk full"))
        h.close()

    def test_process_tasks_run_in_another_process(self):
        """covers: REQ-TSK-006"""
        import os
        task = ui.task(square, 12, process=True)
        value, pid = task.wait(60)
        self.assertEqual(value, 144)
        self.assertNotEqual(pid, os.getpid())

    def test_commands_stream_their_output_and_report_the_exit_status(self):
        """covers: REQ-TSK-007"""
        lines = []
        code = "import sys\nfor i in range(500): print(f'line {i}')\nsys.exit(0)"
        task = ui.run_command([sys.executable, "-c", code], on_line=lines.append)
        self.assertEqual(task.wait(10), 0)
        self.assertEqual(len(lines), 500)
        self.assertEqual(lines[-1], "line 499")

        failing = ui.run_command([sys.executable, "-c", "import sys; print('x'); sys.exit(3)"])
        self.assertRaises(CommandError, failing.wait, 10)
        self.assertEqual(failing.error.returncode, 3)

        slow = ui.run_command([sys.executable, "-c", "import time; print('go', flush=True); time.sleep(30)"])
        time.sleep(0.5)
        t = time.perf_counter()
        slow.cancel()
        slow._finished.wait(5)
        self.assertEqual(slow.status.value, "cancelled")
        self.assertLess(time.perf_counter() - t, 3)

    def test_coroutines_share_one_loop_and_keep_their_window(self):
        """covers: REQ-TSK-008"""
        seen = []
        done = threading.Event()

        async def handler():
            await asyncio.sleep(0.01)
            seen.append((threading.current_thread().name, current_session(), id(asyncio.get_running_loop())))
            if len(seen) == 2:
                done.set()

        h = render(lambda: ui.column(ui.button("a", handler), ui.button("b", handler)))
        buttons = [n for n in _walk(h.tree) if n.get("t") == "button"]
        for i, b in enumerate(buttons):
            h.event(b["e"]["click"][0]["h"], seq=i + 1, expect_render=False)
        self.assertTrue(done.wait(3))
        self.assertEqual({s[0] for s in seen}, {"pygui-asyncio"})
        self.assertEqual(len({s[2] for s in seen}), 1)
        self.assertTrue(all(s[1] is h.session for s in seen))
        h.close()

    def test_a_process_worker_does_not_open_a_window(self):
        """covers: REQ-TSK-009"""
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=run_app_in_child, args=(q,))
        p.start()
        self.assertIsNone(q.get(timeout=30))
        p.join(10)
        self.assertEqual(p.exitcode, 0)


def _click(h):
    return find(h.tree, tag("button"))["e"]["click"][0]["h"]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for c in node.get("c", []):
            yield from _walk(c)


if __name__ == "__main__":
    unittest.main()
