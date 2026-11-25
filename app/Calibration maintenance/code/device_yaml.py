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


def _colorizer_section(text):
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(f"Invalid calibration YAML: {error}") from error
    if not isinstance(document, dict) or not isinstance(document.get(SECTION), dict):
        raise ValueError(f"The calibration file needs a '{SECTION}:' mapping.")
    return document[SECTION]


def read_params(text):
    """Read calibration values from a ROS 1 or ROS 2 pipeline file."""
    section = _colorizer_section(text)
    if "ros__parameters" not in section:
        return section
    params = section["ros__parameters"]
    if not isinstance(params, dict):
        raise ValueError("The pointcloud_colorizer.ros__parameters section needs a mapping.")
    return params


def is_ros2(text):
    return "ros__parameters" in _colorizer_section(text)


def ros2_values(params):
    """Normalize the three calibration arrays for exact comparisons."""
    result = {}
    for key, length in zip(KEYS, (9, 5, 16)):
        values = np.asarray(params.get(key), dtype=float).ravel()
        if len(values) != length or not np.isfinite(values).all():
            raise ValueError(f"{key} needs {length} finite values.")
        result[key] = values.tolist()
    return result


def update_ros2(text, params):
    """Edit only numeric scalar tokens in the existing ROS 2 calibration arrays."""
    def child(node, key):
        matches = [value for name, value in node.value
                   if isinstance(name, yaml.ScalarNode) and name.value == key] if isinstance(node, yaml.MappingNode) else []
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one '{key}' entry in the ROS 2 calibration.")
        return matches[0]

    before = yaml.safe_load(text)
    root = yaml.compose(text)
    mapping = child(child(root, SECTION), "ros__parameters")
    desired = ros2_values(params)
    edits = []
    for key, values in desired.items():
        seq = child(mapping, key)
        if not isinstance(seq, yaml.SequenceNode) or len(seq.value) != len(values):
            raise ValueError(f"'{key}' must be a flat sequence of {len(values)} numbers.")
        for node, old, value in zip(seq.value, before[SECTION]["ros__parameters"][key], values):
            if not isinstance(node, yaml.ScalarNode) or type(old) not in (int, float) or not np.isfinite(old):
                raise ValueError(f"'{key}' must contain finite numbers.")
            if type(old) is float and old == value:
                continue
            literal = repr(value)
            if "e" in literal:
                mantissa, exponent = literal.split("e")
                literal = (mantissa if "." in mantissa else mantissa + ".0") + "e" + exponent
            edits.append((node.start_mark.index, node.end_mark.index, literal))
    updated = text
    for start, end, literal in sorted(edits, reverse=True):
        updated = updated[:start] + literal + updated[end:]
    for key, values in desired.items():
        before[SECTION]["ros__parameters"][key] = values
    actual = yaml.safe_load(updated)
    loaded = actual[SECTION]["ros__parameters"]
    if actual != before or any(any(type(value) is not float for value in loaded[key]) for key in KEYS):
        raise ValueError("The ROS 2 edit would change other settings or produce an invalid parameter array.")
    return updated


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
    if "ros__parameters" in _colorizer_section(text):
        raise ValueError("This app supports reviewing ROS 2 calibration files. Writing changes requires the ROS 2 deployment workflow.")
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
