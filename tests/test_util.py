import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from dorphan import util


class TestPage(unittest.TestCase):
    def test_non_tty_prints_plainly_without_a_pager(self):
        # A redirected/piped stdout isn't a TTY, so output must stay plain so
        # `dorphan log > file` and tests keep working (no pager subprocess).
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            util.page("hello\nworld")
        self.assertEqual(buf.getvalue().splitlines(), ["hello", "world"])

    def test_prints_full_text_when_no_pager_exists(self):
        # On a TTY with tall output but no pager installed, we never install or
        # require one: the complete text is printed instead.
        text = "\n".join(f"line {i}" for i in range(100))
        buf = io.StringIO()
        with mock.patch("sys.stdout") as fake_stdout, \
                mock.patch("dorphan.util._find_pager", return_value=[]):
            fake_stdout.isatty.return_value = True
            util.page(text)
        written = "".join(c.args[0] for c in fake_stdout.write.call_args_list if c.args)
        self.assertIn("line 0", written)
        self.assertIn("line 99", written)

    def test_find_pager_prefers_env_override(self):
        with mock.patch.dict(os.environ, {"DORPHAN_PAGER": "mypager -X"}):
            self.assertEqual(util._find_pager(), ["mypager", "-X"])

    def test_find_pager_empty_when_none_available(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("dorphan.util._git_less", return_value=""):
            self.assertEqual(util._find_pager(), [])

    def test_find_pager_uses_git_less_when_not_on_path(self):
        # less isn't on PATH (PowerShell), but Git ships it; prefer it over more.
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("dorphan.util._git_less", return_value=r"C:\Git\usr\bin\less.exe"):
            self.assertEqual(util._find_pager(), [r"C:\Git\usr\bin\less.exe"])


class TestNormalize(unittest.TestCase):
    def test_strips_non_alphanumeric_and_lowercases(self):
        self.assertEqual(util.normalize("Visual Studio Code!"), "visualstudiocode")
        self.assertEqual(util.normalize("Microsoft.NET"), "microsoftnet")

    def test_empty(self):
        self.assertEqual(util.normalize(""), "")


class TestTokens(unittest.TestCase):
    def test_drops_short_words_and_stopwords(self):
        toks = util.tokens("JetBrains Software Inc", stopwords={"software", "inc"})
        self.assertEqual(toks, {"jetbrains"})

    def test_default_stopwords_used_when_none(self):
        # "app" and "data" are default stopwords; "cursor" survives.
        self.assertEqual(util.tokens("Cursor App Data"), {"cursor"})

    def test_min_length_three(self):
        self.assertNotIn("go", util.tokens("go to"))


class TestHumanSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(util.human_size(0), "0 B")
        self.assertEqual(util.human_size(512), "512 B")
        self.assertEqual(util.human_size(1024), "1.0 KB")
        self.assertEqual(util.human_size(1024 * 1024), "1.0 MB")
        self.assertEqual(util.human_size(5 * 1024 ** 3), "5.0 GB")


class TestDirSize(unittest.TestCase):
    def test_counts_bytes_and_files(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "sub"))
            with open(os.path.join(d, "a.txt"), "wb") as fh:
                fh.write(b"x" * 100)
            with open(os.path.join(d, "sub", "b.txt"), "wb") as fh:
                fh.write(b"y" * 50)
            total, count = util.dir_size(d)
            self.assertEqual(total, 150)
            self.assertEqual(count, 2)

    def test_missing_path_is_zero(self):
        self.assertEqual(util.dir_size(r"Z:\nope\nope"), (0, 0))


if __name__ == "__main__":
    unittest.main()
