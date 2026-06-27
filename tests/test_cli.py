import contextlib
import io
import os
import unittest

from dorphan import cli


class TestParseSize(unittest.TestCase):
    def test_units(self):
        self.assertEqual(cli._parse_size("100MB"), 100 * 1024 ** 2)
        self.assertEqual(cli._parse_size("1.5G"), int(1.5 * 1024 ** 3))
        self.assertEqual(cli._parse_size("200k"), 200 * 1024)
        self.assertEqual(cli._parse_size("2048"), 2048)

    def test_invalid_raises(self):
        with self.assertRaises(Exception):
            cli._parse_size("notasize")


class TestExcluded(unittest.TestCase):
    def test_glob_on_name(self):
        self.assertTrue(cli._excluded("npm-cache", r"C:\x\npm-cache", ["npm*"]))

    def test_substring_on_name(self):
        self.assertTrue(cli._excluded("MetaQuotes", r"C:\x\MetaQuotes", ["quote"]))

    def test_substring_on_path(self):
        self.assertTrue(cli._excluded("X", r"C:\Users\me\AppData\Local\X", ["appdata"]))

    def test_no_match(self):
        self.assertFalse(cli._excluded("Cursor", r"C:\x\Cursor", ["npm*", "yarn"]))


class TestDonate(unittest.TestCase):
    def test_donate_exits_zero_without_scanning(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main(["--donate"])
        self.assertEqual(rc, 0)
        self.assertIn("BTC", out.getvalue())

    def test_addresses_loaded_from_json_file(self):
        coins = [c for c, _ in cli.load_donations()]
        self.assertEqual(coins, ["BTC", "XMR", "AVAX"])

    def test_donate_file_is_valid_json(self):
        self.assertTrue(os.path.isfile(cli.DONATE_FILE))


class TestParserBuilds(unittest.TestCase):
    def test_short_flags_and_confidence(self):
        p = cli.build_parser()
        args = p.parse_args(["-a", "-c", "-d", "-i", "-m", "10mb",
                             "--confidence", "high"])
        self.assertTrue(args.all)
        self.assertTrue(args.clean)
        self.assertTrue(args.delete)
        self.assertTrue(args.interactive)
        self.assertEqual(args.min_size, 10 * 1024 ** 2)
        self.assertEqual(args.confidence, "high")

    def test_confidence_defaults_to_medium(self):
        args = cli.build_parser().parse_args([])
        self.assertEqual(args.confidence, "medium")

    def test_exclude_takes_many_and_repeats(self):
        p = cli.build_parser()
        args = p.parse_args(["--exclude", "npm*", "yarn", "--exclude", "Cursor"])
        self.assertEqual(args.exclude, ["npm*", "yarn", "Cursor"])


if __name__ == "__main__":
    unittest.main()
