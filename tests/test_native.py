"""Native macOS window (REQ-WIN) and client DOM patching (REQ-RND) in a real window.

These open windows on screen, so they are opt-in:  PYGUI_GUI_TESTS=1 python3 -m unittest test_native
"""
import json
import os
import platform
import subprocess
import sys
import unittest

DRIVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "native_driver.py")
ENABLED = platform.system() == "Darwin" and os.environ.get("PYGUI_GUI_TESTS") == "1"


def run_scenario(name):
    proc = subprocess.run([sys.executable, DRIVER, name], capture_output=True, text=True, timeout=60)
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            result = json.loads(line[len("RESULT "):])
            if "error" in result:
                raise AssertionError(result["error"])
            return result
    raise AssertionError(f"no result from scenario {name!r}:\n{proc.stdout}\n{proc.stderr}")


@unittest.skipUnless(ENABLED, "set PYGUI_GUI_TESTS=1 on macOS to run native window tests")
class NativeWindowTests(unittest.TestCase):
    def test_closing_the_window_returns_from_run_after_shutdown_hooks(self):
        """covers: REQ-WIN-001, REQ-WIN-004"""
        r = run_scenario("close")
        self.assertEqual(r["title"], "Home 0")
        self.assertTrue(r["shutdown_hook_ran"])
        self.assertTrue(r["run_returned"])

    def test_native_mode_opens_no_network_socket(self):
        """covers: REQ-WIN-002"""
        r = run_scenario("sockets")
        self.assertEqual(r["rendered"], "Home 0")
        self.assertEqual(r["sockets"], [])

    def test_static_assets_load_from_relative_urls(self):
        """covers: REQ-WIN-010"""
        self.assertEqual(run_scenario("assets")["natural_width"], 4)

    def test_links_navigate_and_record_the_path_in_the_hash(self):
        """covers: REQ-WIN-011"""
        self.assertEqual(run_scenario("nav")["after"], ["Second page", "#/two", "Two · Native nav", "Two"])

    def test_fast_typing_is_never_overwritten(self):
        """covers: REQ-RND-007"""
        r = run_scenario("typing")
        self.assertEqual(r["typed"], ["Hello world", "echo:Hello world"])
        self.assertEqual(r["state"], "Hello world")
        self.assertEqual(r["cleared"], "")

    def test_dom_nodes_are_reused_and_follow_their_keys(self):
        """covers: REQ-RND-006"""
        title, input_kept, order, keyed_mark = run_scenario("reuse")["after"]
        self.assertEqual(title, "Home 1")
        self.assertTrue(input_kept)
        self.assertEqual(order, ["c", "a", "b"])
        self.assertEqual(keyed_mark, "a")

    def test_log_view_streams_70k_lines_but_draws_only_the_visible_ones(self):
        """covers: REQ-LOG-005"""
        rows, last_number, last_text, total = run_scenario("log")["view"]
        self.assertLess(rows, 100)
        self.assertEqual((last_number, last_text), ("70000", "line 69999"))
        self.assertEqual(total, 70_000)

    def test_virtual_table_keeps_a_small_dom_while_scrolling(self):
        """covers: REQ-CMP-012, REQ-EVT-011"""
        r = run_scenario("virtual")
        self.assertLess(r["before"], 60)
        rows, seen = r["after"]
        self.assertLess(rows, 60)
        self.assertTrue(seen.startswith("file_0500"), seen)

    def test_validation_errors_appear_in_the_window(self):
        """covers: REQ-VAL-009"""
        r = run_scenario("form")
        self.assertEqual(r["empty"], ["This field is required"])
        self.assertEqual(r["typing"], ["Enter a valid email address"])
        self.assertEqual(r["valid"], [0, "saved=1"])
        self.assertEqual(r["saved"], ["ada@example.com"])


if __name__ == "__main__":
    unittest.main()
