import os
import tempfile
import unittest

from dorphan import config
from dorphan.inventory import InstalledApp, Inventory
from dorphan.matcher import Matcher
from dorphan.scanner import Folder


def folder(name, path=None, size=0):
    return Folder(path=path or rf"C:\Users\x\AppData\Local\{name}",
                  name=name, root_label="Local", size=size)


class TestMatcher(unittest.TestCase):
    def setUp(self):
        self.cfg = config._defaults()
        self.inv = Inventory(apps=[
            InstalledApp(name="Spotify", publisher="Spotify AB"),
            InstalledApp(name="FooEditor", publisher="JetBrains s.r.o."),
        ])
        self.m = Matcher(self.inv, self.cfg)

    def test_exact_name_is_claimed(self):
        c = self.m.classify(folder("Spotify"))
        self.assertEqual(c.status, "claimed")
        self.assertEqual(c.matched_app, "Spotify")

    def test_publisher_token_is_claimed(self):
        c = self.m.classify(folder("JetBrains"))
        self.assertEqual(c.status, "claimed")
        self.assertIn("JetBrains", c.matched_app)

    def test_system_folder(self):
        c = self.m.classify(folder("Microsoft"))
        self.assertEqual(c.status, "system")

    def test_orphan_high_confidence(self):
        c = self.m.classify(folder("Zwxyztool"))
        self.assertEqual(c.status, "orphan")
        self.assertEqual(c.confidence, "high")

    def test_orphan_medium_confidence_for_short_name(self):
        c = self.m.classify(folder("Zq"))
        self.assertEqual(c.status, "orphan")
        self.assertEqual(c.confidence, "medium")

    def test_ignore_list_classifies_as_system(self):
        self.cfg.ignore_folders = {config.normalize("Zwxyztool")}
        m = Matcher(self.inv, self.cfg)
        self.assertEqual(m.classify(folder("Zwxyztool")).status, "system")

    def test_package_managers_are_not_orphans(self):
        # Package-manager caches/stores must never be flagged for deletion.
        for name in ("npm", "pip", "uv", "cargo", "maven", "chocolatey",
                     "Package Cache"):
            self.assertEqual(self.m.classify(folder(name)).status, "system",
                             f"{name} should be treated as system/ignored")

    def test_windows_servicing_folders_are_system(self):
        for name in ("SoftwareDistribution", "Start Menu", "Templates",
                     "RUXIM", "Reference Assemblies"):
            self.assertEqual(self.m.classify(folder(name)).status, "system",
                             f"{name} should be treated as system")

    def test_non_latin_name_is_not_orphan(self):
        # The localized public Desktop (Greek) normalizes to nothing.
        c = self.m.classify(folder("Επιφάνεια εργασίας",
                                   path=r"C:\ProgramData\Επιφάνεια εργασίας"))
        self.assertEqual(c.status, "system")

    def test_vendor_folders_are_claimed(self):
        # OEM / hardware / driver folders must never be flagged, even with no
        # installed app and even when the name is just a vendor prefix.
        for name in ("HP", "HPPrintScanDoctor", "HPCommRecovery",
                     "Hewlett-Packard", "Dell", "Realtek"):
            c = self.m.classify(folder(name, path=rf"C:\Program Files\{name}"))
            self.assertEqual(c.status, "claimed",
                             f"{name} should be protected as a vendor folder")
            self.assertIn("vendor", c.matched_app)

    def test_vst_plugin_folders_are_not_orphans(self):
        # Shared audio-plugin host folders are kept regardless of casing.
        for name in ("VstPlugins", "Vstplugins", "Vst3"):
            self.assertEqual(self.m.classify(folder(name)).status, "system",
                             f"{name} should be treated as system/ignored")

    def test_real_app_still_beats_vendor_fallback(self):
        # An exact app match should win over the vendor fallback label.
        inv = Inventory(apps=[InstalledApp(name="Intel Driver Assistant")])
        m = Matcher(inv, self.cfg)
        c = m.classify(folder("Intel Driver Assistant"))
        self.assertEqual(c.status, "claimed")
        self.assertNotIn("vendor", c.matched_app)

    def test_install_location_match(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "WeirdName")
            os.makedirs(sub)
            inv = Inventory(apps=[InstalledApp(name="App", install_location=d)])
            m = Matcher(inv, self.cfg)
            c = m.classify(folder("WeirdName", path=sub))
            self.assertEqual(c.status, "claimed")
            self.assertIn("install dir", c.matched_app)

    def test_own_config_dir_is_never_orphan(self):
        # Regression: dorphan's own %APPDATA%\dorphan config folder has no
        # registry entry, so it used to be flagged (and could be deleted).
        c = self.m.classify(folder("dorphan", path=config.config_dir()))
        self.assertEqual(c.status, "system")

    def test_pip_package_name_claims_folder(self):
        # A folder named after an installed pip package (e.g. an editable dev
        # tool with no registry entry) is claimed, not orphaned.
        inv = Inventory(apps=[InstalledApp(name="appcleanx", source="pip")])
        m = Matcher(inv, self.cfg)
        self.assertEqual(m.classify(folder("appcleanx")).status, "claimed")


if __name__ == "__main__":
    unittest.main()
