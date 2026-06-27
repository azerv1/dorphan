"""Classify scanned folders as claimed (an installed app), system, or orphan."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .inventory import Inventory
from .scanner import Folder
from .util import normalize, tokens


@dataclass
class Classified:
    folder: Folder
    status: str  # "claimed" | "orphan" | "system"
    matched_app: str = ""
    confidence: str = ""  # "high" | "medium" for orphans


class Matcher:
    def __init__(self, inv: Inventory, config: Config):
        self._cfg = config
        self._min_token = config.min_token
        self._system = config.system_folders
        self._ignore = config.ignore_folders
        self._stop = config.stopwords

        self._app_norms: dict[str, str] = {}   # normalized name -> display name
        self._app_tokens: dict[str, str] = {}  # token -> display name
        self._publishers: dict[str, str] = {}  # normalized publisher -> publisher
        self._pub_tokens: dict[str, str] = {}  # publisher token -> publisher
        self._locations: list[str] = []

        import os

        for app in inv.apps:
            disp = app.name
            n = normalize(disp)
            if n:
                self._app_norms[n] = disp
            for t in tokens(disp, self._stop):
                self._app_tokens.setdefault(t, disp)
            if app.publisher:
                pn = normalize(app.publisher)
                if pn:
                    self._publishers.setdefault(pn, app.publisher)
                for t in tokens(app.publisher, self._stop):
                    self._pub_tokens.setdefault(t, app.publisher)
            loc = app.install_location.strip().strip('"')
            if loc:
                self._locations.append(os.path.normcase(os.path.normpath(loc)))

    def _match_app(self, folder: Folder) -> str:
        import os

        # 1. Folder sits inside (or is) a known install location.
        fpath = os.path.normcase(os.path.normpath(folder.path))
        for loc in self._locations:
            if fpath == loc or fpath.startswith(loc + os.sep) or loc.startswith(fpath + os.sep):
                return self._loc_label(loc)

        fnorm = normalize(folder.name)
        if not fnorm:
            return ""

        # 2. Exact normalized name match against an app or publisher.
        if fnorm in self._app_norms:
            return self._app_norms[fnorm]
        if fnorm in self._publishers:
            return f"(publisher) {self._publishers[fnorm]}"

        # 3. Substring either direction, but only for reasonably long names to
        #    avoid "go" matching "google", etc.
        if len(fnorm) >= self._min_token:
            for an, disp in self._app_norms.items():
                if len(an) >= self._min_token and (fnorm in an or an in fnorm):
                    return disp
            for pn, pub in self._publishers.items():
                if len(pn) >= self._min_token and (fnorm in pn or pn in fnorm):
                    return f"(publisher) {pub}"

        # 4. Token overlap (handles "Cursor" folder vs "Cursor (User)" app, and
        #    vendor folders like "JetBrains" vs publisher "JetBrains s.r.o.").
        ftoks = tokens(folder.name, self._stop)
        for t in ftoks:
            if len(t) < self._min_token:
                continue
            if t in self._app_tokens:
                return self._app_tokens[t]
            if t in self._pub_tokens:
                return f"(publisher) {self._pub_tokens[t]}"
        return ""

    def _loc_label(self, loc: str) -> str:
        import os

        return f"(install dir) {os.path.basename(loc) or loc}"

    def classify(self, folder: Folder) -> Classified:
        fnorm = normalize(folder.name)
        # A name that normalizes to nothing is a localized/symbol-only shell
        # folder (e.g. the Greek "Επιφάνεια εργασίας" = Desktop). We can't reason
        # about it, so never treat it as an orphan.
        if not fnorm or fnorm in self._system or fnorm in self._ignore:
            return Classified(folder, "system")
        matched = self._match_app(folder)
        if matched:
            return Classified(folder, "claimed", matched_app=matched)
        # Orphan. Single-token, short names are lower confidence.
        conf = "high" if len(fnorm) >= self._min_token else "medium"
        return Classified(folder, "orphan", confidence=conf)


def classify_all(
    inv: Inventory, folders: list[Folder], config: Config
) -> list[Classified]:
    m = Matcher(inv, config)
    return [m.classify(f) for f in folders]
