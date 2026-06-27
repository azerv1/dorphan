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
        # OverflowError guards 'inf'/'1e400' (float() succeeds, int(inf) blows up).
        return int(float(text) * mult)
    except (ValueError, OverflowError):
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


def _confirm_bulk_delete(count: int, recover: bool = False) -> bool:
    """Ask the user to confirm a bulk `-c -d` delete. True to proceed.

    Bulk delete removes every listed orphan at once with no per-folder prompt,
    so make the user pause and confirm they reviewed the `dorphan --scan` preview.
    A non-interactive stdin (piped/redirected) is treated as "no". When `recover`
    is set the folders are moved to a restorable trash, so the wording softens.
    """
    if not sys.stdin or not sys.stdin.isatty():
        print("error: refusing to bulk-delete without an interactive terminal "
              "to confirm. Run `dorphan -d` directly, or use `dorphan -i`.",
              file=sys.stderr)
        return False
    if recover:
        print(f"About to move {count} folder(s) to recovery (restorable).")
    else:
        print(f"About to permanently DELETE {count} folder(s).")
    print("Are you sure? Have you reviewed the report with `dorphan --scan` first?")
    try:
        answer = input("Type 'yes' to proceed, anything else to abort: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in ("yes", "y")


def print_deletion_log() -> None:
    """Show the recent deletion log (compact lines) with a tiny legend."""
    from . import recovery

    lines = recovery.read_log()
    if not lines:
        print("No deletions logged yet.")
        return
    print("act t=yYMMDD-HHMM  size  files  id  path   "
          "(act: d=delete q=quarantine r=restore p=purge)")
    for line in lines:
        print("  " + line)
    items = recovery.entries()
    if items:
        print(f"\n{len(items)} folder(s) recoverable. "
              "Restore with: dorphan --restore <id>")


def run_restore(ident: str) -> int:
    """Restore one quarantined folder by id; return a process exit code."""
    from . import recovery

    ok, msg = recovery.restore(ident)
    if ok:
        print(f"Restored to {msg}")
        return 0
    print(f"error: {msg}", file=sys.stderr)
    return 1


def run_prune() -> int:
    """Permanently purge the recovery trash."""
    from . import recovery

    count, freed = recovery.empty_trash()
    print(f"Purged {human_size(freed)} across {count} recovered folder(s).")
    return 0


def print_advanced_help() -> None:
    """Print advanced cleanup options that are hidden from normal --help."""
    print(textwrap.dedent(
        f"""\
        dorphan advanced help

        Examples:
          dorphan --scan                 preview what bulk delete would remove
          dorphan -d                     delete the orphaned folders
          dorphan -d --trash             delete, but keep a restorable copy
          dorphan -i                     review and delete one folder at a time
          dorphan --scan -m 100MB        preview, only folders >= 100 MB
          dorphan --scan --confidence medium   include lower-confidence orphans
          dorphan -d --exclude npm* node_modules   skip folders by name/glob
          dorphan -i --unsafe            (elevated) reach shallow system folders

        Safety rules:
          - A plain scan never deletes; shallow folders are never bulk-deleted.
          - Reaching shallow folders needs `-i --unsafe` + an elevated terminal.
          - C:\\Windows, Program Files, drive roots, and protected system
            folders are always refused.

        Recovery:
          Every delete is recorded in a compact log (deletions.log under
          %LOCALAPPDATA%\\dorphan). Deletes are permanent by default.
          --trash [PATH]       move deletions to a restorable trash instead
          --log                show the recent deletion log
          --restore ID         put a trashed folder back (id from --log)
          --prune              empty the trash for good

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
          dorphan --scan          preview orphaned folders; delete nothing
          dorphan -d              delete the orphaned folders
          dorphan -i              review and delete one folder at a time
          dorphan --help          show full help
          dorphan --helpme        advanced options and examples

        Safety:
          Plain `dorphan` does not scan or delete.
          Deleting requires `dorphan -d` or `dorphan -i`.
        """
    ))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorphan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Find orphaned Windows app folders. Default: scan only; delete nothing.",
        epilog="More help and examples: dorphan --helpme",
    )

    p.add_argument("--version", action="version", version=f"Dorphan {__version__}")
    p.add_argument(
        "--helpme", action="store_true", help=argparse.SUPPRESS,
    )

    cleanup = p.add_argument_group("cleanup")
    cleanup.add_argument(
        "-s", "--scan", action="store_true",
        help="preview orphaned folders; deletes nothing",
    )
    cleanup.add_argument(
        "-d", "--delete", action="store_true",
        help="delete the orphaned folders",
    )
    cleanup.add_argument(
        "-i", "--interactive", action="store_true",
        help="confirm each folder (y/n, l=list, w=whitelist)",
    )
    cleanup.add_argument(
        "--unsafe", action="store_true",
        help="allow shallow deletes; requires -i and Administrator",
    )

    filters = p.add_argument_group("filters")
    filters.add_argument(
        "--confidence", choices=["high", "medium"], default="high", metavar="LEVEL",
        help="minimum orphan confidence: high or medium; default: high",
    )
    filters.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help="minimum path depth a folder must have to be deletable "
             f"(advanced; default {cleaner.DEFAULT_MIN_DEPTH}, needs --unsafe below it)",
    )
    filters.add_argument(
        "-m", "--min-size", type=_parse_size, default=0, metavar="SIZE",
        help="only show folders at least this big, e.g. 100MB, 1G",
    )
    filters.add_argument(
        "--no-program-files", action="store_true",
        help="skip Program Files; scan data folders only",
    )
    filters.add_argument(
        "-a", "--all", action="store_true",
        help="also show folders matched to installed apps",
    )
    filters.add_argument(
        "--exclude", action="extend", nargs="+", default=[], metavar="PATTERN",
        help="exclude folder names/globs from orphan results",
    )
    filters.add_argument(
        "--json", action="store_true",
        help="output JSON",
    )

    recovery_group = p.add_argument_group("recovery")
    recovery_group.add_argument(
        "--trash", nargs="?", const="", default=None, metavar="PATH",
        help="move deleted folders to a restorable trash (optionally at PATH) "
             "instead of deleting them permanently",
    )
    recovery_group.add_argument(
        "--restore", metavar="ID",
        help="restore a trashed folder by its id (see --log) and exit",
    )
    recovery_group.add_argument(
        "--log", action="store_true",
        help="show the recent deletion log and exit",
    )
    recovery_group.add_argument(
        "--prune", action="store_true",
        help=argparse.SUPPRESS,
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

    if args.log:
        print_deletion_log()
        return 0

    if args.restore is not None:
        return run_restore(args.restore)

    if args.prune:
        return run_prune()

    # --trash only makes sense alongside an actual delete (-d or -i).
    if args.trash is not None and not (args.delete or args.interactive):
        print("error: --trash only applies when deleting; use it with "
              "`dorphan -d` or `dorphan -i`.", file=sys.stderr)
        return 2

    if args.interactive and (args.scan or args.delete):
        print("error: choose either -i/--interactive or -s/--scan/-d/--delete, "
              "not both.", file=sys.stderr)
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

    print("Finding app-data folders...", file=sys.stderr)
    folders = scanner.enumerate_folders(cfg, compute_size=False)
    print(f"  found {len(folders)} folders; classifying...", file=sys.stderr)
    classified = classify_all(inv, folders, cfg)

    all_orphans = [c for c in classified if c.status == "orphan"]
    all_claimed = [c for c in classified if c.status == "claimed"]
    all_system = [c for c in classified if c.status == "system"]

    # Speed: measure only the folders we'll actually display. Installed-app and
    # system folders (often the bulk of the bytes) are skipped unless --all/JSON
    # needs their sizes, so the common run only walks the handful of orphans.
    if args.json:
        to_measure = classified if args.all else all_orphans
    else:
        to_measure = all_orphans + (all_claimed if args.all else [])

    scanned = {"bytes": 0}

    def _scan_progress(done: int, total: int, folder) -> None:
        scanned["bytes"] += folder.size
        pct = done * 100 // total if total else 100
        util.progress(f"  measuring [{done}/{total}] {pct:>3}%  "
                      f"{human_size(scanned['bytes']):>9} seen  "
                      f"{folder.root_label}\\{folder.name}")

    print(f"  measuring {len(to_measure)} folder(s)...", file=sys.stderr)
    # Classified.folder is the same Folder object, so measuring it in place
    # updates the size/file-count we read back through the classified entries.
    scanner.measure([c.folder for c in to_measure], on_progress=_scan_progress)
    util.progress_done()

    orphans = list(all_orphans)
    if args.min_size:
        orphans = [c for c in orphans if c.folder.size >= args.min_size]

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
        if args.all:
            items = classified
            if args.min_size:
                items = [c for c in items if c.folder.size >= args.min_size]
        else:
            items = orphans
        report.print_json(items)
        return 0

    # In interactive mode the user reviews each orphan one by one, so the full
    # table would just repeat what the prompts show. Skip it and let the summary
    # below give the overall headline before we drop into the y/n loop.
    if not args.interactive:
        report.print_table(orphans, "Orphaned leftovers (no installed app claims these)",
                            show_match=True)
        if args.all:
            claimed = all_claimed
            if args.min_size:
                claimed = [c for c in claimed if c.folder.size >= args.min_size]
            report.print_table(claimed, "Installed-app folders", show_match=True)

    # Summary counts reflect true totals; the orphan figure honors your filters.
    report.print_summary(orphans, all_claimed, all_system)

    if args.interactive:
        if not orphans:
            print("\nNothing to clean.")
            return 0
        count, freed = cleaner.clean_interactive(
            orphans, min_depth=min_depth,
            on_whitelist=config_mod.add_to_whitelist,
            recover=args.trash, log=True)
        print()
        verb = "Recovered" if args.trash is not None else "Freed"
        print(f"{verb} {human_size(freed)} across {count} folders.")
        if args.trash is not None and count:
            print("Restore any of them with: dorphan --restore <id>  "
                  "(see dorphan --log)")
    elif args.scan or args.delete:
        print()
        recovering = args.trash is not None
        deletable, _refused = cleaner.partition_orphans(orphans, min_depth)
        if args.delete:
            if deletable and not _confirm_bulk_delete(len(deletable), recovering):
                print("Aborted. Nothing deleted.")
                return 0
            if deletable:
                msg = ("Moving orphaned folders to recovery (largest first)..."
                       if recovering else
                       "Deleting orphaned folders (largest first)...")
                print(msg)
        else:
            print("Dry-run - nothing will be deleted. "
                  "Re-run with -d to delete.")
        count, freed = cleaner.clean(
            orphans, force=args.delete, min_depth=min_depth,
            recover=args.trash, log=True)
        print()
        if count:
            if not args.delete:
                verb = "Would free"
            else:
                verb = "Recovered" if recovering else "Freed"
            print(f"{verb} {human_size(freed)} across {count} folders.")
            if recovering and args.delete:
                print("Restore any of them with: dorphan --restore <id>  "
                      "(see dorphan --log)")
        elif deletable:  # had targets but every delete failed (locked files, ...)
            print("No folders were removed (all delete attempts failed).")
        else:
            print("Nothing here is bulk-deletable. Use `dorphan -i` to review "
                  "folders one by one.")
    elif orphans:
        print()
        print("Tip: review the list above, then run "
              "`dorphan --scan` to preview, or `dorphan -i` to delete one by one.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
