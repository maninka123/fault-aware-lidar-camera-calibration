"""Read-only before/after review of saved device YAML updates and captured read-back."""
import hashlib
import difflib
import json
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
import device_model as dm
import device_yaml as dy
import device_ui as ui


def saved_comparison(folder, record=None, written=None, backup=None):
    folder = Path(folder)
    records = json.loads((folder / 'device_writes.json').read_text(encoding='utf-8')) if (folder / 'device_writes.json').is_file() else []
    def local_paths(item):
        item = dict(item)
        if '.calib_backup_' in item.get('backup', ''):
            stamp = item['backup'].rsplit('.calib_backup_', 1)[1]
            item.setdefault('local_written', f'device_written_{stamp}_pipeline.yaml')
            item.setdefault('local_backup', f'device_backup_{stamp}_pipeline.yaml')
        return item
    records = [local_paths(item) for item in records]
    if record is None:
        record = next((r for r in reversed(records) if r.get('local_written') and
                       (written is None or Path(r['local_written']).name == Path(written).name)), {})
    record = local_paths(record)
    written = Path(written) if written else folder / record.get('local_written', '')
    if not written.is_file():
        raise ValueError('Select a saved written YAML file.')
    if backup is None:
        name = record.get('local_backup') or written.name.replace('device_written_', 'device_backup_', 1)
        backup = folder / name
    backup = Path(backup)
    if backup == written or not backup.is_file():
        raise ValueError('The original backup is needed to compare before and after.')
    old, new = backup.read_text(encoding='utf-8'), written.read_text(encoding='utf-8')
    dimensions = record.get('previous') or {}
    def parameters(text):
        raw = dy.read_params(text)
        for key in ('image_width', 'image_height'):
            raw.setdefault(key, dimensions.get(key))
        return dm.file_params(raw)
    before, after = parameters(old), parameters(new)
    digest = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()
    readback_path = folder / record.get('local_readback', '')
    verified = None
    if readback_path.is_file() and record.get('readback_sha256'):
        actual = readback_path.read_text(encoding='utf-8')
        verified = digest(actual) == digest(new) == record['readback_sha256'] == record.get('written_sha256')
    return dict(record=record, before=before, after=after, old=old, new=new,
                written=written, backup=backup, verified=verified)


class SavedDeviceUpdateDialog(QtWidgets.QDialog):
    def __init__(self, parent, folder, record=None, written=None, backup=None):
        super().__init__(parent)
        self.folder = Path(folder)
        self.data = saved_comparison(folder, record, written, backup)
        self.setWindowTitle('Saved device update - before and after')
        self.resize(1050, 780)
        layout = QtWidgets.QVBoxLayout(self)
        record = self.data['record']
        layout.addWidget(ui.label(f"{record.get('device', 'Device')} | {record.get('date', '')} | {record.get('path', '')}", wrap=True))
        verified = self.data['verified']
        text = ('Verified: the device file read back after writing matches this saved YAML.' if verified else
                'Mismatch: the saved YAML or recorded read-back differs from the verified update.' if verified is False else
                'File comparison only: no captured device read-back is available for this file.')
        layout.addWidget(ui.label(text + ' This is the recorded write-time check, not a new live device check.', wrap=True))
        runtime = record.get('verified')
        runtime_text = ('The recorded runtime parameter check also matched.' if runtime is True else
                        'The runtime parameter check did not match; check the device pipeline.' if runtime is False else
                        'Runtime loading was not verified. A pipeline restart may still be required to use the saved values.')
        layout.addWidget(ui.label(runtime_text, wrap=True))
        layout.addWidget(ui.label(f"Before: {self.data['backup']}\nAfter: {self.data['written']}\nDevice projection: OpenCV pinhole. Translation differences below are in millimetres.", wrap=True))
        tabs = QtWidgets.QTabWidget()
        self.file_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.file_splitter.setChildrenCollapsible(False)
        self.before_file, self.after_file = QtWidgets.QPlainTextEdit(), QtWidgets.QPlainTextEdit()
        for title, path, editor, text in (
                ('Before - original device file', self.data['backup'], self.before_file, self.data['old']),
                ('After - written device file', self.data['written'], self.after_file, self.data['new'])):
            pane = QtWidgets.QWidget(); column = QtWidgets.QVBoxLayout(pane)
            column.setContentsMargins(4, 4, 4, 4)
            column.addWidget(ui.label(title, wrap=True))
            column.addWidget(ui.label(str(path), 'small', wrap=True))
            editor.setPlainText(text)
            editor.setReadOnly(True)
            editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            column.addWidget(editor, 1)
            self.file_splitter.addWidget(pane)
        self.file_splitter.setStretchFactor(0, 1)
        self.file_splitter.setStretchFactor(1, 1)
        changes = difflib.SequenceMatcher(None, self.data['old'].splitlines(), self.data['new'].splitlines(), autojunk=False)
        old_lines, new_lines = [], []
        for tag, i, j, k, l in changes.get_opcodes():
            if tag != 'equal':
                old_lines.extend(range(i, j)); new_lines.extend(range(k, l))
        for editor, lines in ((self.before_file, old_lines), (self.after_file, new_lines)):
            selections = []
            for line in lines:
                selection = QtWidgets.QTextEdit.ExtraSelection()
                selection.cursor = QtGui.QTextCursor(editor.document().findBlockByNumber(line))
                selection.format.setBackground(QtGui.QColor('#fff0ef'))
                selection.format.setForeground(QtGui.QColor('#b42318'))
                selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
                selections.append(selection)
            editor.setExtraSelections(selections)
        self.before_file.verticalScrollBar().valueChanged.connect(self.after_file.verticalScrollBar().setValue)
        self.after_file.verticalScrollBar().valueChanged.connect(self.before_file.verticalScrollBar().setValue)
        tabs.addTab(self.file_splitter, 'Files side by side')
        body = QtWidgets.QWidget(); values = QtWidgets.QVBoxLayout(body)
        from manual_device_calibration import parameter_change_rows
        values.addWidget(ui.table(['Parameter', 'Before on device', 'After on device', 'Change'], parameter_change_rows(self.data['before'], self.data['after']), numeric=[1, 2, 3], stretch=(1, 2, 3)))
        tabs.addTab(ui.scroll(body), 'Changed values')
        difference = QtWidgets.QPlainTextEdit(dy.diff(self.data['old'], self.data['new'], self.data['written'].name) or 'No file changes.')
        difference.setReadOnly(True)
        tabs.addTab(difference, 'Exact YAML changes')
        layout.addWidget(tabs, 1)
        layout.addWidget(ui.hbox(ui.button('Open another saved YAML...', slot=self.open_file), ui.button('Close', slot=self.accept)))

    @staticmethod
    def open_saved(parent, folder):
        try:
            SavedDeviceUpdateDialog(parent, folder).exec_()
        except (ValueError, OSError, KeyError, TypeError) as error:
            ui.warn(parent, 'Cannot open saved device update', str(error))

    def open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Open written device calibration', str(self.folder), 'Calibration files (*.yaml *.yml *.txt)')
        if not path:
            return
        try:
            data = saved_comparison(Path(path).parent, written=path)
        except (ValueError, OSError):
            backup, _ = QtWidgets.QFileDialog.getOpenFileName(self, 'Select the original backup for comparison', str(Path(path).parent), 'Calibration files (*.yaml *.yml *.txt)')
            if not backup:
                return
            try:
                data = saved_comparison(Path(path).parent, written=path, backup=backup)
            except (ValueError, OSError, KeyError, TypeError) as error:
                ui.warn(self, 'Cannot compare these files', str(error))
                return
        SavedDeviceUpdateDialog(self, Path(path).parent, data['record'], path, data['backup']).exec_()
