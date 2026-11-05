"""File system helpers (REQ-FS) and the file browser components (REQ-FB)."""
import ntpath
import os
import posixpath
import shutil
import tempfile
import time
import unittest
from unittest import mock

import http.client
from urllib.parse import quote

from helpers import Harness, LiveServer, find, find_all, has_class, text_of

from zepygui import App, State, fs, ui


def make_tree(root):
    for d in ("beta", "Alpha", "empty"):
        os.makedirs(os.path.join(root, d))
    for name, size in (("file10.txt", 10), ("file2.txt", 2000), ("photo.PNG", 5), ("report.pdf", 300),
                       (".hidden", 1), ("script.py", 50)):
        with open(os.path.join(root, name), "wb") as f:
            f.write(b"x" * size)


class Tmp(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="zepygui-fs-")
        make_tree(self.root)
        fs.invalidate()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        fs.invalidate()


class FsTests(Tmp):
    def test_listing_puts_folders_first_in_natural_order_and_hides_dot_files(self):
        """covers: REQ-FS-001"""
        names = [e.name for e in fs.listdir(self.root)]
        self.assertEqual(names, ["Alpha", "beta", "empty", "file2.txt", "file10.txt", "photo.PNG", "report.pdf",
                                 "script.py"])
        self.assertIn(".hidden", [e.name for e in fs.listdir(self.root, hidden=True)])

    def test_listing_sorts_by_size_and_date(self):
        """covers: REQ-FS-001"""
        files = [e.name for e in fs.listdir(self.root, sort="size", reverse=True) if not e.is_dir]
        self.assertEqual(files[0], "file2.txt")

    def test_entries_know_their_kind(self):
        """covers: REQ-FS-002"""
        kinds = {e.name: e.kind for e in fs.listdir(self.root)}
        self.assertEqual((kinds["Alpha"], kinds["photo.PNG"], kinds["report.pdf"], kinds["script.py"]),
                         ("folder", "image", "pdf", "code"))
        self.assertEqual(fs.kind_of("song.FLAC"), "audio")
        self.assertEqual(fs.kind_of("noext"), "file")

    def test_listings_are_cached_until_the_folder_changes(self):
        """covers: REQ-FS-003"""
        fs.listdir(self.root)
        self.assertTrue(fs.is_cached(self.root))
        with mock.patch.object(fs, "_scan", side_effect=AssertionError("rescanned")):
            fs.listdir(self.root)
            fs.listdir(self.root, sort="size")  # another order of the same listing: no scan either
        time.sleep(0.01)
        with open(os.path.join(self.root, "new.txt"), "w"):
            pass
        os.utime(self.root, None)
        self.assertIn("new.txt", [e.name for e in fs.listdir(self.root)])

    def test_windows_hidden_and_system_attributes_hide_a_file(self):
        """covers: REQ-FS-004"""
        st = mock.Mock(st_file_attributes=0x2)
        self.assertTrue(fs.is_hidden("desktop.ini", st))
        self.assertTrue(fs.is_hidden("x", mock.Mock(st_file_attributes=0x4)))
        self.assertFalse(fs.is_hidden("x", mock.Mock(st_file_attributes=0x20)))

    def test_windows_paths_split_into_breadcrumbs(self):
        """covers: REQ-FS-005"""
        self.assertEqual(fs.crumbs(r"C:\Users\me\Documents", ntpath),
                         [("Local Disk (C:)", "C:\\"), ("Users", "C:\\Users"), ("me", "C:\\Users\\me"),
                          ("Documents", "C:\\Users\\me\\Documents")])
        self.assertEqual(fs.crumbs(r"\\server\share\dir", ntpath)[0], ("share (\\\\server)", "\\\\server\\share\\"))
        self.assertEqual(fs.crumbs("/home/me", posixpath)[-1], ("me", "/home/me"))

    def test_the_parent_of_a_drive_or_root_is_the_computer(self):
        """covers: REQ-FS-005"""
        self.assertEqual(fs.parent(r"C:\Users", ntpath), "C:\\")
        self.assertEqual(fs.parent("C:\\", ntpath), fs.COMPUTER)
        self.assertEqual(fs.parent(r"\\srv\share", ntpath), fs.COMPUTER)
        self.assertEqual(fs.parent("/", posixpath), fs.COMPUTER)
        self.assertEqual(fs.parent("/home/me/", posixpath), "/home")

    def test_drives_and_places_are_listed(self):
        """covers: REQ-FS-006"""
        drives = fs.drives(max_age=0)
        self.assertTrue(drives and all({"name", "path", "kind", "total", "free"} <= set(d) for d in drives))
        self.assertEqual(fs.places()[0]["name"], "Home")

    def test_names_are_checked_for_every_system(self):
        """covers: REQ-FS-007"""
        self.assertIsNone(fs.check_name("Report 2026.pdf"))
        for bad in ("", "a/b", "a:b", "CON", "nul.txt", "trailing.", "what?"):
            self.assertIsNotNone(fs.check_name(bad), bad)

    def test_new_folders_and_renames_never_overwrite(self):
        """covers: REQ-FS-007"""
        a = fs.make_folder(self.root, "Alpha")
        self.assertEqual(os.path.basename(a), "Alpha (2)")
        with self.assertRaises(FileExistsError):
            fs.rename(os.path.join(self.root, "beta"), "Alpha")
        moved = fs.rename(os.path.join(self.root, "beta"), "gamma")
        self.assertTrue(os.path.isdir(moved))

    def test_trash_moves_to_the_freedesktop_trash(self):
        """covers: REQ-FS-008"""
        if fs.WINDOWS or fs.SYSTEM == "Darwin":
            self.skipTest("freedesktop trash is the Linux path")
        data = tempfile.mkdtemp(dir=self.root)
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": data}):
            target = os.path.join(self.root, "report.pdf")
            fs.trash(target)
            self.assertFalse(os.path.exists(target))
            self.assertTrue(os.path.exists(os.path.join(data, "Trash", "files", "report.pdf")))
            info = open(os.path.join(data, "Trash", "info", "report.pdf.trashinfo")).read()
            self.assertIn("Path=", info)

    def test_sizes_and_times_read_like_a_file_manager(self):
        """covers: REQ-FS-009"""
        self.assertEqual(fs.human_size(1536), "1.5 KB")
        self.assertEqual(fs.human_size(500), "500 B")
        self.assertTrue(fs.human_time(time.time()).startswith("Today"))


def page(fn):
    app = App("t")
    app.page("/")(fn)
    return Harness(app)


def rows(tree):
    return [text_of(find(r, has_class("pg-truncate"))) for r in find_all(tree, has_class("pg-fb-row"))]


def pane(tree):
    return find(tree, has_class("pg-fb-pane"))


class BrowserTests(Tmp):
    def test_the_browser_lists_the_folder(self):
        """covers: REQ-FB-001"""
        h = page(lambda: ui.file_browser(self.root))
        self.assertEqual(rows(h.tree)[:3], ["Alpha", "beta", "empty"])
        self.assertIn("8 items", text_of(find(h.tree, has_class("pg-fb-status"))))
        h.close()

    def test_rows_use_one_delegated_handler(self):
        """covers: REQ-FB-002"""
        h = page(lambda: ui.file_browser(self.root))
        self.assertFalse(any("e" in r for r in find_all(h.tree, has_class("pg-fb-row"))))
        self.assertIn("click", pane(h.tree)["e"])
        h.close()

    def test_double_clicking_a_folder_opens_it_and_updates_the_bound_state(self):
        """covers: REQ-FB-003"""
        where = State(self.root)
        h = page(lambda: ui.file_browser(where))
        hid = pane(h.tree)["e"]["dblclick"][0]["h"]
        h.event(hid, {"item": os.path.join(self.root, "Alpha")})
        self.assertEqual(where.value, os.path.join(self.root, "Alpha"))
        self.assertIn("This folder is empty", text_of(h.tree))
        h.close()

    def test_clicks_select_with_ctrl_and_shift(self):
        """covers: REQ-FB-004"""
        picked = []
        h = page(lambda: ui.file_browser(self.root, on_select=picked.append))
        hid = pane(h.tree)["e"]["click"][0]["h"]
        p = lambda n: os.path.join(self.root, n)  # noqa: E731
        h.event(hid, {"item": p("file2.txt")})
        h.event(hid, {"item": p("report.pdf"), "shift": True})
        self.assertEqual(picked[-1], [p("file2.txt"), p("file10.txt"), p("photo.PNG"), p("report.pdf")])
        h.event(hid, {"item": p("file10.txt"), "ctrl": True})
        self.assertNotIn(p("file10.txt"), picked[-1])
        self.assertEqual(len(find_all(h.tree, has_class("selected"))), 3)
        h.close()

    def test_keyboard_moves_the_selection_and_opens(self):
        """covers: REQ-FB-005"""
        where = State(self.root)
        h = page(lambda: ui.file_browser(where))
        hid = pane(h.tree)["e"]["keydown"][0]["h"]
        h.event(hid, {"key": "ArrowDown"})
        h.event(hid, {"key": "ArrowDown"})
        self.assertEqual(text_of(find(find(h.tree, has_class("selected")), has_class("pg-truncate"))), "beta")
        h.event(hid, {"key": "Enter"})
        self.assertEqual(where.value, os.path.join(self.root, "beta"))
        h.event(pane(h.tree)["e"]["keydown"][0]["h"], {"key": "Backspace"})
        self.assertEqual(where.value, self.root)
        h.close()

    def test_search_and_types_filter_the_listing(self):
        """covers: REQ-FB-006"""
        q = State("")
        h = page(lambda: ui.file_browser(self.root, types=["pdf"]))
        self.assertEqual(rows(h.tree), ["Alpha", "beta", "empty", "report.pdf"])
        h.close()
        h = page(lambda: ui.file_browser(self.root))
        search = find(h.tree, lambda n: n.get("t") == "input" and "Search" in (n.get("a", {}).get("placeholder") or ""))
        h.event(search["e"]["input"][0]["h"], {"value": "file*"})
        self.assertEqual(rows(h.tree), ["file2.txt", "file10.txt"])
        h.close()

    def test_large_folders_render_only_the_rows_in_view(self):
        """covers: REQ-FB-007"""
        big = os.path.join(self.root, "big")
        os.mkdir(big)
        for i in range(3000):
            open(os.path.join(big, f"f{i}.txt"), "w").close()
        h = page(lambda: ui.file_browser(big, height=600))
        self.assertLess(len(find_all(h.tree, has_class("pg-fb-row"))), 120)
        self.assertIn("3,000 items", text_of(find(h.tree, has_class("pg-fb-status"))))
        h.close()

    def test_a_slow_folder_shows_a_placeholder_then_its_listing(self):
        """covers: REQ-FB-008"""
        real = fs.listdir

        def slow(*a, **kw):
            time.sleep(0.4)
            return real(*a, **kw)

        with mock.patch.object(fs, "listdir", side_effect=slow):
            h = page(lambda: ui.file_browser(self.root))
            self.assertIsNotNone(find(h.tree, has_class("pg-fb-loading")))
            tree = h.win.next("render", timeout=3)["tree"]
            self.assertEqual(rows(tree)[0], "Alpha")
        h.close()

    def test_an_unreadable_folder_shows_why(self):
        """covers: REQ-FB-009"""
        h = page(lambda: ui.file_browser(os.path.join(self.root, "missing")))
        self.assertIn("Can't open this folder", text_of(h.tree))
        h.close()

    def test_the_computer_view_lists_drives(self):
        """covers: REQ-FB-010"""
        h = page(lambda: ui.file_browser(fs.COMPUTER))
        self.assertIn("Devices and drives", text_of(h.tree))
        h.close()

    def test_manage_creates_folders(self):
        """covers: REQ-FB-011"""
        h = page(lambda: ui.file_browser(self.root, manage=True))
        h.click(lambda n: n.get("t") == "button" and "New folder" in text_of(n))
        h.click(lambda n: n.get("t") == "button" and text_of(n) == "Create")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "New folder")))
        h.close()

    def test_file_dialog_returns_the_chosen_file(self):
        """covers: REQ-FB-012"""
        show, got = State(True), []
        h = page(lambda: ui.file_dialog(show, start=self.root, on_done=got.append))
        target = os.path.join(self.root, "report.pdf")
        h.event(pane(h.tree)["e"]["click"][0]["h"], {"item": target})
        h.click(lambda n: n.get("t") == "button" and text_of(n) == "Open")
        self.assertEqual(got, [target])
        self.assertFalse(show.value)
        h.close()

    def test_save_dialog_adds_the_extension_and_confirms_replacing(self):
        """covers: REQ-FB-012"""
        show, got = State(True), []
        h = page(lambda: ui.file_dialog(show, mode="save", start=self.root, types=["pdf"], default_name="report",
                                        on_done=got.append))
        h.click(lambda n: n.get("t") == "button" and text_of(n) == "Save")
        self.assertEqual(got, [])  # report.pdf exists: asks first
        h.click(lambda n: n.get("t") == "button" and text_of(n) == "Replace")
        self.assertEqual(got, [os.path.join(self.root, "report.pdf")])
        h.close()

    def test_file_icons_are_single_cached_nodes(self):
        """covers: REQ-FB-013"""
        h = page(lambda: ui.row(ui.file_icon("a.pdf", 48), ui.file_icon("b.pdf", 48), ui.file_icon("x", 20, is_dir=True)))
        icons = find_all(h.tree, has_class("pg-fi"))
        self.assertEqual(len(icons), 3)
        self.assertTrue(all("h" in i and "c" not in i for i in icons))
        self.assertIn("PDF", icons[0]["h"])
        h.close()


class FileUrlTests(Tmp):
    def get(self, port, path, headers=None):
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_local_files_are_served_only_to_the_app_window_with_ranges(self):
        """covers: REQ-FS-010"""
        target = os.path.join(self.root, "file2.txt")
        srv = LiveServer(App("t"))
        try:
            path = "/_pg/file?p=" + quote(target, safe="")
            r, _ = self.get(srv.port, path)
            self.assertEqual(r.status, 403)
            r, body = self.get(srv.port, path, {"Cookie": srv.cookie})
            self.assertEqual((r.status, len(body)), (200, 2000))
            self.assertEqual(r.getheader("Content-Security-Policy"), "sandbox")
            r, body = self.get(srv.port, path, {"Cookie": srv.cookie, "Range": "bytes=10-19"})
            self.assertEqual((r.status, len(body), r.getheader("Content-Range")), (206, 10, "bytes 10-19/2000"))
            r, _ = self.get(srv.port, "/_pg/file?p=" + quote(self.root, safe=""), {"Cookie": srv.cookie})
            self.assertEqual(r.status, 404)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
