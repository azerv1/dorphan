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

    def test_own_config_dir_is_protected(self):
        # dorphan must never delete its own %APPDATA%\dorphan config folder.
        from dorphan import config
        reason = cleaner._target_refusal(config.config_dir(), min_depth=cleaner.ABSOLUTE_MIN_DEPTH)
        self.assertIsNotNone(reason)
        self.assertIn("protected", reason)


class TestPartition(unittest.TestCase):
    def test_splits_deletable_from_refused_and_orders_by_size(self):
        with tempfile.TemporaryDirectory() as d:
            big = make_tree(d, "Big", n_files=5)
            small = make_tree(d, "Small", n_files=1)
            shallow = Classified(
                Folder(path=r"C:\Program Files\Foo", name="Foo",
                       root_label="Program Files", size=999, files=1),
                "orphan", confidence="high")
            deletable, refused = cleaner.partition_orphans([small, shallow, big])
            self.assertEqual([c.folder.name for c in deletable], ["Big", "Small"])
            self.assertEqual(len(refused), 1)
            self.assertEqual(refused[0][0].folder.name, "Foo")
            self.assertIn("depth", refused[0][1])

    def test_clean_excludes_refused_from_numbered_list(self):
        with tempfile.TemporaryDirectory() as d:
            ok = make_tree(d, "Keepable", n_files=2)
            shallow = Classified(
                Folder(path=r"C:\Program Files\Foo", name="Foo",
                       root_label="Program Files", size=1, files=1),
                "orphan", confidence="high")
            with mock.patch("builtins.print") as out:
                count, freed = cleaner.clean([ok, shallow], force=False)
            self.assertEqual(count, 1)  # only the deletable one counted
            printed = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
            self.assertIn("would delete", printed)   # the deletable folder
            self.assertIn("Keepable", printed)       # ...is named in the list
            # Refused folders are summarized as a count, not enumerated per-line.
            self.assertIn("1 orphan(s)", printed)
            self.assertIn("--unsafe", printed)
            self.assertNotIn(r"C:\Program Files\Foo", printed)  # no per-folder dump


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

    def test_list_then_keep(self):
        # [l]ist shows the folder's contents, then re-prompts the same item;
        # answering 'n' keeps it. The subfolder name should appear in output.
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=2)  # creates an 'Alpha/sub' folder
            with mock.patch("builtins.input", side_effect=["l", "n"]) as inp, \
                    mock.patch("builtins.print") as out:
                count, freed = cleaner.clean_interactive([a])
            self.assertEqual(count, 0)
            self.assertTrue(os.path.exists(a.folder.path))  # kept, not deleted
            self.assertEqual(inp.call_count, 2)             # listed, then re-asked
            printed = " ".join(str(c.args[0]) for c in out.call_args_list if c.args)
            self.assertIn("sub", printed)                   # listing showed contents

    def test_list_then_delete(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=2)
            with mock.patch("builtins.input", side_effect=["ls", "y"]):
                count, freed = cleaner.clean_interactive([a])
            self.assertEqual(count, 1)
            self.assertFalse(os.path.exists(a.folder.path))  # deleted after peek

    def test_whitelist_keeps_and_invokes_callback(self):
        with tempfile.TemporaryDirectory() as d:
            a = make_tree(d, "Alpha", n_files=2)
            saved = []
            with mock.patch("builtins.input", side_effect=["w"]):
                count, freed = cleaner.clean_interactive(
                    [a], on_whitelist=lambda name: saved.append(name) or "wl.txt")
            self.assertEqual(count, 0)
            self.assertTrue(os.path.exists(a.folder.path))  # kept, not deleted
            self.assertEqual(saved, ["Alpha"])              # callback got the name

    def test_list_descends_single_subfolder_chain(self):
        # Foo\a\b\c\leaf.txt -> listing Foo should descend to where content lives.
        with tempfile.TemporaryDirectory() as d:
            leaf = os.path.join(d, "Wrap", "a", "b", "c")
            os.makedirs(leaf)
            with open(os.path.join(leaf, "leaf.txt"), "wb") as fh:
                fh.write(b"x")
            f = Classified(Folder(path=os.path.join(d, "Wrap"), name="Wrap",
                                  root_label="Local", size=1, files=1), "orphan")
            with mock.patch("builtins.input", side_effect=["l", "n"]), \
                    mock.patch("builtins.print") as out:
                cleaner.clean_interactive([f])
            printed = " ".join(str(c.args[0]) for c in out.call_args_list if c.args)
            self.assertIn("single-subfolder chain", printed)
            self.assertIn("leaf.txt", printed)  # descended to the real content

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


def _make_dir_link(link, target):
    """Create a directory junction (Windows) or dir symlink (POSIX).

    Returns True on success. Junctions need no privilege; Windows symlinks and
    some sandboxes do, so callers skip the test when this returns False.
    """
    if os.name == "nt":
        import subprocess
        try:
            r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                               capture_output=True)
            return r.returncode == 0 and os.path.exists(link)
        except OSError:
            return False
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False


class TestReparseSafety(unittest.TestCase):
    """Deletion must never cross a junction/symlink into its target (C-1/C-2)."""

    def test_delete_does_not_cross_a_junction(self):
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "victim")
            os.makedirs(victim)
            precious = os.path.join(victim, "precious.txt")
            with open(precious, "wb") as fh:
                fh.write(b"keep me")
            orphan = os.path.join(d, "lvl1", "lvl2", "Orphan")
            os.makedirs(orphan)
            link = os.path.join(orphan, "link")
            if not _make_dir_link(link, victim):
                self.skipTest("cannot create junctions/symlinks here")
            ok, msg = cleaner.delete(orphan)
            self.assertTrue(ok, msg)
            self.assertFalse(os.path.exists(orphan))     # orphan removed
            self.assertTrue(os.path.exists(precious))    # target untouched

    def test_delete_refuses_a_reparse_point_target(self):
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "victim")
            os.makedirs(victim)
            link = os.path.join(d, "lvl1", "lvl2", "linkdir")
            os.makedirs(os.path.dirname(link))
            if not _make_dir_link(link, victim):
                self.skipTest("cannot create junctions/symlinks here")
            ok, msg = cleaner.delete(link)
            self.assertFalse(ok)
            self.assertIn("reparse", msg)
            self.assertTrue(os.path.exists(victim))      # target survived


class TestProtectedPaths(unittest.TestCase):
    def test_canonical_roots_protected_without_env(self):
        # With the environment wiped, the big trees must STILL be protected
        # because they're anchored to the system drive, not read from env (M-1).
        with mock.patch.dict(os.environ, {}, clear=True):
            prot = cleaner._protected_paths()
        for p in ("C:\\", r"C:\Windows", r"C:\Program Files",
                  r"C:\Program Files (x86)", r"C:\ProgramData", r"C:\Users"):
            self.assertIn(cleaner._norm_key(p), prot)


if __name__ == "__main__":
    unittest.main()
