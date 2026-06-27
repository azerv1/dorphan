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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dorphan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Find installed apps and orphaned leftover folders on Windows, "
        "sorted largest-first.\n\n"
        "Windows' app list is basically the registry uninstall keys, but apps\n"
        "scatter data across AppData, ProgramData and Program Files. When an app\n"
        "is uninstalled (or just vanishes, like Cursor), those folders are left\n"
        "behind. Dorphan finds them by matching every data folder against the\n"
        "full set of installed apps and flagging the ones nothing claims.",
        epilog=textwrap.dedent(
            """\
            examples:
              dorphan                      scan and report orphaned leftovers
              dorphan -m 100MB             only show folders >= 100 MB
              dorphan -a                   also list folders matched to an app
              dorphan --no-program-files   data folders only (much faster)
              dorphan --exclude npm* yarn  hide folders matching names/globs
              dorphan --confidence high    show only high-confidence leftovers
              dorphan --json               machine-readable output

              dorphan -c                   DRY-RUN: preview what would be deleted
              dorphan -c -d                delete all orphans at once (largest first)
              dorphan -i                   go through orphans one by one, y/n each

              dorphan -c --depth 3         also reach shallow folders (Program Files\\App)
              dorphan -i --unsafe          review even shallow folders, confirming each

              dorphan --init-config        write an editable config you can customize
              dorphan --config my.toml     use a specific config file

            note: a plain run only reports. Deletion needs -c -d (all at once)
                  or -i / --interactive (confirm each folder).
                  Shallow folders (e.g. C:\\Program Files\\App) are refused by
                  default; lower --depth or pass --unsafe to include them.
                  Protected system folders are never deleted, even with --unsafe.
            """
        ),
    )
    p.add_argument("--version", action="version", version=f"Dorphan {__version__}")
    p.add_argument(
        "-m", "--min-size", type=_parse_size, default=0, metavar="SIZE",
        help="only show folders at least this big (e.g. 100MB, 1G)",
    )
    p.add_argument(
        "--no-program-files", action="store_true",
        help="skip Program Files (faster; data folders only)",
    )
    p.add_argument(
        "-a", "--all", action="store_true",
        help="also list folders matched to installed apps",
    )
    p.add_argument(
        "--exclude", action="extend", nargs="+", default=[], metavar="PATTERN",
        help="keep folders matching these names/globs out of the orphan list "
             "(takes many, and repeatable: --exclude npm* yarn Cursor)",
    )
    p.add_argument(
        "--confidence", choices=["high", "medium"], default="medium", metavar="LEVEL",
        help="minimum orphan confidence to show: 'high' (strict) or "
             "'medium' (everything). default: medium",
    )
    p.add_argument(
        "--json", action="store_true",
        help="emit machine-readable JSON",
    )
    p.add_argument(
        "-c", "--clean", action="store_true",
        help="preview deletion of orphaned folders (dry-run, deletes nothing)",
    )
    p.add_argument(
        "-d", "--delete", action="store_true",
        help="use with --clean: actually delete the orphaned folders",
    )
    p.add_argument(
        "-i", "--interactive", action="store_true",
        help="go through one by one by size desc with a y/n prompt each",
    )
    p.add_argument(
        "--depth", type=int, default=cleaner.DEFAULT_MIN_DEPTH, metavar="N",
        help="minimum path depth required to delete a folder (default "
             f"{cleaner.DEFAULT_MIN_DEPTH}); lower it to reach shallow folders "
             "like C:\\Program Files\\App",
    )
    p.add_argument(
        "--unsafe", action="store_true",
        help="bypass the depth guard entirely (protected system folders such as "
             "C:\\Windows and C:\\Program Files are still refused)",
    )
    p.add_argument(
        "--config", metavar="PATH",
        help="use this TOML config file",
    )
    p.add_argument(
        "--init-config", nargs="?", const="", metavar="PATH",
        help="write a commented starter config (default: %%APPDATA%%\\dorphan) and exit",
    )
    p.add_argument(
        "--donate", action="store_true",
        help="donate crypto",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.donate:
        print_donation()
        return 0

    if args.init_config is not None:
        target = config_mod.write_default_config(args.init_config or None)
        print(f"Wrote starter config to {target}")
        print("Edit it, then run dorphan (it's picked up automatically).")
        return 0

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
        count, freed = cleaner.clean_interactive(
            orphans, min_depth=args.depth, unsafe=args.unsafe)
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
            orphans, force=args.delete, min_depth=args.depth, unsafe=args.unsafe)
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
