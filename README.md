# Dorphan

> WARNING: Vibe coded. This tool was built with Clauden make sure you know what you are doing. It works, but it has
> not been exhaustively tested — The default command does not delete any files. Always review the report and use the dry-run
> before deleting anything.

Delete orphan app files of already uninstalled apps that Windows can't find.

Windows' "Apps & features" list is basically the registry Uninstall keys. But
apps scatter data across `AppData\Roaming`, `AppData\Local`, `LocalLow`,
`ProgramData`, and `Program Files`. When you uninstall something those folders
are left behind. The uninstaller can't reclaim what the app list can't even see.

This script scans every place apps leave data (machine 64-bit + 32-bit uninstall
keys, per-user keys, App Paths, and Store/MSIX packages) and reports the orphans:
folders matched to no installed app.

## Install

Python 3.8+. Windows only (it reads the Windows registry).

With uv:

```
uv tool install .           # global dorphan command
uv tool install git+https://github.com/azerv1/dorphan
```

With pip:

```
pip install .       # from a checkout of this repo
pip install git+https://github.com/azerv1/dorphan
```

## Usage

run `dorphan --help` for usage guide.

```
dorphan                      # scan + report orphaned leftovers ordered by size desc
dorphan -a --all             # also list folders that DO map to an installed app
dorphan -m --min-size 100MB  # only show folders >= 100 MB
dorphan --no-program-files   # data folders only (faster)
dorphan --json               # machine-readable output

dorphan --exclude npm* yarn  # hide folders matching names/globs (many, repeatable)
dorphan --confidence high    # show only high-confidence leftovers

dorphan -c --clean           # DRY RUN: show exactly what would be deleted
dorphan -c -d --delete       # actually delete the orphans (largest first)
dorphan -i                   # interactive: confirm each folder one by one

dorphan -c --depth 3         # also reach shallow folders (e.g. C:\Program Files\App)
dorphan -i --unsafe          # review even shallow folders, confirming each by name
```

### Filtering

- `--exclude PATTERN ...` keeps matching folders out of the report. Each pattern
  matches as a glob against the folder name, or as a plain substring of the
  name/path. Takes many at once and is repeatable: `--exclude npm* yarn Cursor`.
- `--confidence LEVEL` sets the lowest orphan confidence to show: `high` (strict,
  hides short/ambiguous guesses) or `medium` (everything, the default).

### Safety

- Default run deletes nothing — it only reports.
- `--clean` is a dry-run preview. You must add `--delete` to actually delete, or
  use `-i` to confirm each folder.
- Deletion has two safety floors:
  - **Hard floor (never overridable):** drive roots and protected system trees
    (`C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\Users`, your user
    profile and its `AppData` roots) are refused even with `--unsafe`.
  - **Depth guard (tunable):** folders shallower than `--depth` (default 4) are
    refused, since shallow paths like `C:\Program Files\App` are riskier. Lower
    it (`--depth 3`) to include them, or pass `--unsafe` to drop the depth guard
    entirely — the hard floor still applies. Pair with `-i` to confirm each
    shallow folder by name.
- Deletion processes largest-first and skips locked/unremovable files instead of
  crashing.
- Known Windows/system/framework folders are never flagged as orphans.

## Configuration

Generate a commented starter file, edit it, and it's picked up automatically:

```
dorphan --init-config        # writes %APPDATA%\dorphan\config.toml
dorphan --config my.toml     # or point at a specific file
```

A config only overrides the keys it sets, so it can be tiny:

```
[match]
ignore_folders = ["MetaQuotes", "SomeVendorCache"]   # stop flagging these
```

Loaded with the stdlib `tomllib` (Python 3.11+); a UTF-8 BOM is tolerated.

## How matching works

A scanned folder is claimed when its name maps to an installed app's display
name, publisher, or install location (exact, substring, or token overlap). Known
OS/framework folders are classified system. Everything else is an orphan.

The matcher errs toward not deleting: anything ambiguous stays in the report for
you to judge.

## License

[GPLv3](LICENSE) (GNU General Public License v3 or later).

## Problems & Support

Feel free to open an issue.

Support:

BTC   bc1q7dr9selflp32k3c6tsen99mdvtw6255s2uytcj
XMR   8C2gKgWtdyifiU8WFTSCK3CubsBitUxCNYU2Xn15ZUa11YPkiPctHsRHtoJzvYJTX7UHuYuwpD6d9Dsk5M6UePyh2TguoXo
AVAX  0x6019BBC14E0b06595601dB7D17D8E82813D87D9D
