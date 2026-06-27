import os
import tempfile
import unittest

from dorphan import config, scanner


def make_config(root_path):
    cfg = config._defaults()
    cfg.roots = [("Test", root_path, False)]
    return cfg


class TestScanner(unittest.TestCase):
    def test_enumerate_folders_with_sizes(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "AppOne"))
            os.makedirs(os.path.join(d, "AppTwo", "nested"))
            with open(os.path.join(d, "AppOne", "f.bin"), "wb") as fh:
                fh.write(b"x" * 200)
            # a loose file at the root should be ignored (only dirs are folders)
            with open(os.path.join(d, "loose.txt"), "wb") as fh:
                fh.write(b"z")

            folders = scanner.enumerate_folders(make_config(d), compute_size=True)
            names = sorted(f.name for f in folders)
            self.assertEqual(names, ["AppOne", "AppTwo"])
            one = next(f for f in folders if f.name == "AppOne")
            self.assertEqual(one.size, 200)
            self.assertEqual(one.files, 1)

    def test_progress_callback_fires_per_folder(self):
        with tempfile.TemporaryDirectory() as d:
            for n in ("A", "B", "C"):
                os.makedirs(os.path.join(d, n))
            seen = []
            scanner.enumerate_folders(
                make_config(d), compute_size=True,
                on_progress=lambda done, total, f: seen.append((done, total)),
            )
            self.assertEqual(seen, [(1, 3), (2, 3), (3, 3)])

    def test_scan_roots_skips_missing_and_dedups(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = config._defaults()
            cfg.roots = [
                ("Real", d, False),
                ("Dup", d, False),
                ("Missing", r"Z:\nope\nope", False),
            ]
            roots = scanner.scan_roots(cfg)
            self.assertEqual([label for label, _ in roots], ["Real"])


if __name__ == "__main__":
    unittest.main()
