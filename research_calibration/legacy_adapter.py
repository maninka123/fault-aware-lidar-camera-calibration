"""Reuse the cloned application's extractors and input readers without editing them."""
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
import importlib
import sys
import copy
import json
import os
import numpy as np

REPOSITORY = Path(__file__).resolve().parents[1]


def io_path(value):
    """Extended Windows paths for local writes, without changing OS policy/settings."""
    path=Path(value).resolve()
    text=str(path)
    if os.name=='nt' and not text.startswith('\\\\?\\'):
        text='\\\\?\\UNC\\'+text[2:] if text.startswith('\\\\') else '\\\\?\\'+text
    return Path(text)


@lru_cache(None)
def legacy_modules():
    maintenance = REPOSITORY/'Calibration maintenance'/'code'
    targetless = REPOSITORY/'Targetless calibration'/'code'
    sys.path[:0] = [str(maintenance),str(targetless)]
    settings = importlib.import_module('settings')
    return SimpleNamespace(settings=settings, cb=importlib.import_module('calib'),
        image=importlib.import_module('image_edges'), lidar=importlib.import_module('lidar_edges'),
        common=importlib.import_module('common'), maintain=importlib.import_module('maintain'))


def read_calibration(value):
    calibration = copy.deepcopy(value) if isinstance(value,dict) else json.loads(Path(value).read_text(encoding='utf-8'))
    try:
        K = np.asarray(calibration['intrinsics']['camera_matrix'],float)
        T = np.asarray(calibration['extrinsics']['transform_lidar_to_camera'],float)
        D = np.ravel(calibration['intrinsics'].get('distortion_coefficients',[]))
    except (KeyError,ValueError,TypeError) as error:
        raise ValueError('Expected the existing intrinsics/extrinsics JSON layout') from error
    if K.shape!=(3,3) or T.shape!=(4,4) or len(D)>4 or not np.isfinite(K).all() or not np.isfinite(T).all() or not np.isfinite(D.astype(float)).all():
        raise ValueError('Invalid calibration matrices or distortion coefficients')
    if min(K[0,0],K[1,1])<=0 or not np.allclose(T[3],[0,0,0,1]) or not np.allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=1e-5) or np.linalg.det(T[:3,:3])<0:
        raise ValueError('Positive focal lengths and a proper LiDAR-to-camera rigid transform required')
    if not np.allclose(K,[[K[0,0],0,K[0,2]],[0,K[1,1],K[1,2]],[0,0,1]],atol=1e-12):
        raise ValueError('The adapter requires a zero-skew canonical camera matrix')
    model = calibration['intrinsics'].get('model',calibration.get('camera_model','opencv_fisheye'))
    if model not in ('opencv_fisheye','fisheye','equidistant'):
        raise ValueError('Research adapter currently supports the existing OpenCV equidistant camera model only')
    return calibration


def load_capture_bundle(captures, output, max_features=1600, seed=0, cloud_units='m', allow_unusual_units=False,
                        intensity_points=0, intensity_bins=32):
    """``intensity_points`` > 0 also keeps a reflectivity sample per capture for the experimental intensity cue
    (fault_diagnostics); the default 0 leaves the production bundle exactly as before."""
    legacy = legacy_modules()
    cfg = legacy.settings.load_config()
    from .resources import check_resources
    check_resources()
    folder = Path(captures).resolve()
    try:
        frames, _ = legacy.maintain.get_frames(folder,Path(output),cfg,cloud_units,allow_unusual_units)
    except SystemExit as error:
        raise ValueError(str(error)) from error
    if not frames:
        raise ValueError('No usable recorded captures')
    size = list(frames[0].image.shape[1::-1])
    if any(list(frame.image.shape[1::-1])!=size for frame in frames):
        raise ValueError('Capture image resolutions differ')
    # Predeclared image-domain mask, never estimated from held-out appearance.
    circle = dict(cx=(size[0]-1)/2,cy=(size[1]-1)/2,radius=min(size)/2)
    caps, metadata, probe = [], [], []
    for index, frame in enumerate(frames):
        check_resources()
        edges, _ = legacy.lidar.extract(frame,cfg['lidar'],seed)
        cap = legacy.cb.from_edges(frame.short,edges,legacy.image.extract(frame.image,circle,cfg['image']))
        if len(cap.xyz)>max_features:
            ids = np.sort(np.random.default_rng(seed+index).choice(len(cap.xyz),max_features,replace=False))
            cap = legacy.cb.Capture(cap.name,cap.xyz[ids],cap.dir[ids],cap.typ[ids],cap.sgn[ids],cap.img)
        if intensity_points>0 and getattr(frame,'intensity',None) is not None and len(frame.intensity)==len(frame.xyz):
            # Separate generator: the production edge subsample above is unaffected.
            legacy.cb.prepare_nid(cap, frame, int(intensity_points), int(intensity_bins), np.random.default_rng(seed+10007+index))
            cap.capture_time = float(np.median(frame.time)) if getattr(frame,'time',None) is not None and len(frame.time) else None
        caps.append(cap)
        metadata.append(dict(id=cap.name,points=int(len(frame.xyz)),used_edges=int(len(cap.xyz))))
        probe.append(frame.xyz[::30])
    return SimpleNamespace(caps=caps, circle=circle, size=size, cfg=cfg,
                           metadata=metadata, source=str(folder), probe=np.concatenate(probe))


def subset_capture(cap, indices):
    cb = legacy_modules().cb
    return cb.Capture(cap.name,cap.xyz[indices],cap.dir[indices],cap.typ[indices],cap.sgn[indices],cap.img)
