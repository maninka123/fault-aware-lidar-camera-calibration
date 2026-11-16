from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

project = Path(SPECPATH).parent
hidden = ['numpy', 'scipy.optimize', 'scipy.spatial', 'scipy.ndimage', 'scipy.stats',
          'scipy.linalg', 'scipy.sparse', 'cv2', 'yaml', 'matplotlib.pyplot',
          'matplotlib.backends.backend_qtagg', 'PIL.Image', 'PyQt5.QtCore',
          'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtSvg', 'paramiko', 'websocket',
          'websockets', 'pypcd4', 'win32crypt', 'cbor2']
data = []
for package in ('rosbags', 'keyring', 'pypcd4', 'websockets'):
    hidden += collect_submodules(package)
    data += copy_metadata(package)
a = Analysis([str(project / 'packaging' / 'portable_entry.py')], pathex=[],
             binaries=[], datas=data, hiddenimports=hidden,
             hookspath=[], runtime_hooks=[],
             excludes=['PyQt6', 'PySide6', 'PySide2', 'tkinter', 'torch', 'tensorflow',
                       'IPython', 'notebook', 'pytest', 'pandas', 'sklearn'],
             hooksconfig={'matplotlib': {'backends': ['Agg', 'QtAgg']}})
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='FaultAwareCalibration',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='FaultAwareCalibration')
