"""Discover image/PCD pairs and validate them before calibration; inputs stay read-only."""
from __future__ import annotations

import os
import re
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff'}
UNITS = {'m': 1.0, 'mm': 0.001}
PREFIXES = {'image', 'images', 'img', 'camera', 'rgb', 'photo', 'cloud', 'pointcloud',
            'points', 'pcd', 'lidar', 'scan', 'capture', 'frame'}


def inventory(folder):
    result = {}
    for directory, children, files in os.walk(folder):
        children[:] = sorted(name for name in children if not name.startswith('.') and name != '__pycache__')
        path = Path(directory)
        images = sorted((path / name for name in files if Path(name).suffix.lower() in IMAGE_EXTENSIONS), key=lambda p: p.name.casefold())
        clouds = sorted((path / name for name in files if Path(name).suffix.lower() == '.pcd'), key=lambda p: p.name.casefold())
        if images or clouds:
            result[path] = (images, clouds)
    return result


def has_pairs(folder):
    contents = inventory(folder)
    return any(images for images, _ in contents.values()) and any(clouds for _, clouds in contents.values())


def match_key(path):
    stem = Path(path).stem.casefold()
    # image0001 / cloud0001 and image_0001 / scan_0001 are the same capture ID.
    pattern = '|'.join(sorted(PREFIXES, key=len, reverse=True))
    stem = re.sub(rf'^(?:{pattern})(?=\d)', '', stem)
    tokens = re.split(r'[\s_.-]+', stem)
    while tokens and tokens[0] in PREFIXES:
        tokens.pop(0)
    while tokens and tokens[-1] in PREFIXES:
        tokens.pop()
    return '_'.join(str(int(token)) if token.isdigit() else token for token in tokens)


def discover_pairs(folder):
    root = Path(folder).resolve()
    contents = inventory(root)
    groups, separated, orphaned = [], {}, []
    capture_parents = {directory.parent for directory, (images, clouds) in contents.items() if images and clouds}
    for directory, (images, clouds) in contents.items():
        if images and clouds:
            groups.append((directory, images, clouds, True))
        else:
            sides = separated.setdefault(directory.parent, [[], []])
            sides[0 if images else 1].append((directory, images or clouds))
    for parent, (image_dirs, cloud_dirs) in separated.items():
        if parent in capture_parents or not (image_dirs and cloud_dirs):
            orphaned.extend(path for _, paths in image_dirs + cloud_dirs for path in paths)
            continue
        if image_dirs and cloud_dirs:
            if len(image_dirs) != 1 or len(cloud_dirs) != 1:
                raise ValueError(f'Ambiguous folders in {parent.name}: choose a parent with one image folder '
                                 'and one PCD folder, or put each pair in its own capture folder.')
            groups.append((parent, image_dirs[0][1], cloud_dirs[0][1], False))
    pairs, warnings, used = [], [f'No partner for {path.relative_to(root)}; not used.' for path in orphaned], set()

    def add_pair(parent, image, cloud, single=False):
        relative = parent.relative_to(root)
        parts = list(relative.parts) + ([] if single and relative.parts else [image.stem])
        name = '__'.join(parts)
        short = re.sub(r'[^\w.-]', '_', name)
        if short.casefold() in used:
            raise ValueError(f'Duplicate capture ID: {name}. Give capture folders unique names.')
        used.add(short.casefold())
        pairs.append(dict(name=name, short=short, image=str(image), cloud=str(cloud),
                          npz=None, size_mb=cloud.stat().st_size / 1e6))

    def index(paths):
        indexed = {}
        for path in paths:
            key = match_key(path) or path.stem.casefold()
            if not key or key in indexed:
                raise ValueError(f'Ambiguous capture names in {path.parent.name}: {path.name}. '
                                 'Each image and cloud needs a unique capture ID.')
            indexed[key] = path
        return indexed

    for parent, images, clouds, same_folder in sorted(groups, key=lambda item: str(item[0]).casefold()):
        if same_folder and len(images) == len(clouds) == 1:
            add_pair(parent, images[0], clouds[0], single=True)
            continue
        image_index, cloud_index = index(images), index(clouds)
        for key in sorted(image_index.keys() & cloud_index.keys()):
            add_pair(parent, image_index[key], cloud_index[key])
        for key in sorted(image_index.keys() - cloud_index.keys()):
            warnings.append(f'No PCD for {image_index[key].relative_to(root)}; not used.')
        for key in sorted(cloud_index.keys() - image_index.keys()):
            warnings.append(f'No image for {cloud_index[key].relative_to(root)}; not used.')
    if not pairs:
        raise ValueError('No matching image/PCD pairs. Use matching capture IDs in two sibling folders, '
                         'or one image and one PCD inside each capture folder.')
    return dict(captures=pairs, warnings=warnings)


def read_image(path):
    try:
        image = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    except (OSError, cv2.error) as error:
        raise ValueError(f'Cannot read image {Path(path).name}: {error}') from error
    if image is None or min(image.shape[:2]) < 8:
        raise ValueError(f'Cannot read a usable image from {Path(path).name}.')
    return image


def read_cloud(path):
    try:
        from pypcd4 import PointCloud
    except ImportError as error:
        raise ValueError('PCD support needs pypcd4. Install the app requirements, then reopen the folder.') from error
    try:
        cloud = PointCloud.from_path(path)
        fields = {name.casefold(): name for name in cloud.fields}
        if not {'x', 'y', 'z'} <= fields.keys():
            raise ValueError('PCD needs x, y and z fields')
        xyz = cloud.numpy(tuple(fields[axis] for axis in 'xyz')).astype(np.float64)
        if len(xyz) != cloud.points:
            raise ValueError('PCD point count does not match its header')
        if xyz.ndim != 2 or xyz.shape[1] != 3:
            raise ValueError('x, y and z must be scalar fields')
        intensity_field = next((fields[name] for name in ('intensity', 'reflectivity', 'reflectance') if name in fields), None)
        intensity = cloud.numpy((intensity_field,)).ravel().astype(np.float64) if intensity_field else np.zeros(len(xyz))
        if intensity.shape != (len(xyz),):
            raise ValueError('intensity must be a scalar field')
    except Exception as error:
        raise ValueError(f'Cannot read PCD {Path(path).name}: {error}') from error
    valid = np.isfinite(xyz).all(axis=1) & (np.linalg.norm(xyz, axis=1) > 0)
    discarded = int((~valid).sum())
    if valid.sum() < 100:
        raise ValueError(f'{Path(path).name}: only {valid.sum()} usable XYZ points; at least 100 are needed.')
    return xyz[valid], np.nan_to_num(intensity[valid], nan=0.0, posinf=0.0, neginf=0.0), bool(intensity_field), discarded


def validate_pairs(folder, units='m', probe_range=(1.5, 10.0), include_frames=False):
    if units not in UNITS:
        raise ValueError('Choose PCD coordinate units: m or mm.')
    discovered = discover_pairs(folder)
    reports, frames = [], []
    warnings = list(discovered['warnings'])
    shape = None
    for capture in discovered['captures']:
        image = read_image(capture['image'])
        if shape is not None and image.shape != shape:
            raise ValueError(f'{Path(capture["image"]).name}: image dimensions differ. Use one camera resolution per check.')
        shape = image.shape
        xyz, intensity, has_intensity, discarded = read_cloud(capture['cloud'])
        xyz *= UNITS[units]
        ranges = np.linalg.norm(xyz, axis=1)
        median = float(np.median(ranges))
        low, high = (float(value) for value in np.percentile(ranges, [5, 95]))
        in_range = int(((ranges >= probe_range[0]) & (ranges <= probe_range[1])).sum())
        alternate = ranges * (0.001 if units == 'm' else 1000)
        alternate_in_range = int(((alternate >= probe_range[0]) & (alternate <= probe_range[1])).sum())
        suspicious = median < 0.1 or median > 500 or (in_range < 100 and alternate_in_range >= 100)
        message = ''
        if suspicious:
            other = 'millimetres' if units == 'm' else 'metres'
            message = (f'{Path(capture["cloud"]).name}: median range {median:g} m with the selected units. '
                       f'Check whether this export uses {other}.')
        if not has_intensity:
            warnings.append(f'{Path(capture["cloud"]).name}: no intensity; geometry edges only.')
        if discarded:
            warnings.append(f'{Path(capture["cloud"]).name}: discarded {discarded} nonfinite or zero XYZ points.')
        reports.append(dict(name=capture['name'], image=capture['image'], cloud=capture['cloud'],
                            points=len(xyz), median_range_m=median, range_5_95_m=[low, high],
                            points_in_analysis_range=in_range, units_review=suspicious, message=message))
        if include_frames:
            from common import Frame
            frames.append(Frame(capture['name'], capture['short'], image, xyz, intensity, np.zeros(len(xyz))))
    return dict(captures=discovered['captures'], units=units, reports=reports, warnings=warnings,
                image_size=list(shape[1::-1]),
                units_review=any(report['units_review'] for report in reports),
                analysis_usable=sum(report['points_in_analysis_range'] for report in reports) >= 100,
                probe_range_m=list(probe_range), frames=frames)


def load_pairs(folder, units='m', allow_unusual_units=False, probe_range=(1.5, 10.0)):
    verified = validate_pairs(folder, units, probe_range, include_frames=True)
    if verified['units_review'] and not allow_unusual_units:
        raise ValueError('PCD ranges do not agree with the selected units. Check metres versus millimetres before running.')
    if not verified['analysis_usable']:
        raise ValueError(f'Too few points at {probe_range[0]:g}–{probe_range[1]:g} m. Check PCD units or capture nearer scene structure.')
    frames = verified.pop('frames')
    return frames, verified


def save_stacked(frames, folder):
    """Prepare static pairs for the existing from-scratch solver, without inventing timing."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    for index, frame in enumerate(frames, 1):
        times, indices = np.unique(frame.time, return_inverse=True)
        np.savez_compressed(folder / f'capture_paired_{index:04d}_{frame.short}.npz', image=frame.image, xyz_mm=frame.xyz * 1000,
                            intensity=frame.intensity, frame=indices, frame_time=times)
