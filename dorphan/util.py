"""Small shared helpers: name normalization and disk-size math."""

from __future__ import annotations

import os
import re
import sys


def progress(text: str) -> None:
    """Overwrite the current stderr line with a live status (TTY only)."""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + text)
        sys.stderr.flush()


def progress_done() -> None:
    """Clear the live status line."""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K")
        sys.stderr.flush()

_NORM_RE = re.compile(r"[^a-z0-9]+")

# Fallback stopwords, used only when a caller doesn't pass its own set (the
# real list is user-configurable and lives in config.py).
_DEFAULT_STOPWORDS = frozenset({
    "app", "apps", "data", "the", "inc", "llc", "ltd", "corp", "corporation",
    "company", "co", "software", "technologies", "technology", "labs", "studio",
    "studios", "team", "limited", "gmbh", "x64", "x86", "win", "windows",
})


def normalize(name: str) -> str:
    """Lowercase a name and strip everything that isn't a-z0-9."""
    if not name:
        return ""
    return _NORM_RE.sub("", name.lower())


def tokens(name: str, stopwords=None) -> set[str]:
    """Split a name into meaningful lowercase tokens (stopwords removed)."""
    if not name:
        return set()
    if stopwords is None:
        stopwords = _DEFAULT_STOPWORDS
    raw = _NORM_RE.sub(" ", name.lower()).split()
    return {t for t in raw if len(t) >= 3 and t not in stopwords}


def is_elevated() -> bool:
    """True if the process has Administrator rights (Windows).

    Deleting shallow folders under Program Files / ProgramData needs elevation,
    so the CLI gates --unsafe / low --depth on this. On non-Windows we can't ask
    Windows, so fall back to a Unix root check (mostly for tests).
    """
    if sys.platform == "win32":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:  # pragma: no cover - defensive; assume not elevated
            return False
    try:  # pragma: no cover - non-Windows convenience only
        return os.geteuid() == 0
    except AttributeError:
        return False


def human_size(num_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def dir_size(path: str) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a tree; skips symlinks and errors."""
    total = 0
    count = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            count += 1
                    except (OSError, ValueError):
                        continue
        except (OSError, ValueError):
            continue
    return total, count
