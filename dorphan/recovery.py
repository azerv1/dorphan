"""Deletion log + optional recoverable trash for folders dorphan removes.

Two independent pieces, both living under %LOCALAPPDATA%\\dorphan (config.data_dir):

  deletions.log   append-only, one compact line per action (see _log line format)
  trash/<id>/     a quarantined folder, kept so it can be restored
  trash/index.json  manifest: id -> {orig, t, size, files, name}

By default a delete is permanent and only the log line is written (a record of
what went, so nothing vanishes silently again). With `dorphan --trash` the
folder is *moved* into trash instead, restorable via `dorphan --restore <id>`.
The trash is bounded by a byte cap; the oldest entries are evicted when it's
exceeded, so recovery never grows the disk without limit.

Log line:  <act> <yYMMDD-HHMM> <size> <files> <id> <path>
  act : d=permanent delete  q=quarantine  r=restore  p=purge(evicted/emptied)
  id  : short trash id, or "-" for actions with no trash copy (permanent delete)
example:  d 260627-2009 164.9K 30 - C:\\ProgramData\\Whesvc
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import time
import uuid

from .config import data_dir

# Default ceiling for the recovery trash. When a new quarantine would push the
# total over this, the oldest entries are evicted (permanently) first. Generous
# enough to hold a typical cleanup, small enough not to swallow the disk.
DEFAULT_TRASH_CAP_BYTES = 2 * 1024 ** 3  # 2 GiB


def log_path() -> str:
    return os.path.join(data_dir(), "deletions.log")


def trash_dir() -> str:
    return os.path.join(data_dir(), "trash")


def _index_path() -> str:
    return os.path.join(trash_dir(), "index.json")


def _csize(num_bytes: int) -> str:
    """Compact size for the log: 164.9K, 12K, 1.5G, 0B (no spaces)."""
    n = float(num_bytes)
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.1f}".rstrip("0").rstrip(".") + unit
        n /= 1024
    return f"{n:.1f}T"


def _now_compact() -> str:
    return time.strftime("%y%m%d-%H%M")


def _append_log(act: str, path: str, size: int, files: int, ident: str) -> None:
    """Append one compact line; never raise — logging must not break a delete."""
    try:
        os.makedirs(data_dir(), exist_ok=True)
        line = f"{act} {_now_compact()} {_csize(size)} {files} {ident} {path}\n"
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _load_index() -> dict:
    try:
        with open(_index_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(index: dict) -> None:
    os.makedirs(trash_dir(), exist_ok=True)
    tmp = _index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=0)
    os.replace(tmp, _index_path())


def _new_id(index: dict) -> str:
    while True:
        ident = uuid.uuid4().hex[:6]
        if ident not in index:
            return ident


def _force_rmtree(path: str) -> None:
    """Remove our own trash tree, clearing read-only bits that block deletion."""
    def _onerror(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    shutil.rmtree(path, onerror=_onerror)


def record_delete(folder) -> None:
    """Log a permanent (non-recoverable) deletion. No trash copy is kept."""
    _append_log("d", folder.path, folder.size, folder.files, "-")


def quarantine(folder, min_depth: int, dest_dir: str | None = None,
               write_log: bool = True, cap: int = DEFAULT_TRASH_CAP_BYTES):
    """Move `folder` into the recovery trash instead of deleting it.

    Returns (True, id) on success or (False, reason). Honors the same safety
    refusals as a real delete (protected/shallow paths, reparse points), so it
    can never quarantine something delete itself would refuse.
    """
    from . import cleaner  # lazy: cleaner imports us back

    reason = cleaner._target_refusal(folder.path, min_depth)
    if reason is not None:
        return False, reason
    from .util import is_reparse_point

    src = os.path.normpath(folder.path)
    if is_reparse_point(src):
        return False, "refused (reparse point: junction/symlink)"
    if not os.path.isdir(src):
        return False, "not a directory"

    base = dest_dir or trash_dir()
    index = _load_index()
    ident = _new_id(index)
    slot = os.path.join(base, ident)
    try:
        os.makedirs(slot, exist_ok=True)
        dest = os.path.join(slot, os.path.basename(src) or "folder")
        try:
            os.rename(src, dest)          # fast path: same volume
        except OSError:
            shutil.move(src, dest)        # cross-volume: copy + remove
    except OSError as exc:
        try:
            _force_rmtree(slot)
        except OSError:
            pass
        return False, f"recover failed ({exc.strerror or exc})"

    index[ident] = {
        "orig": src,
        "t": int(time.time()),
        "size": int(folder.size),
        "files": int(folder.files),
        "name": os.path.basename(src),
        "dir": base,
    }
    _save_index(index)
    if write_log:
        _append_log("q", src, folder.size, folder.files, ident)
    _purge_to_cap(cap)
    return True, ident


def restore(ident: str) -> tuple[bool, str]:
    """Move a quarantined folder back to its original path. (ok, message)."""
    index = _load_index()
    entry = index.get(ident)
    if entry is None:
        return False, f"no recovery entry with id {ident!r}"
    orig = entry["orig"]
    slot = os.path.join(entry.get("dir") or trash_dir(), ident)
    src = os.path.join(slot, entry.get("name") or "")
    if os.path.exists(orig):
        return False, f"target already exists: {orig}"
    if not os.path.isdir(src):
        return False, "trash copy is missing on disk"
    try:
        os.makedirs(os.path.dirname(orig), exist_ok=True)
        try:
            os.rename(src, orig)
        except OSError:
            shutil.move(src, orig)
    except OSError as exc:
        return False, f"restore failed ({exc.strerror or exc})"
    _append_log("r", orig, entry.get("size", 0), entry.get("files", 0), ident)
    try:
        _force_rmtree(slot)
    except OSError:
        pass
    index.pop(ident, None)
    _save_index(index)
    return True, orig


def _purge_to_cap(cap: int) -> tuple[int, int]:
    """Evict oldest trash entries until total size <= cap. (count, bytes freed)."""
    index = _load_index()
    total = sum(int(e.get("size", 0)) for e in index.values())
    if total <= cap:
        return 0, 0
    # Oldest first (smallest timestamp).
    order = sorted(index.items(), key=lambda kv: kv[1].get("t", 0))
    freed = 0
    removed = 0
    for ident, entry in order:
        if total <= cap:
            break
        size = int(entry.get("size", 0))
        slot = os.path.join(entry.get("dir") or trash_dir(), ident)
        try:
            if os.path.isdir(slot):
                _force_rmtree(slot)
        except OSError:
            continue
        _append_log("p", entry.get("orig", ""), size, entry.get("files", 0), ident)
        index.pop(ident, None)
        total -= size
        freed += size
        removed += 1
    _save_index(index)
    return removed, freed


def empty_trash() -> tuple[int, int]:
    """Permanently remove everything in the trash. (count, bytes freed)."""
    index = _load_index()
    freed = 0
    removed = 0
    for ident, entry in list(index.items()):
        size = int(entry.get("size", 0))
        slot = os.path.join(entry.get("dir") or trash_dir(), ident)
        try:
            if os.path.isdir(slot):
                _force_rmtree(slot)
        except OSError:
            continue
        _append_log("p", entry.get("orig", ""), size, entry.get("files", 0), ident)
        freed += size
        removed += 1
    _save_index({})
    return removed, freed


def entries() -> list[dict]:
    """Current recoverable entries, newest first, each with its id."""
    index = _load_index()
    out = [dict(e, id=ident) for ident, e in index.items()]
    out.sort(key=lambda e: e.get("t", 0), reverse=True)
    return out


def read_log(limit: int = 40) -> list[str]:
    """Last `limit` raw log lines, oldest first; [] if no log yet."""
    try:
        with open(log_path(), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return lines[-limit:] if limit else lines
