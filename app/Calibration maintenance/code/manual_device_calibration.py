"""Explicit manual device calibration: import/edit, compare, then the guarded write workflow."""
import copy
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import yaml
from PyQt5 import QtCore, QtGui, QtWidgets

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


def parameter_change_rows(previous, candidate):
    rows = []
    def append(name, before, after):
        delta = after - before
        rows.append([name, format(before, '.12g'), format(after, '.12g'), format(delta, '+.6g') if delta else '-'])
    for name, row, column in (('fx (px)', 0, 0), ('fy (px)', 1, 1), ('cx (px)', 0, 2), ('cy (px)', 1, 2)):
        append(name, previous['camera_matrix'][row][column], candidate['camera_matrix'][row][column])
    for index, name in enumerate(('k1', 'k2', 'p1', 'p2', 'k3')):
        append(name, previous['dist_coeffs'][index], candidate['dist_coeffs'][index])
    for index, name in enumerate(('x', 'y', 'z')):
        append('t ' + name + ' (mm)', previous['extrinsic_matrix'][index][3] * 1000, candidate['extrinsic_matrix'][index][3] * 1000)
    for i in range(3):
        for j in range(3):
            a, b = previous['extrinsic_matrix'][i][j], candidate['extrinsic_matrix'][i][j]
            append(f'Rotation R[{i+1},{j+1}]', a, b)
    return rows


class DeviceMatrixEditor(QtWidgets.QWidget):
    """Read-only matrix preview; edits arrive exclusively from the parameter table."""
    textChanged = QtCore.pyqtSignal()

    def __init__(self, previous):
        super().__init__()
        self.previous = copy.deepcopy(previous)
        self.imported_text = self.invalid_text = None
        self.values = copy.deepcopy(previous)
        self.cells = {}
        layout = QtWidgets.QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        for key, title, rows, columns, position in (
                ('camera_matrix', 'Camera matrix K (pixels) - OpenCV pinhole', 3, 3, (0, 0, 1)),
                ('extrinsic_matrix', 'LiDAR to camera T - translation in metres', 4, 4, (0, 1, 1)),
                ('dist_coeffs', 'Distortion coefficients', 1, 5, (1, 0, 2))):
            group = QtWidgets.QGroupBox(title)
            grid = QtWidgets.QGridLayout(group)
            grid.setContentsMargins(14, 24, 14, 10)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(6)
            for row in range(rows):
                for column in range(columns):
                    cell = QtWidgets.QWidget(); cell_layout = QtWidgets.QVBoxLayout(cell)
                    cell_layout.setContentsMargins(2, 0, 2, 0); cell_layout.setSpacing(1)
                    if key == 'dist_coeffs':
                        name = ui.label(('k1', 'k2', 'p1', 'p2', 'k3')[column], 'small')
                        name.setAlignment(QtCore.Qt.AlignCenter)
                        cell_layout.addWidget(name)
                    value = QtWidgets.QLabel(); delta = QtWidgets.QLabel()
                    for label in (value, delta):
                        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
                        label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                        if key == 'dist_coeffs':
                            label.setAlignment(QtCore.Qt.AlignCenter)
                        label.setWordWrap(True)
                    value.setMinimumWidth(76)
                    delta.setMinimumHeight(16)
                    delta.setStyleSheet('color: #c62828; font-size: 11px; background: transparent;')
                    cell_layout.addWidget(value); cell_layout.addWidget(delta)
                    grid.addWidget(cell, row, column)
                    grid.setColumnStretch(column, 1)
                    self.cells[key, row, column] = (value, delta)
            layout.addWidget(group, position[0], position[1], 1, position[2])
        self.setPlainText(template(previous))

    def setPlainText(self, text):
        try:
            self.values, _ = parse_values(text, self.previous)
        except (ValueError, KeyError, TypeError):
            self.invalid_text = text
            self.textChanged.emit()
            return
        self.invalid_text = None
        self.imported_text = text
        self.show_values(self.values)
        self.textChanged.emit()

    def set_value(self, key, row, column, text, scale=1.):
        self.invalid_text = self.imported_text = None
        try:
            value = float(text) / scale
        except ValueError:
            value = text
        if key == 'dist_coeffs':
            self.values[key][column] = value
        else:
            self.values[key][row][column] = value
        self.show_values(self.values)
        self.textChanged.emit()

    def toPlainText(self):
        if self.invalid_text is not None:
            return self.invalid_text
        if self.imported_text is not None:
            return self.imported_text
        return template(self.values)

    def show_values(self, values):
        for (key, row, column), (value_label, delta_label) in self.cells.items():
            before = self.previous[key][column] if key == 'dist_coeffs' else self.previous[key][row][column]
            after = values[key][column] if key == 'dist_coeffs' else values[key][row][column]
            try:
                after = float(after)
                valid = np.isfinite(after)
                difference = after - before
                changed = difference != 0
                value_label.setText(format(after, '.12g'))
                delta_label.setText(('Delta ' + format(difference, '+.6g')) if changed and valid else 'Invalid value' if not valid else '')
            except (ValueError, TypeError):
                changed = True
                value_label.setText(str(after)); delta_label.setText('Invalid value')
            value_label.setStyleSheet('font-family: Consolas; font-size: 13px; background: transparent; color: ' + ('#c62828;' if changed else '#1d1d1f;'))
            value_label.setToolTip('Existing: ' + format(before, '.15g') + '\nNew: ' + str(after))


def editable_parameters():
    return ([('camera_matrix', r, c, 1.) for r, c in ((0, 0), (1, 1), (0, 2), (1, 2))]
            + [('dist_coeffs', 0, c, 1.) for c in range(5)]
            + [('extrinsic_matrix', r, 3, 1000.) for r in range(3)]
            + [('extrinsic_matrix', r, c, 1.) for r in range(3) for c in range(3)])


class ManualDeviceCalibrationDialog(QtWidgets.QDialog):
    def __init__(self, page, allow_write=False, embedded=False):
        super().__init__(page)
        self.page = page
        self.allow_write = allow_write
        self.previous = copy.deepcopy(page.params)
        self.candidate = None
        key = hashlib.sha256(page.current['key'].encode()).hexdigest()[:12]
        self.folder = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'FaultAwareCalibration' / 'manual_updates' / key
        self.setWindowTitle('Edit device calibration manually - ' + page.current['name'])
        self.resize(1100, 820)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(ui.label('Edit only the New value column in the table below and press Enter. Matrices above show the selected changes and their deltas in red. Import TXT remains available. Sending values to the device requires review and confirmation.', wrap=True))
        self.mode = QtWidgets.QComboBox()
        self.mode.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mode.setMinimumContentsLength(12)
        self.mode.setMinimumWidth(0)
        for title, value in (('Camera intrinsics + LiDAR-to-camera extrinsics', 'full'), ('Camera intrinsics only', 'intrinsic'), ('LiDAR-to-camera extrinsics only', 'extrinsic')):
            self.mode.addItem(title, value)
        layout.addWidget(ui.hbox(ui.button('Import TXT...', slot=self.import_file), ui.button('Save current template...', slot=self.save_template), self.mode))
        self.editor = DeviceMatrixEditor(self.previous)
        layout.addWidget(self.editor)
        self.note = ui.label('', wrap=True)
        layout.addWidget(self.note)
        self.comparison = QtWidgets.QWidget()
        self.comparison_layout = QtWidgets.QVBoxLayout(self.comparison)
        self.comparison_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(ui.scroll(self.comparison), 2)
        self.write_button = ui.button('Update device...' if allow_write else 'Use in Calibration review', 'primary', self.write if allow_write else self.send_to_review)
        self.write_button.setEnabled(False)
        self.restore_button = ui.button('Restore previous values...', slot=self.restore)
        from device_update_review import SavedDeviceUpdateDialog
        self.saved_update_button = ui.button('View saved device update...', slot=lambda: SavedDeviceUpdateDialog.open_saved(self, self.folder))
        close = ui.button('Close', slot=self.reject)
        self.reset_button = ui.button('Cancel edits / use existing', slot=self.reset_edits)
        layout.addWidget(action_flow([self.reset_button, self.write_button, self.restore_button, self.saved_update_button, close]))
        self.restore_button.setVisible(allow_write)
        self.saved_update_button.setVisible(allow_write)
        close.setVisible(not embedded)
        self.editor.textChanged.connect(self.invalidate)
        self.mode.currentIndexChanged.connect(self.preview)
        self.refresh_restore()
        self.preview()

    def invalidate(self, *_):
        self.candidate = None
        self.write_button.setEnabled(False)
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

    def reset_edits(self):
        self.editor.previous = copy.deepcopy(self.previous)
        self.editor.setPlainText(template(self.previous))
        self.preview()

    def preview(self, *_):
        self.invalidate()
        try:
            candidate, note = parse_values(self.editor.toPlainText(), self.previous, self.mode.currentData())
        except (ValueError, KeyError, TypeError) as error:
            self.note.setText(str(error))
            return
        rows = parameter_change_rows(self.previous, candidate)
        self.editor.show_values(candidate)
        if not hasattr(self, 'values_table'):
            self.values_table = ui.table(['Parameter', 'Existing device value', 'New value (edit here)', 'Difference'], rows, numeric=[1, 2, 3], stretch=(1, 2, 3))
            self.values_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            self.values_table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.SelectedClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
            self.values_table.itemClicked.connect(lambda item: self.values_table.editItem(item) if item.column() == 2 and item.flags() & QtCore.Qt.ItemIsEditable else None)
            self.values_table.itemChanged.connect(self.table_edited)
            self.comparison_layout.addWidget(self.values_table)
        self.values_table.blockSignals(True)
        for row, values in enumerate(rows):
            key, _, _, _ = editable_parameters()[row]
            enabled = self.mode.currentData() != ('intrinsic' if key == 'extrinsic_matrix' else 'extrinsic')
            for column, text in enumerate(values):
                item = self.values_table.item(row, column)
                item.setText(str(text))
                flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                if column == 2 and enabled:
                    flags |= QtCore.Qt.ItemIsEditable
                item.setFlags(flags)
                item.setForeground(QtGui.QColor('#c62828' if column in (2, 3) and values[3] != '-' else '#1d1d1f' if enabled else '#6e6e73'))
        self.values_table.blockSignals(False)
        self.note.setText(note)
        if self.mode.currentData() == 'intrinsic':
            self.note.setText(note + ' Camera only: the existing device alignment stays unchanged.')
        elif self.mode.currentData() == 'extrinsic':
            self.note.setText(note + ' Alignment only: the existing device camera values stay unchanged.')
        self.candidate = candidate
        changed = any(not np.array_equal(self.previous[key], candidate[key]) for key in ('camera_matrix', 'dist_coeffs', 'extrinsic_matrix'))
        self.write_button.setEnabled(changed)

    def table_edited(self, item):
        if item.column() != 2:
            return
        item.setForeground(QtGui.QColor('#c62828'))
        key, row, column, scale = editable_parameters()[item.row()]
        self.editor.set_value(key, row, column, item.text(), scale)
        self.preview()

    def info(self):
        writes = json.loads((self.folder / 'device_writes.json').read_text(encoding='utf-8')) if (self.folder / 'device_writes.json').exists() else []
        link = getattr(self.page, 'link', None)
        return dict(name='manual_' + datetime.now().strftime('%Y%m%d_%H%M%S'), out=self.folder,
                    device=dict(device=dict(self.page.current), params=self.previous, theta_max_deg=55,
                                transport=link.describe() if link else ''),
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
            if dialog.written_record.get('ros_version') == 2:
                self.previous = copy.deepcopy(self.page.params or dialog.written_record['previous'])
            else:
                self.previous = copy.deepcopy(dialog.written_record['new'])
                self.page.set_params(self.previous, f"{self.page.current['ssh_host']}:{dialog.path}, written {datetime.now():%Y-%m-%d %H:%M:%S}")
                self.page.calibration_file_text = dialog.new_text
                self.page.render_params()
            self.reset_edits()
        self.refresh_restore()

    def refresh_restore(self):
        self.restore_button.setEnabled((self.folder / 'device_writes.json').is_file())
        self.saved_update_button.setEnabled((self.folder / 'device_writes.json').is_file())

    def restore(self):
        if not self.allow_write:
            return
        restored = ui.RestoreDialog.run(self, self.info())
        if restored:
            if restored.get('ros_version') != 2:
                self.page.set_params(restored['params'], f"Restored device file {restored['path']} at {datetime.now():%Y-%m-%d %H:%M:%S}")
                self.page.calibration_file_text = restored['text']
                self.page.render_params()
            if self.page.params is not None:
                self.previous = copy.deepcopy(self.page.params)
            self.reset_edits()
        self.refresh_restore()
