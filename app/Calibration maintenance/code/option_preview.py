"""Visualize saved calibration options on the same camera and LiDAR capture."""
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PyQt5 import QtWidgets

import appcore as core
from calibration_io import MODE_LABELS
from cloud_view import CloudView
from settings import load_config, load_stacked_frame
from ui_common import ImageView, button, hbox, label, np_to_pixmap


def read_capture(info, name, cfg):
    from common import Frame, short_name
    from paired_data import UNITS, discover_pairs, read_cloud, read_image

    data = info.get('inputs', {}).get('data') or info['summary'].get('data')
    folder = core.resolve(data) if data else None
    stack = info['out'] / 'stacked' / 'data'
    def stacked_frame(location):
        for path in sorted(location.glob('*.npz')):
            if short_name(path.stem) == name:
                frame = load_stacked_frame(path)
                if frame is not None:
                    return frame
        return None

    frame = stacked_frame(stack)
    if frame is not None:
        return frame
    if folder is None or not folder.is_dir():
        raise ValueError('The original capture folder is unavailable.')

    bags = [p for p in folder.glob('capture_*') if (p / 'rig_0.bag').is_file()]
    if bags:
        bag = next((p for p in bags if short_name(p.name) == name), None)
        if bag is None:
            raise ValueError('The original bag for this capture is unavailable.')
        from decode_bags import decode_capture
        with TemporaryDirectory(prefix='cal-preview-') as temp:
            decode_capture(bag, 'data', dict(cfg, stacked_dir=temp, output_dir=temp))
            return load_stacked_frame(Path(temp) / 'data' / f'{bag.name}.npz')

    if next(folder.glob('*.npz'), None) is not None:
        frame = stacked_frame(folder)
        if frame is None:
            raise ValueError('The original stacked capture file is unavailable.')
        return frame

    pair = next((p for p in discover_pairs(folder)['captures'] if p['short'] == name), None)
    if pair is None:
        raise ValueError('The original image and point cloud for this capture are unavailable.')
    xyz, intensity, _, _ = read_cloud(pair['cloud'])
    units = info['summary'].get('cloud_units', 'm')
    return Frame(pair['name'], name, read_image(pair['image']), xyz * UNITS[units], intensity, np.zeros(len(xyz)))


class PinholePreviewModel:
    """The device projector, with the interface used by the alignment figure."""

    def __init__(self, calibration, image_size):
        import device_model as dm

        self.w, self.h = image_size
        self.uv = dm.pinhole_uv
        self.K = calibration['intrinsics']['camera_matrix']
        self.D = calibration['intrinsics']['distortion_coefficients']
        self.fold = np.radians(dm.pinhole_fold_deg(self.D))
        self.T = np.asarray(calibration['extrinsics']['transform_lidar_to_camera'])

    def to_camera(self, xyz, _signs, _params):
        return xyz @ self.T[:3, :3].T + self.T[:3, 3]

    def project(self, points, _params):
        x, y, z = points.T
        th = np.arctan2(np.hypot(x, y), np.maximum(z, 1e-9))
        u, v = self.uv(th, np.arctan2(y, x), self.K[0][0], self.K[1][1],
                       self.K[0][2], self.K[1][2], self.D)
        return u, v, (z > 0) & (th < self.fold) & (u >= 0) & (u < self.w) & (v >= 0) & (v < self.h)


def prepare_capture(info, name):
    import calib
    import image_edges
    import lidar_edges
    from common import image_circle

    cfg = load_config()
    frame = read_capture(info, name, cfg)
    circle = info['summary'].get('image_circle') or image_circle([frame])
    lidar, _ = lidar_edges.extract(frame, cfg['lidar'], cfg['seed'])
    edges = calib.from_edges(name, lidar, image_edges.extract(frame.image, circle, cfg['image']))
    points = frame.xyz[np.isfinite(frame.xyz).all(axis=1)]
    return frame, circle, edges, points[::max(1, (len(points) + 59999) // 60000)]


def render_option(data, calibration, title):
    from figures import alignment
    from maintain import params_of
    from maintenance_model import Model
    from settings import Calibration

    frame, circle, edges, points = data
    image = frame.image
    h, w = image.shape[:2]
    intrinsics = calibration['intrinsics']
    if intrinsics.get('model') in ('pinhole', 'opencv_pinhole', 'plumb_bob'):
        model, params = PinholePreviewModel(calibration, (w, h)), None
    else:
        distortion = np.r_[intrinsics['distortion_coefficients'], np.zeros(4)][:4]
        transform = np.asarray(calibration['extrinsics']['transform_lidar_to_camera'])
        cal = Calibration(np.asarray(intrinsics['camera_matrix']), distortion, transform, '', '', calibration)
        model = Model(transform[:3, :3], (w, h), circle, distortion)
        params = params_of(cal, model.R0)

    u, v, inside = model.project(model.to_camera(points, np.zeros(len(points)), params), params)
    inside &= np.isfinite(u) & np.isfinite(v) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    colors = np.full((len(points), 3), 85, dtype=np.uint8)
    x = np.clip(np.rint(u[inside]).astype(int), 0, w - 1)
    y = np.clip(np.rint(v[inside]).astype(int), 0, h - 1)
    colors[inside] = image[y, x]
    return colors, int(inside.sum()), alignment(frame, edges, model, params, title)


class OptionPreviewDialog(QtWidgets.QDialog):
    def __init__(self, info, calibrations, mode, parent=None):
        super().__init__(parent)
        self.info, self.calibrations = info, calibrations
        self.data = None
        self.rendered = {}
        self.setWindowTitle('Calibration preview')
        self.resize(1120, 720)
        layout = QtWidgets.QVBoxLayout(self)
        self.options = QtWidgets.QComboBox()
        for key, title in MODE_LABELS.items():
            if calibrations.get(key):
                self.options.addItem(title, key)
        self.options.setCurrentIndex(self.options.findData(mode))
        self.captures = QtWidgets.QComboBox()
        for index, name in enumerate(info['summary'].get('captures') or (), 1):
            self.captures.addItem(core.capture_display_name(name, index), name)
        self.compare = QtWidgets.QCheckBox('Compare with Keep current')
        self.compare.setChecked(mode != 'existing')
        layout.addWidget(hbox(label('Option'), self.options, label('Capture'), self.captures,
                              self.compare, stretch_at=4))
        self.status = label('', 'muted', wrap=True)
        layout.addWidget(self.status)

        self.tabs = QtWidgets.QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.rows = {}
        self.titles = {}
        self.views = {}
        for key, title, description in (
            ('cloud', 'Colourized point cloud',
             'Drag to rotate, scroll to zoom, or double-click to reset both views. Grey points have no camera colour.'),
            ('edges', 'Edge alignment',
             'Green points are within 1 px of an image edge, amber points are 1–3 px away, and red points are farther away. '
             'Click an image to enlarge.'),
        ):
            page = QtWidgets.QWidget()
            column = QtWidgets.QVBoxLayout(page)
            column.addWidget(label(description, 'muted', wrap=True))
            row = QtWidgets.QHBoxLayout()
            column.addLayout(row, 1)
            self.rows[key], self.titles[key], self.views[key] = [], [], []
            for _ in range(2):
                panel = QtWidgets.QWidget()
                panel_layout = QtWidgets.QVBoxLayout(panel)
                panel_layout.setContentsMargins(0, 0, 0, 0)
                heading = label('', 'h3', wrap=True)
                panel_layout.addWidget(heading)
                if key == 'cloud':
                    view = CloudView(None, show_info=False)
                    view.setToolTip('Drag to rotate. Scroll to zoom. Double-click to reset. Colours come from the camera.')
                else:
                    view = ImageView()
                panel_layout.addWidget(view, 1)
                row.addWidget(panel, 1)
                self.rows[key].append(panel)
                self.titles[key].append(heading)
                self.views[key].append(view)
            self.tabs.addTab(page, title)
        left, right = self.views['cloud']
        left.view_changed.connect(right.set_view)
        right.view_changed.connect(left.set_view)

        layout.addWidget(hbox(button('Close', slot=self.accept), stretch_at=0))
        self.captures.currentIndexChanged.connect(self.change_capture)
        self.options.currentIndexChanged.connect(self.refresh)
        self.compare.toggled.connect(self.refresh)

    def change_capture(self):
        self.data = None
        self.rendered.clear()
        self.views['cloud'][0].reset_view()
        self.refresh()

    def _prepare(self, name, modes):
        data = self.data if self.data is not None else prepare_capture(self.info, name)
        rendered = {mode: render_option(data, self.calibrations[mode], MODE_LABELS[mode]) for mode in modes}
        return data, rendered

    def refresh(self):
        from device_ui import busy

        mode, name = self.options.currentData(), self.captures.currentData()
        can_compare = mode not in (None, 'existing') and bool(self.calibrations.get('existing'))
        self.compare.setEnabled(can_compare)
        compare = can_compare and self.compare.isChecked()
        modes = ['existing', mode] if compare else [mode]
        self.tabs.hide()
        if not mode or not name:
            self.status.setText('This result has no saved calibration or capture to preview.')
            return
        missing = [key for key in modes if key not in self.rendered]
        try:
            if missing:
                self.data, rendered = busy(self, 'Preparing capture preview…', self._prepare, name, missing)
                self.rendered.update(rendered)
        except RuntimeError as error:
            self.status.setText(f'Preview unavailable. {error}')
            return
        native = self.calibrations[mode]['intrinsics'].get('model') in ('pinhole', 'opencv_pinhole', 'plumb_bob')
        projector = 'Device pinhole model' if native else 'Maintenance fisheye model'
        self.status.setText(f'{projector} · Saved capture · Edge colours describe this capture')
        for kind, panels in self.rows.items():
            panels[1].setVisible(compare)
            for index, key in enumerate(modes):
                colors, count, image = self.rendered[key]
                heading = MODE_LABELS[key]
                view = self.views[kind][index]
                if kind == 'cloud':
                    heading += f' · {count:,} points coloured'
                    view.set_cloud(self.data[3], colors)
                else:
                    view.caption = heading
                    view.set_source(pixmap=np_to_pixmap(image))
                self.titles[kind][index].setText(heading)
        self.tabs.show()
