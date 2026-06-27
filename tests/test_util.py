import os
import tempfile
import unittest

from dorphan import util


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
