"""Delete orphaned folders, with dry-run, interactive, and safety rails."""

from __future__ import annotations

import os
import stat

from .matcher import Classified

# Default minimum path depth (drive + N-1 components) a folder must have before
# we'll delete it. Tunable from the CLI via --depth (down to ABSOLUTE_MIN_DEPTH).
DEFAULT_MIN_DEPTH = 4

# Hard absolute floor: anything shallower than this is NEVER deletable, whatever
# --depth/--unsafe say. Depth 2 (e.g. C:\Foo) and drive roots are off limits.
ABSOLUTE_MIN_DEPTH = 3


def _norm_key(path: str) -> str:
    """Case/separator-normalized key for comparing paths on Windows."""
    return os.path.normcase(os.path.normpath(path))


def _protected_paths() -> frozenset[str]:
    """Exact folders that must NEVER be deleted, not even with --unsafe.

    Drive roots and the big shared system trees (Windows, Program Files,
    ProgramData, Users, the user profile and its AppData roots).
    """
    sysdrive = os.environ.get("SystemDrive", "C:")
    candidates = [
        sysdrive + os.sep,                          # C:\
        os.environ.get("SystemRoot"),               # C:\Windows
        os.environ.get("windir"),
        os.environ.get("ProgramFiles"),             # C:\Program Files
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramW6432"),
        os.environ.get("ProgramData"),              # C:\ProgramData
        os.environ.get("PUBLIC"),
        os.environ.get("USERPROFILE"),              # C:\Users\<me>
        os.environ.get("APPDATA"),                  # ...\AppData\Roaming
        os.environ.get("LOCALAPPDATA"),             # ...\AppData\Local
        os.path.join(sysdrive + os.sep, "Users"),   # C:\Users
    ]
    return frozenset(_norm_key(c) for c in candidates if c)


_PROTECTED = _protected_paths()


def _target_refusal(path: str, min_depth: int = DEFAULT_MIN_DEPTH) -> str | None:
    """Reason this path must not be deleted, or None if it's safe to delete.

    The hard floor (protected system folders, drive roots) always applies.
    The depth guard is the soft floor; the CLI lowers `min_depth` only when
    --unsafe is given (depths of 3 or lower require that explicit opt-in).
    """
    norm = os.path.normpath(path)
    if _norm_key(norm) in _PROTECTED:
        return "refused (protected system folder)"
    depth = len([p for p in norm.split(os.sep) if p])
    if depth < ABSOLUTE_MIN_DEPTH:  # too shallow to ever delete (e.g. C:\Foo)
        return (f"refused (depth {depth} < {ABSOLUTE_MIN_DEPTH}; "
                "too shallow to ever delete)")
    if depth < min_depth:
        return (f"refused (depth {depth} < {min_depth}; "
                "use -i --unsafe to remove it)")
    return None


def _is_safe_target(path: str, min_depth: int = DEFAULT_MIN_DEPTH) -> bool:
    """True if `path` is safe to delete under the given depth policy."""
    return _target_refusal(path, min_depth) is None


def _remove_file(fp: str) -> bool:
    try:
        os.remove(fp)
        return True
    except PermissionError:
        try:
            os.chmod(fp, stat.S_IWRITE)
            os.remove(fp)
            return True
        except OSError:
            return False
    except OSError:
        return False


def delete(path: str, on_progress=None,
           min_depth: int = DEFAULT_MIN_DEPTH) -> tuple[bool, str]:
    """Delete a folder tree file-by-file; on_progress(files_removed) per file."""
    reason = _target_refusal(path, min_depth)
    if reason is not None:
        return False, reason
    if not os.path.isdir(os.path.normpath(path)):
        return False, "not a directory"

    removed = 0
    try:
        for root, dirs, files in os.walk(path, topdown=False, followlinks=False):
            for name in files:
                if _remove_file(os.path.join(root, name)):
                    removed += 1
                    if on_progress is not None:
                        on_progress(removed)
            for name in dirs:
                dp = os.path.join(root, name)
                try:
                    if os.path.islink(dp):
                        os.unlink(dp)  # junction/symlink: remove without descending
                    else:
                        os.rmdir(dp)
                except OSError:
                    pass
        os.rmdir(path)
    except OSError as exc:
        if os.path.exists(path):
            return False, f"partially removed ({exc.strerror or exc})"
    if os.path.exists(path):
        return False, "partially removed (locked files?)"
    return True, "deleted"


def _delete_with_progress(c: Classified, label: str,
                          min_depth: int = DEFAULT_MIN_DEPTH) -> tuple[bool, str]:
    """Delete one folder, streaming a live 'deleting X/Y files' line."""
    from .util import human_size, progress, progress_done

    f = c.folder
    total = max(f.files, 1)

    def report(done: int) -> None:
        pct = min(100, done * 100 // total)
        progress(f"  {label} deleting {f.name}  {done}/{f.files} files ({pct}%)")

    progress(f"  {label} deleting {f.name} ...")
    ok, msg = delete(f.path, on_progress=report, min_depth=min_depth)
    progress_done()
    state = "deleted" if ok else "skipped"
    detail = human_size(f.size) if ok else msg
    print(f"  {label} {state} {f.name}  ({detail})")
    return ok, msg


def clean(orphans: list[Classified], force: bool,
          min_depth: int = DEFAULT_MIN_DEPTH) -> tuple[int, int]:
    """Process orphans largest-first. Returns (count, bytes) actioned."""
    ordered = sorted(orphans, key=lambda c: c.folder.size, reverse=True)
    total_bytes = 0
    count = 0
    n = len(ordered)
    for idx, c in enumerate(ordered, 1):
        f = c.folder
        if not force:
            reason = _target_refusal(f.path, min_depth)
            if reason is not None:
                print(f"  [dry-run] would SKIP    {f.path}  ({reason})")
                continue
            print(f"  [dry-run] would delete  {f.path}  ({f.files} files)")
            total_bytes += f.size
            count += 1
            continue
        ok, _ = _delete_with_progress(c, f"[{idx}/{n}]", min_depth)
        if ok:
            total_bytes += f.size
            count += 1
    return count, total_bytes


def _scan_one(path: str):
    """One level of a folder -> (dirs, files, error).

    `dirs` is a list of subfolder names; `files` is [(size, name)]; `error` is a
    string if the folder couldn't be read (else None).
    """
    try:
        entries = list(os.scandir(path))
    except OSError as exc:
        return [], [], (exc.strerror or str(exc))
    dirs: list[str] = []
    files: list[tuple[int, str]] = []
    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                dirs.append(e.name)
            else:
                files.append((e.stat(follow_symlinks=False).st_size, e.name))
        except OSError:
            files.append((0, e.name))
    return dirs, files, None


def _list_dir(path: str, limit: int = 50) -> None:
    """Print a folder's immediate contents so the user can decide before y/n.

    If a level holds exactly one subfolder and no files, descend into it (up to a
    cap) so nested wrappers like Foo\\sub\\sub2\\ reveal where content actually
    lives. Directories are listed first (most telling — e.g. a 'MSSQL' subfolder),
    then files with sizes. We don't recurse for sizes, so this stays instant.
    """
    from .util import human_size

    display = path
    for _ in range(40):  # cap guards against junction loops
        dirs, files, err = _scan_one(display)
        if err is not None:
            print(f"    (cannot list: {err})")
            return
        if len(dirs) == 1 and not files:
            display = os.path.join(display, dirs[0])
            continue
        break

    if display != path:
        print(f"    (single-subfolder chain, showing: {display})")
    if not dirs and not files:
        print("    (empty)")
        return

    dirs.sort(key=str.lower)
    files.sort(key=lambda r: r[0], reverse=True)
    print(f"    contents  ({len(dirs)} folder(s), {len(files)} file(s)):")
    shown = 0
    for name in dirs:
        if shown >= limit:
            break
        print(f"      {'<DIR>':>10}  {name}\\")
        shown += 1
    for size, name in files:
        if shown >= limit:
            break
        print(f"      {human_size(size):>10}  {name}")
        shown += 1
    remaining = len(dirs) + len(files) - shown
    if remaining > 0:
        print(f"      ... and {remaining} more")


def clean_interactive(orphans: list[Classified],
                      min_depth: int = DEFAULT_MIN_DEPTH,
                      on_whitelist=None) -> tuple[int, int]:
    """Walk orphans largest-first, asking y/n per folder. Returns (count, bytes).

    `on_whitelist(name)` (if given) persists a folder so it's never scanned again;
    it should return where it was saved (or a falsy value).
    """
    from .util import human_size

    ordered = sorted(orphans, key=lambda c: c.folder.size, reverse=True)
    total_bytes = 0
    count = 0
    delete_rest = False

    print()
    print("Interactive cleanup - [y]es delete  [n]o keep  [l]ist contents  "
          "[w]hitelist (never scan again)  [a]ll remaining  [q]uit")
    quit_now = False
    for idx, c in enumerate(ordered, 1):
        f = c.folder
        remaining = len(ordered) - idx + 1
        reason = _target_refusal(f.path, min_depth)
        if reason is not None:
            print(f"\n[{idx}/{len(ordered)}] {human_size(f.size):>10}  {f.path}"
                  f"\n    auto-skipped: {reason}")
            continue
        if not delete_rest:
            # Re-prompt the same folder after a [l]ist, so the user can peek
            # inside (e.g. spot a database/server subfolder) before deciding.
            decision = None  # "delete" | "keep" | "whitelist"
            print(f"\n[{idx}/{len(ordered)}] {human_size(f.size):>10}  {f.path}")
            while decision is None:
                try:
                    answer = input("    delete this? [y/N/l/w/a/q] ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nAborted.")
                    quit_now = True
                    break
                if answer in ("q", "quit"):
                    print("Stopped.")
                    quit_now = True
                    break
                if answer in ("l", "ls", "list"):
                    _list_dir(f.path)
                    continue
                if answer in ("w", "whitelist"):
                    dest = on_whitelist(f.name) if on_whitelist is not None else None
                    note = f" (saved to {dest})" if dest else ""
                    print(f"    whitelisted '{f.name}' - won't be scanned again{note}.")
                    decision = "whitelist"
                    break
                if answer in ("a", "all"):
                    confirm = input(
                        f"    delete ALL {remaining} remaining without asking? [y/N] "
                    ).strip().lower()
                    if confirm in ("y", "yes"):
                        delete_rest = True
                        decision = "delete"
                    else:
                        decision = "keep"  # treat as 'no' for this item
                elif answer in ("y", "yes"):
                    decision = "delete"
                else:
                    decision = "keep"
            if quit_now:
                break
            if decision == "whitelist":
                continue  # kept this run; message already printed
            if decision == "keep":
                print("    kept.")
                continue

        ok, _ = _delete_with_progress(c, "   ", min_depth)
        if ok:
            total_bytes += f.size
            count += 1
    return count, total_bytes
