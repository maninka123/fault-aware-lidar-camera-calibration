"""Camera–LiDAR Simulation Lab. ROS and Blender are optional external processes."""
import os as _os

# Process-local limits only: never write machine/user environment variables.
# Set before importing numpy/Open3D/BLAS. This project deliberately favors a responsive host.
for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_key] = "1"

__version__ = "0.1.0"
