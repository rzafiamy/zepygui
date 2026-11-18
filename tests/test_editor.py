"""The code editor component (REQ-CMP-014, REQ-CMP-015)."""
import json
import unittest

from helpers import Harness, find, handler_id

from zepygui import App, State, ui


def editor_node(tree):
    return find(tree, lambda n: n.get("a", {}).get("data-pg-editor") is not None)


class EditorTests(unittest.TestCase):
    def test_the_editor_sends_text_language_and_markers_and_binds_a_state(self):
        """covers: REQ-CMP-014"""
        text = State("name: demo\n")
        app = App("t")
        app.page("/")(lambda: ui.code_editor(text, language="yaml",
                                             markers=[{"line": "2", "message": "oops", "severity": "warning"},
                                                      {"message": "no line", "severity": "bogus"}]))
        h = Harness(app)
        node = editor_node(h.tree)
        self.assertEqual(node["a"]["data-pg-editor"], "yaml")
        self.assertEqual(node["a"]["data-value"], "name: demo\n")
        self.assertEqual(json.loads(node["a"]["data-markers"]), [
            {"line": 2, "message": "oops", "severity": "warning"},
            {"line": 1, "message": "no line", "severity": "error"}])
        h.event(handler_id(node, "input"), {"value": "name: other\n"})
        self.assertEqual(text.value, "name: other\n")
        self.assertEqual(editor_node(h.tree)["a"]["data-value"], "name: other\n")
        h.close()

    def test_an_unknown_language_falls_back_to_plain_text(self):
        """covers: REQ-CMP-014"""
        app = App("t")
        app.page("/")(lambda: ui.code_editor("x", language="cobol", goto=(3, 1)))
        h = Harness(app)
        node = editor_node(h.tree)
        self.assertEqual(node["a"]["data-pg-editor"], "text")
        self.assertEqual(node["a"]["data-goto"], "3:1")
        self.assertNotIn("input", node.get("e") or {})  # no State, no on_change: nothing to send
        h.close()

    def test_save_calls_on_save_with_the_text(self):
        """covers: REQ-CMP-015"""
        saved = []
        app = App("t")
        app.page("/")(lambda: ui.code_editor("a", on_save=saved.append))
        h = Harness(app)
        h.event(handler_id(editor_node(h.tree), "pgsave"), {"value": "a: 1"}, expect_render=False)
        h.win.drain("render", wait=0.3)
        self.assertEqual(saved, ["a: 1"])
        h.close()


if __name__ == "__main__":
    unittest.main()
