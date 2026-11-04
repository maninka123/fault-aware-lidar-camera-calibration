"""Edit the calibration in a Sensor_Computer pipeline.yaml, changing nothing else.

Only the pointcloud_colorizer keys camera_matrix, dist_coeffs and extrinsic_matrix are replaced (text
edit: comments, order and every other setting stay as they are); a comment line records the update.
The result is checked by parsing both files: every other value must be identical.
camera_matrix is written as a flat list of 9 numbers: the colorizer reads it with
getParam(std::vector<double>) and ignores the nested [[...], [...], [...]] form.
"""
from __future__ import annotations

import difflib
import re

import numpy as np
import yaml

SECTION = "pointcloud_colorizer"
KEYS = ("camera_matrix", "dist_coeffs", "extrinsic_matrix")


def read_params(text):
    return yaml.safe_load(text)[SECTION]


def _section(lines):
    start = next((i for i, l in enumerate(lines) if re.match(rf"^{SECTION}\s*:", l)), None)
    if start is None:
        raise ValueError(f"no '{SECTION}:' section in pipeline.yaml")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    return start, end


def _value_span(lines, i):
    """Lines i..j of a 'key: [ ... ]' flow sequence (brackets balanced)."""
    depth, j = 0, i
    while True:
        s = lines[j].split("#", 1)[0]
        depth += s.count("[") - s.count("]")
        if depth <= 0:
            return i, j
        j += 1
        if j >= len(lines):
            raise ValueError(f"unbalanced brackets after line {i + 1}")


def _fmt(key, values, indent):
    pad = " " * (indent + len(key) + 3)

    def f(x):                                            # always a float literal (ROS reads 0 as an int)
        s = f"{float(x):.9g}"
        return s if any(c in s for c in ".en") else s + ".0"
    v = np.asarray(values, float).ravel()
    if key == "camera_matrix":
        rows = [", ".join(f(x) for x in v[k:k + 3]) for k in (0, 3, 6)]
        return [f"{' ' * indent}{key}: [{rows[0]},", f"{pad}{rows[1]},", f"{pad}{rows[2]}]"]
    if key == "extrinsic_matrix":
        rows = [", ".join(f(x) for x in v[k:k + 4]) for k in (0, 4, 8, 12)]
        return [f"{' ' * indent}{key}: [{rows[0]},"] + [f"{pad}{r}," for r in rows[1:3]] + [f"{pad}{rows[3]}]"]
    return [f"{' ' * indent}{key}: [{', '.join(f(x) for x in v)}]"]


def update(text, params, note):
    """New pipeline.yaml text with the device parameters `params` (camera_matrix, dist_coeffs,
    extrinsic_matrix) written into the pointcloud_colorizer section."""
    nl = "\r\n" if "\r\n" in text else "\n"               # keep the file's line endings
    lines = text.splitlines()
    s, e = _section(lines)
    body = lines[s + 1:e]
    indent = next((len(l) - len(l.lstrip()) for l in body if l.strip() and not l.lstrip().startswith("#")), 2)
    new_vals = {"camera_matrix": np.ravel(params["camera_matrix"]), "dist_coeffs": np.ravel(params["dist_coeffs"]),
                "extrinsic_matrix": np.ravel(params["extrinsic_matrix"])}
    out = lines[:s + 1]
    i, done = s + 1, set()
    while i < e:
        m = re.match(rf"^(\s*)({'|'.join(KEYS)})\s*:", lines[i])
        if m and len(m.group(1)) == indent:
            key = m.group(2)
            _, j = _value_span(lines, i)
            if key == KEYS[0] and note:
                out.append(f"{' ' * indent}# {note}")
            out += _fmt(key, new_vals[key], indent)
            done.add(key)
            i = j + 1
            continue
        if note and lines[i].strip().startswith("# Calibration updated"):
            i += 1                                       # replace an earlier note of this tool
            continue
        out.append(lines[i])
        i += 1
    tail = [k for k in KEYS if k not in done]
    while out and not out[-1].strip():
        out.pop()                                        # (keys missing from the file are appended to the section)
    for k in tail:
        out += _fmt(k, new_vals[k], indent)
    out += [""] if e < len(lines) and tail else []
    out += lines[e:]
    new = nl.join(out) + (nl if text.endswith("\n") else "")
    check(text, new, new_vals)
    return new


def check(old, new, new_vals):
    """Every value outside the three calibration keys is unchanged; the three hold the new values."""
    a, b = yaml.safe_load(old), yaml.safe_load(new)
    if set(a) != set(b):
        raise ValueError("pipeline.yaml sections changed")
    for sec in a:
        if sec != SECTION:
            if a[sec] != b[sec]:
                raise ValueError(f"section {sec} changed")
            continue
        for k in set(a[sec]) | set(b[sec]):
            if k in KEYS:
                if not np.allclose(np.ravel(b[sec][k]).astype(float), new_vals[k], rtol=1e-8, atol=1e-12):
                    raise ValueError(f"{k} was not written correctly")
            elif a[sec].get(k) != b[sec].get(k):
                raise ValueError(f"{SECTION}.{k} changed")


def diff(old, new, name="pipeline.yaml"):
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"{name} (on the device now)",
                                        f"{name} (new)", n=1))
