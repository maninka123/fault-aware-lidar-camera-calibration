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


class CaptureFormatDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Capture format')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(640)
        self.resize(700, 570)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label('How to organise captures', 'h1'))
        layout.addWidget(label('Choose the parent folder highlighted below.', 'muted'))

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.setStyleSheet('QTabBar::tab { min-width: 140px; }')
        layout.addWidget(self.tabs)
        self.raw_tree = self.add_example(False)
        self.stacked_tree = self.add_example(True)

        note = QtWidgets.QFrame()
        note.setObjectName('soft')
        note_layout = QtWidgets.QVBoxLayout(note)
        note_layout.setContentsMargins(12, 10, 12, 10)
        note_layout.addWidget(label('Aim for 3+ captures, about 4–10 seconds each. Keep the rig still during '
                                    'each recording; vary the view between captures.', wrap=True))
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

    def add_example(self, stacked):
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
        for index in range(1, 4):
            if stacked:
                item = QtWidgets.QTreeWidgetItem(root, [f'capture_{index:03}.npz'])
                item.setIcon(0, file_icon)
            else:
                item = QtWidgets.QTreeWidgetItem(root, [f'capture_{index:03}/'])
                item.setIcon(0, folder_icon)
                recording = QtWidgets.QTreeWidgetItem(item, ['rig_0.bag'])
                recording.setIcon(0, file_icon)
        tree.expandAll()
        tree.header().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        tree.header().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        box.addWidget(tree)
        if stacked:
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
            box.addWidget(label('Loose images or PCD files are not accepted here.', 'small'))
        else:
            box.addWidget(label('Folder names start with capture_. The recording inside each is named rig_0.bag.', wrap=True))
            box.addWidget(label('Each bag needs exactly one image topic and one PointCloud2 topic.', 'small', wrap=True))
            box.addWidget(label('Defaults: /camera/image_raw  ·  /livox/lidar', 'small', wrap=True))
        self.tabs.addTab(page, 'Stacked captures' if stacked else 'Recorded bags')
        return tree

    def copy_layout(self):
        QtWidgets.QApplication.clipboard().setText(STACKED_LAYOUT if self.tabs.currentIndex() else RAW_LAYOUT)
        self.copy_button.setText('Copied')
        self.copy_timer.start(1400)
