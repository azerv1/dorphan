"""Plain-text reporting: tables sorted largest-first, no dependencies."""

from __future__ import annotations

import json

from .matcher import Classified
from .util import human_size, supports_color


def _c(text: str, code: str) -> str:
    if not supports_color():
        return text
    return f"\033[{code}m{text}\033[0m"


def print_table(items: list[Classified], title: str, show_match: bool = False) -> None:
    items = sorted(items, key=lambda c: c.folder.size, reverse=True)
    print()
    print(_c(title, "1"))
    if not items:
        print("  (none)")
        return

    name_w = max((len(c.folder.name) for c in items), default=4)
    name_w = min(max(name_w, 4), 40)
    root_w = max((len(c.folder.root_label) for c in items), default=4)

    header = f"  {'SIZE':>10}  {'FILES':>7}  {'LOCATION':<{root_w}}  NAME"
    if show_match:
        header += " " * (name_w - 4) + "   MATCHED"
    print(_c(header, "2"))

    for c in items:
        f = c.folder
        line = (
            f"  {human_size(f.size):>10}  {f.files:>7}  "
            f"{f.root_label:<{root_w}}  {f.name:<{name_w}}"
        )
        if show_match:
            extra = c.matched_app or (f"orphan ({c.confidence})" if c.status == "orphan" else "")
            line += f"   {extra}"
        print(line)


def print_summary(
    orphans: list[Classified], claimed: list[Classified], system: list[Classified]
) -> None:
    orphan_bytes = sum(c.folder.size for c in orphans)
    print()
    print(_c("Summary", "1"))
    print(f"  installed-app folders : {len(claimed)}")
    print(f"  system/OS folders     : {len(system)}")
    print(
        f"  {_c('orphaned leftovers', '33')}    : "
        f"{_c(str(len(orphans)), '1')}  "
        f"({_c(human_size(orphan_bytes), '1')} reclaimable)"
    )


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
