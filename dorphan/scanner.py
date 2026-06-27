"""Enumerate candidate app-data folders and compute their sizes."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
                    except OSError:
                        continue
                    folders.append(
                        Folder(path=entry.path, name=entry.name, root_label=label)
                    )
        except OSError:
            continue

    # Pass 2 — slow: measure each folder, reporting progress.
    if compute_size:
        total = len(folders)
        for i, f in enumerate(folders, 1):
            f.size, f.files = dir_size(f.path)
            if on_progress is not None:
                on_progress(i, total, f)
    return folders
