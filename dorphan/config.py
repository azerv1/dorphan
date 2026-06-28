"""Scan roots and name-matching word lists, with TOML overrides."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from .util import normalize
from .data import (
    DEFAULT_ROOTS,
    DEFAULT_MIN_TOKEN,
    DEFAULT_SYSTEM_FOLDERS,
    DEFAULT_IGNORE_FOLDERS,
    DEFAULT_VENDOR_FOLDERS,
    DEFAULT_STOPWORDS,
)

# The default word lists and scan roots live in data.py (pure data, hand-edited);
# they are re-exported here so existing `config.DEFAULT_*` references keep working.
__all__ = [
    "DEFAULT_ROOTS", "DEFAULT_MIN_TOKEN", "DEFAULT_SYSTEM_FOLDERS",
    "DEFAULT_IGNORE_FOLDERS", "DEFAULT_VENDOR_FOLDERS", "DEFAULT_STOPWORDS",
    "Config", "load", "render_template", "write_default_config",
]

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - older Pythons
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:
        _toml = None  # type: ignore


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

    # Each list supports three forms, applied in this order:
    #   <name>         -> replace the whole default list
    #   extra_<name>   -> add to it
    #   remove_<name>  -> drop entries from it
    # so a user can extend the defaults without restating them (the common case).
    if "system_folders" in match:
        cfg.system_folders = {normalize(n) for n in match["system_folders"]}
    if "ignore_folders" in match:
        cfg.ignore_folders = {normalize(n) for n in match["ignore_folders"]}
    if "vendor_folders" in match:
        cfg.vendor_folders = [str(n) for n in match["vendor_folders"]]
    if "stopwords" in match:
        cfg.stopwords = {s.lower() for s in match["stopwords"]}

    _add_norm(cfg.system_folders, match.get("extra_system_folders"))
    _discard_norm(cfg.system_folders, match.get("remove_system_folders"))
    _add_norm(cfg.ignore_folders, match.get("extra_ignore_folders"))
    _discard_norm(cfg.ignore_folders, match.get("remove_ignore_folders"))
    _add_norm(cfg.stopwords, match.get("extra_stopwords"), lower=True)
    _discard_norm(cfg.stopwords, match.get("remove_stopwords"), lower=True)
    cfg.vendor_folders = _merge_vendors(
        cfg.vendor_folders,
        match.get("extra_vendor_folders"),
        match.get("remove_vendor_folders"),
    )


def _add_norm(target: set[str], names, *, lower: bool = False) -> None:
    """Add names to a normalized set (skips entries that normalize to nothing)."""
    for n in names or []:
        key = str(n).lower() if lower else normalize(str(n))
        if key:
            target.add(key)


def _discard_norm(target: set[str], names, *, lower: bool = False) -> None:
    for n in names or []:
        target.discard(str(n).lower() if lower else normalize(str(n)))


def _merge_vendors(current: list[str], extra, remove) -> list[str]:
    """Append extras and drop removals from the (display-name) vendor list.

    Vendors are compared by normalized name so "Logi" removes "logi" regardless
    of casing/punctuation. Order is preserved; appended extras keep their casing.
    """
    out = list(current) + [str(n) for n in (extra or [])]
    drop = {normalize(str(n)) for n in (remove or [])}
    return [v for v in out if normalize(v) not in drop]


def _toml_list(items: list[str], indent: str = "  ") -> str:
    return "".join(f'{indent}{_q(i)},\n' for i in items)


def _toml_block_commented(key: str, items: list[str]) -> str:
    """Render `key = [ ... ]` for reference, every line commented out."""
    body = "".join(f'#   {_q(i)},\n' for i in items)
    return f"# {key} = [\n{body}# ]"


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

# Each word list below comes with sensible built-in defaults. You almost never
# need to restate them -- just tweak with the extra_/remove_ keys:
#
#   extra_system_folders  = ["Windows Kits"]     # add to the defaults
#   remove_ignore_folders = ["Cypress"]          # let a default be flagged again
#   extra_vendor_folders  = ["Canon", "Epson"]   # protect more vendor folders
#   extra_stopwords       = ["launcher"]          # stop a generic word from matching
#
# The bare keys (system_folders / ignore_folders / vendor_folders / stopwords)
# REPLACE the whole built-in list instead of extending it -- only use those if
# you really want to start from scratch. The current built-in lists are shown,
# commented out, below for reference.

# system_folders: part of Windows or shared frameworks; NEVER reported.
{_toml_block_commented("system_folders", DEFAULT_SYSTEM_FOLDERS)}

# ignore_folders: package managers and dev toolchains (npm, pip, uv, cargo, ...)
# whose caches/global stores look orphaned but are in use; never flagged.
{_toml_block_commented("ignore_folders", DEFAULT_IGNORE_FOLDERS)}

# vendor_folders: hardware makers / OEMs / driver vendors. Matched by exact name,
# name prefix, or token, so "HP" also covers "HPPrintScanDoctor".
{_toml_block_commented("vendor_folders", DEFAULT_VENDOR_FOLDERS)}

# stopwords: generic words stripped from names before matching.
{_toml_block_commented("stopwords", DEFAULT_STOPWORDS)}
"""


def write_default_config(path: str | None = None) -> str:
    """Write a starter config (from defaults) and return where it landed."""
    target = path or default_config_path()
    os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(render_template())
    return target
