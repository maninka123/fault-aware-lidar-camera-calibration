"""Research calibration backend. Original application and recordings are read-only inputs."""
import os
import sys

for _name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ[_name] = '1'  # This process only; user requested conservative Windows resource use.
sys.dont_write_bytecode = True


def assess(*args, **kwargs):
    from .calibration_pipeline import assess as run
    return run(*args, **kwargs)


def calibrate_from_scratch(*args, **kwargs):
    from .calibration_pipeline import calibrate_from_scratch as run
    return run(*args, **kwargs)


__all__ = ['assess', 'calibrate_from_scratch']
