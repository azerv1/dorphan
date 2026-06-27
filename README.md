# Dorphan

> [!WARNING]
> Dorphan was vibe coded by me using Claude Opus and has not been exhaustively tested.
> The default command only scans and reports; it does not delete files.
> Always review the report and run a dry-run before deleting anything.

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

Scan and report likely orphaned folders:

```powershell
dorphan -c
```

Show only large leftovers:

```powershell
dorphan -m 100MB
```

Delete after reviewing the dry-run:

```powershell
dorphan -c -d
```

Delete interactively, confirming each folder one by one:

```powershell
dorphan -i
```

At each prompt: `y` delete, `n` keep, `l` list contents (descends through single nested subfolders), `w` whitelist so it's never scanned again, `a` all remaining, `q` quit.

## Common options

```text
dorphan                      scan and report orphaned leftovers
dorphan -m 100MB             only show folders >= 100 MB
dorphan --no-program-files   scan data folders only; faster
dorphan -a                   also show folders matched to installed apps
dorphan --exclude npm* yarn  hide matching folder names/globs
dorphan --confidence medium  include medium-confidence guesses
dorphan --json               output JSON
```

Run this for the full CLI help:

```powershell
dorphan --help
```

Run this for advanced/safety details:

```powershell
dorphan --helpme
```

Safety

Dorphan is designed to make accidental deletion harder, but it is still a deletion tool. Review the output before removing anything.

Safety rules:

- `dorphan, dorphan -c` is a dry-run and deletes nothing.
- Bulk deletion requires both flags: `dorphan -c -d`.
- Interactive deletion with `dorphan -i` asks before each folder.
- `--unsafe` only works with `-i`; shallow folders must be confirmed one by one and requires an elevated Administrator terminal.
- Protected roots such as `C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\Users`, profile roots, drive roots, and anything shallower than depth 3 are refused.
- Known Windows, system, framework, package-manager, and dev-tool folders are excluded from orphan results by default.

### Shallow folders and `--unsafe`

By default, Dorphan avoids shallow paths because they are riskier. For example:

```text
C:\Program Files\SomeApp
C:\ProgramData\SomeVendor
```

To remove shallow folders, use:

```powershell
dorphan -i --unsafe [--depth 3]
```

This mode:

- runs interactively only;
- asks `y/n` for each folder;
- requires Administrator privileges;
- still refuses protected system roots;
- never allows bulk deletion of shallow folders.

## Filtering

Exclude noisy or known-safe folders:

```powershell
dorphan --exclude npm* yarn Cursor
```

`--exclude` matches:

Change confidence level:

```powershell
dorphan --confidence medium
```

Confidence levels:

- `high`: strict mode; default and recommended.
- `medium`: also shows short or ambiguous guesses.

## Configuration

Generate a starter config:

```powershell
dorphan --init-config
```

Use a specific config file:

```powershell
dorphan --config my.toml
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
- Store/MSIX packages.

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

The matcher is heuristic. It errs toward not deleting automatically, but false positives are still possible.

## JSON output

You can combine JSON with filters:

```powershell
dorphan --json -m 100MB --confidence medium
```

## License

[GPLv3](LICENSE) — GNU General Public License v3 or later.

## Problems and support

Feel free to open an issue.

### Support

BTC   bc1q7dr9selflp32k3c6tsen99mdvtw6255s2uytcj

AVAX  0x6019BBC14E0b06595601dB7D17D8E82813D87D9D

XMR 8C2gKgWtdyifiU8WFTSCK3CubsBitUxCNYU2Xn15ZUa11YPkiPctHsRHtoJzvYJTX7UHuYuwpD6d9Dsk5M6UePyh2TguoXo
