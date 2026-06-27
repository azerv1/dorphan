import os
import tempfile
import unittest
from unittest import mock

from dorphan import config


class TestExpandPath(unittest.TestCase):
    def test_env_substitution(self):
        os.environ["ACX_TESTVAR"] = r"C:\somewhere"
        self.assertEqual(config.expand_path("{env:ACX_TESTVAR}/sub"),
                         r"C:\somewhere/sub")

    def test_missing_env_becomes_empty(self):
        self.assertEqual(config.expand_path("{env:ACX_NOT_SET_XYZ}"), "")


class TestDefaults(unittest.TestCase):
    def test_defaults_populated(self):
        cfg = config._defaults()
        self.assertEqual(cfg.min_token, config.DEFAULT_MIN_TOKEN)
        self.assertIn(config.normalize("Microsoft"), cfg.system_folders)
        self.assertIn(config.normalize("SoftwareDistribution"), cfg.system_folders)
        # ignore_folders is seeded with package managers (npm, pip, uv, ...).
        self.assertIn(config.normalize("npm"), cfg.ignore_folders)
        self.assertIn(config.normalize("chocolatey"), cfg.ignore_folders)
        self.assertTrue(cfg.roots)

    def test_active_roots_honors_program_files_flag(self):
        cfg = config._defaults()
        cfg.roots = [("A", "{env:ACX_TESTVAR}", False),
                     ("PF", "{env:ACX_TESTVAR}", True)]
        os.environ["ACX_TESTVAR"] = r"C:\x"
        cfg.include_program_files = False
        labels = [label for label, _ in cfg.active_roots()]
        self.assertEqual(labels, ["A"])
        cfg.include_program_files = True
        labels = [label for label, _ in cfg.active_roots()]
        self.assertEqual(labels, ["A", "PF"])


class TestLoad(unittest.TestCase):
    def test_no_file_returns_defaults(self):
        cfg, path = config.load(r"Z:\does\not\exist.toml")
        self.assertIsNone(path)
        self.assertEqual(cfg.min_token, config.DEFAULT_MIN_TOKEN)

    def test_partial_override_only_changes_given_keys(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.toml")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('[match]\nignore_folders = ["MetaQuotes"]\nmin_token = 6\n')
            cfg, path = config.load(p)
            self.assertEqual(path, p)
            self.assertEqual(cfg.min_token, 6)
            self.assertIn(config.normalize("MetaQuotes"), cfg.ignore_folders)
            # untouched key keeps its default
            self.assertIn(config.normalize("Windows"), cfg.system_folders)

    def test_bom_is_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.toml")
            with open(p, "w", encoding="utf-8-sig") as fh:  # writes a BOM
                fh.write('[match]\nmin_token = 7\n')
            cfg, _ = config.load(p)
            self.assertEqual(cfg.min_token, 7)


class TestWhitelist(unittest.TestCase):
    def test_add_dedups_and_load_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "whitelist.txt")
            config.add_to_whitelist("Krokiet", path=p)
            config.add_to_whitelist("krokiet", path=p)  # same after normalize
            config.add_to_whitelist("MetaQuotes", path=p)
            names = config.load_whitelist(p)
            self.assertEqual(names, ["Krokiet", "MetaQuotes"])

    def test_load_merges_whitelist_into_ignore_folders(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "whitelist.txt")
            config.add_to_whitelist("Krokiet", path=p)
            with mock.patch.object(config, "whitelist_path", return_value=p):
                cfg, _ = config.load(r"Z:\no\config.toml")
            self.assertIn(config.normalize("Krokiet"), cfg.ignore_folders)


class TestTemplate(unittest.TestCase):
    def test_written_config_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "out.toml")
            written = config.write_default_config(p)
            self.assertEqual(written, p)
            self.assertTrue(os.path.isfile(p))
            cfg, path = config.load(p)
            self.assertEqual(path, p)
            self.assertEqual(cfg.min_token, config.DEFAULT_MIN_TOKEN)
            self.assertEqual(len(cfg.roots), len(config.DEFAULT_ROOTS))


if __name__ == "__main__":
    unittest.main()
