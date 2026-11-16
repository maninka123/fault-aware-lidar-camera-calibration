"""Small inspectable data formats with explicit units and no pickle."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import numpy as np


def json_write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, allow_nan=False) + "\n"
    # Complete metadata before publishing its filename. Abrupt host failure must
    # not turn an in-progress JSON write into a misleading completion record.
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=p.parent,
                                         prefix=p.name+".", suffix=".tmp", delete=False) as stream:
            name = stream.name
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, p)
    finally:
        if name is not None and Path(name).exists():
            Path(name).unlink()


def capture_dir(run, side, capture_id):
    """Folder of one capture. Current layout is <run>/<side>/<id>; older runs used <run>/<side>/captures/<id>."""
    base = Path(run)/side
    flat = base/capture_id
    return flat if flat.is_dir() or not (base/"captures"/capture_id).is_dir() else base/"captures"/capture_id


def json_read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for data in iter(lambda: f.read(1024*1024), b""):
            h.update(data)
    return h.hexdigest()


def write_pcd(path, xyz, intensity, timestamps, channel):
    xyz = np.asarray(xyz)
    if xyz.shape != (len(intensity), 3):
        raise ValueError("PCD XYZ and intensity lengths disagree")
    header = ("# .PCD v0.7 - XYZ in metres, time in seconds\nVERSION 0.7\n"
              "FIELDS x y z intensity time channel\nSIZE 4 4 4 4 8 4\n"
              "TYPE F F F F F I\nCOUNT 1 1 1 1 1 1\n"
              f"WIDTH {len(xyz)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(xyz)}\nDATA ascii\n")
    with Path(path).open("w", encoding="ascii", newline="\n") as f:
        f.write(header)
        np.savetxt(f, np.c_[xyz, intensity, timestamps, channel], fmt=["%.9g"]*4+["%.12g", "%d"])
