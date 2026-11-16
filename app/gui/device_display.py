"""Native device values for review; processing calibration files remain unchanged."""
import copy
import json
from pathlib import Path

import device_model as dm


def device_record(meta):
    try:
        path = Path((meta or {}).get('device_source') or '') / 'device.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    except (OSError, ValueError, TypeError):
        return {}


def native_calibration(params):
    p = dm.device_params(params)
    return dict(method='Saved device values: native OpenCV pinhole model',
                image_size=[p['image_width'], p['image_height']],
                intrinsics=dict(model='opencv_pinhole', distortion_model='k1 k2 p1 p2 k3',
                                camera_matrix=p['camera_matrix'], distortion_coefficients=p['dist_coeffs']),
                extrinsics=dict(transform_lidar_to_camera=p['extrinsic_matrix']), native_device=p)


def display_options(calibrations, meta):
    """Mirror WriteDialog mode handling, with exact original values for Keep and alignment-only."""
    record = device_record(meta)
    existing = (calibrations or {}).get('existing') or {}
    previous = record.get('params') or existing.get('device_parameters')
    if not previous:
        return calibrations
    shown = {'existing': native_calibration(previous)}
    for mode, cal in (calibrations or {}).items():
        if mode not in ('intrinsic', 'extrinsic', 'full') or not cal:
            continue
        try:
            new, _ = dm.to_device(cal, previous=previous, intrinsics=mode != 'extrinsic', theta_max_deg=record.get('theta_max_deg', 55.))
            if mode == 'intrinsic':
                new['extrinsic_matrix'] = copy.deepcopy(previous['extrinsic_matrix'])
            shown[mode] = native_calibration(new)
        except (ValueError, KeyError, TypeError):
            # An unconvertible candidate must not be presented as writable native values.
            continue
    return shown


def result_calibration(result, meta):
    cal = (result or {}).get('updated_calibration')
    previous = device_record(meta).get('params') or (cal or {}).get('device_parameters')
    if not previous:
        return cal
    hypothesis = result.get('selected_hypothesis', 'KEEP')
    if hypothesis == 'KEEP':
        return native_calibration(previous)
    from use_result import mode_for
    mode = mode_for(hypothesis)
    return display_options({'existing': cal, mode: cal}, meta).get(mode, cal)
