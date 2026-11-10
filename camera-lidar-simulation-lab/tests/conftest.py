"""Requirements for integration checks that use locally generated Blender scenes."""
from pathlib import Path

import pytest


@pytest.fixture
def built_scene(scene):
    mesh = Path(__file__).resolve().parents[1] / "blender" / "scenes" / scene / "mesh.npz"
    if not mesh.is_file():
        pytest.skip(f"{scene} mesh not built; run python -m simulator build-scene {scene} with explicit rendering flags")
    return mesh
