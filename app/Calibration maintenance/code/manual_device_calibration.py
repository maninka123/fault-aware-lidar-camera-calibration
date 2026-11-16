"""Explicit manual device calibration: import/edit, compare, then the guarded write workflow."""
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from PyQt5 import QtWidgets

import device_model as dm
import device_ui as ui
from calibration_io import read_calibration_text, _arrays
from ui_widgets import action_flow


def validate_values(raw, previous):
    values = copy.deepcopy(raw)
    declared = values.get('camera_model') or values.get('distortion_model') or 'opencv_pinhole'
    if declared not in ('pinhole', 'opencv_pinhole', 'plumb_bob', 'brown_conrady'):
        raise ValueError('The device colorizer requires OpenCV pinhole values. Convert a declared fisheye calibration through the model-aware import first.')
    for key, size in (('camera_matrix', 9), ('dist_coeffs', 5), ('extrinsic_matrix', 16)):
        array = np.asarray(values.get(key), dtype=float)
        if array.size != size or not np.isfinite(array).all():
            raise ValueError(f'{key} needs {size} finite numbers.')
    for key in ('image_width', 'image_height'):
        values.setdefault(key, previous[key])
        if values[key] != previous[key]:
            raise ValueError('The imported image dimensions must match the connected camera.')
    values = dm.file_params(values)
    K, T = np.asarray(values['camera_matrix']), np.asarray(values['extrinsic_matrix'])
    if K[0, 0] <= 0 or K[1, 1] <= 0 or not np.allclose(K, [[K[0, 0], 0, K[0, 2]], [0, K[1, 1], K[1, 2]], [0, 0, 1]], atol=1e-8):
        raise ValueError('Use positive focal lengths and a canonical zero-skew camera matrix.')
    if not np.allclose(T[3], [0, 0, 0, 1], atol=1e-8) or not np.allclose(T[:3, :3].T @ T[:3, :3], np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(T[:3, :3]), 1, atol=1e-6):
        raise ValueError('The LiDAR-to-camera transform must have a proper rotation and last row 0 0 0 1.')
    return values


def template(previous):
    values = dm.device_params(previous)
    for key in ('camera_matrix', 'extrinsic_matrix'):
        values[key] = np.asarray(values[key]).ravel().tolist()
    values['camera_model'] = 'opencv_pinhole'
    return ('# Native device pinhole values. Intrinsics: pixels; translation: metres.\n'
            '# Transform direction: LiDAR to camera. Distortion: k1 k2 p1 p2 k3.\n'
            + yaml.safe_dump({'pointcloud_colorizer': values}, sort_keys=False, default_flow_style=None))


def project_values(cal, previous, mode, theta_max_deg=55.):
    cal = copy.deepcopy(cal)
    cal['intrinsics']['camera_matrix'] = np.asarray(cal['intrinsics']['camera_matrix'], float).reshape(3, 3).tolist()
    cal['extrinsics']['transform_lidar_to_camera'] = np.asarray(cal['extrinsics']['transform_lidar_to_camera'], float).reshape(4, 4).tolist()
    _arrays(cal)
    intrinsics = cal['intrinsics']
    model = intrinsics.get('model') or cal.get('camera_model') or 'opencv_fisheye'
    if model in ('pinhole', 'opencv_pinhole', 'plumb_bob'):
        raw = dict(camera_matrix=intrinsics['camera_matrix'], dist_coeffs=intrinsics['distortion_coefficients'],
                   extrinsic_matrix=cal['extrinsics']['transform_lidar_to_camera'])
        if len(raw['dist_coeffs']) == 4:
            raw['dist_coeffs'] = list(raw['dist_coeffs']) + [0.]
        if cal.get('image_size'):
            raw['image_width'], raw['image_height'] = cal['image_size']
        return raw, None
    if model not in ('fisheye', 'opencv_fisheye', 'equidistant'):
        raise ValueError('Unsupported camera model: ' + str(model))
    raw, report = dm.to_device(cal, previous=previous, intrinsics=mode != 'extrinsic', theta_max_deg=theta_max_deg)
    return raw, report if mode != 'extrinsic' else None


def parse_values(text, previous, mode='full'):
    if mode not in ('full', 'intrinsic', 'extrinsic'):
        raise ValueError('Select which values to update.')
    note = 'Native pinhole values: no camera-model conversion; translation in metres, LiDAR to camera.'
    report = None
    if text.lstrip().startswith('[') or 'format = calibration-maintenance-v1' in text:
        cal = read_calibration_text(text)
        if cal.get('image_size') and list(cal['image_size']) != [previous['image_width'], previous['image_height']]:
            raise ValueError('The imported image dimensions must match the connected camera.')
        raw, report = project_values(cal, previous, mode)
    else:
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(f'Could not parse the calibration text: {error}') from error
        if not isinstance(raw, dict):
            raise ValueError('Import a device calibration TXT/YAML or an app-exported calibration TXT.')
        if 'intrinsics' in raw:
            cal = read_calibration_text(text)
            raw, report = project_values(cal, previous, mode)
        else:
            raw = raw.get('pointcloud_colorizer', raw)
            if isinstance(raw, dict) and (raw.get('camera_model') or raw.get('distortion_model')) in ('fisheye', 'opencv_fisheye', 'equidistant'):
                cal = dict(image_size=[raw.get('image_width', previous['image_width']), raw.get('image_height', previous['image_height'])],
                           intrinsics=dict(model='opencv_fisheye', camera_matrix=raw['camera_matrix'], distortion_coefficients=raw['dist_coeffs']),
                           extrinsics=dict(transform_lidar_to_camera=raw['extrinsic_matrix']))
                if len(np.ravel(raw['dist_coeffs'])) != 4:
                    raise ValueError('OpenCV fisheye requires four coefficients: k1 k2 k3 k4.')
                raw, report = project_values(cal, previous, mode)
    if not isinstance(raw, dict):
        raise ValueError('The pointcloud_colorizer values must be a mapping.')
    raw = validate_values(raw, previous)
    if report:
        raw['_conversion_report'] = report
        note = f"Source: OpenCV fisheye. Device: OpenCV pinhole. Converted fit: {report['rms_px']:.3f} px RMS, {report['max_px']:.3f} px maximum; covered angle {report['covered_deg']:.1f} degrees."
    if mode == 'intrinsic':
        raw['extrinsic_matrix'] = copy.deepcopy(previous['extrinsic_matrix'])
    elif mode == 'extrinsic':
        raw['camera_matrix'] = copy.deepcopy(previous['camera_matrix'])
        raw['dist_coeffs'] = copy.deepcopy(previous['dist_coeffs'])
    return raw, note


class ManualDeviceCalibrationDialog(QtWidgets.QDialog):
    def __init__(self, page, allow_write=False):
        super().__init__(page)
        self.page = page
        self.allow_write = allow_write
        self.previous = copy.deepcopy(page.params)
        self.candidate = None
        key = hashlib.sha256(page.current['key'].encode()).hexdigest()[:12]
        self.folder = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'FaultAwareCalibration' / 'manual_updates' / key
        self.setWindowTitle('Edit device calibration manually - ' + page.current['name'])
        self.resize(1000, 780)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(ui.label('Import a TXT file, or edit the current values below. Preview compares with the values read from the device. Device updates require a separate review and confirmation.', wrap=True))
        self.mode = QtWidgets.QComboBox()
        self.mode.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(12)
        self.mode.setMinimumWidth(0)
        for title, value in (('Camera intrinsics + LiDAR-to-camera extrinsics', 'full'), ('Camera intrinsics only', 'intrinsic'), ('LiDAR-to-camera extrinsics only', 'extrinsic')):
            self.mode.addItem(title, value)
        layout.addWidget(ui.hbox(ui.button('Import TXT...', slot=self.import_file), ui.button('Save current template...', slot=self.save_template), self.mode))
        self.editor = QtWidgets.QPlainTextEdit(template(self.previous))
        self.editor.setMinimumHeight(160)
        layout.addWidget(self.editor, 1)
        self.note = ui.label('', wrap=True)
        layout.addWidget(self.note)
        self.comparison = QtWidgets.QWidget()
        self.comparison_layout = QtWidgets.QVBoxLayout(self.comparison)
        self.comparison_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui.scroll(self.comparison), 2)
        self.write_button = ui.button('Review device update...' if allow_write else 'Use in Calibration review', 'primary', self.write if allow_write else self.send_to_review)
        self.write_button.setEnabled(False)
        self.restore_button = ui.button('Restore previous values...', slot=self.restore)
        close = ui.button('Close', slot=self.reject)
        layout.addWidget(action_flow([ui.button('Preview changes', slot=self.preview), self.write_button, self.restore_button, close]))
        self.restore_button.setVisible(allow_write)
        close.setVisible(not allow_write)
        self.editor.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.invalidate)
        self.refresh_restore()
        self.preview()

    def invalidate(self, *_):
        self.candidate = None
        self.write_button.setEnabled(False)
        ui.clear(self.comparison_layout)
        self.note.setText('Values changed. Preview again before updating the device.')

    def import_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Import new device values', str(Path.home()), 'Calibration text (*.txt *.yaml *.yml *.json);;All files (*)')
        if path:
            try:
                self.editor.setPlainText(Path(path).read_text(encoding='utf-8-sig'))
                self.preview()
            except (OSError, UnicodeError) as error:
                ui.warn(self, 'Could not import values', str(error))

    def save_template(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, 'Save current device values to edit', 'device_calibration.txt', 'Text (*.txt)')
        if path:
            try:
                Path(path).write_text(template(self.previous), encoding='utf-8')
            except OSError as error:
                ui.warn(self, 'Could not save template', str(error))

    def preview(self):
        self.invalidate()
        try:
            candidate, note = parse_values(self.editor.toPlainText(), self.previous, self.mode.currentData())
        except (ValueError, KeyError, TypeError) as error:
            self.note.setText(str(error))
            return
        rows = ui.param_rows(self.previous, candidate)
        for i in range(3):
            for j in range(3):
                a, b = self.previous['extrinsic_matrix'][i][j], candidate['extrinsic_matrix'][i][j]
                rows.append([f'Rotation R[{i+1},{j+1}]', f'{a:.8g}', f'{b:.8g}', f'{b-a:+.8g}'])
        self.comparison_layout.addWidget(ui.table(['Parameter', 'Existing device value', 'New value', 'Difference'], rows, numeric=[1, 2, 3]))
        self.note.setText(note)
        self.candidate = candidate
        self.write_button.setEnabled(not ui.same_params(self.previous, candidate))

    def info(self):
        writes = json.loads((self.folder / 'device_writes.json').read_text(encoding='utf-8')) if (self.folder / 'device_writes.json').exists() else []
        return dict(name='manual_' + datetime.now().strftime('%Y%m%d_%H%M%S'), out=self.folder,
                    device=dict(device=dict(self.page.current), params=self.previous, theta_max_deg=55),
                    summary=dict(mode=self.mode.currentData(), verdict='INCONCLUSIVE'),
                    device_writes=writes, tool='Manual device calibration', manual=True,
                    device_params_override=self.candidate, import_note=self.note.text(),
                    conversion_report=(self.candidate or {}).get('_conversion_report'))

    def send_to_review(self):
        if self.candidate is not None and self.page.main is not None:
            if self.page.main.review_manual_device(self.page, self.editor.toPlainText(), self.mode.currentData()):
                self.accept()

    def write(self):
        if not self.allow_write or self.candidate is None:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        dialog = ui.WriteDialog(self, self.info())
        dialog.exec_()
        if getattr(dialog, 'written_record', None):
            self.previous = copy.deepcopy(dialog.new)
            self.page.set_params(dialog.new, f"{self.page.current['ssh_host']}:{dialog.path}, written {datetime.now():%Y-%m-%d %H:%M:%S}")
            self.page.calibration_file_text = dialog.new_text
            self.page.render_params()
            self.editor.setPlainText(template(self.previous))
            self.preview()
        self.refresh_restore()

    def refresh_restore(self):
        self.restore_button.setEnabled((self.folder / 'device_writes.json').is_file())

    def restore(self):
        if not self.allow_write:
            return
        restored = ui.RestoreDialog.run(self, self.info())
        if restored:
            raw = restored['params']
            self.page.set_params(raw, f"Restored device file {restored['path']} at {datetime.now():%Y-%m-%d %H:%M:%S}")
            self.page.calibration_file_text = restored['text']
            self.page.render_params()
            self.previous = copy.deepcopy(self.page.params)
            self.editor.setPlainText(template(self.previous))
            self.preview()
        self.refresh_restore()
