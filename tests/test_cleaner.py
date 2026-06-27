import os
import tempfile
import unittest
from unittest import mock

from dorphan import cleaner
from dorphan.matcher import Classified
from dorphan.scanner import Folder


def make_tree(parent, name, n_files=3):
    path = os.path.join(parent, name)
    os.makedirs(os.path.join(path, "sub"))
    for i in range(n_files):
        with open(os.path.join(path, "sub", f"f{i}.dat"), "wb") as fh:
            fh.write(b"x" * 10)
    return Classified(Folder(path=path, name=name, root_label="Local",
                             size=10 * n_files, files=n_files), "orphan", confidence="high")


class TestSafety(unittest.TestCase):
    def test_rejects_shallow_paths(self):
        self.assertFalse(cleaner._is_safe_target(r"C:\foo"))
        self.assertFalse(cleaner._is_safe_target(r"C:\\"))

    def test_accepts_deep_existing_dir(self):
        with tempfile.TemporaryDirectory() as d:
            deep = os.path.join(d, "a", "b", "c")
            os.makedirs(deep)
            self.assertTrue(cleaner._is_safe_target(deep))

    def test_depth3_refused_by_default_allowed_when_lowered(self):
        # A real depth-3 dir like C:\Program Files\App: refused at default depth 4.
        with tempfile.TemporaryDirectory() as d:
            # Build an actual 3-component path on the temp drive's root isn't
            # possible portably; instead exercise the depth math directly.
            self.assertIsNotNone(cleaner._target_refusal(r"C:\Program Files\Foo"))
            self.assertIsNone(
                cleaner._target_refusal(r"C:\Program Files\Foo", min_depth=3))

    def test_depth3_floor_allows_shallow_but_not_protected(self):
        # min_depth=3 lets a depth-3 non-protected folder through...
        self.assertIsNone(
            cleaner._target_refusal(r"C:\Program Files\Foo", min_depth=3))
        # ...but never the protected roots themselves, at any min_depth.
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        self.assertIsNotNone(cleaner._target_refusal(pf, min_depth=3))
        self.assertIn("protected", cleaner._target_refusal(pf, min_depth=3))

    def test_depth2_never_deletable_even_below_floor(self):
        # A non-protected depth-2 folder is refused even if min_depth is lowered
        # under the absolute floor of 3 -- the hard floor still wins.
        reason = cleaner._target_refusal(r"C:\Foo", min_depth=2)
        self.assertIsNotNone(reason)
        self.assertIn("too shallow", reason)

    def test_drive_root_never_deletable(self):
        self.assertIsNotNone(cleaner._target_refusal("C:\\", min_depth=1))


class TestDelete(unittest.TestCase):
    def test_delete_removes_tree_and_reports_progress(self):
        with tempfile.TemporaryDirectory() as d:
            c = make_tree(d, "FakeApp", n_files=4)
            seen = []
            ok, msg = cleaner.delete(c.folder.path, on_progress=seen.append)
            self.assertTrue(ok)
            self.assertFalse(os.path.exists(c.folder.path))
            self.assertEqual(seen[-1], 4)  # final count equals file count

    def test_delete_refuses_unsafe(self):
        ok, msg = cleaner.delete(r"C:\foo")
        self.assertFalse(ok)
        self.assertIn("refused", msg)


class TestClean(unittest.TestCase):
    def test_dry_run_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            c = make_tree(d, "FakeApp")
            count, freed = cleaner.clean([c], force=False)
            self.assertEqual(count, 1)
            self.assertEqual(freed, c.folder.size)
            self.assertTrue(os.path.exists(c.folder.path))

    def test_force_deletes_largest_first(self):
        with tempfile.TemporaryDirectory() as d:
            small = make_tree(d, "Small", n_files=1)
            big = make_tree(d, "Big", n_files=5)
            order = []
            real_delete = cleaner.delete

            def spy(path, on_progress=None, **kw):
                order.append(os.path.basename(path))
                return real_delete(path, on_progress, **kw)

            with mock.patch.object(cleaner, "delete", spy):
                count, freed = cleaner.clean([small, big], force=True)
            self.assertEqual(count, 2)
            self.assertEqual(order, ["Big", "Small"])  # largest first


class TestInteractive(unittest.TestCase):
    def test_yes_then_quit(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=5)   # largest -> prompted first
            b = make_tree(d, "Beta", n_files=1)
            with mock.patch("builtins.input", side_effect=["y", "q"]):
                count, freed = cleaner.clean_interactive([a, b])
            self.assertEqual(count, 1)
            self.assertFalse(os.path.exists(a.folder.path))  # deleted
            self.assertTrue(os.path.exists(b.folder.path))    # quit before it

    def test_no_keeps_folder(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=2)
            with mock.patch("builtins.input", side_effect=["n"]):
                count, freed = cleaner.clean_interactive([a])
            self.assertEqual(count, 0)
            self.assertTrue(os.path.exists(a.folder.path))

    def test_min_depth_is_forwarded_to_the_actual_delete(self):
        # Regression: the y/n gate honored min_depth but the real delete didn't,
        # so a folder you confirmed at a lowered depth was still refused.
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=2)
            seen = {}
            real_delete = cleaner.delete

            def spy(path, on_progress=None, **kw):
                seen["min_depth"] = kw.get("min_depth")
                return real_delete(path, on_progress, **kw)

            with mock.patch.object(cleaner, "delete", spy), \
                    mock.patch("builtins.input", side_effect=["y"]):
                count, freed = cleaner.clean_interactive([a], min_depth=3)
            self.assertEqual(count, 1)
            self.assertEqual(seen["min_depth"], 3)
            self.assertFalse(os.path.exists(a.folder.path))


if __name__ == "__main__":
    unittest.main()
