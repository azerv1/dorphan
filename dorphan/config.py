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
        stopwords={s.lower() for s in DEFAULT_STOPWORDS},
    )


def default_config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "dorphan", "config.toml")


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
    if not path or not os.path.isfile(path):
        return cfg, None
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
    if "stopwords" in match:
        cfg.stopwords = {s.lower() for s in match["stopwords"]}

    return cfg, path


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
