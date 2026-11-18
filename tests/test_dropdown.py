"""The dropdown menu (REQ-CMP-017, REQ-CMP-018)."""
import unittest

from helpers import Harness, find, find_all, has_class, handler_id, text_of

from zepygui import App, ui


def page(items, **kw):
    app = App("t")
    app.page("/")(lambda: ui.table([{"n": 1}], ["n", {"key": "n", "label": "", "format": lambda v: ui.dropdown(
        items, **kw)}], on_row_click=lambda r: picked.append(("row", r["n"]))))
    return Harness(app)


picked = []


class DropdownTests(unittest.TestCase):
    def setUp(self):
        picked.clear()

    def test_the_menu_opens_lists_items_and_runs_the_choice(self):
        """covers: REQ-CMP-017"""
        h = page([("Edit", lambda: picked.append("edit"), "edit"), None,
                  {"label": "Delete", "on_click": lambda: picked.append("delete"), "danger": True},
                  {"label": "Off", "disabled": True}])
        self.assertIsNone(find(h.tree, has_class("pg-menu")))
        h.click(lambda n: n.get("a", {}).get("data-pg-trigger") is not None)
        menu = find(h.tree, has_class("pg-menu"))
        items = find_all(menu, has_class("pg-menu-item"))
        self.assertEqual([text_of(i) for i in items], ["Edit", "Delete", "Off"])
        self.assertIsNotNone(find(menu, has_class("pg-menu-sep")))
        self.assertIn("pg-menu-danger", items[1]["a"]["class"])
        self.assertNotIn("click", items[2].get("e") or {})            # disabled: no handler
        h.event(handler_id(items[1], "click"))
        self.assertEqual(picked, ["delete"])                          # the row's handler did not run
        self.assertIsNone(find(h.tree, has_class("pg-menu")))         # and the menu closed
        h.close()

    def test_a_click_outside_or_escape_closes_without_choosing(self):
        """covers: REQ-CMP-018"""
        h = page([("Edit", lambda: picked.append("edit"))], label="Actions")
        trigger = find(h.tree, lambda n: n.get("a", {}).get("data-pg-trigger") is not None)
        self.assertIn("Actions", text_of(trigger))
        h.click(lambda n: n.get("a", {}).get("data-pg-trigger") is not None)
        catcher = find(h.tree, has_class("pg-menu-catch"))
        self.assertTrue(catcher["a"].get("data-pg-esc"))              # Escape clicks the top layer
        for spec in [catcher["e"]["click"][0], find(h.tree, lambda n: n.get("a", {}).get("data-pg-trigger")
                                                     is not None)["e"]["click"][0]]:
            self.assertTrue(spec.get("stop"))                         # never reaches the table row
        h.event(handler_id(catcher, "click"))
        self.assertIsNone(find(h.tree, has_class("pg-menu")))
        self.assertEqual(picked, [])
        h.close()


if __name__ == "__main__":
    unittest.main()
