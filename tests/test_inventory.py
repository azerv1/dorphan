import json
import unittest
from unittest import mock

from dorphan import inventory


class _FakeDist:
    """Minimal stand-in for an importlib.metadata.Distribution."""

    def __init__(self, name, direct_url=None):
        self.metadata = {"Name": name}
        self._direct_url = direct_url

    def read_text(self, filename):
        if filename == "direct_url.json":
            return self._direct_url
        return None


class TestPythonPackages(unittest.TestCase):
    def test_scan_lists_packages_by_name(self):
        dists = [_FakeDist("dorphan"), _FakeDist("requests"), _FakeDist("")]
        with mock.patch("importlib.metadata.distributions", return_value=dists):
            apps = inventory._scan_python_packages()
        names = [a.name for a in apps]
        self.assertIn("dorphan", names)
        self.assertIn("requests", names)
        self.assertNotIn("", names)  # blank-name dists are skipped
        self.assertTrue(all(a.source == "pip" for a in apps))

    def test_scan_survives_metadata_errors(self):
        with mock.patch("importlib.metadata.distributions",
                        side_effect=RuntimeError("boom")):
            self.assertEqual(inventory._scan_python_packages(), [])

    def test_editable_location_parsed_from_direct_url(self):
        url = json.dumps({
            "url": "file:///C:/Users/me/projects/dorphan",
            "dir_info": {"editable": True},
        })
        loc = inventory._editable_location(_FakeDist("dorphan", direct_url=url))
        self.assertIn("dorphan", loc)
        self.assertNotIn("file:", loc)

    def test_non_editable_has_no_location(self):
        url = json.dumps({"url": "file:///tmp/x", "dir_info": {"editable": False}})
        self.assertEqual(
            inventory._editable_location(_FakeDist("x", direct_url=url)), "")
        # Missing direct_url.json -> empty, not an error.
        self.assertEqual(inventory._editable_location(_FakeDist("x")), "")

    def test_collect_includes_pip_packages(self):
        dists = [_FakeDist("appcleanx")]
        with mock.patch("importlib.metadata.distributions", return_value=dists):
            inv = inventory.collect()
        self.assertIn("appcleanx", [a.name for a in inv.apps])


if __name__ == "__main__":
    unittest.main()
