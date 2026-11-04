"""Capture-folder guidance beside the manual check's folder chooser."""
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt

from ui_common import BLUE, BLUE_SOFT, LINE, button, hbox, label


RAW_LAYOUT = ('my_captures/\n'
              '├── capture_001/\n'
              '│   └── rig_0.bag\n'
              '├── capture_002/\n'
              '│   └── rig_0.bag\n'
              '└── capture_003/\n'
              '    └── rig_0.bag')
STACKED_LAYOUT = ('my_captures/\n'
                  '├── capture_001.npz\n'
                  '├── capture_002.npz\n'
                  '└── capture_003.npz')
PAIRED_LAYOUT = ('my_captures/\n'
                 '├── photos/\n'
                 '│   ├── capture_001.png\n'
                 '│   └── capture_002.png\n'
                 '└── lidar_scans/\n'
                 '    ├── capture_001.pcd\n'
                 '    └── capture_002.pcd')
CAPTURE_PAIR_LAYOUT = ('my_captures/\n'
                       '├── capture_001/\n'
                       '│   ├── image.png\n'
                       '│   └── cloud.pcd\n'
                       '└── capture_002/\n'
                       '    ├── image.png\n'
                       '    └── cloud.pcd')


class CaptureFormatDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Capture format')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(720)
        self.resize(760, 610)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label('How to organise captures', 'h1'))
        layout.addWidget(label('Choose the parent folder highlighted below.', 'muted'))

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.setStyleSheet('QTabBar::tab { min-width: 110px; }')
        layout.addWidget(self.tabs)
        self.paired_tree = self.add_example('paired')
        self.capture_pair_tree = self.add_example('capture_pairs')
        self.raw_tree = self.add_example('raw')
        self.stacked_tree = self.add_example('stacked')
        self.layouts = [PAIRED_LAYOUT, CAPTURE_PAIR_LAYOUT, RAW_LAYOUT, STACKED_LAYOUT]

        note = QtWidgets.QFrame()
        note.setObjectName('soft')
        note_layout = QtWidgets.QVBoxLayout(note)
        note_layout.setContentsMargins(12, 10, 12, 10)
        self.note = label('', wrap=True)
        note_layout.addWidget(self.note)
        self.tabs.currentChanged.connect(self.update_note)
        self.update_note()
        layout.addWidget(note)
        self.copy_button = button('Copy layout', 'link', self.copy_layout)
        done = button('Done', slot=self.reject)
        done.setDefault(True)
        choose = button('Choose folder…', 'primary', self.accept)
        choose.setAutoDefault(False)
        layout.addWidget(hbox(self.copy_button, done, choose, stretch_at=1))
        self.copy_timer = QtCore.QTimer(self)
        self.copy_timer.setSingleShot(True)
        self.copy_timer.timeout.connect(lambda: self.copy_button.setText('Copy layout'))

    def add_example(self, mode):
        stacked = mode == 'stacked'
        page = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(page)
        box.setContentsMargins(0, 12, 0, 0)
        box.setSpacing(10)
        tree = QtWidgets.QTreeWidget()
        tree.setObjectName('captureTree')
        tree.setColumnCount(2)
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(False)
        tree.setItemsExpandable(False)
        tree.setExpandsOnDoubleClick(False)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        tree.setFocusPolicy(Qt.NoFocus)
        tree.setIndentation(22)
        tree.setFixedHeight(250)
        tree.setStyleSheet(f'''
            QTreeWidget#captureTree {{ background: white; border: 1px solid {LINE};
                border-radius: 12px; padding: 10px; font-family: Consolas; font-size: 10pt; }}
            QTreeWidget#captureTree::item {{ height: 29px; border: none; }}
            QTreeWidget#captureTree::branch {{ image: none; border-image: none; }}
        ''')
        assets = Path(__file__).resolve().parent / 'assets'
        folder_icon = QtGui.QIcon(str(assets / 'folder.svg'))
        file_icon = QtGui.QIcon(str(assets / 'capture-file.svg'))
        root = QtWidgets.QTreeWidgetItem(tree, ['my_captures/', 'Choose this folder'])
        root.setIcon(0, folder_icon)
        for column in range(2):
            root.setForeground(column, QtGui.QColor(BLUE))
            root.setBackground(column, QtGui.QColor(BLUE_SOFT))
        font = QtGui.QFont('Segoe UI', 9)
        font.setBold(True)
        root.setFont(1, font)
        if mode == 'paired':
            for name, extension in [('photos/', 'png'), ('lidar_scans/', 'pcd')]:
                directory = QtWidgets.QTreeWidgetItem(root, [name])
                directory.setIcon(0, folder_icon)
                for index in range(1, 3):
                    item = QtWidgets.QTreeWidgetItem(directory, [f'capture_{index:03}.{extension}'])
                    item.setIcon(0, file_icon)
        for index in range(1, 3 if mode == 'capture_pairs' else 4) if mode != 'paired' else []:
            if stacked:
                item = QtWidgets.QTreeWidgetItem(root, [f'capture_{index:03}.npz'])
                item.setIcon(0, file_icon)
            else:
                item = QtWidgets.QTreeWidgetItem(root, [f'capture_{index:03}/'])
                item.setIcon(0, folder_icon)
                for filename in (['image.png', 'cloud.pcd'] if mode == 'capture_pairs' else ['rig_0.bag']):
                    recording = QtWidgets.QTreeWidgetItem(item, [filename])
                    recording.setIcon(0, file_icon)
        tree.expandAll()
        tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        box.addWidget(tree)
        if mode in ('paired', 'capture_pairs'):
            text = ('Folder names can vary. Match capture IDs, such as image_001.png and cloud_001.pcd.'
                    if mode == 'paired' else 'Capture folders can have any name. One image + one PCD in each is an unambiguous pair.')
            box.addWidget(label(text, wrap=True))
            box.addWidget(label('PNG, JPG, BMP or TIFF + PCD · metres by default, millimetres selectable', 'small', wrap=True))
            box.addWidget(label('Files, matching and coordinate ranges are checked. Review the import notes in View pairs.', 'small', wrap=True))
        elif stacked:
            box.addWidget(label('One stacked .npz per capture, directly inside the selected folder.', wrap=True))
            details = label('<b>Required arrays</b><br>'
                            '<code>image</code> — BGR image, H × W × 3, uint8<br>'
                            '<code>xyz_mm</code> — N × 3 coordinates in millimetres<br>'
                            '<code>intensity</code> — N reflectivity values<br>'
                            '<code>frame</code> — N integer source-frame indices<br>'
                            '<code>frame_time</code> — F source-frame timestamps in seconds',
                            rich=True, wrap=True)
            details.setStyleSheet(f'background: white; border: 1px solid {LINE}; border-radius: 10px; padding: 12px;')
            details.hide()
            toggle = button('What’s inside a stacked capture?', 'link')
            toggle.setCheckable(True)
            toggle.toggled.connect(details.setVisible)
            box.addWidget(hbox(toggle, stretch_at=1))
            box.addWidget(details)
            box.addWidget(label('For separate images and PCD files, use an image + PCD layout.', 'small'))
        else:
            box.addWidget(label('Folder names start with capture_. The recording inside each is named rig_0.bag.', wrap=True))
            box.addWidget(label('Each bag needs exactly one image topic and one PointCloud2 topic.', 'small', wrap=True))
            box.addWidget(label('Defaults: /camera/image_raw  ·  /livox/lidar', 'small', wrap=True))
        self.tabs.addTab(page, {'paired': 'Image + PCD', 'capture_pairs': 'Per-capture',
                               'raw': 'ROS bags', 'stacked': 'Stacked'}[mode])
        return tree

    def update_note(self):
        paired = self.tabs.currentIndex() < 2
        self.note.setText('Aim for 3+ pairs from different views. Each image and PCD must show the same capture, '
                          'with points in the LiDAR coordinate frame.' if paired else
                          'Aim for 3+ captures. For bags, record about 4–10 seconds each; keep the rig still '
                          'during each recording and vary the view between captures.')

    def copy_layout(self):
        QtWidgets.QApplication.clipboard().setText(self.layouts[self.tabs.currentIndex()])
        self.copy_button.setText('Copied')
        self.copy_timer.start(1400)
