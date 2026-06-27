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

    def test_install_location_match(self):
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "WeirdName")
            os.makedirs(sub)
            inv = Inventory(apps=[InstalledApp(name="App", install_location=d)])
            m = Matcher(inv, self.cfg)
            c = m.classify(folder("WeirdName", path=sub))
            self.assertEqual(c.status, "claimed")
            self.assertIn("install dir", c.matched_app)


if __name__ == "__main__":
    unittest.main()
