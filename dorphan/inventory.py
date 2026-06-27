"""Inventory installed apps from registry uninstall keys, App Paths, and Store."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    import winreg
except ImportError:  # non-Windows, lets the module import for tests/tooling
    winreg = None  # type: ignore[assignment]


@dataclass
class InstalledApp:
    name: str
    publisher: str = ""
    install_location: str = ""
    source: str = ""
    raw_key: str = ""


@dataclass
class Inventory:
    apps: list[InstalledApp] = field(default_factory=list)

    def install_locations(self) -> list[str]:
        out = []
        for app in self.apps:
            loc = app.install_location.strip().strip('"')
            if loc and os.path.isdir(loc):
                out.append(os.path.normpath(loc))
        return out


_UNINSTALL_PATHS = [
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "64-bit"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", "32-bit"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", "per-user"),
]

_ROOTS = {}
if winreg is not None:
    _ROOTS = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}


def _read_value(key, name: str) -> str:
    try:
        val, _ = winreg.QueryValueEx(key, name)
        return str(val) if val is not None else ""
    except OSError:
        return ""


def _scan_uninstall() -> list[InstalledApp]:
    apps: list[InstalledApp] = []
    for root_name, subpath, label in _UNINSTALL_PATHS:
        root = _ROOTS[root_name]
        try:
            base = winreg.OpenKey(root, subpath)
        except OSError:
            continue
        with base:
            i = 0
            while True:
                try:
                    sub_name = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, sub_name) as sub:
                        name = _read_value(sub, "DisplayName")
                        if not name:
                            continue
                        # Skip pure OS hotfixes/updates which aren't real apps.
                        if _read_value(sub, "SystemComponent") == "1":
                            continue
                        apps.append(
                            InstalledApp(
                                name=name,
                                publisher=_read_value(sub, "Publisher"),
                                install_location=_read_value(sub, "InstallLocation"),
                                source=f"uninstall/{label}",
                                raw_key=f"{root_name}\\{subpath}\\{sub_name}",
                            )
                        )
                except OSError:
                    continue
    return apps


def _scan_app_paths() -> list[InstalledApp]:
    """Registered executables under App Paths give us more install folders."""
    apps: list[InstalledApp] = []
    sub = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    for root_name in ("HKLM", "HKCU"):
        try:
            base = winreg.OpenKey(_ROOTS[root_name], sub)
        except OSError:
            continue
        with base:
            i = 0
            while True:
                try:
                    exe = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, exe) as k:
                        path = _read_value(k, "")  # default value = full exe path
                        loc = os.path.dirname(path.strip('"')) if path else ""
                        apps.append(
                            InstalledApp(
                                name=os.path.splitext(exe)[0],
                                install_location=loc,
                                source="app-paths",
                                raw_key=f"{root_name}\\{sub}\\{exe}",
                            )
                        )
                except OSError:
                    continue
    return apps


def _scan_store_apps() -> list[InstalledApp]:
    """MSIX / Microsoft Store packages installed for the current user."""
    apps: list[InstalledApp] = []
    sub = r"SOFTWARE\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion\AppModel\Repository\Packages"
    try:
        base = winreg.OpenKey(_ROOTS["HKLM"], sub)
    except OSError:
        return apps
    with base:
        i = 0
        while True:
            try:
                pkg = winreg.EnumKey(base, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(base, pkg) as k:
                    name = _read_value(k, "DisplayName") or pkg.split("_")[0]
                    apps.append(
                        InstalledApp(
                            name=name,
                            publisher=_read_value(k, "PublisherDisplayName"),
                            install_location=_read_value(k, "PackageRootFolder"),
                            source="store",
                            raw_key=pkg,
                        )
                    )
            except OSError:
                continue
    return apps


def _editable_location(dist) -> str:
    """Project directory for an editable (`pip install -e`) install, else "".

    Editable installs record their source tree in direct_url.json with
    dir_info.editable = true; that folder (e.g. C:\\Users\\me\\projects\\dorphan)
    is a real install location worth matching against.
    """
    import json

    try:
        raw = dist.read_text("direct_url.json")
    except Exception:  # pragma: no cover - metadata layout varies
        raw = None
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return ""
    info = data.get("dir_info") or {}
    url = data.get("url", "")
    if info.get("editable") and url.startswith("file:"):
        from urllib.request import url2pathname
        from urllib.parse import urlparse

        return url2pathname(urlparse(url).path)
    return ""


def _scan_python_packages() -> list[InstalledApp]:
    """Packages installed in the running interpreter (same set as `pip list`).

    Uses stdlib importlib.metadata (no subprocess), so it's fast and can't hang.
    Catches dev tools that have no registry entry — e.g. an editable install of
    `dorphan` itself — so their data folders aren't mistaken for orphans.
    """
    try:
        from importlib import metadata
    except ImportError:  # pragma: no cover - importlib.metadata is 3.8+
        return []
    apps: list[InstalledApp] = []
    try:
        dists = list(metadata.distributions())
    except Exception:  # pragma: no cover - defensive: never break a scan
        return []
    for dist in dists:
        try:
            name = (dist.metadata["Name"] or "").strip()
        except Exception:
            name = ""
        if not name:
            continue
        apps.append(
            InstalledApp(
                name=name,
                install_location=_editable_location(dist),
                source="pip",
                raw_key=f"pip/{name}",
            )
        )
    return apps


def _dedupe(all_apps: list[InstalledApp]) -> Inventory:
    """Drop entries sharing a (name, install_location) pair, preserving order."""
    seen: set[tuple[str, str]] = set()
    deduped: list[InstalledApp] = []
    for app in all_apps:
        key = (app.name.lower(), app.install_location.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(app)
    return Inventory(apps=deduped)


def collect() -> Inventory:
    """Gather installed apps from all registry sources, de-duplicated."""
    pkgs = _scan_python_packages()  # cross-platform; safe even off Windows
    if winreg is None:
        return _dedupe(pkgs)
    all_apps = _scan_uninstall() + _scan_app_paths() + _scan_store_apps() + pkgs
    return _dedupe(all_apps)
