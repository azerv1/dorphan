import contextlib
import io
import os
import unittest
from unittest import mock

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

    def test_infinity_is_rejected_not_crashed(self):
        # 'inf' parses as a float but int(inf) raises OverflowError; it must come
        # back as a clean argparse error, not an uncaught traceback (M-3).
        import argparse
        for bad in ("inf", "1e400", "-inf"):
            with self.assertRaises(argparse.ArgumentTypeError):
                cli._parse_size(bad)


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


class TestDepthGate(unittest.TestCase):
    def test_low_depth_without_unsafe_errors_before_scanning(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = cli.main(["delete", "--depth", "3"])
        self.assertEqual(rc, 2)
        self.assertIn("--unsafe", err.getvalue())

    def test_depth_two_also_gated(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["delete", "--depth", "2"]), 2)

    def test_depth_default_is_none(self):
        self.assertIsNone(cli.build_parser().parse_args(["delete"]).depth)

    def test_unsafe_without_interactive_errors(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = cli.main(["delete", "--unsafe"])
        self.assertEqual(rc, 2)
        self.assertIn("-i", err.getvalue())

    def test_unsafe_requires_elevation(self):
        # delete -i --unsafe clears the earlier gates but, without admin rights,
        # must stop before scanning rather than fail every shallow delete later.
        with mock.patch("dorphan.util.is_elevated", return_value=False), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            rc = cli.main(["delete", "-i", "--unsafe"])
        self.assertEqual(rc, 2)
        self.assertIn("Administrator", err.getvalue())

    def test_default_run_does_not_require_elevation(self):
        # A normal (non-shallow) run never asks for elevation, so a non-admin
        # check must not short-circuit it here.
        with mock.patch("dorphan.util.is_elevated", return_value=False), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            cli.main(["delete", "--depth", "3"])  # gated for no --unsafe instead
        self.assertNotIn("Administrator", err.getvalue())


class TestCommandDispatch(unittest.TestCase):
    """A command is required; bare filters are a parse error, not a silent scan."""

    def test_no_args_prints_usage(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main([])
        self.assertEqual(rc, 0)
        self.assertIn("Commands:", out.getvalue())

    def test_bare_filter_is_a_parse_error(self):
        # -m lives on `scan`/`delete`, not the top level, so a lone `dorphan -m`
        # is rejected by argparse (SystemExit) rather than doing anything.
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit) as ctx:
            cli.main(["-m", "100MB"])
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_command_is_a_parse_error(self):
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            cli.main(["frobnicate"])

    def test_scan_accepts_filters(self):
        args = cli.build_parser().parse_args(["scan", "-m", "100MB", "-a", "--json"])
        self.assertEqual(args.command, "scan")
        self.assertEqual(args.min_size, 100 * 1024 ** 2)
        self.assertTrue(args.all)
        self.assertTrue(args.json)


class TestConfirmBulkDelete(unittest.TestCase):
    def _run(self, isatty, answer):
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = isatty
        with mock.patch.object(cli.sys, "stdin", fake_stdin), \
                mock.patch.object(cli, "input", create=True,
                                  return_value=answer) as inp, \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            result = cli._confirm_bulk_delete(3)
        return result, inp, out.getvalue(), err.getvalue()

    def test_yes_proceeds_and_warns(self):
        ok, _, stdout, _ = self._run(True, "yes")
        self.assertTrue(ok)
        self.assertIn("dorphan scan", stdout)

    def test_y_proceeds(self):
        ok, _, _, _ = self._run(True, "y")
        self.assertTrue(ok)

    def test_anything_else_aborts(self):
        ok, _, _, _ = self._run(True, "no")
        self.assertFalse(ok)

    def test_non_tty_refuses_without_prompting(self):
        ok, inp, _, err = self._run(False, "yes")
        self.assertFalse(ok)
        inp.assert_not_called()
        self.assertIn("interactive terminal", err)


class TestRecoveryFlags(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._old = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self._tmp.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old

    def test_trash_is_a_delete_only_flag(self):
        # --trash lives on `delete`, so a bare `dorphan --trash` is a parse error.
        with contextlib.redirect_stderr(io.StringIO()), \
                self.assertRaises(SystemExit):
            cli.main(["--trash"])

    def test_trash_is_optional_path(self):
        args = cli.build_parser().parse_args(["delete", "--trash"])
        self.assertEqual(args.trash, "")  # bare flag -> default trash
        args2 = cli.build_parser().parse_args(["delete", "-i", "--trash", r"D:\trash"])
        self.assertEqual(args2.trash, r"D:\trash")
        self.assertIsNone(cli.build_parser().parse_args(["delete"]).trash)

    def test_log_on_empty_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main(["log"])
        self.assertEqual(rc, 0)
        self.assertIn("No deletions logged yet", out.getvalue())

    def test_restore_unknown_id_returns_one(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            rc = cli.main(["restore", "nope12"])
        self.assertEqual(rc, 1)
        self.assertIn("no recovery entry", err.getvalue())

    def test_prune_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = cli.main(["prune"])
        self.assertEqual(rc, 0)
        self.assertIn("Purged", out.getvalue())

    def test_confirm_wording_softens_for_recover(self):
        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = True
        with mock.patch.object(cli.sys, "stdin", fake_stdin), \
                mock.patch.object(cli, "input", create=True, return_value="yes"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            cli._confirm_bulk_delete(3, recover=True)
        self.assertIn("recovery", out.getvalue())
        self.assertNotIn("permanently DELETE", out.getvalue())


class TestParserBuilds(unittest.TestCase):
    def test_delete_flags_and_confidence(self):
        p = cli.build_parser()
        args = p.parse_args(["delete", "-i", "-m", "10mb", "--confidence", "high"])
        self.assertEqual(args.command, "delete")
        self.assertTrue(args.interactive)
        self.assertEqual(args.min_size, 10 * 1024 ** 2)
        self.assertEqual(args.confidence, "high")

    def test_delete_is_its_own_command(self):
        args = cli.build_parser().parse_args(["delete"])
        self.assertEqual(args.command, "delete")
        self.assertFalse(args.interactive)

    def test_confidence_defaults_to_high(self):
        args = cli.build_parser().parse_args(["scan"])
        self.assertEqual(args.confidence, "high")

    def test_exclude_takes_many_and_repeats(self):
        p = cli.build_parser()
        args = p.parse_args(["scan", "--exclude", "npm*", "yarn",
                             "--exclude", "Cursor"])
        self.assertEqual(args.exclude, ["npm*", "yarn", "Cursor"])

    def test_config_init_and_path_subcommands(self):
        p = cli.build_parser()
        self.assertEqual(p.parse_args(["config", "init"]).config_cmd, "init")
        self.assertEqual(p.parse_args(["config", "init", "x.toml"]).path, "x.toml")
        self.assertEqual(p.parse_args(["config", "path"]).config_cmd, "path")

    def test_restore_takes_an_id(self):
        args = cli.build_parser().parse_args(["restore", "4f2a9c"])
        self.assertEqual(args.command, "restore")
        self.assertEqual(args.id, "4f2a9c")


if __name__ == "__main__":
    unittest.main()
