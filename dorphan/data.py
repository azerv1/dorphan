"""Default scan roots and name-matching word lists.

This module is pure data — no logic, no imports — so the word lists stay easy
to read and edit by hand. ``config.py`` imports these, layers any TOML overrides
on top, and is the only place that turns them into a ``Config``.

Editing guide:
  - system_folders / ignore_folders are matched by EXACT normalized name.
  - vendor_folders are matched by exact name, name PREFIX, or token, so keep them
    specific: a short/generic prefix like "Logi" would also protect "Logic".
  - stopwords are stripped before token matching; add a word here when it is
    generic enough to wrongly bridge unrelated folders to an installed app
    (e.g. "audio" bridging "Camel Audio" -> "...Audio Driver").
"""

from __future__ import annotations

# Each root: (label, path-template, is_program_files).
# {env:NAME} expands an environment variable; ~ expands the home directory.
DEFAULT_ROOTS: list[tuple[str, str, bool]] = [
    ("Roaming", "{env:APPDATA}", False),
    ("Local", "{env:LOCALAPPDATA}", False),
    ("LocalLow", "~/AppData/LocalLow", False),
    ("Local\\Programs", "{env:LOCALAPPDATA}/Programs", False),
    ("ProgramData", "{env:PROGRAMDATA}", False),
    ("Program Files", "{env:ProgramFiles}", True),
    ("Program Files (x86)", "{env:ProgramFiles(x86)}", True),
]

DEFAULT_MIN_TOKEN = 4

# Windows / shared-framework folders that must never be reported as leftovers.
# Matched by exact normalized name.
DEFAULT_SYSTEM_FOLDERS: list[str] = [
    "Microsoft", "Microsoft.NET", "Windows", "WindowsApps", "Common Files",
    "Packages", "Temp", "Tmp", "ConnectedDevicesPlatform", "CrashDumps",
    "D3DSCache", "ElevatedDiagnostics", "INetCache", "INetCookies", "IconCache",
    "GroupPolicy", "History", "Microsoft Help", "ModifiableWindowsApps",
    "PackageStaging", "PeerDistRepub", "Publishers", "ssh", "VirtualStore",
    "WER", "Caches", "CLR", "Diagnostics", "PlaceholderTileLogoFolder",
    "Comms", "Application Data", "Internet Explorer", "Defender", "EdgeUpdate",
    "OneDrive", "Windows Defender", "Windows Mail", "Windows Media Player",
    "Windows NT", "Windows Photo Viewer", "WindowsPowerShell", "PowerShell",
    "USOShared", "USOPrivate", "regid.1991-06.com.microsoft", "SystemData",
    "MSBuild", "dotnet", "GameBarPresenceWriter", "WinSxS", "DiagTrack",
    # Windows update/servicing, shell, and SDK/debug folders that scatter into
    # ProgramData and Program Files and must never be flagged as leftovers.
    "SoftwareDistribution", "Start Menu", "Templates", "Desktop", "Documents",
    "Favorites", "Links", "RUXIM", "PCHealthCheck", "Application Verifier",
    "Reference Assemblies", "MSECache", "SystemApps", "PerfLogs", "Boot",
    "Recovery", "System Volume Information", "$Recycle.Bin", "Installer",
    "Downloaded Installations", "Device Stage", "Whesvc",
    # Loose top-level SDK/security folders that have no uninstall entry and so
    # would otherwise look orphaned. Pre-installed Microsoft *bloatware* (Edge,
    # Cortana, ...) is intentionally NOT protected here: it's removable, so leave
    # it flaggable rather than hiding it.
    "Windows Kits", "Microsoft SDKs", "Windows Security",
    "Windows Defender Advanced Threat Protection",
]

# Folder names that are never flagged because they belong to package managers
# and language/dev toolchains (their caches and global stores look orphaned but
# are very much in use). Matched by exact normalized name.
DEFAULT_IGNORE_FOLDERS: list[str] = [
    # JavaScript / Node
    "npm", "npm-cache", "yarn", "pnpm", "node-gyp", "nvm", "corepack",
    "volta", "fnm", "bower", "electron", "Cypress",
    # Python
    "pip", "pipx", "uv", "pipenv", "poetry", "pdm", "hatch", "virtualenv",
    # Python / data science (conda ecosystem + newer managers)
    "conda", "miniconda3", "mamba", "micromamba", "pixi", "rye",
    # Rust
    "cargo", "rustup",
    # Go / Deno / Bun
    "go", "deno", "bun",
    # Ruby
    "gem", "bundle", "rbenv", "rvm",
    # JVM (Java / Scala / Kotlin)
    "maven", "gradle", "sbt", "coursier", "ivy2",
    # PHP
    "composer",
    # Dart / Flutter
    "pub-cache",
    # Haskell
    "cabal", "stack", "ghcup",
    # .NET / NuGet
    "NuGet", "Package Cache", "paket",
    # C / C++
    "vcpkg", "conan",
    # Windows package managers / shims
    "chocolatey", "ChocolateyHttpCache", "shimgen", "scoop", "Webdrivers",
    # Audio plugin host folders shared by many DAWs/apps; never a single app's
    # leftover. Both "VstPlugins" and "Vstplugins" normalize to the same entry.
    "VstPlugins", "Vst3",
]

# Hardware makers, PC OEMs, and driver/peripheral vendors. Their folders (printer
# utilities, driver leftovers, control panels) frequently have no matching
# registry entry yet must never be flagged: they're either still needed or risky
# to remove. Matched by exact name, name prefix, or token, so "HP" also protects
# "HPPrintScanDoctor" and "HPCommRecovery". Keep entries specific: a short prefix
# (e.g. "Logi") would also swallow unrelated names ("Logic", "Logisim").
DEFAULT_VENDOR_FOLDERS: list[str] = [
    "HP", "Hewlett-Packard",
    "Dell", "Alienware",
    "Lenovo", "Acer", "ASUS", "ASUSTeK", "MSI", "Gigabyte", "Toshiba",
    "Samsung", "Razer", "Corsair", "SteelSeries", "Elgato", "Logitech", "LogiShrd",
    "Intel", "NVIDIA", "AMD",
    "Realtek", "Synaptics", "Conexant", "Qualcomm", "Broadcom", "Atheros",
    # Printers / scanners
    "Canon", "Epson", "Brother", "Xerox", "Kyocera", "Ricoh", "Lexmark", "Zebra",
    # Tablets / peripherals
    "Wacom", "Huion", "XP-Pen", "3Dconnexion", "AVerMedia",
    # Storage / networking
    "Kingston", "SanDisk", "Seagate", "Western Digital",
    "TP-Link", "D-Link", "Netgear", "Ubiquiti",
    # Audio interfaces
    "Focusrite", "PreSonus", "MOTU",
]

# Generic words stripped from app/folder names before token matching. Anything
# here can never link a folder to an app, so add only words too generic to
# identify a product (legal suffixes, platform tags, role words like "driver").
DEFAULT_STOPWORDS: list[str] = [
    "app", "apps", "data", "the", "inc", "llc", "ltd", "corp", "corporation",
    "company", "co", "software", "technologies", "technology", "labs", "studio",
    "studios", "team", "limited", "gmbh", "x64", "x86", "win", "windows",
    # Generic enough to bridge unrelated folders to driver/utility apps, e.g.
    # "Camel Audio"/"Universal Audio" -> "Realtek High Definition Audio Driver".
    "audio",
    # Role/descriptor words shared by countless installers, drivers, and helpers
    # (e.g. "NVIDIA ... Driver", "Adobe Update Service", "Epic Games Launcher").
    "driver", "drivers", "runtime", "runtimes", "redistributable",
    "update", "updater", "helper", "service", "services", "launcher",
    "client", "setup", "installer", "manager", "utility", "utilities",
    "tool", "tools", "desktop",
]
