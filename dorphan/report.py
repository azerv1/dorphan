"""Plain-text reporting: tables sorted largest-first, no dependencies."""

from __future__ import annotations

import json
import re

from .matcher import Classified
from .util import human_size

# First run of letters/digits in a name; the "family" rows are clustered by.
# "Docker Desktop Installer" -> "Docker", "Mozilla-1de4..." -> "Mozilla",
# "Code_backup" -> "Code". Underscores split too, so backups group with the app.
_FAMILY_RE = re.compile(r"[^\W_]+", re.UNICODE)


def _family(name: str) -> tuple[str, str]:
    """Return (lowercase key, display word) for the leading word of a name."""
    m = _FAMILY_RE.search(name)
    word = m.group(0) if m else name.strip()
    return word.lower(), word


def _fmt_row(c: Classified, root_w: int, name_w: int, show_match: bool) -> str:
    f = c.folder
    line = (
        f"  {human_size(f.size):>10}  {f.files:>7}  "
        f"{f.root_label:<{root_w}}  {f.name:<{name_w}}"
    )
    if show_match:
        extra = c.matched_app or (f"orphan ({c.confidence})" if c.status == "orphan" else "")
        line += f"   {extra}"
    return line


def print_table(
    items: list[Classified], title: str, show_match: bool = False, group: bool = False
) -> None:
    items = sorted(items, key=lambda c: c.folder.size, reverse=True)
    print()
    print(title)
    if not items:
        print("  (none)")
        return

    name_w = max((len(c.folder.name) for c in items), default=4)
    name_w = min(max(name_w, 4), 40)
    root_w = max((len(c.folder.root_label) for c in items), default=4)

    header = f"  {'SIZE':>10}  {'FILES':>7}  {'LOCATION':<{root_w}}  NAME"
    if show_match:
        header += " " * (name_w - 4) + "   MATCHED"
    print(header)

    if not group:
        for c in items:
            print(_fmt_row(c, root_w, name_w, show_match))
        return

    # Group rows sharing a name family (Docker, Mozilla, ...) so the many folders
    # one app scatters across roots sit together. items is already size-sorted, so
    # each bucket stays largest-first; we order buckets by their combined size.
    buckets: dict[str, list[Classified]] = {}
    for c in items:
        buckets.setdefault(_family(c.folder.name)[0], []).append(c)
    ordered = sorted(
        buckets.values(),
        key=lambda rows: sum(c.folder.size for c in rows),
        reverse=True,
    )
    # Every family gets a `-- name --` header (even singletons), so each app is
    # one clearly delimited block and its rows read as nested beneath it.
    for rows in ordered:
        total = sum(c.folder.size for c in rows)
        disp = _family(rows[0].folder.name)[1]
        n = len(rows)
        print(f"  -- {disp}  ({human_size(total)}, {n} folder{'s' if n != 1 else ''}) --")
        for c in rows:
            print("  " + _fmt_row(c, root_w, name_w, show_match))


def print_summary(
    orphans: list[Classified], claimed: list[Classified], system: list[Classified]
) -> None:
    orphan_bytes = sum(c.folder.size for c in orphans)
    print()
    print("Summary")
    print(f"  installed-app folders : {len(claimed)}")
    print(f"  system/OS folders     : {len(system)}")
    print(f"  orphaned leftovers    : {len(orphans)}  "
          f"({human_size(orphan_bytes)} reclaimable)")


def print_json(items: list[Classified]) -> None:
    out = [
        {
            "name": c.folder.name,
            "path": c.folder.path,
            "location": c.folder.root_label,
            "size_bytes": c.folder.size,
            "files": c.folder.files,
            "status": c.status,
            "matched_app": c.matched_app,
            "confidence": c.confidence,
        }
        for c in sorted(items, key=lambda c: c.folder.size, reverse=True)
    ]
    print(json.dumps(out, indent=2))
