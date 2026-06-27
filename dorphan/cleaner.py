"""Delete orphaned folders, with dry-run, interactive, and safety rails."""

from __future__ import annotations

import os
import stat

from .matcher import Classified
from .util import is_reparse_point

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
    from .config import config_dir

    sysdrive = os.environ.get("SystemDrive") or "C:"
    root = sysdrive + os.sep
    # Canonical absolute roots, built from the system drive rather than read from
    # the environment. Env vars (ProgramFiles, SystemRoot, ...) are inherited and
    # can be unset or tampered with by whoever launched us; if we trusted them
    # alone, clearing one would silently un-protect that whole tree. These fixed
    # entries keep the big shared trees protected no matter what the env says.
    fixed = [
        root,                                       # C:\
        os.path.join(root, "Windows"),
        os.path.join(root, "Windows", "System32"),
        os.path.join(root, "Program Files"),
        os.path.join(root, "Program Files (x86)"),
        os.path.join(root, "ProgramData"),
        os.path.join(root, "Users"),
        os.path.join(root, "Users", "Public"),
    ]
    # Env-derived entries still help for non-standard installs and the per-user
    # profile/AppData roots (which aren't fixed), but only ever ADD protection.
    env = [
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
        config_dir(),                               # %APPDATA%\dorphan (our own)
    ]
    return frozenset(_norm_key(c) for c in fixed + env if c)


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


def _remove_link(p: str) -> None:
    """Remove a symlink/junction itself, never touching what it points at.

    A directory junction/symlink is removed with rmdir (Windows) or unlink
    (POSIX dir symlink fails rmdir); a file symlink with unlink. We try both so
    one helper covers every reparse point on either platform.
    """
    try:
        os.rmdir(p)
    except OSError:
        try:
            os.unlink(p)
        except OSError:
            pass


def delete(path: str, on_progress=None,
           min_depth: int = DEFAULT_MIN_DEPTH) -> tuple[bool, str]:
    """Delete a folder tree file-by-file; on_progress(files_removed) per file.

    Never crosses a reparse point: an NTFS junction or symlink found inside the
    tree is unlinked in place, never descended into, so deletion can't escape
    `path` and destroy its target. The target itself is refused outright, since
    the depth/protected checks only inspected this (short) path, not wherever a
    junction would lead.
    """
    reason = _target_refusal(path, min_depth)
    if reason is not None:
        return False, reason
    norm = os.path.normpath(path)
    if is_reparse_point(norm):
        return False, "refused (reparse point: junction/symlink)"
    if not os.path.isdir(norm):
        return False, "not a directory"

    removed = 0
    dirs_seen: list[str] = []
    try:
        # topdown=True so we can prune reparse-point dirs from `dirs` BEFORE
        # os.walk would descend through them (it follows junctions otherwise,
        # since they aren't symlinks). We remove dirs deepest-first afterwards.
        for root, dirs, files in os.walk(norm, topdown=True, followlinks=False):
            kept = []
            for name in dirs:
                dp = os.path.join(root, name)
                if is_reparse_point(dp):
                    _remove_link(dp)  # the link only, not its target
                else:
                    kept.append(name)
            dirs[:] = kept
            for name in files:
                fp = os.path.join(root, name)
                if is_reparse_point(fp):
                    _remove_link(fp)
                elif _remove_file(fp):
                    removed += 1
                    if on_progress is not None:
                        on_progress(removed)
            dirs_seen.append(root)
        # Children were appended after their parents, so reversed() removes the
        # deepest directories first, then `norm` last.
        for d in reversed(dirs_seen):
            try:
                os.rmdir(d)
            except OSError:
                pass
    except OSError as exc:
        if os.path.exists(norm):
            return False, f"partially removed ({exc.strerror or exc})"
    if os.path.exists(norm):
        return False, "partially removed (locked files?)"
    return True, "deleted"


def _action_with_progress(c: Classified, label: str,
                          min_depth: int = DEFAULT_MIN_DEPTH,
                          recover=None, log: bool = False) -> tuple[bool, str]:
    """Remove one folder and print a result line.

    `recover` None -> permanent delete (optionally logged); otherwise the folder
    is *moved* into the recovery trash at `recover` (a dir, or "" for the default
    location) so it can be restored later. `log` records the action either way.
    """
    from .util import human_size, progress, progress_done

    f = c.folder

    if recover is not None:
        from . import recovery
        progress(f"  {label} moving {f.name} to recovery ...")
        ok, info = recovery.quarantine(
            f, min_depth, dest_dir=(recover or None), write_log=log)
        progress_done()
        if ok:
            print(f"  {label} recovered {f.name}  "
                  f"({human_size(f.size)}, restore id {info})")
        else:
            print(f"  {label} skipped {f.name}  ({info})")
        return ok, info

    total = max(f.files, 1)

    def report(done: int) -> None:
        pct = min(100, done * 100 // total)
        progress(f"  {label} deleting {f.name}  {done}/{f.files} files ({pct}%)")

    progress(f"  {label} deleting {f.name} ...")
    ok, msg = delete(f.path, on_progress=report, min_depth=min_depth)
    progress_done()
    if ok and log:
        from . import recovery
        recovery.record_delete(f)
    state = "deleted" if ok else "skipped"
    detail = human_size(f.size) if ok else msg
    print(f"  {label} {state} {f.name}  ({detail})")
    return ok, msg


def partition_orphans(
    orphans: list[Classified], min_depth: int = DEFAULT_MIN_DEPTH
) -> tuple[list[Classified], list[tuple[Classified, str]]]:
    """Split orphans (largest-first) into (deletable, refused).

    `deletable` is what a `delete` run would actually touch; `refused` pairs
    each skipped folder with the reason (too shallow, protected, ...). Keeping
    these apart means the numbered delete list and its count reflect only the
    folders that will really be removed, instead of burying one deletion among
    seven "skipped" lines.
    """
    ordered = sorted(orphans, key=lambda c: c.folder.size, reverse=True)
    deletable: list[Classified] = []
    refused: list[tuple[Classified, str]] = []
    for c in ordered:
        reason = _target_refusal(c.folder.path, min_depth)
        if reason is None:
            deletable.append(c)
        else:
            refused.append((c, reason))
    return deletable, refused


def _report_refused(refused: list[tuple[Classified, str]]) -> None:
    """Summarize folders that can't be deleted here in one line, not one each.

    The folder names already appear in the orphan table above, so re-listing each
    with an identical "refused (depth ...)" reason is just noise. We collapse to a
    count plus the one action that unlocks them.
    """
    shallow = sum(1 for _, reason in refused if "--unsafe" in reason)
    protected = len(refused) - shallow
    if shallow:
        print(f"  {shallow} orphan(s) sit in shallow ProgramData/Program Files "
              "folders and aren't bulk-deletable.")
        print("  To remove them, re-run from an elevated terminal: "
              "dorphan delete -i --unsafe")
    if protected:
        print(f"  {protected} orphan(s) are protected system paths and are never "
              "deleted.")


def clean(orphans: list[Classified], force: bool,
          min_depth: int = DEFAULT_MIN_DEPTH,
          recover=None, log: bool = False) -> tuple[int, int]:
    """Process orphans largest-first. Returns (count, bytes) actioned.

    Refused folders (too shallow / protected) are reported once as a block and
    excluded from the numbered list, so [i/n] counts only real deletions.
    `recover`/`log` are forwarded to the per-folder action (see
    _action_with_progress).
    """
    deletable, refused = partition_orphans(orphans, min_depth)
    if refused:
        _report_refused(refused)
        if deletable:
            print()
    total_bytes = 0
    count = 0
    n = len(deletable)
    for idx, c in enumerate(deletable, 1):
        f = c.folder
        if not force:
            verb = "would recover" if recover is not None else "would delete"
            print(f"  [dry-run] {verb}  {f.path}  ({f.files} files)")
            total_bytes += f.size
            count += 1
            continue
        ok, _ = _action_with_progress(c, f"[{idx}/{n}]", min_depth, recover, log)
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
                      on_whitelist=None, recover=None,
                      log: bool = False) -> tuple[int, int]:
    """Walk orphans largest-first, asking y/n per folder. Returns (count, bytes).

    `on_whitelist(name)` (if given) persists a folder so it's never scanned again;
    it should return where it was saved (or a falsy value). `recover`/`log` are
    forwarded to the per-folder action (recoverable trash vs permanent delete).
    """
    from .util import human_size

    ordered = sorted(orphans, key=lambda c: c.folder.size, reverse=True)
    total_bytes = 0
    count = 0

    print()
    print("Interactive cleanup - [y]es delete  [n]o keep  [l]ist contents  "
          "[w]hitelist (never scan again)  [q]uit")
    quit_now = False
    for idx, c in enumerate(ordered, 1):
        f = c.folder
        head = f"[{idx}/{len(ordered)}] {human_size(f.size):>10}  {f.path}"
        reason = _target_refusal(f.path, min_depth)
        if reason is not None:
            print(f"{head}  -- skipped: {reason}")
            continue
        # Prompt on the same line as the folder, so a kept folder is one line;
        # only an actual delete adds its result line below. A [l]ist re-prompts
        # the same item (the user can peek inside before deciding). There is no
        # bulk "delete all remaining" option here on purpose -- every folder must
        # be confirmed individually.
        decision = None  # "delete" | "keep" | "whitelist"
        while decision is None:
            try:
                answer = input(f"{head}  delete? [y/N/l/w/q] ").strip().lower()
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
                print(f"    whitelisted '{f.name}'{note}.")
                decision = "whitelist"
                break
            elif answer in ("y", "yes"):
                decision = "delete"
            else:
                decision = "keep"
        if quit_now:
            break
        # keep/whitelist need no extra line: the typed answer (and the whitelist
        # note) already show what happened.
        if decision in ("whitelist", "keep"):
            continue

        ok, _ = _action_with_progress(c, "   ", min_depth, recover, log)
        if ok:
            total_bytes += f.size
            count += 1
    return count, total_bytes
