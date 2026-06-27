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


def collect() -> Inventory:
    """Gather installed apps from all registry sources, de-duplicated."""
    if winreg is None:
        return Inventory(apps=[])
    all_apps = _scan_uninstall() + _scan_app_paths() + _scan_store_apps()
    seen: set[tuple[str, str]] = set()
    deduped: list[InstalledApp] = []
    for app in all_apps:
        key = (app.name.lower(), app.install_location.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(app)
    return Inventory(apps=deduped)
