import os
import tempfile
import unittest

from dorphan import recovery
from dorphan.scanner import Folder


def make_tree(parent, name, n_files=3, size=30):
    path = os.path.join(parent, name)
    os.makedirs(os.path.join(path, "sub"))
    for i in range(n_files):
        with open(os.path.join(path, "sub", f"f{i}.dat"), "wb") as fh:
            fh.write(b"x" * 10)
    return Folder(path=path, name=name, root_label="Local", size=size, files=n_files)


class _RecoveryCase(unittest.TestCase):
    """Redirects %LOCALAPPDATA% so the log/trash land in a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._tmp.name
        # Workspace where the "real" folders live (deep enough to be deletable).
        self.work = os.path.join(self._tmp.name, "a", "b", "c", "d")
        os.makedirs(self.work)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old


class TestCompactSize(_RecoveryCase):
    def test_formats(self):
        self.assertEqual(recovery._csize(0), "0B")
        self.assertEqual(recovery._csize(512), "512B")
        self.assertEqual(recovery._csize(1024), "1K")
        self.assertEqual(recovery._csize(1536), "1.5K")
        self.assertEqual(recovery._csize(2 * 1024 ** 3), "2G")


class TestQuarantineRestore(_RecoveryCase):
    def test_quarantine_moves_folder_and_logs(self):
        f = make_tree(self.work, "Foo", n_files=2, size=20)
        ok, ident = recovery.quarantine(f, min_depth=3)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(f.path))      # moved out of place
        entries = recovery.entries()
        self.assertEqual([e["id"] for e in entries], [ident])
        log = recovery.read_log()
        self.assertTrue(log[-1].startswith(f"q "))
        self.assertIn(ident, log[-1])
        self.assertIn(f.path, log[-1])

    def test_restore_brings_it_back(self):
        f = make_tree(self.work, "Bar", n_files=1, size=10)
        ok, ident = recovery.quarantine(f, min_depth=3)
        self.assertTrue(ok)
        ok2, where = recovery.restore(ident)
        self.assertTrue(ok2)
        self.assertEqual(os.path.normpath(where), os.path.normpath(f.path))
        self.assertTrue(os.path.isdir(f.path))        # back in place
        self.assertEqual(recovery.entries(), [])      # gone from trash
        self.assertTrue(recovery.read_log()[-1].startswith("r "))

    def test_restore_unknown_id(self):
        ok, msg = recovery.restore("deadbe")
        self.assertFalse(ok)
        self.assertIn("no recovery entry", msg)

    def test_restore_refuses_when_target_exists(self):
        f = make_tree(self.work, "Baz", n_files=1, size=10)
        ok, ident = recovery.quarantine(f, min_depth=3)
        os.makedirs(f.path)  # something re-created the original path
        ok2, msg = recovery.restore(ident)
        self.assertFalse(ok2)
        self.assertIn("already exists", msg)

    def test_quarantine_refuses_shallow(self):
        f = Folder(path=r"C:\Foo", name="Foo", root_label="x", size=1, files=1)
        ok, reason = recovery.quarantine(f, min_depth=4)
        self.assertFalse(ok)
        self.assertIn("refused", reason)


class TestPermanentLog(_RecoveryCase):
    def test_record_delete_logs_dash_id(self):
        f = make_tree(self.work, "Gone", n_files=3, size=30)
        recovery.record_delete(f)
        line = recovery.read_log()[-1]
        parts = line.split(" ", 5)
        self.assertEqual(parts[0], "d")        # action
        self.assertEqual(parts[4], "-")        # no trash id
        self.assertEqual(parts[5], f.path)     # path is last (may hold spaces)


class TestRetention(_RecoveryCase):
    def test_size_cap_evicts_oldest(self):
        import time
        # Three 100-byte folders; cap at 250 bytes forces the oldest out.
        ids = []
        for i in range(3):
            f = make_tree(self.work, f"F{i}", n_files=1, size=100)
            ok, ident = recovery.quarantine(f, min_depth=3, cap=250)
            self.assertTrue(ok)
            ids.append(ident)
            time.sleep(0.01)  # keep timestamps ordered
        kept = {e["id"] for e in recovery.entries()}
        self.assertNotIn(ids[0], kept)         # oldest evicted
        self.assertIn(ids[2], kept)            # newest survives
        self.assertLessEqual(
            sum(e["size"] for e in recovery.entries()), 250)
        self.assertTrue(any(l.startswith("p ") for l in recovery.read_log()))

    def test_empty_trash_removes_all(self):
        for i in range(2):
            recovery.quarantine(make_tree(self.work, f"E{i}", size=10),
                                min_depth=3)
        count, freed = recovery.empty_trash()
        self.assertEqual(count, 2)
        self.assertEqual(recovery.entries(), [])


if __name__ == "__main__":
    unittest.main()
