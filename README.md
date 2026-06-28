# Dorphan

Delete orphan app files of already uninstalled apps that Windows can't find.

> [!WARNING]
> Dorphan was vibe coded by me using Claude Opus.
> `dorphan scan` only reports; it never deletes. Deleting is a separate command, `dorphan delete`.
> Always review the report with `dorphan scan` before deleting anything.

Dorphan finds and deletes orphan Windows application folders from apps that appear to be uninstalled.

Windows' Apps & features list mostly comes from registry uninstall entries, but applications often leave data in places like:

- `AppData\Roaming`
- `AppData\Local`
- `AppData\LocalLow`
- `ProgramData`
- `Program Files`

When an app is removed, these folders can stay behind. Dorphan scans common app locations, compares folders against installed applications, and reports folders that no installed app appears to claim.

## Requirements

- Python 3.8+

Dorphan is Windows-only because it reads Windows registry and app-package data.

## Install

With `uv`:

```powershell
uv tool install .
uv tool install git+https://github.com/azerv1/dorphan
```

With `pip`:

```powershell
pip install .
pip install git+https://github.com/azerv1/dorphan
```

## Quick start

Dorphan uses subcommands. The two you'll use most:

Scan and report likely orphaned folders (read-only):

```powershell
dorphan scan
```

Show only large leftovers:

```powershell
dorphan scan -m 100MB
```

Delete after reviewing the report (asks once before removing anything):

```powershell
dorphan delete
```

Delete interactively, confirming each folder one by one:

```powershell
dorphan delete -i
```

At each prompt: `y` delete, `n` keep, `l` list contents (descends through single nested subfolders), `w` whitelist so it's never scanned again, `q` quit. There is no bulk "delete all" shortcut — every folder is confirmed individually.

## Commands

```text
dorphan scan        list orphaned folders (read-only)
dorphan delete      delete them (asks first; add -i to confirm each)
dorphan restore ID  restore a folder from the trash
dorphan log         show the deletion log
dorphan prune       empty the recoverable trash
dorphan config init write a starter config
```

Filters and `--json` are options on `scan`/`delete`, not commands of their own:

```text
dorphan scan -m 100MB             only show folders >= 100 MB
dorphan scan --no-program-files   scan data folders only; faster
dorphan scan -a                   also show folders matched to installed apps
dorphan scan --exclude npm* yarn  hide matching folder names/globs
dorphan scan --confidence medium  include medium-confidence guesses
dorphan scan --json               output JSON
```

Run `dorphan <command> -h` to see a command's own options, or `dorphan --help` for the full help (commands, examples, and safety notes).

## Safety

Dorphan is designed to make accidental deletion harder, but it is still a deletion tool. Review the output before removing anything.

Safety rules:

- `dorphan scan` is read-only and deletes nothing.
- Bulk deletion (`dorphan delete`) asks for confirmation before removing anything.
- Interactive deletion (`dorphan delete -i`) asks before each folder.
- Reaching shallow folders requires a lowered `--depth`, which only works with `delete -i` (each confirmed one by one) and an elevated Administrator terminal.
- Protected roots such as `C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\Users`, profile roots, drive roots, and anything shallower than depth 3 are refused.
- Known Windows, system, framework, package-manager, and dev-tool folders are excluded from orphan results by default.

### Shallow folders and `--depth`

By default, Dorphan avoids shallow paths because they are riskier. For example:

```text
C:\Program Files\SomeApp
C:\ProgramData\SomeVendor
```

To remove shallow folders, lower the depth floor (3 is the minimum):

```powershell
dorphan delete -i --depth 3
```

This mode:

- runs interactively only;
- asks `y/n` for each folder;
- requires Administrator privileges;
- still refuses protected system roots;
- never allows bulk deletion of shallow folders.

## Recovery

Deletes are permanent by default, but every deletion is recorded to a compact log under `%LOCALAPPDATA%\dorphan`, so nothing vanishes silently:

```powershell
dorphan log
```

To make deletions restorable, add `--trash` to a delete. Instead of removing folders, Dorphan moves them to a recoverable bin (a kind of trash) that you can restore from later:

```powershell
dorphan delete --trash         # delete to the recoverable bin
dorphan delete -i --trash      # same, one folder at a time
dorphan restore <id>           # put a trashed folder back (id comes from `dorphan log`)
dorphan prune                  # empty the bin for good
```

The bin is size-capped; when it fills up the oldest entries are evicted automatically, so recovery never grows the disk without limit. You can point the bin at a custom location with `dorphan delete --trash D:\path`.

## Filtering

Exclude noisy or known-safe folders:

```powershell
dorphan scan --exclude npm* yarn Cursor
```

`--exclude` matches a folder when the pattern matches its name or full path. Each pattern is treated as a case-insensitive glob (`npm*`) and as a plain substring (`quote` matches `MetaQuotes`).

Change confidence level:

```powershell
dorphan scan --confidence medium
```

Confidence levels:

- `high`: strict mode; default and recommended.
- `medium`: also shows short or ambiguous guesses.

## Configuration

Generate a starter config:

```powershell
dorphan config init
```

See where the config, whitelist, and trash live:

```powershell
dorphan config path
```

Use a specific config file for a run (option on `scan`/`delete`):

```powershell
dorphan scan --config my.toml
```

A config only needs to include the keys you want to override:

```toml
[match]
ignore_folders = ["MetaQuotes", "SomeVendorCache"]
```

## How matching works

Dorphan builds an installed-app inventory from:

- machine-wide 64-bit uninstall keys;
- machine-wide 32-bit uninstall keys;
- per-user uninstall keys;
- App Paths;
- Store/MSIX packages;
- pip-installed Python packages (including editable installs), so their folders aren't flagged as orphans.

A scanned folder is considered claimed when its name appears to match an installed app's display name, publisher, or install location. Matching uses exact matches, substrings, and token overlap.

Known OS, shell, framework, package-manager, and development-tool folders are classified as system or ignored so they are not shown as orphaned.

Examples of ignored/system-style folders include:

- `SoftwareDistribution`
- `Start Menu`
- `Templates`
- `Reference Assemblies`
- `npm`
- `pip`
- `uv`
- `cargo`

## License

[GPLv3](LICENSE) — GNU General Public License v3 or later.

## Problems and support

Feel free to open an issue.

### Support

BTC   bc1q7dr9selflp32k3c6tsen99mdvtw6255s2uytcj

AVAX  0x6019BBC14E0b06595601dB7D17D8E82813D87D9D

XMR 8C2gKgWtdyifiU8WFTSCK3CubsBitUxCNYU2Xn15ZUa11YPkiPctHsRHtoJzvYJTX7UHuYuwpD6d9Dsk5M6UePyh2TguoXo
