"""Dorphan command-line interface.

Subcommand-based (git/docker style): `dorphan scan|delete|restore|log|prune|config`.
Filters (-m/--confidence/--exclude/--no-program-files/--config) are shared by the
`scan` and `delete` commands; delete-only knobs (-i/--trash/--depth) live
on `delete`.
"""

from __future__ import annotations

import argparse
import contextlib
import fnmatch
import io
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
    """Ask the user to confirm a bulk `dorphan delete` run. True to proceed.

    Bulk delete removes every listed orphan at once with no per-folder prompt,
    so make the user pause and confirm they reviewed the `dorphan scan` preview.
    A non-interactive stdin (piped/redirected) is treated as "no". When `recover`
    is set the folders are moved to a restorable trash, so the wording softens.
    """
    if not sys.stdin or not sys.stdin.isatty():
        print("error: refusing to bulk-delete without an interactive terminal "
              "to confirm. Run `dorphan delete` directly, or `dorphan delete -i`.",
              file=sys.stderr)
        return False
    if recover:
        print(f"About to move {count} folder(s) to recovery (restorable).")
    else:
        print(f"About to permanently DELETE {count} folder(s).")
    print("Are you sure? Have you reviewed the report with `dorphan scan` first?")
    try:
        answer = input("Type 'yes' to proceed, anything else to abort: ")
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer.strip().lower() in ("yes", "y")


def print_deletion_log() -> None:
    """Show the recent deletion log (compact lines) with a tiny legend."""
    from . import recovery

    lines = recovery.read_log(limit=0)  # full history; the pager handles length
    if not lines:
        print("No deletions logged yet.")
        return
    out = ["act t=yYMMDD-HHMM  size  files  id  path   "
           "(act: d=delete q=quarantine r=restore p=purge)"]
    out += ["  " + line for line in lines]
    items = recovery.entries()
    if items:
        out.append(f"\n{len(items)} folder(s) recoverable. "
                   "Restore with: dorphan restore <id>")
    util.page("\n".join(out))


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


def run_config(args: argparse.Namespace) -> int:
    """Handle `dorphan config init|path`."""
    action = getattr(args, "config_cmd", None)
    if action == "init":
        target = config_mod.write_default_config(args.path or None)
        print(f"Wrote starter config to {target}")
        print("Edit it, then run dorphan (it's picked up automatically).")
        return 0
    if action == "path":
        print(f"config file : {config_mod.default_config_path()}")
        print(f"whitelist   : {config_mod.whitelist_path()}")
        print(f"data / trash: {config_mod.data_dir()}")
        return 0
    print("usage: dorphan config {init [PATH] | path}", file=sys.stderr)
    return 2


def _help_epilog() -> str:
    """Examples + safety + recovery, appended to the standard `dorphan --help`."""
    return textwrap.dedent(
        f"""\
        examples:
          dorphan scan                list orphaned folders (read-only)
          dorphan scan -m 100MB       only folders >= 100 MB
          dorphan delete              delete them (asks once first)
          dorphan delete -i           review and delete one at a time
          dorphan delete --trash      delete, but keep a restorable copy
          dorphan delete -i --depth 3 (elevated) reach shallow system folders

        safety:
          - `dorphan scan` is read-only; it never deletes.
          - `dorphan delete` asks first; shallow folders are never bulk-deleted
            (default {cleaner.DEFAULT_MIN_DEPTH}-deep minimum).
          - Reaching shallow folders needs `delete -i --depth 3` + an elevated
            terminal.
          - C:\\Windows, Program Files, drive roots, and protected system folders
            are always refused.

        recovery (deletes are permanent + logged by default):
          dorphan log            show the deletion log
          dorphan restore <id>   put a trashed folder back
          dorphan prune          empty the trash for good

        support:
          dorphan --donate       show donation addresses

        Run `dorphan <command> -h` for a command's own options."""
    )


def print_basic_usage() -> None:
    """Landing-page help shown when the user runs plain `dorphan`."""
    print(textwrap.dedent(
        """\
        Dorphan - find orphaned Windows app folders.

        Commands:
          dorphan scan             list orphaned folders (read-only)
          dorphan delete           delete them (asks first; add -i to confirm each)
          dorphan restore <id>     restore a folder from the trash
          dorphan log              show the deletion log
          dorphan prune            empty the recoverable trash
          dorphan config init      write a starter config

          dorphan <command> -h     options for a command
          dorphan --help           full help, examples, and safety notes
        """
    ))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorphan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Find orphaned Windows app folders.",
        epilog=_help_epilog(),
    )
    p.add_argument("--version", action="version", version=f"Dorphan {__version__}")
    p.add_argument("--donate", action="store_true", help=argparse.SUPPRESS)

    # Filters shared by `scan` and `delete`, defined once and reused via parents=.
    common = argparse.ArgumentParser(add_help=False)
    f = common.add_argument_group("filters")
    f.add_argument(
        "-m", "--min-size", type=_parse_size, default=0, metavar="SIZE",
        help="only show folders at least this big, e.g. 100MB, 1G",
    )
    f.add_argument(
        "--confidence", choices=["high", "medium"], default="high", metavar="LEVEL",
        help="minimum orphan confidence: high or medium; default: high",
    )
    f.add_argument(
        "--exclude", action="extend", nargs="+", default=[], metavar="PATTERN",
        help="exclude folder names/globs from results",
    )
    f.add_argument(
        "--no-program-files", action="store_true",
        help="skip Program Files; data folders only",
    )
    f.add_argument(
        "--config", metavar="PATH", help="use a TOML config file",
    )

    sub = p.add_subparsers(dest="command", metavar="<command>")

    sc = sub.add_parser(
        "scan", parents=[common], help="list orphaned folders (read-only)",
        description="List orphaned folders. Read-only; never deletes.",
    )
    sc.add_argument(
        "-a", "--all", action="store_true",
        help="also show folders matched to installed apps",
    )
    sc.add_argument("--json", action="store_true", help="output JSON")

    dl = sub.add_parser(
        "delete", parents=[common], help="delete orphaned folders (asks first)",
        description="Delete orphaned folders. Asks for confirmation first.",
    )
    dl.add_argument(
        "-i", "--interactive", action="store_true",
        help="confirm each folder (y/n, l=list, w=whitelist)",
    )
    dl.add_argument(
        "--trash", nargs="?", const="", default=None, metavar="PATH",
        help="move folders to a restorable trash (optionally at PATH) instead "
             "of deleting them permanently",
    )
    dl.add_argument(
        "--depth", type=int, default=None, metavar="N",
        help="minimum path depth a folder must have to be deletable (advanced; "
             f"default {cleaner.DEFAULT_MIN_DEPTH}; below it needs -i and Administrator)",
    )

    sub.add_parser("log", help="show the deletion log")

    rs = sub.add_parser("restore", help="restore a trashed folder by id")
    rs.add_argument("id", metavar="ID", help="trash id (from `dorphan log`)")

    sub.add_parser("prune", help="empty the recoverable trash for good")

    cf = sub.add_parser("config", help="manage the config file")
    cf_sub = cf.add_subparsers(dest="config_cmd", metavar="<action>")
    ci = cf_sub.add_parser("init", help="write a starter config")
    ci.add_argument(
        "path", nargs="?", metavar="PATH",
        help="where to write it (default: standard config dir)",
    )
    cf_sub.add_parser("path", help="show where config and data live")

    return p


def _resolve_delete_depth(args: argparse.Namespace) -> tuple[int | None, int]:
    """Validate delete's depth/elevation gates.

    Returns (exit_code, min_depth). If exit_code is not None, main should return
    it immediately; otherwise min_depth is the resolved deletion floor.

    A `--depth` below the default reaches shallow ProgramData/Program Files
    folders, so it is gated twice: it requires `-i` (each one confirmed by hand,
    never a bulk force-delete) and Administrator rights (those files need it).
    """
    # Depth 3 is the lowest allowed value; anything shallower is never deletable.
    if args.depth is not None and args.depth < cleaner.ABSOLUTE_MIN_DEPTH:
        print(f"error: the minimum --depth is {cleaner.ABSOLUTE_MIN_DEPTH}; "
              "folders shallower than that are never deletable.", file=sys.stderr)
        return 2, 0

    min_depth = args.depth if args.depth is not None else cleaner.DEFAULT_MIN_DEPTH

    if min_depth < cleaner.DEFAULT_MIN_DEPTH:
        # Shallow folders may only be removed one at a time with a y/n
        # confirmation, never in a bulk force-delete.
        if not args.interactive:
            print(f"error: --depth {args.depth} reaches shallow folders; add -i "
                  "to confirm and remove them one by one.", file=sys.stderr)
            return 2, 0
        # Reaching shallow folders means deleting files only Administrators can
        # touch. Require elevation up front instead of having every delete fail
        # with permission errors midway through.
        if not util.is_elevated():
            print(f"error: removing shallow folders (--depth below "
                  f"{cleaner.DEFAULT_MIN_DEPTH}) deletes files under Program Files / "
                  "ProgramData that need Administrator rights. Re-run dorphan from "
                  "an elevated terminal (right-click > Run as administrator).",
                  file=sys.stderr)
            return 2, 0
        print(f"warning: --depth {min_depth} lets dorphan reach shallow system "
              "folders; each is still confirmed individually before deletion.",
              file=sys.stderr)

    return None, min_depth


def _collect_orphans(args: argparse.Namespace, cfg, command: str):
    """Run the inventory -> scan -> classify -> measure -> filter pipeline.

    Returns (orphans, all_claimed, all_system, classified). `orphans` already
    honors --min-size/--confidence/--exclude; the *_all lists are true totals.
    """
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
    # system folders (often the bulk of the bytes) are skipped unless scan --all
    # / --json needs their sizes, so the common run only walks the few orphans.
    is_json = command == "scan" and getattr(args, "json", False)
    show_all = command == "scan" and getattr(args, "all", False)
    if is_json:
        to_measure = classified if show_all else all_orphans
    else:
        to_measure = all_orphans + (all_claimed if show_all else [])

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

    return orphans, all_claimed, all_system, classified


def _paged(render) -> None:
    """Capture what render() prints to stdout and show it through the pager.

    The report tables can run hundreds of lines (especially `scan -a`), so we
    collect them and hand them to util.page, which scrolls them in a pager when
    the terminal is interactive and too short, and prints plainly otherwise.
    Progress lines go to stderr, so they're unaffected by the capture.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        render()
    util.page(buf.getvalue().rstrip("\n"))


def _run_scan(args, orphans, all_claimed, all_system, classified) -> int:
    """Read-only report for `dorphan scan`."""
    if args.json:
        if args.all:
            items = classified
            if args.min_size:
                items = [c for c in items if c.folder.size >= args.min_size]
        else:
            items = orphans
        report.print_json(items)
        return 0

    def render() -> None:
        report.print_table(orphans, "Orphaned leftovers (no installed app claims these)",
                            show_match=True)
        if args.all:
            claimed = all_claimed
            if args.min_size:
                claimed = [c for c in claimed if c.folder.size >= args.min_size]
            report.print_table(claimed, "Installed-app folders", show_match=True,
                               group=True)
        # Summary counts reflect true totals; the orphan figure honors your filters.
        report.print_summary(orphans, all_claimed, all_system)
        if orphans:
            print()
            print("To remove these: `dorphan delete` (asks first), "
                  "or `dorphan delete -i` to review each.")

    _paged(render)
    return 0


def _run_delete(args, orphans, all_claimed, all_system, min_depth: int) -> int:
    """Delete for `dorphan delete` (bulk, or per-folder with -i)."""
    recovering = args.trash is not None

    if args.interactive:
        # One-by-one review repeats what the prompts show, so skip the full table
        # and let the summary headline the totals before the y/n loop.
        report.print_summary(orphans, all_claimed, all_system)
        if not orphans:
            print("\nNothing to clean.")
            return 0
        count, freed = cleaner.clean_interactive(
            orphans, min_depth=min_depth,
            on_whitelist=config_mod.add_to_whitelist,
            recover=args.trash, log=True)
        print()
        verb = "Recovered" if recovering else "Freed"
        print(f"{verb} {human_size(freed)} across {count} folders.")
        if recovering and count:
            print("Restore any of them with: dorphan restore <id>  "
                  "(see dorphan log)")
        return 0

    # Bulk delete: show what's about to go, then require an explicit confirmation.
    # The listing is paged (it can be long); the confirm prompt follows after.
    def render() -> None:
        report.print_table(orphans, "Orphaned leftovers (no installed app claims these)",
                            show_match=True)
        report.print_summary(orphans, all_claimed, all_system)
    _paged(render)
    print()
    deletable, _refused = cleaner.partition_orphans(orphans, min_depth)
    if deletable and not _confirm_bulk_delete(len(deletable), recovering):
        print("Aborted. Nothing deleted.")
        return 0
    if deletable:
        print("Moving orphaned folders to recovery (largest first)..."
              if recovering else
              "Deleting orphaned folders (largest first)...")
    count, freed = cleaner.clean(
        orphans, force=True, min_depth=min_depth, recover=args.trash, log=True)
    print()
    if count:
        verb = "Recovered" if recovering else "Freed"
        print(f"{verb} {human_size(freed)} across {count} folders.")
        if recovering:
            print("Restore any of them with: dorphan restore <id>  "
                  "(see dorphan log)")
    elif deletable:  # had targets but every delete failed (locked files, ...)
        print("No folders were removed (all delete attempts failed).")
    else:
        print("Nothing here is bulk-deletable. Use `dorphan delete -i` to review "
              "folders one by one.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    args = build_parser().parse_args(argv)

    if getattr(args, "donate", False):
        print_donation()
        return 0

    command = getattr(args, "command", None)
    if command is None:
        print_basic_usage()
        return 0

    # Recovery/config commands don't scan; handle and return early.
    if command == "log":
        print_deletion_log()
        return 0
    if command == "restore":
        return run_restore(args.id)
    if command == "prune":
        return run_prune()
    if command == "config":
        return run_config(args)

    # scan / delete from here on.
    min_depth = cleaner.DEFAULT_MIN_DEPTH
    if command == "delete":
        rc, min_depth = _resolve_delete_depth(args)
        if rc is not None:
            return rc

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

    orphans, all_claimed, all_system, classified = _collect_orphans(args, cfg, command)

    if command == "scan":
        return _run_scan(args, orphans, all_claimed, all_system, classified)
    return _run_delete(args, orphans, all_claimed, all_system, min_depth)


if __name__ == "__main__":
    raise SystemExit(main())
