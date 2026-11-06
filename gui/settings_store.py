"""What the app remembers between sessions: the last calibration and captures, where the file dialogs were last opened,
the chosen options and the window size and position.

Stored as a small JSON file in the user's app data folder. Reading and writing can never stop the app: a missing,
damaged, wrongly typed or unwritable file simply means "remember nothing". Saving is atomic, so a crash while saving
cannot leave a half-written file. Paths are only offered again if they still exist.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "FaultAwareCalibration"
FILE = "settings.json"
VERSION = 1
# key -> type it must have to be trusted
KEYS = {"calibration": str, "captures": str, "cal_dir": str, "data_dir": str, "mode": str, "strategy": str,
        "auto_review": bool, "geometry": str}
log = logging.getLogger("faultaware")


class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else APP_DIR / FILE
        self.data = self._read()

    def _read(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {}
        if not isinstance(raw, dict) or raw.get("version") != VERSION:
            return {}
        return {k: v for k, v in raw.items() if k in KEYS and isinstance(v, KEYS[k]) and (k != "auto_review" or isinstance(v, bool))}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def existing(self, key, kind="file"):
        """A remembered path, only if it still exists as a file or a folder."""
        value = self.data.get(key)
        if not value:
            return None
        try:
            p = Path(value)
            return str(p) if (p.is_file() if kind == "file" else p.is_dir()) else None
        except OSError:
            return None

    def update(self, **values):
        """Remember values (unknown keys and wrongly typed values are ignored). Returns whether anything changed."""
        changed = False
        for key, value in values.items():
            if key in KEYS and isinstance(value, KEYS[key]) and self.data.get(key) != value:
                self.data[key] = value
                changed = True
        if changed:
            self._write()
        return changed

    def clear(self):
        self.data = {}
        self._write()

    def _write(self):
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(dict(self.data, version=VERSION), indent=2), encoding="utf-8")
            os.replace(tmp, self.path)              # atomic: the file is either the old one or the new one
        except OSError as error:
            log.warning("Could not save settings: %s", error)
            try:
                tmp.unlink()
            except OSError:
                pass
