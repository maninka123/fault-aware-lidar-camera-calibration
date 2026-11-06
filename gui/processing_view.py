"""Processing tab of the fault-aware app: the stages of a check, and its results drawn as they are generated.

Layout (like the maintenance app's Processing tab): a stage tracker, a list of stages on the left, and the page of
the selected stage on the right. The page of the stage that is running is followed automatically until the user
clicks another stage.

What is shown comes from real data only:
  * progress.jsonl, which the assessment writes while it runs (research_calibration/progress_events.py)
  * the lines the child process prints (decoded captures, cross-validation folds)
  * the stacked capture images the loader writes into inputs/
  * for a finished or older check, the saved assessment.json, which can be replayed.

Nothing here can change an assessment. Malformed, partial, duplicated or unknown events are ignored.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from result_visuals import GainChart
import review_adapter as ra
from review_adapter import REVIEW_STEPS

BLUE, GOOD, WARN, BAD = "#007aff", "#248a3d", "#9b6500", "#d70015"
SOFT = dict(blue="#edf5ff", good="#eaf6ed", warn="#fff6e5", bad="#fff0f1", grey="#eeeef2")
INK, MUTED, LINE = "#1d1d1f", "#6e6e73", "#e5e5ea"

HYP = {"KEEP": "Keep current", "R": "Rotation", "T": "Translation", "I": "Camera intrinsics",
       "RT": "Rotation + translation", "RI": "Rotation + intrinsics", "TI": "Translation + intrinsics",
       "RTI": "Everything"}

# key, tracker label, list title, what to look for
STAGES = [
    ("data", "Data", "Load and stack the captures",
     "Each tile is one capture: the camera image with the LiDAR frames stacked over the still part. Images should be sharp "
     "and show the scene. Missing tiles mean a capture could not be read."),
    ("features", "Edges", "Find edges in every capture",
     "Edges are what camera and LiDAR are matched on. Long bars mean a capture has plenty of structure; very short bars "
     "mean a bland scene that adds little evidence."),
    ("folds", "Testing", "Test every explanation on held-out captures",
     "Each explanation of what might have changed is refitted while one capture is held out, then scored on that capture. "
     "Dots are single held-out captures; bars are the running average improvement over keeping the current calibration. "
     "An explanation has to pass the dashed line, and do it consistently."),
    ("decision", "Decision", "Decide whether anything should change",
     "The best explanation must beat the declared improvement threshold, with intervals that survive resampling the captures."),
    ("candidate", "Candidate", "Fit the best explanation on all training captures",
     "The surviving explanation is refitted on every training capture to produce a candidate calibration."),
    ("outer", "Final test", "Check on captures never used before",
     "If enough captures were kept aside, the candidate is tested on them. Without them this check cannot be run and the "
     "result says so."),
    ("verdict", "Verdict", "Verdict", ""),
]
REVIEW_STAGE = ("review", "Review", "Run the maintenance comparison",
                "The original calibration maintenance analysis runs on the same calibration and captures: the four update choices, "
                "edge RMSE, parameter changes, leave-one-out evidence and the image comparison. It is a separate calculation and never "
                "changes the verdict above. Its results are in the Calibration review tab when this finishes.")
SCRATCH_STAGES = [
    ("data", "Data", "Load and stack the captures", STAGES[0][3]),
    ("scratch", "Calibrating", "Estimate a calibration from scratch",
     "A calibration is estimated from the captures alone, then assessed. This takes about ten minutes; the log shows progress."),
    ("verdict", "Result", "Result", ""),
]

# one-line captions for the stage list (the pages keep the long titles)
SHORT = {"data": "Load and stack the captures", "features": "Find edges in each capture", "folds": "Test on held-out captures",
         "decision": "Decide whether to change", "candidate": "Fit the best explanation", "outer": "Check on unused captures",
         "verdict": "Final result", "scratch": "Estimate from scratch", "review": "Maintenance comparison"}
# the maintenance app's own stage names, for the review stage
REVIEW_TITLES = {"data": "Stacking the captures", "features": "Detecting edges", "health": "Checking the current calibration",
                 "options": "Comparing the update choices", "search": "Searching for refinements", "refined": "Refining the calibration",
                 "evidence": "Leave-one-out evidence", "verdict": "Writing the verdict"}


DECODED = re.compile(r"decoded\s+(\S+?):\s+still window\s+([\d.]+)\s*s,\s+(\d+)\s+images,\s+(\d+)\s+LiDAR frames")
FOLD = re.compile(r"comparison fold\s+(\d+)\s*/\s*(\d+)\s*\(([^)]*)\)")
MAX_THUMBS = 48


def short_id(name):
    """'191640_838463' or 'capture_20261105_191640_838463_enclosure_on' -> '19:16:40'."""
    parts = str(name).replace("capture_", "").split("_")
    for part in parts:
        if len(part) == 6 and part.isdigit():
            return f"{part[:2]}:{part[2:4]}:{part[4:]}"
    return str(name)


def _secs(seconds):
    return "< 1 s" if seconds < 1 else f"{seconds:.0f} s"


def num(value):
    """float or None (also for NaN / infinity / junk)."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


# ================================================================== model (no Qt)
class RunModel:
    """Everything the Processing tab knows about one check, built from events. Tolerates any input."""

    def __init__(self, scratch=False, total=None, review=False):
        self.scratch = scratch
        self.stages = SCRATCH_STAGES if scratch else (STAGES + [REVIEW_STAGE] if review else STAGES)
        self.keys = [s[0] for s in self.stages]
        self.state = {k: "pending" for k in self.keys}
        self.started, self.ended, self.message = {}, {}, {}
        self.stamp = {}                    # (stage, 's' or 'e') -> seconds since the assessment started (the event's own 't')
        self.live = False                  # True while following a running check, so wall-clock time may be used
        self._t = None
        self.total_captures = total if isinstance(total, int) and total > 0 else None
        self.decoded = []                  # (id, window_s, images, lidar_frames)
        self.captures = []                 # dicts from the features event
        self.max_features = None
        self.hypotheses = []
        self.folds_total = 0
        self.fold_started = {}             # fold index -> test id
        self.fits = {}                     # (fold, hypothesis) -> loss or None
        self.fit_test = {}                 # fold -> test id
        self.gate = None                   # minimum relative gain, fraction
        self.decision = None
        self.candidate = None
        self.outer = None
        self.verdict = None
        self.failure = None
        self.review = dict(done=0, total=len(REVIEW_STEPS), step=None, title="", sub=None, images=[], summary=None, message="")
        self.cancelled = False
        self.folds_t0 = None
        self.version = 0                   # increments on every change (the view redraws when it moves)

    # ---- helpers
    def _begin(self, key):
        if key in self.state and self.state[key] == "pending":
            self.state[key] = "active"
            self.started[key] = time.monotonic()
            if self._t is not None:
                self.stamp[(key, "s")] = self._t

    def _end(self, key, ok=True):
        if key in self.state and self.state[key] in ("pending", "active"):
            self.started.setdefault(key, time.monotonic())
            self.state[key] = "done" if ok else "failed"
            self.ended[key] = time.monotonic()
            if self._t is not None:
                self.stamp.setdefault((key, "s"), self._t)
                self.stamp[(key, "e")] = self._t

    def duration(self, key):
        """Seconds a stage took, or None when that is not known. Replays of saved results without timestamps give None."""
        s, e = self.stamp.get((key, "s")), self.stamp.get((key, "e"))
        if s is not None and e is not None:
            return max(0.0, e - s)
        if self.live and key in self.started:
            return max(0.0, self.ended.get(key, time.monotonic()) - self.started[key])
        return None

    def _finish_before(self, key):
        """Stages earlier than `key` cannot still be running."""
        for k in self.keys[:self.keys.index(key)]:
            if self.state[k] in ("pending", "active"):
                self._end(k)

    # ---- events
    def apply(self, event):
        """Apply one event dict; returns True when anything changed. Never raises."""
        try:
            return self._apply(event)
        except Exception:  # noqa: BLE001 - a bad event must never break the view
            return False

    def _apply(self, ev):
        if not isinstance(ev, dict) or not isinstance(ev.get("stage"), str):
            return False
        self._t = num(ev.get("t"))
        stage = ev["stage"]
        changed = True
        if stage == "data":
            self._begin("data")
            self.message["data"] = str(ev.get("message") or "Loading the captures")
        elif stage == "features":
            self._begin("data")
            caps = ev.get("captures")
            self.captures = [c for c in caps if isinstance(c, dict)] if isinstance(caps, list) else []
            self.max_features = num(ev.get("max_features"))
            self._end("data")
            self._end("features")
            if not self.total_captures:
                self.total_captures = len(self.captures) or None
        elif stage == "folds":
            self._finish_before("folds")
            self._begin("folds")
            self.folds_t0 = time.monotonic()
            total = ev.get("total")
            self.folds_total = total if isinstance(total, int) and total >= 0 else 0
            names = ev.get("hypotheses")
            if isinstance(names, list):
                self.hypotheses = [str(n) for n in names]
            gate = num(ev.get("min_relative_gain"))
            self.gate = gate if gate is not None and gate >= 0 else self.gate
            self.message["folds"] = f"{self.folds_total} held-out captures, {max(len(self.hypotheses) - 1, 0)} explanations plus keeping the current calibration"
        elif stage == "fold":
            self._begin("folds")
            index = ev.get("index")
            if isinstance(index, int) and index >= 0:
                self.fold_started[index] = str(ev.get("test") or index)
                total = ev.get("total")
                if isinstance(total, int) and total > self.folds_total:
                    self.folds_total = total
        elif stage == "fit":
            self._begin("folds")
            fold, name = ev.get("fold"), ev.get("hypothesis")
            if not isinstance(fold, int) or fold < 0 or not isinstance(name, str) or not name:
                return False
            if name not in self.hypotheses:
                self.hypotheses.append(name)
            self.fits[(fold, name)] = num(ev.get("loss"))
            self.fit_test[fold] = str(ev.get("test") or fold)
            self.folds_total = max(self.folds_total, fold + 1)
        elif stage == "decision":
            self._end("folds")
            self._begin("decision")
            self.decision = dict(status=ev.get("status"), candidate=ev.get("candidate"), gain=num(ev.get("best_relative_gain")),
                                 gate=num(ev.get("min_relative_gain")), reason=ev.get("reason"))
            if self.decision["gate"] is not None:
                self.gate = self.decision["gate"]
            self._end("decision")
        elif stage == "candidate":
            self._finish_before("candidate")
            self._begin("candidate")
            self.candidate = str(ev.get("hypothesis") or "")
        elif stage == "outer":
            self._finish_before("outer")
            self._end("candidate")
            self._begin("outer")
            self.outer = dict(count=ev.get("count") if isinstance(ev.get("count"), int) else None, gain=num(ev.get("gain")),
                              passed=bool(ev.get("passed")))
            self._end("outer")
        elif stage == "verdict":
            for k in self.keys[:self.keys.index("verdict")]:
                if self.state[k] in ("pending", "active"):
                    self._end(k)
            self.verdict = dict(status=ev.get("status"), action=ev.get("action"))
            self._begin("verdict")
            self._end("verdict")
        elif stage == "scratch" and self.scratch:
            self._finish_before("scratch")
            self._begin("scratch")
            self.message["scratch"] = str(ev.get("message") or "Estimating a calibration")
        else:
            return False
        if changed:
            self.version += 1
        return changed

    # ---- the maintenance comparison (its progress comes from its own files, not from progress.jsonl)
    def enable_review(self):
        self._t = None
        """Add the review as a last stage (a check that is already finished gets it when the review starts)."""
        if "review" not in self.keys and not self.scratch:
            self.stages = list(self.stages) + [REVIEW_STAGE]
            self.keys.append("review")
            self.state["review"] = "pending"
            self.version += 1

    def review_begin(self):
        self._t = None
        self.enable_review()
        if "review" in self.state and self.state["review"] == "pending":
            self._begin("review")
            self.review.update(done=0, step=None, title="Starting", sub=None, summary=None, message="")
            self.version += 1

    def review_progress(self, done_steps, step, message="", sub=None, images=()):
        if self.state.get("review") != "active":
            return
        r = self.review
        title = REVIEW_TITLES.get(step, step or "Working")
        new = (min(done_steps, r["total"]), step, title, message, sub, list(images))
        if new != (r["done"], r["step"], r["title"], r["message"], r["sub"], r["images"]):
            r.update(done=new[0], step=step, title=title, message=message, sub=sub, images=list(images))
            self.version += 1

    def review_done(self, summary=None):
        self._t = None
        if "review" in self.state and self.state["review"] in ("pending", "active"):
            self._begin("review")
            self._end("review")
            self.review.update(done=self.review["total"], summary=summary)
            self.version += 1

    def review_failed(self, message):
        self._t = None
        if "review" in self.state:
            self.state["review"] = "failed"
            self.review["message"] = str(message or "The maintenance comparison did not finish.")
            self.version += 1

    def apply_log_line(self, line):
        """Understand the lines the child process prints. Returns True when something was recognised."""
        self._t = None
        text = str(line or "")
        m = DECODED.search(text)
        if m:
            self._begin("data")
            self.decoded.append((m.group(1), num(m.group(2)), int(m.group(3)), int(m.group(4))))
            self.version += 1
            return True
        m = FOLD.search(text)
        if m:
            self._begin("folds")
            self.version += 1
            return True
        if self.scratch and self.state.get("scratch") == "pending" and ("initializ" in text.lower() or "targetless" in text.lower()):
            self._finish_before("scratch")
            self._begin("scratch")
            self.version += 1
            return True
        return False

    def mark_failed(self, message):
        self._t = None
        """The run stopped with an error: the active stage (or the first pending one) turns red. Only the first failure counts."""
        if self.failure:
            return
        if self.state.get("review") == "active":
            self.state["review"] = "failed"
            self.failure = str(message or "The check stopped.")
            self.version += 1
            return
        key = next((k for k in self.keys if self.state[k] == "active"), None) or next((k for k in self.keys if self.state[k] == "pending"), self.keys[-1])
        self.started.setdefault(key, time.monotonic())
        self.state[key] = "failed"
        self.failure = str(message or "The check stopped.")
        self.version += 1

    def mark_cancelled(self):
        self.cancelled = True
        self.mark_failed("Stopped by you. Your calibration is unchanged.")

    # ---- derived
    @property
    def active(self):
        return next((k for k in self.keys if self.state[k] == "active"), None)

    def folds_done(self):
        """Folds for which every known explanation has a result."""
        done = 0
        for fold in sorted({f for f, _ in self.fits}):
            if all((fold, h) in self.fits for h in self.hypotheses):
                done += 1
        return done

    def eta_seconds(self):
        done, total = self.folds_done(), self.folds_total
        if not self.folds_t0 or done < 1 or total <= done:
            return None
        return (time.monotonic() - self.folds_t0) / done * (total - done)

    def race_rows(self):
        """Rows for the explanation chart from the results so far (stable order, KEEP first)."""
        names = [h for h in self.hypotheses if h == "KEEP"] + [h for h in self.hypotheses if h != "KEEP"]
        rows = []
        folds = sorted({f for f, _ in self.fits})
        for name in names:
            dots, g_num, g_den, wins = [], 0.0, 0.0, 0
            for f in folds:
                loss, keep = self.fits.get((f, name)), self.fits.get((f, "KEEP"))
                gain = None
                if loss is not None and keep not in (None, 0):
                    gain = (keep - loss) / keep * 100
                    g_num += keep - loss
                    g_den += keep
                    wins += gain > 0
                dots.append(dict(label=short_id(self.fit_test.get(f, f)), gain=gain, px=float("nan")))
            gain_mean = g_num / g_den * 100 if g_den else (0.0 if name == "KEEP" else None)
            rows.append(dict(key=name, name=HYP.get(name, name), loss=float("nan"), gain=gain_mean, keep=name == "KEEP", best=False,
                             folds=dots, px=float("nan"), wins=wins))
        chosen = (self.decision or {}).get("candidate")      # marked only once the pipeline's decision exists
        for r in rows:
            r["best"] = bool(chosen) and r["key"] == chosen and not r["keep"]
            if r["gain"] is None:
                r["gain"] = 0.0
        return rows


class EventTail:
    """Reads new lines of a JSON-lines file as it grows. Handles a missing file, a half-written last line,
    a truncated or replaced file, blank and malformed lines."""

    def __init__(self, path):
        self.path = Path(path)
        self.offset = 0
        self.buffer = b""

    def read(self):
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self.offset:                 # replaced or truncated: start over
            self.offset, self.buffer = 0, b""
        if size == self.offset:
            return []
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                chunk = handle.read(size - self.offset)
        except OSError:
            return []
        self.offset += len(chunk)
        data = self.buffer + chunk
        *lines, self.buffer = data.split(b"\n")
        events = []
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                events.append(json.loads(raw.decode("utf-8")))
            except (ValueError, UnicodeDecodeError):
                continue
        return events


def events_from_result(result, folder=None):
    """Rebuild the events of a finished check from its saved assessment (used to show and replay older checks).
    Missing pieces are simply left out."""
    r = result if isinstance(result, dict) else {}
    diag = r.get("diagnostics") if isinstance(r.get("diagnostics"), dict) else {}
    decision = diag.get("decision") if isinstance(diag.get("decision"), dict) else {}
    folds = (r.get("validation") or {}).get("folds") if isinstance(r.get("validation"), dict) else None
    out = [dict(stage="data", message="Captures")]
    caps = (diag.get("input") or {}).get("captures") if isinstance(diag.get("input"), dict) else None
    if isinstance(caps, list):
        out.append(dict(stage="features", captures=caps, max_features=(diag.get("configuration") or {}).get("max_features_per_capture")))
    if isinstance(folds, dict) and folds:
        names = list(folds)
        first = next((v for v in folds.values() if isinstance(v, list) and v), [])
        gate = (decision.get("thresholds") or {}).get("min_relative_gain") if isinstance(decision.get("thresholds"), dict) else None
        out.append(dict(stage="folds", total=len(first), hypotheses=names, min_relative_gain=gate))
        for index in range(len(first)):
            out.append(dict(stage="fold", index=index, total=len(first), test=first[index].get("test_id") if isinstance(first[index], dict) else index))
            for name in names:
                rows = folds.get(name)
                if isinstance(rows, list) and index < len(rows) and isinstance(rows[index], dict):
                    row = rows[index]
                    out.append(dict(stage="fit", fold=index, test=row.get("test_id"), hypothesis=name,
                                    loss=(row.get("metrics") or {}).get("loss") if isinstance(row.get("metrics"), dict) else None,
                                    success=bool(row.get("fitting_success")), rank=row.get("rank")))
    if decision:
        out.append(dict(stage="decision", status=decision.get("status"), candidate=decision.get("candidate_hypothesis"),
                        best_relative_gain=decision.get("best_relative_gain"),
                        min_relative_gain=(decision.get("thresholds") or {}).get("min_relative_gain") if isinstance(decision.get("thresholds"), dict) else None,
                        reason=decision.get("reason"), mean_losses=decision.get("mean_losses")))
        out.append(dict(stage="candidate", hypothesis=decision.get("candidate_hypothesis")))
    outer = (r.get("validation") or {}).get("outer_test") if isinstance(r.get("validation"), dict) else None
    if isinstance(outer, dict):
        out.append(dict(stage="outer", count=len(outer.get("test_ids") or []), gain=outer.get("relative_gain"), passed=outer.get("passed")))
    out.append(dict(stage="verdict", status=r.get("status"), action=r.get("recommended_action")))
    return out


def saved_events(folder):
    """The events a finished run wrote while it ran (with real timestamps), or None when absent or incomplete."""
    try:
        events = EventTail(Path(folder) / "progress.jsonl").read()
    except OSError:
        return None
    stages = [e.get("stage") for e in events if isinstance(e, dict)]
    return events if "data" in stages and stages and stages[-1] == "verdict" else None


def count_captures(path):
    """How many captures a folder holds (raw capture_* folders, or stacked .npz files); None when unknown."""
    try:
        p = Path(path)
        bags = [d for d in p.glob("capture_*") if (d / "rig_0.bag").exists()]
        if bags:
            return len(bags)
        npz = list(p.glob("*.npz"))
        return len(npz) or None
    except OSError:
        return None


# ================================================================== widgets
class StageBar(QtWidgets.QWidget):
    """Numbered stage chips; the running one pulses."""
    clicked = QtCore.pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.model = RunModel()
        self.phase = 0.0
        self.setMinimumHeight(68)
        self.setCursor(Qt.PointingHandCursor)

    def set_model(self, model):
        self.model = model
        self.update()

    def tick(self, phase):
        self.phase = phase
        if self.model.active:
            self.update()

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        stages = self.model.stages
        n, w, r, y = len(stages), self.width(), 13, 20
        xs = [w * (i + 0.5) / n for i in range(n)]
        states = [self.model.state[s[0]] for s in stages]
        for i in range(1, n):
            done = states[i - 1] == "done" and states[i] in ("done", "active")
            p.setPen(QtGui.QPen(QtGui.QColor(GOOD if done else LINE), 2))
            p.drawLine(QtCore.QPointF(xs[i - 1] + r + 4, y), QtCore.QPointF(xs[i] - r - 4, y))
        for i, (x, st) in enumerate(zip(xs, states)):
            colour, text, fg = {"done": (GOOD, "✓", "white"), "active": (BLUE, str(i + 1), "white"),
                                "failed": (BAD, "!", "white")}.get(st, (SOFT["grey"], str(i + 1), MUTED))
            if st == "active":
                pulse = 0.5 + 0.5 * math.sin(self.phase * 2 * math.pi)
                ring = QtGui.QColor(BLUE)
                ring.setAlphaF(0.25 * (1 - pulse))
                p.setPen(Qt.NoPen)
                p.setBrush(ring)
                p.drawEllipse(QtCore.QPointF(x, y), r + 3 + 6 * pulse, r + 3 + 6 * pulse)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(colour))
            p.drawEllipse(QtCore.QPointF(x, y), r, r)
            f = p.font()
            f.setPixelSize(13)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QtGui.QColor(fg))
            p.drawText(QtCore.QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, text)
            f.setBold(st == "active")
            f.setPixelSize(12)
            p.setFont(f)
            p.setPen(QtGui.QColor(BLUE if st == "active" else BAD if st == "failed" else INK if st == "done" else MUTED))
            p.drawText(QtCore.QRectF(x - w / n / 2, y + r + 6, w / n, 20), Qt.AlignHCenter | Qt.AlignTop, stages[i][1])

    def mousePressEvent(self, e):
        n = len(self.model.stages)
        self.clicked.emit(max(0, min(n - 1, int(e.x() / max(1, self.width() / n)))))


class RaceChart(GainChart):
    """The explanation chart, growing as folds complete: bars ease to their new values."""

    def __init__(self):
        super().__init__([dict(key="KEEP", name="Keep current", loss=float("nan"), gain=0.0, keep=True, best=False, folds=[],
                               px=float("nan"), wins=0)], None)
        self.target = []
        self.setMinimumHeight(300)

    def set_live(self, rows, gate_percent):
        """rows: RunModel.race_rows(); the displayed bars ease toward them."""
        self.gate = gate_percent
        shown = {r["key"]: r for r in self.rows}
        new = []
        for r in rows:
            keep = shown.get(r["key"])
            row = dict(r)
            row["_target"] = r["gain"]
            row["gain"] = keep["gain"] if keep else 0.0
            new.append(row)
        self.rows = new
        self.setMinimumHeight(self.TOP + self.ROW * max(1, len(new)) + self.AXIS)
        self.updateGeometry()
        self.update()

    def step(self):
        """One easing step; True while bars are still moving."""
        moving = False
        for r in self.rows:
            target = r.get("_target")
            if target is None:
                continue
            delta = target - r["gain"]
            if abs(delta) > 0.002:
                r["gain"] += delta * 0.22
                moving = True
            else:
                r["gain"] = target
        if moving:
            self.update()
        return moving

    def mouseMoveEvent(self, e):
        i = self._row_at(e.y())
        if i != self.hover:
            self.hover = i
            self.update()
        if i < 0:
            return QtWidgets.QToolTip.hideText()
        r = self.rows[i]
        results = [f"{f['label']}: {f['gain']:+.2f} %" for f in r["folds"] if f["gain"] is not None]
        text = f"<b>{r['name']}</b>" + ("<br>baseline" if r["keep"] else f"<br>{r['_target']:+.2f} % on average so far") \
            + ("<br>" + "<br>".join(results) if results and not r["keep"] else "")
        QtWidgets.QToolTip.showText(e.globalPos(), text, self)


class CaptureBars(QtWidgets.QWidget):
    """Edges used per capture, growing in."""
    ROW = 26

    def __init__(self):
        super().__init__()
        self.rows = []          # dict(name, points, edges, shown)
        self.cap = 1200.0
        self.setMouseTracking(True)
        self.setMinimumHeight(60)

    def set_captures(self, caps, cap):
        self.cap = float(cap) if cap else 0.0
        self.rows = []
        for c in caps:
            edges, points = num(c.get("used_edges")), num(c.get("points"))
            self.rows.append(dict(name=short_id(c.get("id", "?")), edges=edges or 0.0, points=points, shown=0.0))
        if not self.cap:
            self.cap = max([r["edges"] for r in self.rows] + [1.0])
        self.setMinimumHeight(max(60, self.ROW * len(self.rows) + 12))
        self.update()

    def step(self):
        moving = False
        for r in self.rows:
            d = r["edges"] - r["shown"]
            if abs(d) > 0.5:
                r["shown"] += d * 0.2
                moving = True
            else:
                r["shown"] = r["edges"]
        if moving:
            self.update()
        return moving

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        left, right = 74, 120
        top_cap = max(self.cap, max([r["edges"] for r in self.rows] + [1.0]))
        for i, r in enumerate(self.rows):
            y = 6 + i * self.ROW
            p.setPen(QtGui.QColor(MUTED))
            p.drawText(QtCore.QRectF(0, y, left - 8, self.ROW - 4), Qt.AlignVCenter | Qt.AlignRight, r["name"])
            width = max(0.0, (self.width() - left - right) * r["shown"] / top_cap)
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor("#e9e9ee"))
            p.drawRoundedRect(QtCore.QRectF(left, y + 4, self.width() - left - right, self.ROW - 12), 4, 4)
            p.setBrush(QtGui.QColor(BLUE if r["edges"] >= 0.5 * top_cap else "#9cc7ff"))
            p.drawRoundedRect(QtCore.QRectF(left, y + 4, max(width, 2), self.ROW - 12), 4, 4)
            p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(self.width() - right + 8, y, right - 8, self.ROW - 4), Qt.AlignVCenter,
                       f"{int(r['shown']):,} edges")

    def mouseMoveEvent(self, e):
        i = int((e.y() - 6) // self.ROW)
        if 0 <= i < len(self.rows):
            r = self.rows[i]
            QtWidgets.QToolTip.showText(e.globalPos(), f"Capture {r['name']}: {int(r['edges']):,} edges used"
                                        + (f" · {int(r['points']):,} LiDAR points" if r["points"] else ""), self)


class GateMeter(QtWidgets.QWidget):
    """How far the best explanation got towards the improvement it needs; fills in when the decision arrives."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(64)
        self.gain, self.gate, self.shown = None, None, 0.0

    def set_values(self, gain, gate):
        self.gain, self.gate = gain, gate
        self.shown = 0.0
        self.update()

    def step(self):
        if self.gain is None or not self.gate:
            return False
        target = max(0.0, min(1.0, self.gain / self.gate))
        d = target - self.shown
        if abs(d) > 0.002:
            self.shown += d * 0.12
            self.update()
            return True
        self.shown = target
        return False

    def paintEvent(self, _):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w = self.width() - 4
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor("#e9e9ee"))
        p.drawRoundedRect(QtCore.QRectF(2, 22, w, 16), 8, 8)
        ok = self.gain is not None and self.gate and self.gain >= self.gate
        p.setBrush(QtGui.QColor(GOOD if ok else BLUE))
        p.drawRoundedRect(QtCore.QRectF(2, 22, max(8.0, w * self.shown), 16), 8, 8)
        f = p.font()
        f.setPixelSize(12)
        p.setFont(f)
        p.setPen(QtGui.QColor(MUTED))
        p.drawText(QtCore.QRectF(2, 42, w, 18), Qt.AlignLeft, "no improvement")
        p.drawText(QtCore.QRectF(2, 42, w, 18), Qt.AlignRight,
                   f"needed: {self.gate * 100:.1f} %" if self.gate is not None else "")
        if self.gain is not None:
            p.setPen(QtGui.QColor(INK))
            p.drawText(QtCore.QRectF(2, 2, w, 18), Qt.AlignLeft, f"largest improvement found: {self.gain * 100:+.2f} %")


class Thumbs(QtWidgets.QWidget):
    """Stacked capture images, fading in as they are written."""

    def __init__(self):
        super().__init__()
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.seen = set()
        self.count = 0
        self.animations = []

    def clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.seen, self.count, self.animations = set(), 0, []

    def add_folder(self, folder, fade=True):
        """Pick up images that appeared since the last call. Half-written files are retried on the next call."""
        try:
            files = sorted(Path(folder).glob("*.png"))
        except OSError:
            return 0
        added = 0
        for path in files:
            if path in self.seen or self.count >= MAX_THUMBS:
                continue
            pm = QtGui.QPixmap(str(path))
            if pm.isNull():
                continue
            self.seen.add(path)
            tile = QtWidgets.QFrame()
            tile.setStyleSheet(f"QFrame {{ background: white; border: 1px solid {LINE}; border-radius: 10px; }} QLabel {{ border: none; }}")
            tl = QtWidgets.QVBoxLayout(tile)
            tl.setContentsMargins(6, 6, 6, 6)
            tl.setSpacing(3)
            img = QtWidgets.QLabel()
            img.setPixmap(pm.scaledToHeight(110, Qt.SmoothTransformation))
            img.setAlignment(Qt.AlignCenter)
            tl.addWidget(img)
            cap = QtWidgets.QLabel(short_id(path.stem))
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            tl.addWidget(cap)
            self.grid.addWidget(tile, self.count // 5, self.count % 5)
            self.count += 1
            added += 1
            if fade:
                effect = QtWidgets.QGraphicsOpacityEffect(tile)
                tile.setGraphicsEffect(effect)
                anim = QtCore.QPropertyAnimation(effect, b"opacity", tile)
                anim.setDuration(450)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.finished.connect(lambda t=tile: t.setGraphicsEffect(None))
                anim.start()
                self.animations.append(anim)
        return added


def _label(text="", name=None, rich=False):
    w = QtWidgets.QLabel(text)
    if name:
        w.setObjectName(name)
    w.setWordWrap(True)
    if rich:
        w.setTextFormat(Qt.RichText)
    return w


def _card():
    f = QtWidgets.QFrame()
    f.setObjectName("card")
    lay = QtWidgets.QVBoxLayout(f)
    lay.setContentsMargins(24, 20, 24, 22)
    lay.setSpacing(12)
    return f, lay


class ImageStrip(QtWidgets.QWidget):
    """The newest images a stage produced, with captions; new ones fade in. Unreadable or half-written files are retried."""
    LIMIT = 8

    def __init__(self):
        super().__init__()
        self.grid = QtWidgets.QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(10)
        self.shown = []
        self.more = QtWidgets.QLabel("")
        self.more.setObjectName("footnote")
        self.anim = []

    def clear(self):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.shown, self.anim = [], []

    def set_images(self, items):
        """items: [(path, caption)], oldest first. Shows the newest LIMIT."""
        wanted = list(items)[-self.LIMIT:]
        if [str(p) for p, _c in wanted] == [str(p) for p, _c in self.shown]:
            return
        fresh = {str(p) for p, _c in wanted} - {str(p) for p, _c in self.shown}
        self.clear()
        for n, (path, caption) in enumerate(wanted):
            pm = QtGui.QPixmap(str(path))
            if pm.isNull():
                continue
            self.shown.append((path, caption))
            tile = QtWidgets.QFrame()
            tile.setStyleSheet(f"QFrame {{ background: white; border: 1px solid {LINE}; border-radius: 10px; }} QLabel {{ border: none; }}")
            tl = QtWidgets.QVBoxLayout(tile)
            tl.setContentsMargins(6, 6, 6, 6)
            tl.setSpacing(3)
            img = QtWidgets.QLabel()
            img.setPixmap(pm.scaledToHeight(96, Qt.SmoothTransformation))
            img.setAlignment(Qt.AlignCenter)
            tl.addWidget(img)
            cap = QtWidgets.QLabel(caption)
            cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            tl.addWidget(cap)
            self.grid.addWidget(tile, n // 4, n % 4)
            if str(path) in fresh:
                effect = QtWidgets.QGraphicsOpacityEffect(tile)
                tile.setGraphicsEffect(effect)
                anim = QtCore.QPropertyAnimation(effect, b"opacity", tile)
                anim.setDuration(450)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.finished.connect(lambda t=tile: t.setGraphicsEffect(None))
                anim.start()
                self.anim.append(anim)


class StageDelegate(QtWidgets.QStyledItemDelegate):
    """One stage as a timeline row: numbered badge (a tick when done, a pulsing ring while running), the stage name, a
    one-line caption, and how long it took. A line joins the badges and turns green as stages complete."""
    HEIGHT = 62

    def __init__(self, parent=None):
        super().__init__(parent)
        self.phase = 0.0

    def sizeHint(self, option, index):
        return QtCore.QSize(option.rect.width(), self.HEIGHT)

    def paint(self, p, option, index):
        d = index.data(Qt.UserRole) or {}
        state = d.get("state", "pending")
        p.save()
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = QtCore.QRectF(option.rect).adjusted(4, 3, -4, -3)
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)
        hover = bool(option.state & QtWidgets.QStyle.State_MouseOver) and state != "pending"
        if selected or hover:
            p.setPen(QtGui.QPen(QtGui.QColor(BLUE), 1.2) if selected else Qt.NoPen)
            p.setBrush(QtGui.QColor(SOFT["blue"] if selected else "#f1f3f7"))
            p.drawRoundedRect(r, 12, 12)
        cx, cy, rad = r.left() + 26, r.center().y(), 14
        # the timeline between badges
        if not d.get("first"):
            p.setPen(QtGui.QPen(QtGui.QColor(GOOD if d.get("prev_done") else LINE), 2))
            p.drawLine(QtCore.QPointF(cx, r.top() - 3), QtCore.QPointF(cx, cy - rad - 1))
        if not d.get("last"):
            p.setPen(QtGui.QPen(QtGui.QColor(GOOD if state == "done" else LINE), 2))
            p.drawLine(QtCore.QPointF(cx, cy + rad + 1), QtCore.QPointF(cx, r.bottom() + 3))
        colour, text, fg = {"done": (GOOD, "✓", "white"), "active": (BLUE, str(d.get("number", "")), "white"),
                            "failed": (BAD, "!", "white")}.get(state, ("#e4e4ea", str(d.get("number", "")), MUTED))
        if state == "active":
            pulse = 0.5 + 0.5 * math.sin(self.phase * 2 * math.pi)
            ring = QtGui.QColor(BLUE)
            ring.setAlphaF(0.28 * (1 - pulse))
            p.setPen(Qt.NoPen)
            p.setBrush(ring)
            p.drawEllipse(QtCore.QPointF(cx, cy), rad + 2 + 5 * pulse, rad + 2 + 5 * pulse)
        p.setPen(Qt.NoPen)
        p.setBrush(QtGui.QColor(colour))
        p.drawEllipse(QtCore.QPointF(cx, cy), rad, rad)
        f = QtGui.QFont(option.font)
        f.setPixelSize(13)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor(fg))
        p.drawText(QtCore.QRectF(cx - rad, cy - rad, 2 * rad, 2 * rad), Qt.AlignCenter, text)
        # text
        x0, x1 = cx + rad + 12, r.right() - 10
        took = d.get("duration") or ""
        f.setPixelSize(12)
        f.setBold(False)
        p.setFont(f)
        took_w = p.fontMetrics().horizontalAdvance(took) + 4 if took else 0
        p.setPen(QtGui.QColor(MUTED))
        if took:
            p.drawText(QtCore.QRectF(x1 - took_w, cy - 20, took_w, 22), Qt.AlignRight | Qt.AlignVCenter, took)
        title_color = {"done": INK, "active": BLUE, "failed": BAD}.get(state, MUTED)
        f.setPixelSize(14)
        f.setBold(state in ("active", "failed", "done"))
        p.setFont(f)
        p.setPen(QtGui.QColor(title_color))
        room = max(10, x1 - x0 - took_w - 6)
        p.drawText(QtCore.QRectF(x0, cy - 21, room, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("title", ""), Qt.ElideRight, int(room)))
        f.setPixelSize(12)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QtGui.QColor(MUTED if state != "pending" else "#a1a1a8"))
        p.drawText(QtCore.QRectF(x0, cy + 2, x1 - x0, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(d.get("caption", ""), Qt.ElideRight, int(x1 - x0)))
        p.restore()


class StageList(QtWidgets.QListWidget):
    """The stages of a check as a timeline."""

    def __init__(self):
        super().__init__()
        self.setObjectName("stages")
        self.delegate = StageDelegate(self)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet("QListWidget#stages { background: transparent; border: none; outline: none; }")
        self.setMinimumWidth(270)
        self.setMaximumWidth(330)

    def set_phase(self, phase):
        self.delegate.phase = phase
        self.viewport().update()


class ProcessingView(QtWidgets.QWidget):
    """The tab. begin() starts following a run; poll() is called by a timer; show_result() shows a finished check."""
    stage_changed = QtCore.pyqtSignal(str)
    stop_review = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.review_check = None
        self._review_tick = 0
        self.model = RunModel()
        self.tail = None
        self.folder = None
        self.follow = True
        self.replaying = False
        self.replay_events = []
        self.pages = {}
        self.phase = 0.0
        self.shown_version = -1
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 8, 0, 0)
        outer.setSpacing(10)
        self.bar = StageBar()
        self.bar.clicked.connect(self.select_stage_index)
        outer.addWidget(self.bar)
        split = QtWidgets.QSplitter()
        split.setHandleWidth(10)
        self.list = StageList()
        self.list.currentRowChanged.connect(self._row_selected)
        self.list.itemClicked.connect(lambda *_: setattr(self, "follow", False))
        self.stack = QtWidgets.QStackedWidget()
        split.addWidget(self.list)
        split.addWidget(self.stack)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, 1)
        foot = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setObjectName("footnote")
        foot.addWidget(self.status, 1)
        self.replay_button = QtWidgets.QPushButton("Replay")
        self.replay_button.setToolTip("Play this check back stage by stage from its saved results")
        self.replay_button.clicked.connect(self.replay)
        self.replay_button.hide()
        foot.addWidget(self.replay_button)
        self.log_button = QtWidgets.QPushButton("Show log")
        self.log_button.setObjectName("link")
        self.log_button.setCursor(Qt.PointingHandCursor)
        self.log_button.clicked.connect(self._toggle_log)
        foot.addWidget(self.log_button)
        outer.addLayout(foot)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        self.log.setMaximumHeight(200)
        self.log.hide()
        outer.addWidget(self.log)
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)
        self.reset()

    # ---------------------------------------------------------------- lifecycle
    def reset(self, scratch=False, total=None, review=False):
        self.timer.stop()
        self.review_check = None
        self.model = RunModel(scratch, total, review)
        self.tail, self.folder, self.follow, self.replaying, self.replay_events = None, None, True, False, []
        self.shown_version = -1
        self._build_pages()
        self.replay_button.hide()
        self.status.setText("")
        self.bar.set_model(self.model)
        self._refresh_list()

    def begin(self, output, scratch=False, total=None, review=False):
        """Start following a running check whose output folder is `output`. review=True adds the maintenance comparison
        as the last stage, shown here as it runs after the fault-aware result."""
        self.reset(scratch, total, review and not scratch)
        self.folder = Path(output)
        self.tail = EventTail(self.folder / "progress.jsonl")
        self.model.live = True
        self.model._begin("data")
        self.model.version += 1
        self.timer.start()
        self._sync(force=True)

    def feed_log(self, text):
        """Process output text (any chunking): appended to the log, and understood where possible."""
        text = str(text or "")
        if not text:
            return
        self.log.appendPlainText(text.rstrip())
        for line in text.splitlines():
            if self.model.apply_log_line(line) and DECODED.search(line):
                self._decoded_row(line)

    def poll(self):
        """Read new events and new images, update the pages. Safe to call at any time."""
        if self.tail is not None:
            for ev in self.tail.read():
                self.model.apply(ev)
        if self.folder is not None and not self.model.scratch:
            self.pages["data"]["thumbs"].add_folder(self.folder / "inputs" / "stacked" / "data")
        self._poll_review()
        self._sync()

    def _poll_review(self, force=False):
        """Read the running comparison's own progress files (about twice a second)."""
        if self.review_check is None or self.model.state.get("review") != "active":
            return
        self._review_tick += 1
        if not force and self._review_tick % 15:
            return
        try:
            info = ra.live_progress(self.review_check)
        except Exception:  # noqa: BLE001 - a half-written progress file is simply read again next time
            return
        self.model.review_progress(info["done"], info["step"], info["message"], info["sub"], info["images"])

    def add_review(self, check):
        """The maintenance comparison of a finished check has started: it becomes the last stage, shown live."""
        self.review_check = Path(check)
        self.model.live = True
        if "review" not in self.model.keys:
            self.model.enable_review()
            self._make_page("review", REVIEW_STAGE[2], REVIEW_STAGE[3])
        self.model.review_begin()
        self.follow = True
        self.timer.start()
        self._sync(force=True)

    def review_finished(self, ok, message=""):
        """The comparison ended: done (its summary is read) or failed with a reason."""
        if self.model.state.get("review") not in ("pending", "active"):
            return
        self._poll_review(force=True)
        if ok and self.review_check is not None:
            summary = ra.read_json(ra.run_folder(self.review_check) / "summary.json") or {}
            self.model.review_done(summary)
        else:
            self.model.review_failed(message)
        self.review_check = None
        self._sync(force=True)

    def finish(self, ok, message=""):
        """The child process ended. Final read; mark failure when it did not succeed."""
        self.poll()
        if not ok:
            self.model.mark_failed(message)
        self._sync(force=True)
        if not self.replaying:
            self.timer.stop()
        self.tail = None

    def cancelled(self):
        self.poll()
        self.model.mark_cancelled()
        self._sync(force=True)
        self.timer.stop()
        self.tail = None

    def show_result(self, folder, result, review=None):
        """A finished check (new or older): every stage done, with the saved results; Replay plays it back.
        review: None (no maintenance comparison), 'done' (saved in the check) or 'running'."""
        events = saved_events(folder) or events_from_result(result, folder)
        self.reset(False, None, bool(review))
        self.folder = Path(folder)
        for ev in events:
            self.model.apply(ev)
        self.model.total_captures = len(self.model.captures) or None
        self.follow = False
        thumbs = self.pages["data"]["thumbs"]
        thumbs.add_folder(self.folder / "inputs" / "stacked" / "data", fade=False)
        self.replay_events = events
        self.replay_button.setVisible(len(events) > 3)
        if review == "done":
            self.model.enable_review()
            self.model.review_done(ra.read_json(ra.run_folder(folder) / "summary.json") or {})
        elif review == "running":
            self.review_check = self.folder
            self.model.review_begin()
            self.timer.start()
        self._sync(force=True)
        self._finalize_visuals()
        key = "review" if review == "running" else ("verdict" if self.model.state.get("verdict") == "done" else self.model.keys[0])
        self.select_stage(key)

    def replay(self):
        """Play the saved events back with animation (no timing is claimed: it is a replay of stored results)."""
        if not self.replay_events or self.replaying:
            return
        events, folder = list(self.replay_events), self.folder
        had_review = "review" in self.model.keys
        summary = self.model.review.get("summary")
        self.reset(False, None, had_review)
        self._replay_review = (had_review, summary)
        self.folder = folder
        self.replaying = True
        self.follow = True
        self.replay_button.setEnabled(False)
        self.pending = events
        self.pages["data"]["thumbs"].add_folder(folder / "inputs" / "stacked" / "data", fade=True)
        self.timer.start()
        self._sync(force=True)

    # ---------------------------------------------------------------- pages
    def _build_pages(self):
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        self.pages = {}
        for key, _tab, title, hint in self.model.stages:
            self._make_page(key, title, hint)

    def _make_page(self, key, title, hint):
        if True:
            card, lay = _card()
            head = QtWidgets.QHBoxLayout()
            t = _label(title, "headline")
            clock = _label("", "footnote")
            clock.setWordWrap(False)
            head.addWidget(t, 1)
            head.addWidget(clock)
            lay.addLayout(head)
            msg = _label("", "muted")
            lay.addWidget(msg)
            page = dict(card=card, lay=lay, msg=msg, clock=clock)
            if hint:
                box = QtWidgets.QFrame()
                box.setObjectName("subtle")
                bl = QtWidgets.QVBoxLayout(box)
                bl.setContentsMargins(12, 8, 12, 8)
                bl.addWidget(_label(f"<b style='color:{BLUE}'>What to look for:</b> {hint}", rich=True))
                box.hide()
                toggle = QtWidgets.QPushButton("What to look for")
                toggle.setObjectName("link")
                toggle.setCursor(Qt.PointingHandCursor)
                toggle.clicked.connect(lambda _=False, b=box: b.setVisible(not b.isVisible()))
                row = QtWidgets.QHBoxLayout()
                row.addWidget(toggle)
                row.addStretch(1)
                lay.addLayout(row)
                lay.addWidget(box)
            if key == "data":
                page["thumbs"] = Thumbs()
                page["decoded"] = _label("", "footnote", rich=True)
                lay.addWidget(page["thumbs"])
                lay.addWidget(page["decoded"])
            elif key == "features":
                page["bars"] = CaptureBars()
                lay.addWidget(page["bars"])
            elif key == "folds":
                page["progress"] = QtWidgets.QProgressBar()
                page["progress"].setTextVisible(False)
                page["eta"] = _label("", "footnote")
                page["race"] = RaceChart()
                lay.addWidget(page["progress"])
                lay.addWidget(page["eta"])
                lay.addWidget(page["race"])
            elif key == "decision":
                page["meter"] = GateMeter()
                page["result"] = _label("", "muted", rich=True)
                lay.addWidget(page["meter"])
                lay.addWidget(page["result"])
            elif key == "scratch":
                page["spinner"] = QtWidgets.QProgressBar()
                page["spinner"].setRange(0, 0)
                page["spinner"].setTextVisible(False)
                lay.addWidget(page["spinner"])
            elif key in ("candidate", "outer", "verdict"):
                page["detail"] = _label("", "muted", rich=True)
                lay.addWidget(page["detail"])
            elif key == "review":
                page["bar"] = QtWidgets.QProgressBar()
                page["bar"].setTextVisible(False)
                page["bar"].setRange(0, len(REVIEW_STEPS))
                page["now"] = _label("", "muted", rich=True)
                page["sub"] = QtWidgets.QProgressBar()
                page["sub"].setTextVisible(False)
                page["sub"].hide()
                page["images"] = ImageStrip()
                page["summary"] = _label("", "muted", rich=True)
                page["stop"] = QtWidgets.QPushButton("Stop the comparison")
                page["stop"].clicked.connect(self.stop_review.emit)
                for w in (page["bar"], page["now"], page["sub"], page["images"], page["summary"]):
                    lay.addWidget(w)
                row = QtWidgets.QHBoxLayout()
                row.addWidget(page["stop"])
                row.addStretch(1)
                lay.addLayout(row)
            lay.addStretch(1)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setWidget(card)
            self.stack.addWidget(scroll)
            page["scroll"] = scroll
            self.pages[key] = page

    def _decoded_row(self, _line):
        rows = self.model.decoded[-6:]
        self.pages["data"]["decoded"].setText("<br>".join(
            f"decoded {short_id(i)}: still window {w:.1f} s · {im} images · {fr} LiDAR frames" if w is not None else f"decoded {short_id(i)}"
            for i, w, im, fr in rows))

    # ---------------------------------------------------------------- refresh
    def _sync(self, force=False):
        m = self.model
        if not force and m.version == self.shown_version:
            return
        self.shown_version = m.version
        self.bar.update()
        self._refresh_list()
        self._refresh_pages()
        active = m.active or ("verdict" if m.state.get("verdict") == "done" else None)
        if m.failure:
            active = next((k for k in m.keys if m.state[k] == "failed"), active)
        if self.follow and active:
            self.select_stage(active, user=False)
        done = sum(1 for k in m.keys if m.state[k] == "done")
        if m.failure:
            self.status.setText(m.failure)
            self.status.setStyleSheet(f"color: {BAD};")
        else:
            self.status.setStyleSheet("")
            self.status.setText(f"{done} of {len(m.keys)} stages done" + (f" · {m.active and dict((s[0], s[2]) for s in m.stages)[m.active]}" if m.active else ""))

    def _refresh_list(self):
        m = self.model
        current = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for n, (key, tab, _title, _hint) in enumerate(m.stages):
            st = m.state[key]
            seconds = m.duration(key)
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.UserRole, dict(
                number=n + 1, title=tab, caption=SHORT.get(key, ""), state=st, first=n == 0, last=n == len(m.stages) - 1,
                prev_done=n > 0 and m.state[m.keys[n - 1]] == "done",
                duration=_secs(seconds) if seconds is not None and st in ("active", "done") else ""))
            if st == "pending":
                item.setFlags(Qt.ItemIsEnabled)
            self.list.addItem(item)
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)
        self.list.blockSignals(False)

    def _refresh_pages(self):
        m = self.model
        for key, page in self.pages.items():
            st = m.state[key]
            page["msg"].setText(m.failure if st == "failed" and m.failure else m.message.get(key, "") or
                                {"pending": "Waiting for the earlier stages.", "done": "Done.", "active": "Working…", "failed": "This stage did not finish."}.get(st, ""))
            seconds = m.duration(key)
            page["clock"].setText(_secs(seconds) if seconds is not None and st in ("active", "done") else "")
        data = self.pages["data"]
        if m.decoded:
            self._decoded_row("")
        if m.total_captures:
            data["msg"].setText(f"{data['thumbs'].count} of {m.total_captures} captures stacked" if m.state["data"] != "done"
                                else f"{m.total_captures} captures loaded")
        if "features" in self.pages and m.captures:
            bars = self.pages["features"]["bars"]
            if len(bars.rows) != len(m.captures):
                bars.set_captures(m.captures, m.max_features)
        if "folds" in self.pages:
            page = self.pages["folds"]
            total = max(m.folds_total, 1)
            done = m.folds_done()
            page["progress"].setRange(0, total)
            page["progress"].setValue(min(done, total))
            eta = m.eta_seconds()
            page["eta"].setText(f"{done} of {m.folds_total} held-out captures tested" +
                                (f" · about {eta:.0f} s left" if eta is not None and m.state["folds"] == "active" else ""))
            page["race"].set_live(m.race_rows(), m.gate * 100 if m.gate is not None else None)
        if "decision" in self.pages and m.decision:
            page = self.pages["decision"]
            d = m.decision
            if page["meter"].gain != d["gain"] or page["meter"].gate != d["gate"]:
                page["meter"].set_values(d["gain"], d["gate"])
            page["result"].setText(f"Candidate chosen by the decision policy: <b>{HYP.get(d['candidate'], d['candidate'] or 'none')}</b>. {d['reason'] or ''}")
        if "candidate" in self.pages and m.candidate:
            self.pages["candidate"]["detail"].setText(f"Fitting <b>{HYP.get(m.candidate, m.candidate)}</b> on every training capture.")
        if "outer" in self.pages and m.outer:
            o = m.outer
            self.pages["outer"]["detail"].setText(
                "No captures were kept aside, so the final independent test was not run." if not o["count"] else
                f"{o['count']} untouched captures tested: gain {o['gain'] * 100:.2f} %, " + ("passed." if o["passed"] else "not passed.") if o["gain"] is not None
                else f"{o['count']} untouched captures were tested; the test could not be scored.")
        if "review" in self.pages:
            page, r, st = self.pages["review"], m.review, m.state["review"]
            page["bar"].setRange(0, r["total"])
            page["bar"].setValue(r["done"])
            page["stop"].setVisible(st == "active")
            if st == "pending":
                page["now"].setText("Waiting for the check to finish.")
            elif st == "active":
                page["now"].setText(f"<b>{r['title'] or 'Starting'}</b>" + (f" · {r['message']}" if r["message"] and r["message"] != r["title"] else ""))
            elif st == "done":
                page["now"].setText("Finished. Everything is in the Calibration review tab.")
            else:
                page["now"].setText(f"<span style='color:{BAD}'>{r['message'] or m.failure or 'The comparison did not finish.'}</span>")
            sub = r["sub"] if st == "active" else None
            page["sub"].setVisible(bool(sub))
            if sub:
                page["sub"].setRange(0, max(sub[1], 1))
                page["sub"].setValue(min(sub[0], sub[1]))
            page["images"].set_images([(p, short_id(Path(p).stem.split("_")[-3] if False else Path(p).stem)) for p in r["images"]])
            s = r["summary"]
            if st == "done" and isinstance(s, dict) and s.get("verdict"):
                shift = num(s.get("shift_median_px"))
                page["summary"].setText(f"<b>Maintenance recommendation: {str(s['verdict']).capitalize()}.</b>" +
                                        (f" Typical point shift of the refined calibration: {shift:.2f} px." if shift is not None else ""))
            else:
                page["summary"].setText("")
        if "verdict" in self.pages and m.verdict:
            self.pages["verdict"]["detail"].setText(f"<b>{str(m.verdict.get('status') or '').replace('_', ' ').capitalize()}</b>. "
                                                    "Open the Result tab for the full assessment.")

    def _finalize_visuals(self):
        """Jump the animated widgets to their final state (used when a finished check is opened)."""
        for _ in range(60):
            moving = False
            if "folds" in self.pages:
                moving |= self.pages["folds"]["race"].step()
            if "features" in self.pages:
                moving |= self.pages["features"]["bars"].step()
            if "decision" in self.pages:
                moving |= self.pages["decision"]["meter"].step()
            if not moving:
                break

    # ---------------------------------------------------------------- selection
    def select_stage(self, key, user=True):
        if key not in self.model.keys:
            return
        index = self.model.keys.index(key)
        if user:
            self.follow = False
        self.stack.setCurrentIndex(index)
        self.list.blockSignals(True)
        self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        self.stage_changed.emit(key)

    def select_stage_index(self, index):
        if 0 <= index < len(self.model.keys) and self.model.state[self.model.keys[index]] != "pending":
            self.select_stage(self.model.keys[index])

    def _row_selected(self, row):
        if 0 <= row < len(self.model.keys) and self.model.state[self.model.keys[row]] != "pending":
            self.stack.setCurrentIndex(row)

    def _toggle_log(self):
        show = not self.log.isVisible()
        self.log.setVisible(show)
        self.log_button.setText("Hide log" if show else "Show log")

    # ---------------------------------------------------------------- animation clock
    def _tick(self):
        self.phase = (self.phase + 0.03) % 1.0
        self.bar.tick(self.phase)
        if self.model.active:
            self.list.set_phase(self.phase)
        if self.replaying:
            if getattr(self, "_replay_wait", 0) > 0:
                self._replay_wait -= 1
            elif self.pending:
                ev = self.pending.pop(0)
                self.model.apply(ev)
                self._replay_wait = {"fit": 2, "fold": 5, "features": 18, "decision": 18}.get(ev.get("stage"), 8)
                self.poll()
            else:
                self.replaying = False
                self.replay_button.setEnabled(True)
                self.follow = False
                had, summary = getattr(self, "_replay_review", (False, None))
                if had:
                    self.model.review_done(summary)
        if self.tail is not None:
            self.poll()
        else:
            self._poll_review()
            self._sync()
        moving = False
        if "folds" in self.pages:
            moving |= self.pages["folds"]["race"].step()
            moving |= self.pages["features"]["bars"].step()
            moving |= self.pages["decision"]["meter"].step()
        if self.model.active:
            self._refresh_list() if int(self.phase * 30) == 0 else None   # keeps the running clock current
        if not (self.tail or self.replaying or moving or self.model.active):
            self.timer.stop()
