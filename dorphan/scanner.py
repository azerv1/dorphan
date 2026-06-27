"""Enumerate candidate app-data folders and compute their sizes."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .util import is_reparse_point


@dataclass
class Folder:
    path: str
    name: str
    root_label: str
    size: int = 0
    files: int = 0


def scan_roots(config) -> list[tuple[str, str]]:
    """Return existing (label, path) pairs for every configured data location."""
    # De-dup while preserving order (Programs may resolve under Local, etc.)
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for label, path in config.active_roots():
        norm = os.path.normcase(os.path.normpath(path))
        if norm in seen or not os.path.isdir(path):
            continue
        seen.add(norm)
        out.append((label, path))
    return out


def enumerate_folders(
    config,
    compute_size: bool = True,
    on_progress=None,
) -> list[Folder]:
    """List each scan root's subfolders; on_progress(done, total, folder) per size."""
    from .util import dir_size

    # Pass 1 — cheap: discover every top-level folder.
    folders: list[Folder] = []
    for label, root in scan_roots(config):
        try:
            with os.scandir(root) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        # A junction/symlink reports as a directory but points
                        # elsewhere; never offer it as a deletion candidate, or
                        # deleting it would reach into its target.
                        if is_reparse_point(entry.path):
                            continue
                    except OSError:
                        continue
                    folders.append(
                        Folder(path=entry.path, name=entry.name, root_label=label)
                    )
        except OSError:
            continue

    # Pass 2 — slow: measure each folder, reporting progress.
    if compute_size:
        measure(folders, on_progress=on_progress)
    return folders


def measure(folders: list[Folder], on_progress=None, workers: int | None = None) -> None:
    """Fill in size/file-count for the given folders, in place.

    Sizing walks each tree, which is I/O-bound, so we fan the folders out across
    a small thread pool — Python releases the GIL during the os.scandir/stat
    syscalls, so this overlaps disk latency and is markedly faster than serial on
    SSDs. Progress is reported from this (single) thread as each folder finishes.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from .util import dir_size

    total = len(folders)
    if total == 0:
        return
    if workers is None:
        workers = min(16, (os.cpu_count() or 4) * 4)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(dir_size, f.path): f for f in folders}
        for fut in as_completed(futures):
            f = futures[fut]
            try:
                f.size, f.files = fut.result()
            except Exception:  # pragma: no cover - dir_size already swallows OSError
                f.size, f.files = 0, 0
            done += 1
            if on_progress is not None:
                on_progress(done, total, f)
