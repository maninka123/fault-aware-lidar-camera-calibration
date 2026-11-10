"""Chunked CPU ray casting into the SAME evaluated Blender mesh used for RGB."""
from pathlib import Path
import time
import numpy as np
import open3d as o3d


class MeshScene:
    backend = "Open3D RaycastingScene CPU:0 (Embree); no NVIDIA ray-casting claim"

    def __init__(self, mesh_path):
        self.path = Path(mesh_path)
        with np.load(self.path, allow_pickle=False) as m:
            vertices = np.asarray(m["vertices"], np.float32)
            triangles = np.asarray(m["triangles"], np.uint32)
            self.face_ids = np.asarray(m["face_ids"], np.int32)
            self.colors = np.asarray(m["colors"], np.float32)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("Mesh requires vertices Vx3 and triangles Fx3")
        if len(triangles) == 0 or not np.isfinite(vertices).all() or np.max(triangles) >= len(vertices):
            raise ValueError("Mesh is empty or has invalid vertices/indices")
        if self.colors.shape != (len(triangles), 3) or self.face_ids.shape != (len(triangles),):
            raise ValueError("colors and face_ids must describe every evaluated triangle")
        self.scene = o3d.t.geometry.RaycastingScene(nthreads=1)
        self.scene.add_triangles(o3d.core.Tensor(vertices), o3d.core.Tensor(triangles))
        self.triangle_count = len(triangles)

    def cast(self, origins, directions, chunk_size=131072):
        if not isinstance(chunk_size, int) or isinstance(chunk_size, bool) or chunk_size < 1:
            raise ValueError("chunk_size must be a positive integer")
        d = np.asarray(directions, float).reshape(-1, 3)
        o = np.broadcast_to(np.asarray(origins, float), d.shape)
        if not np.isfinite(o).all() or not np.isfinite(d).all() or not np.allclose(np.linalg.norm(d, axis=1), 1, atol=1e-6):
            raise ValueError("Ray origins and unit directions must be finite")
        ranges = np.empty(len(d), np.float32)
        normals = np.empty_like(d, dtype=np.float32)
        ids = np.empty(len(d), np.int64)
        begin = time.perf_counter()
        for start in range(0, len(d), chunk_size):
            stop = min(start+chunk_size, len(d))
            rays = np.c_[o[start:stop], d[start:stop]].astype(np.float32)
            hit = self.scene.cast_rays(o3d.core.Tensor(rays), nthreads=1)
            ranges[start:stop] = hit["t_hit"].numpy()
            normals[start:stop] = hit["primitive_normals"].numpy()
            ids[start:stop] = hit["primitive_ids"].numpy().astype(np.int64)
        elapsed = time.perf_counter()-begin
        valid = np.isfinite(ranges) & (ids < self.triangle_count)
        object_ids = np.full(len(d), -1, np.int32)
        colors = np.zeros((len(d), 3), np.float32)
        object_ids[valid] = self.face_ids[ids[valid]]
        colors[valid] = self.colors[ids[valid]]
        return dict(ranges=ranges, normals=normals, triangle_ids=ids, object_ids=object_ids,
                    colors=colors, valid=valid, elapsed_s=elapsed,
                    rays_per_second=len(d)/elapsed if elapsed else 0.)
