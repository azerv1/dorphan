"""Small shared helpers: name normalization and disk-size math."""

from __future__ import annotations

import os
import re
import sys


_progress_len = 0  # length of the last status line, so we can blank it cleanly


def progress(text: str) -> None:
    """Overwrite the current stderr line with a live status (TTY only).

    Uses a carriage return plus space-padding (no ANSI escapes) so it renders
    correctly even on consoles that don't interpret the `\\033[K` clear code.
    """
    global _progress_len
    if not sys.stderr.isatty():
        return
    pad = max(0, _progress_len - len(text))
    sys.stderr.write("\r" + text + " " * pad)
    sys.stderr.flush()
    _progress_len = len(text)


def progress_done() -> None:
    """Clear the live status line."""
    global _progress_len
    if sys.stderr.isatty():
        sys.stderr.write("\r" + " " * _progress_len + "\r")
        sys.stderr.flush()
        _progress_len = 0


_color_enabled = False


def enable_color() -> bool:
    """Turn on ANSI color for this run and report whether it's usable.

    Windows consoles print raw escapes (you'd see `←[1m`) unless we opt in via
    SetConsoleMode's virtual-terminal flag. If that fails, output is redirected,
    or NO_COLOR is set, color stays off and callers fall back to plain text.
    """
    global _color_enabled
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        _color_enabled = False
        return False
    if sys.platform != "win32":
        _color_enabled = True
        return True
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ok = False
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = k32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if k32.GetConsoleMode(handle, ctypes.byref(mode)):
                k32.SetConsoleMode(handle, mode.value | enable_vt)
                ok = True
        _color_enabled = ok
    except Exception:  # pragma: no cover - defensive; assume no color
        _color_enabled = False
    return _color_enabled


def supports_color() -> bool:
    """True if ANSI color was successfully enabled this run (see enable_color)."""
    return _color_enabled

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
