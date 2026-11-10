"""Fetch only reviewed assets from docs/ASSETS.json and verify their exact bytes."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(asset, root=ROOT):
    root = Path(root).resolve()
    target = (root / asset["file"]).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Asset path must stay inside the project directory")
    if asset["license"] != "CC0-1.0" or not asset["license_url"].startswith("https://polyhaven.com/"):
        raise ValueError("Only the reviewed CC0 Poly Haven assets are supported")
    if not asset["download_url"].startswith("https://dl.polyhaven.org/file/ph-assets/"):
        raise ValueError("Asset URL is outside the verified provider download interface")
    if target.exists():
        if target.stat().st_size == asset["size_bytes"] and digest(target) == asset["sha256"]:
            print(f"Verified existing asset: {target.name}")
            return target
        raise FileExistsError(f"Existing asset differs from the manifest; preserve or move it before retrying: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".asset-", suffix=".download", delete=False) as stream:
            staged = Path(stream.name)
            request = urllib.request.Request(asset["download_url"], headers={"User-Agent": "Camera-LiDAR-Simulation-Lab/0.1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                while True:
                    chunk = response.read(1024*1024)
                    if not chunk:
                        break
                    stream.write(chunk)
        if staged.stat().st_size != asset["size_bytes"] or digest(staged) != asset["sha256"]:
            raise ValueError("Downloaded asset failed size or SHA256 verification")
        if target.exists():
            raise FileExistsError(f"Target appeared during download; refusing to overwrite: {target}")
        staged.rename(target)
        print(f"Downloaded and verified: {target.name}")
        return target
    finally:
        if staged is not None and staged.exists():
            staged.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--asset", help="Optional reviewed asset ID; defaults to all manifest assets")
    args = parser.parse_args()
    assets = json.loads((ROOT/"docs/ASSETS.json").read_text(encoding="utf8"))["assets"]
    selected = [a for a in assets if args.asset is None or a["id"] == args.asset]
    if not selected:
        parser.error("Unknown asset ID")
    for asset in selected:
        fetch(asset)


if __name__ == "__main__":
    main()
