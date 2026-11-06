"""Best-effort structured progress for the desktop app: one JSON object per line in <output>/progress.jsonl.

The assessment writes a line when a stage starts or a result becomes available (for example the held-out loss of
one explanation in one cross-validation fold), so the app can draw results as they are generated. Writing is
best effort by design: a failure here never changes or stops an assessment, and nothing reads the file back
into the assessment.
"""
import json
import math
import time
from pathlib import Path

FILE = 'progress.jsonl'


def _plain(value):
    """json default: numpy scalars and arrays (both have tolist), anything else as text."""
    tolist = getattr(value, 'tolist', None)
    return tolist() if callable(tolist) else str(value)


def number(value):
    """A float, or None when it is missing or not finite (NaN is not valid JSON)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


class Events:
    def __init__(self, output=None):
        self.path = Path(output) / FILE if output else None
        self.started = time.time()

    def emit(self, stage, **data):
        if self.path is None:
            return
        try:
            row = dict(t=round(time.time() - self.started, 2), stage=stage, **data)
            with open(self.path, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(row, default=_plain) + '\n')
        except Exception:  # noqa: BLE001 - progress must never affect the assessment
            pass
