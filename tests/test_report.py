"""Report formatting: name-family grouping in the installed-app table."""

from __future__ import annotations

import contextlib
import io
import unittest

from dorphan import report
from dorphan.matcher import Classified
from dorphan.scanner import Folder


def _claimed(name: str, root: str, size: int) -> Classified:
    return Classified(
        Folder(path=f"X:\\{root}\\{name}", name=name, root_label=root, size=size),
        "claimed", matched_app="app")


def _render(items, **kw) -> str:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report.print_table(items, "Installed-app folders", show_match=True, **kw)
    return buf.getvalue()


class TestFamily(unittest.TestCase):
    def test_leading_word_is_the_key(self):
        self.assertEqual(report._family("Docker Desktop Installer"), ("docker", "Docker"))
        self.assertEqual(report._family("Mozilla-1de4eec8")[0], "mozilla")
        self.assertEqual(report._family("Code_backup"), ("code", "Code"))


class TestGrouping(unittest.TestCase):
    def test_grouped_clusters_same_family_with_header(self):
        items = [
            _claimed("Docker", "Local", 100),
            _claimed("Mozilla", "Roaming", 50),
            _claimed("Docker Desktop", "Roaming", 30),
        ]
        out = _render(items, group=True)
        # Header names the family, its combined size, and the folder count.
        self.assertIn("-- Docker  (", out)
        self.assertIn("2 folders", out)
        # Every family is headed, singletons included (pluralized "1 folder").
        self.assertIn("-- Mozilla  (", out)
        self.assertIn("1 folder)", out)
        # The Docker group (combined 130) outranks the Mozilla singleton (50), so
        # the second Docker row sits above Mozilla despite being smaller (30).
        self.assertLess(out.index("Docker Desktop"), out.index("Mozilla"))
        # Rows are indented beneath their header.
        member = next(l for l in out.splitlines() if "Docker Desktop" in l)
        self.assertTrue(member.startswith("    "))

    def test_ungrouped_is_pure_size_order(self):
        items = [
            _claimed("Docker", "Local", 100),
            _claimed("Mozilla", "Roaming", 50),
            _claimed("Docker Desktop", "Roaming", 30),
        ]
        out = _render(items, group=False)
        self.assertNotIn("--", out)
        # Pure size order: Docker(100), Mozilla(50), Docker Desktop(30).
        self.assertLess(out.index("Mozilla"), out.index("Docker Desktop"))


if __name__ == "__main__":
    unittest.main()
