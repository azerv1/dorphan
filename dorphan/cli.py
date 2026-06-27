"""Dorphan command-line interface."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import textwrap

from . import __version__, cleaner, config as config_mod, inventory, report, scanner, util
from .matcher import classify_all
from .util import human_size

# Donation addresses live in this data file, not in code — edit it to update.
DONATE_FILE = os.path.join(os.path.dirname(__file__), "donate.json")


def load_donations() -> list[tuple[str, str]]:
    """Read (coin, address) pairs from donate.json; [] if missing/unreadable."""
    try:
        with open(DONATE_FILE, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [(str(k), str(v)) for k, v in data.items()]


def print_donation() -> None:
    items = load_donations()
    if not items:
        print("No donation info available.")
        return
    for coin, address in items:
        print(f"  {coin:<5} {address}")


def _parse_size(text: str) -> int:
    """Parse '500MB', '1.5G', '200k', or a raw byte count into bytes."""
    text = text.strip().upper().rstrip("B")
    mult = 1
    for suffix, factor in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20), ("K", 1 << 10)):
        if text.endswith(suffix):
            mult = factor
            text = text[:-1]
            break
    try:
        return int(float(text) * mult)
    except ValueError:
        raise argparse.ArgumentTypeError(f"invalid size: {text!r}")


def _excluded(folder_name: str, folder_path: str, patterns: list[str]) -> bool:
    """True if a folder matches any --exclude pattern (glob or substring)."""
    name = folder_name.lower()
    path = folder_path.lower()
    for pat in patterns:
        p = pat.lower()
        if fnmatch.fnmatch(name, p) or p in name or p in path:
            return True
    return False


def print_advanced_help() -> None:
    """Print advanced cleanup options that are hidden from normal --help."""
    print(textwrap.dedent(
        f"""\
        dorphan advanced help

        Normal usage:
          dorphan              scan only; delete nothing
          dorphan -c           dry-run cleanup preview
          dorphan -i           confirm each deletion manually

        Advanced cleanup:
          --depth N            minimum path depth allowed for deletion
                               default: {cleaner.DEFAULT_MIN_DEPTH}
                               absolute minimum: {cleaner.ABSOLUTE_MIN_DEPTH} (Adminstrator only)

          --unsafe             allow depth-{cleaner.ABSOLUTE_MIN_DEPTH} folders such as:
                               C:\\Program Files\\SomeApp
                               C:\\ProgramData\\SomeApp

        Safety rules:
          - Nothing is deleted by a normal scan.
          - Bulk delete requires: dorphan -c -d
          - --unsafe requires: dorphan -i --unsafe
          - --unsafe requires an elevated Administrator terminal.
          - Shallow folders are never bulk-deleted.
          - C:\\Windows, C:\\Program Files, drive roots, and protected system
            folders are always refused.

        Support:
          --donate
        """
    ))


def print_basic_usage() -> None:
    """Print the tiny landing-page help shown when the user runs plain `dorphan`."""
    print(textwrap.dedent(
        """\
        Dorphan

        Find orphaned Windows app folders.

        Usage:
          dorphan --help          show full help
          dorphan -m 100MB        scan folders >= 100 MB
          dorphan --json          scan and output JSON
          dorphan -c              dry-run cleanup preview
          dorphan -i              interactive cleanup

        Safety:
          Plain `dorphan` does not scan or delete.
          Deleting requires `dorphan -c -d` or `dorphan -i`.
        """
    ))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorphan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Find orphaned Windows app folders. Default: scan only; delete nothing.",
        epilog=textwrap.dedent(
            """\
            examples:
              dorphan                 scan only
              dorphan -m 100MB        show folders >= 100 MB
              dorphan --exclude npm*  hide matching folders
              dorphan -c              preview cleanup; delete nothing
              dorphan -c -d           delete listed orphans
              dorphan -i              confirm each deletion manually

            safety:
              Normal scans never delete.
              Bulk delete requires -c -d.
              Risky shallow deletes require -i --unsafe and Administrator.

            More help: dorphan --helpme
            """
        ),
    )

    p.add_argument("--version", action="version", version=f"Dorphan {__version__}")
    p.add_argument(
        "--helpme", action="store_true", help=argparse.SUPPRESS,
    )

    scan = p.add_argument_group("scan")
    scan.add_argument(
        "-m", "--min-size", type=_parse_size, default=0, metavar="SIZE",
        help="only show folders at least this big, e.g. 100MB, 1G",
    )
    scan.add_argument(
        "--no-program-files", action="store_true",
        help="skip Program Files; scan data folders only",
    )
    scan.add_argument(
        "-a", "--all", action="store_true",
        help="also show folders matched to installed apps",
    )
    scan.add_argument(
        "--exclude", action="extend", nargs="+", default=[], metavar="PATTERN",
        help="exclude folder names/globs from orphan results",
    )
    scan.add_argument(
        "--confidence", choices=["high", "medium"], default="high", metavar="LEVEL",
        help="minimum orphan confidence: high or medium; default: high",
    )
    scan.add_argument(
        "--json", action="store_true",
        help="output JSON",
    )

    cleanup = p.add_argument_group("cleanup")
    cleanup.add_argument(
        "-c", "--clean", action="store_true",
        help="preview cleanup; deletes nothing",
    )
    cleanup.add_argument(
        "-d", "--delete", action="store_true",
        help="actually delete; requires --clean",
    )
    cleanup.add_argument(
        "-i", "--interactive", action="store_true",
        help="ask y/n before each deletion",
    )
    cleanup.add_argument(
        "--unsafe", action="store_true",
        help="allow shallow deletes; requires -i and Administrator",
    )

    config_group = p.add_argument_group("config")
    config_group.add_argument(
        "--config", metavar="PATH",
        help="use a TOML config file",
    )
    config_group.add_argument(
        "--init-config", nargs="?", const="", metavar="PATH",
        help="write a starter config and exit",
    )

    # Hidden from normal help. It is intentionally advanced because lowering
    # the deletion depth can reach shallow Program Files / ProgramData folders.
    p.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help=argparse.SUPPRESS,
    )
    p.add_argument(
        "--donate", action="store_true",
        help=argparse.SUPPRESS,
    )
    return p

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print_basic_usage()
        return 0

    args = build_parser().parse_args(argv)

    if args.helpme:
        print_advanced_help()
        return 0

    if args.donate:
        print_donation()
        return 0

    if args.init_config is not None:
        target = config_mod.write_default_config(args.init_config or None)
        print(f"Wrote starter config to {target}")
        print("Edit it, then run dorphan (it's picked up automatically).")
        return 0

    if args.interactive and (args.clean or args.delete):
        print("error: choose either -i/--interactive or --clean/--delete, not both.",
              file=sys.stderr)
        return 2

    if args.delete and not args.clean:
        print("error: --delete is only valid with --clean. Use `dorphan -c` "
              "to preview, or `dorphan -c -d` to delete.",
              file=sys.stderr)
        return 2

    # --unsafe is interactive-only: shallow folders may only be removed one at a
    # time with a y/n confirmation, never in a bulk force-delete.
    if args.unsafe and not args.interactive:
        print("error: --unsafe only works with -i/--interactive; shallow "
              "folders must be confirmed one by one, not mass-deleted.",
              file=sys.stderr)
        return 2

    # Resolve the deletion depth floor. Depth 3 is the lowest allowed value:
    # anything shallower is never deletable. Reaching depth 3 needs -i --unsafe.
    if args.depth is not None and args.depth < cleaner.ABSOLUTE_MIN_DEPTH:
        print(f"error: the minimum --depth is {cleaner.ABSOLUTE_MIN_DEPTH}; "
              "folders shallower than that are never deletable.", file=sys.stderr)
        return 2
    if args.depth is not None and args.depth <= 3 and not args.unsafe:
        print(f"error: --depth {args.depth} reaches shallow folders; re-run "
              "with -i --unsafe to remove them one by one.", file=sys.stderr)
        return 2
    if args.depth is not None:
        min_depth = args.depth
    elif args.unsafe:
        min_depth = cleaner.ABSOLUTE_MIN_DEPTH  # -i --unsafe drops to depth 3
    else:
        min_depth = cleaner.DEFAULT_MIN_DEPTH

    # Reaching shallow folders (Program Files, ProgramData) means deleting files
    # only Administrators can touch. Require elevation up front instead of having
    # every delete fail with permission errors midway through.
    if min_depth < cleaner.DEFAULT_MIN_DEPTH and not util.is_elevated():
        print("error: removing shallow folders (--unsafe / --depth below "
              f"{cleaner.DEFAULT_MIN_DEPTH}) deletes files under Program Files / "
              "ProgramData that need Administrator rights. Re-run dorphan from an "
              "elevated terminal (right-click > Run as administrator).",
              file=sys.stderr)
        return 2

    if sys.platform != "win32":
        print("Dorphan targets Windows; registry sources are unavailable here.",
              file=sys.stderr)

    try:
        cfg, cfg_path = config_mod.load(args.config)
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    cfg.include_program_files = not args.no_program_files
    if cfg_path:
        print(f"Using config {cfg_path}", file=sys.stderr)

    print("Scanning installed apps...", file=sys.stderr)
    inv = inventory.collect()
    print(f"  found {len(inv.apps)} installed app entries.", file=sys.stderr)

    print("Scanning app-data folders (this can take a moment)...", file=sys.stderr)

    scanned = {"bytes": 0}

    def _scan_progress(done: int, total: int, folder) -> None:
        scanned["bytes"] += folder.size
        pct = done * 100 // total if total else 100
        util.progress(f"  measuring [{done}/{total}] {pct:>3}%  "
                      f"{human_size(scanned['bytes']):>9} seen  "
                      f"{folder.root_label}\\{folder.name}")

    folders = scanner.enumerate_folders(
        cfg,
        compute_size=True,
        on_progress=_scan_progress,
    )
    util.progress_done()
    print(f"  measured {len(folders)} folders.", file=sys.stderr)
    classified = classify_all(inv, folders, cfg)

    if args.min_size:
        classified = [c for c in classified if c.folder.size >= args.min_size]

    orphans = [c for c in classified if c.status == "orphan"]
    claimed = [c for c in classified if c.status == "claimed"]
    system = [c for c in classified if c.status == "system"]

    # Keep orphans at or above the requested confidence ("high" > "medium").
    _conf_rank = {"medium": 0, "high": 1}
    threshold = _conf_rank[args.confidence]
    if threshold > 0:
        before = len(orphans)
        orphans = [c for c in orphans
                   if _conf_rank.get(c.confidence, 0) >= threshold]
        dropped = before - len(orphans)
        if dropped:
            print(f"  hid {dropped} folder(s) below '{args.confidence}' confidence.",
                  file=sys.stderr)

    if args.exclude:
        kept = [c for c in orphans
                if not _excluded(c.folder.name, c.folder.path, args.exclude)]
        excluded_n = len(orphans) - len(kept)
        orphans = kept
        if excluded_n:
            print(f"  excluded {excluded_n} folder(s) via --exclude.",
                  file=sys.stderr)

    if args.json:
        report.print_json(orphans if not args.all else classified)
        return 0

    report.print_table(orphans, "Orphaned leftovers (no installed app claims these)",
                        show_match=True)
    if args.all:
        report.print_table(claimed, "Installed-app folders", show_match=True)

    report.print_summary(orphans, claimed, system)

    if args.interactive:
        if not orphans:
            print("\nNothing to clean.")
            return 0
        count, freed = cleaner.clean_interactive(orphans, min_depth=min_depth)
        print()
        print(f"Freed {human_size(freed)} across {count} folders.")
    elif args.clean:
        print()
        if args.delete:
            print(report._c("Deleting orphaned folders (largest first)...", "1;31"))
        else:
            print(report._c("Dry-run - nothing will be deleted. "
                            "Re-run with --clean --delete to delete.", "1;33"))
        count, freed = cleaner.clean(
            orphans, force=args.delete, min_depth=min_depth)
        verb = "Freed" if args.delete else "Would free"
        print()
        print(f"{verb} {human_size(freed)} across {count} folders.")
    elif orphans:
        print()
        print("Tip: review the list above, then run "
              "`dorphan --clean` to preview, or `dorphan -i` to delete one by one.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
