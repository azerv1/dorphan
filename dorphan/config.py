"""Scan roots and name-matching word lists, with TOML overrides."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .util import normalize

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - older Pythons
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None  # type: ignore


# --------------------------------------------------------------------------
# Canonical defaults (the single source of truth)
# --------------------------------------------------------------------------

# Each root: (label, path-template, is_program_files).
# {env:NAME} expands an environment variable; ~ expands the home directory.
DEFAULT_ROOTS: list[tuple[str, str, bool]] = [
    ("Roaming", "{env:APPDATA}", False),
    ("Local", "{env:LOCALAPPDATA}", False),
    ("LocalLow", "~/AppData/LocalLow", False),
    ("Local\\Programs", "{env:LOCALAPPDATA}/Programs", False),
    ("ProgramData", "{env:PROGRAMDATA}", False),
    ("Program Files", "{env:ProgramFiles}", True),
    ("Program Files (x86)", "{env:ProgramFiles(x86)}", True),
]

DEFAULT_MIN_TOKEN = 4

DEFAULT_SYSTEM_FOLDERS = [
    "Microsoft", "Microsoft.NET", "Windows", "WindowsApps", "Common Files",
    "Packages", "Temp", "Tmp", "ConnectedDevicesPlatform", "CrashDumps",
    "D3DSCache", "ElevatedDiagnostics", "INetCache", "INetCookies", "IconCache",
    "GroupPolicy", "History", "Microsoft Help", "ModifiableWindowsApps",
    "PackageStaging", "PeerDistRepub", "Publishers", "ssh", "VirtualStore",
    "WER", "Caches", "CLR", "Diagnostics", "PlaceholderTileLogoFolder",
    "Comms", "Application Data", "Internet Explorer", "Defender", "EdgeUpdate",
    "OneDrive", "Windows Defender", "Windows Mail", "Windows Media Player",
    "Windows NT", "Windows Photo Viewer", "WindowsPowerShell", "PowerShell",
    "USOShared", "USOPrivate", "regid.1991-06.com.microsoft", "SystemData",
    "MSBuild", "dotnet", "GameBarPresenceWriter", "WinSxS", "DiagTrack",
    # Windows update/servicing, shell, and SDK/debug folders that scatter into
    # ProgramData and Program Files and must never be flagged as leftovers.
    "SoftwareDistribution", "Start Menu", "Templates", "Desktop", "Documents",
    "Favorites", "Links", "RUXIM", "PCHealthCheck", "Application Verifier",
    "Reference Assemblies", "MSECache", "SystemApps", "PerfLogs", "Boot",
    "Recovery", "System Volume Information", "$Recycle.Bin", "Installer",
    "Downloaded Installations", "WindowsPowerShell", "Device Stage",
]

# Folder names that are never flagged because they belong to package managers
# and language/dev toolchains (their caches and global stores look orphaned but
# are very much in use). Add your own via the [match] ignore_folders config key.
DEFAULT_IGNORE_FOLDERS: list[str] = [
    # JavaScript / Node
    "npm", "npm-cache", "yarn", "pnpm", "node-gyp", "nvm", "corepack",
    "volta", "fnm", "bower", "electron", "Cypress",
    # Python
    "pip", "pipx", "uv", "pipenv", "poetry", "pdm", "hatch", "virtualenv",
    # Rust
    "cargo", "rustup",
    # Go / Deno / Bun
    "go", "deno", "bun",
    # Ruby
    "gem", "bundle", "rbenv", "rvm",
    # JVM (Java / Scala / Kotlin)
    "maven", "gradle", "sbt", "coursier", "ivy2",
    # PHP
    "composer",
    # Haskell
    "cabal", "stack", "ghcup",
    # .NET / NuGet
    "NuGet", "Package Cache", "paket",
    # C / C++
    "vcpkg", "conan",
    # Windows package managers / shims
    "chocolatey", "ChocolateyHttpCache", "shimgen", "scoop", "Webdrivers",
    # Audio plugin host folders shared by many DAWs/apps; never a single app's
    # leftover. Both "VstPlugins" and "Vstplugins" normalize to the same entry.
    "VstPlugins", "Vst3",
]

# Hardware makers, PC OEMs, and driver/peripheral vendors. Their folders (printer
# utilities, driver leftovers, control panels) frequently have no matching
# registry entry yet must never be flagged: they're either still needed or risky
# to remove. Matched by exact name, name prefix, or token, so "HP" also protects
# "HPPrintScanDoctor" and "HPCommRecovery". Extend via [match] vendor_folders.
DEFAULT_VENDOR_FOLDERS: list[str] = [
    "HP", "Hewlett-Packard",
    "Dell", "Alienware",
    "Lenovo", "Acer", "ASUS", "ASUSTeK", "MSI", "Gigabyte", "Toshiba",
    "Samsung", "Razer", "Corsair", "SteelSeries", "Elgato", "Logitech", "Logi",
    "Intel", "NVIDIA", "AMD",
    "Realtek", "Synaptics", "Conexant", "Qualcomm", "Broadcom", "Atheros",
]

DEFAULT_STOPWORDS = [
    "app", "apps", "data", "the", "inc", "llc", "ltd", "corp", "corporation",
    "company", "co", "software", "technologies", "technology", "labs", "studio",
    "studios", "team", "limited", "gmbh", "x64", "x86", "win", "windows",
]


_ENV_RE = re.compile(r"\{env:([^}]+)\}")


def expand_path(template: str) -> str:
    """Resolve {env:NAME} and ~ in a path template; missing vars -> empty."""
    def _sub(m: "re.Match[str]") -> str:
        return os.environ.get(m.group(1), "")

    return os.path.expanduser(_ENV_RE.sub(_sub, template))


@dataclass
class Config:
    roots: list[tuple[str, str, bool]] = field(default_factory=list)
    include_program_files: bool = True
    min_token: int = DEFAULT_MIN_TOKEN
    system_folders: set[str] = field(default_factory=set)   # normalized
    ignore_folders: set[str] = field(default_factory=set)   # normalized
    vendor_folders: list[str] = field(default_factory=list)  # display names
    stopwords: set[str] = field(default_factory=set)

    def active_roots(self) -> list[tuple[str, str]]:
        """Expanded (label, path) pairs, honoring include_program_files."""
        out: list[tuple[str, str]] = []
        for label, template, is_pf in self.roots:
            if is_pf and not self.include_program_files:
                continue
            path = expand_path(template)
            if path:
                out.append((label, path))
        return out


def _defaults() -> Config:
    return Config(
        roots=list(DEFAULT_ROOTS),
        include_program_files=True,
        min_token=DEFAULT_MIN_TOKEN,
        system_folders={normalize(n) for n in DEFAULT_SYSTEM_FOLDERS},
        ignore_folders={normalize(n) for n in DEFAULT_IGNORE_FOLDERS},
        vendor_folders=list(DEFAULT_VENDOR_FOLDERS),
        stopwords={s.lower() for s in DEFAULT_STOPWORDS},
    )


def config_dir() -> str:
    """Dorphan's own settings folder (%APPDATA%\\dorphan).

    It holds config.toml and whitelist.txt. Nothing in the registry claims it,
    so without special-casing it dorphan would flag — and could delete — its own
    config. matcher treats it as system and cleaner refuses to delete it.
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "dorphan")


def data_dir() -> str:
    """Local (non-roaming) state folder (%LOCALAPPDATA%\\dorphan).

    Holds the deletion log and the recovery trash. Kept under LOCALAPPDATA, not
    the roaming config dir, so quarantined folders (potentially large) never sync
    and survive config edits. See recovery.py.
    """
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            or os.path.expanduser("~"))
    return os.path.join(base, "dorphan")


def default_config_path() -> str:
    return os.path.join(config_dir(), "config.toml")


def whitelist_path() -> str:
    """Plain-text list of folder names the user whitelisted via `dorphan delete -i` (w)."""
    return os.path.join(config_dir(), "whitelist.txt")


def load_whitelist(path: str | None = None) -> list[str]:
    """Folder names from the whitelist file; [] if missing. Skips blanks/#."""
    target = path or whitelist_path()
    try:
        with open(target, "r", encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def add_to_whitelist(name: str, path: str | None = None) -> str:
    """Append a folder name to the whitelist (deduped). Returns the file path."""
    target = path or whitelist_path()
    if normalize(name) in {normalize(n) for n in load_whitelist(target)}:
        return target
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    fresh = not os.path.isfile(target)
    with open(target, "a", encoding="utf-8") as fh:
        if fresh:
            fh.write("# Dorphan whitelist - folder names never flagged as orphans.\n"
                     "# Added by the 'w' option in `dorphan delete -i`. One name per line.\n")
        fh.write(name + "\n")
    return target


def find_config(explicit: str | None = None) -> str | None:
    """Locate a config file: explicit > %APPDATA%\\dorphan > ./dorphan.toml."""
    if explicit:
        return explicit
    for candidate in (default_config_path(), os.path.abspath("dorphan.toml")):
        if os.path.isfile(candidate):
            return candidate
    return None


def load(explicit: str | None = None) -> tuple[Config, str | None]:
    """Return (config, source_path); a TOML file overrides only the keys it sets."""
    cfg = _defaults()
    path = find_config(explicit)
    if path and os.path.isfile(path):
        _apply_toml(cfg, path)
    else:
        path = None

    # The whitelist (added via `dorphan delete -i` w) always folds into ignore_folders,
    # whether or not a TOML config exists, so whitelisted folders stop appearing.
    for name in load_whitelist():
        n = normalize(name)
        if n:
            cfg.ignore_folders.add(n)
    return cfg, path


def _apply_toml(cfg: Config, path: str) -> None:
    """Overlay a TOML config file's keys onto an existing Config in place."""
    if _toml is None:
        # Can't parse TOML on this interpreter; keep defaults but signal it.
        raise RuntimeError(
            f"found config '{path}' but TOML support is unavailable "
            f"(Python 3.11+ or `pip install tomli` required)"
        )
    # Read as utf-8-sig so a BOM (common from Windows editors) is tolerated.
    with open(path, "r", encoding="utf-8-sig") as fh:
        data = _toml.loads(fh.read())

    scan = data.get("scan", {})
    if "include_program_files" in scan:
        cfg.include_program_files = bool(scan["include_program_files"])
    if "roots" in scan:
        cfg.roots = [
            (r["label"], r["path"], bool(r.get("program_files", False)))
            for r in scan["roots"]
        ]

    match = data.get("match", {})
    if "min_token" in match:
        cfg.min_token = int(match["min_token"])
    if "system_folders" in match:
        cfg.system_folders = {normalize(n) for n in match["system_folders"]}
    if "ignore_folders" in match:
        cfg.ignore_folders = {normalize(n) for n in match["ignore_folders"]}
    if "vendor_folders" in match:
        cfg.vendor_folders = [str(n) for n in match["vendor_folders"]]
    if "stopwords" in match:
        cfg.stopwords = {s.lower() for s in match["stopwords"]}


def _toml_list(items: list[str], indent: str = "  ") -> str:
    return "".join(f'{indent}{_q(i)},\n' for i in items)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_template() -> str:
    """Produce a fully-commented TOML config seeded with the current defaults."""
    roots = "".join(
        f'  {{ label = {_q(l)}, path = {_q(p)}'
        + (", program_files = true" if pf else "")
        + " },\n"
        for (l, p, pf) in DEFAULT_ROOTS
    )
    return f"""\
# Dorphan configuration
#
# Anything you omit falls back to the built-in defaults, so you can keep this
# file as short as you like. Save it as one of:
#   - the path you pass to  --config PATH
#   - %APPDATA%\\dorphan\\config.toml   (the default location)
#   - ./dorphan.toml                    (next to where you run the command)

[scan]
# Scan Program Files too (slower). --no-program-files overrides this at runtime.
include_program_files = true

# Top-level data locations to scan. {{env:NAME}} expands an environment
# variable; ~ expands your home folder. Folders that don't exist are skipped.
# Set program_files = true on entries that --no-program-files should drop.
roots = [
{roots}]

[match]
# Minimum length for fuzzy substring/token matching (avoids tiny accidental
# matches like "go" -> "google"). Folder names shorter than this that don't
# match an app are reported as medium-confidence orphans.
min_token = {DEFAULT_MIN_TOKEN}

# Folder names that are part of Windows or shared frameworks. These are NEVER
# reported as orphaned leftovers. Add your own to silence false positives.
system_folders = [
{_toml_list(DEFAULT_SYSTEM_FOLDERS)}]

# Folders never flagged as orphans even though nothing installed claims them.
# Seeded with package managers and dev toolchains (npm, pip, uv, cargo, maven,
# chocolatey, ...) whose caches/global stores look orphaned but are in use.
# Add your own, e.g.: ignore_folders = ["SomeVendorCache", "OldGameSaves"]
ignore_folders = [
{_toml_list(DEFAULT_IGNORE_FOLDERS)}]

# Hardware makers / PC OEMs / driver vendors. Their folders are never flagged,
# even with no matching installed app, because they're usually still needed or
# risky to remove (printer tools, driver leftovers). Matched by exact name,
# name prefix, or token, so "HP" also covers "HPPrintScanDoctor".
vendor_folders = [
{_toml_list(DEFAULT_VENDOR_FOLDERS)}]

# Generic words stripped from app/folder names before matching.
stopwords = [
{_toml_list(DEFAULT_STOPWORDS)}]
"""


def write_default_config(path: str | None = None) -> str:
    """Write a starter config (from defaults) and return where it landed."""
    target = path or default_config_path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(render_template())
    return target
