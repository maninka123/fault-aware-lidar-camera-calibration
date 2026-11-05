"""Lossless calibration JSON/TXT interchange shared by the app and checker."""
from __future__ import annotations

import configparser
import copy
import io
import json
from pathlib import Path

import numpy as np

FORMAT = 'calibration-maintenance-v1'
MODE_LABELS = {'existing': 'Keep current', 'extrinsic': 'Alignment only',
               'intrinsic': 'Camera only', 'full': 'Camera + alignment'}


def _arrays(calibration):
    try:
        K = np.asarray(calibration['intrinsics']['camera_matrix'], dtype=float)
        D = np.asarray(calibration['intrinsics']['distortion_coefficients'], dtype=float).ravel()
        T = np.asarray(calibration['extrinsics']['transform_lidar_to_camera'], dtype=float)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError('Calibration needs camera intrinsics, distortion coefficients and a LiDAR → camera matrix.') from error
    if K.shape != (3, 3) or T.shape != (4, 4) or len(D) > 4:
        raise ValueError('Expected a 3 × 3 camera matrix, up to four fisheye coefficients and a 4 × 4 LiDAR → camera matrix.')
    if not all(np.isfinite(value).all() for value in (K, D, T)):
        raise ValueError('Calibration values must be finite numbers.')
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K[2], [0, 0, 1], atol=1e-8):
        raise ValueError('Camera focal lengths must be positive and its last row must be 0 0 1.')
    if not np.allclose(T[3], [0, 0, 0, 1], atol=1e-8):
        raise ValueError('The last row of the LiDAR → camera matrix must be 0 0 0 1.')
    if not np.allclose(T[:3, :3] @ T[:3, :3].T, np.eye(3), atol=1e-3) or not np.isclose(np.linalg.det(T[:3, :3]), 1, atol=1e-3):
        raise ValueError('The LiDAR → camera matrix must contain a valid rotation.')
    return K, D, T


def write_calibration_txt(path, calibration, mode, run_name=''):
    """Write the selected candidate, preserving precision, units and all metadata."""
    if mode not in MODE_LABELS:
        raise ValueError('Choose a calibration option before saving.')
    K, D, T = _arrays(calibration)
    config = configparser.ConfigParser(interpolation=None)
    config['calibration'] = {'format': FORMAT, 'selected_mode': mode,
                             'translation_unit': 'metres', 'transform_direction': 'lidar_to_camera'}
    number_row = lambda values: ' '.join(format(float(value), '.17g') for value in values)
    config['camera_matrix'] = {f'row_{i+1}': number_row(row) for i, row in enumerate(K)}
    config['distortion_coefficients'] = {'values': number_row(D)}
    config['transform_lidar_to_camera'] = {f'row_{i+1}': number_row(row) for i, row in enumerate(T)}
    # Preserve image size, lens model and any other original calibration fields.
    metadata = copy.deepcopy(calibration)
    metadata['intrinsics'].pop('camera_matrix')
    metadata['intrinsics'].pop('distortion_coefficients')
    metadata['extrinsics'].pop('transform_lidar_to_camera')
    config['metadata'] = {'json': json.dumps(metadata, ensure_ascii=False, allow_nan=False)}
    output = io.StringIO()
    output.write('# Camera + LiDAR calibration\n')
    output.write(f'# Selected option: {MODE_LABELS[mode]}\n')
    if run_name:
        output.write('# Source check: ' + str(run_name).replace('\n', ' ').replace('\r', ' ') + '\n')
    output.write('# Intrinsics: pixels. Extrinsic translation: metres.\n')
    output.write('# Transform: p_camera = R * p_lidar + t\n')
    output.write('# Open this file under Existing calibration → Open file.\n\n')
    config.write(output)
    Path(path).write_text(output.getvalue(), encoding='utf-8')


def read_calibration(path):
    """Read existing project JSON or a TXT export without changing the source."""
    text = Path(path).read_text(encoding='utf-8-sig')
    if text.lstrip().startswith('{'):
        result = json.loads(text)
        _arrays(result)
        return result
    config = configparser.ConfigParser(interpolation=None)
    try:
        config.read_string(text)
        if config['calibration']['format'] != FORMAT:
            raise ValueError('Unknown calibration TXT format.')
        if config['calibration']['translation_unit'] != 'metres' or config['calibration']['transform_direction'] != 'lidar_to_camera':
            raise ValueError('Calibration TXT must use metres and the LiDAR → camera transform direction.')
        def matrix(section, size):
            return [[float(value) for value in config[section][f'row_{i+1}'].split()] for i in range(size)]
        result = json.loads(config.get('metadata', 'json', fallback='{}'))
        result.setdefault('intrinsics', {}).update(camera_matrix=matrix('camera_matrix', 3),
                    distortion_coefficients=[float(value) for value in config['distortion_coefficients']['values'].split()])
        result.setdefault('extrinsics', {})['transform_lidar_to_camera'] = matrix('transform_lidar_to_camera', 4)
        _arrays(result)
        return result
    except (configparser.Error, KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError(f'Could not read calibration TXT: {error}') from error
