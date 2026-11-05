"""Render the changed screens against a saved check; never recalibrate a device."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import sys
from pathlib import Path

from PyQt5 import QtWidgets
from app import Main
from ui_common import QSS


def main():
    output = Path(__file__).resolve().parents[1] / 'results' / '_ui_review_20261104'
    output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet(QSS)
    window = Main()
    window.resize(1920, 1040)
    window.show()
    window.open_run('rig_20261104_174529')
    window.run_page.tabs.setCurrentIndex(1)
    def settle():
        for _ in range(5):
            app.processEvents()
    settle()
    page = window.run_page
    for mode in ('existing', 'extrinsic', 'intrinsic', 'full'):
        page.options_results.select_mode(mode)
        page.matrix_preview.set_expanded(True)
        settle()
        assert page.selected_result_mode == mode
        assert page.export_txt_btn.isEnabled()
        page.matrix_preview.grab().save(str(output / f'matrices_{mode}.png'))
    page.matrix_preview.set_expanded(False)
    settle()
    assert page.matrix_preview.heading.text() == 'Calibration matrices'
    window.grab().save(str(output / 'results_collapsed.png'))
    page.matrix_preview.set_expanded(True)
    page.options_results.select_mode('extrinsic')
    settle()
    window.grab().save(str(output / 'results_expanded.png'))
    selector = page.findChild(QtWidgets.QComboBox, 'resultCaptureSelector')
    assert selector.itemText(0) == 'Capture 01 · 16:43:27'
    assert 'flicker' not in page.findChild(QtWidgets.QPushButton, 'alternateViews').text().lower()
    for width in (1360, 1680):
        window.resize(width, 1000)
        settle()
        window.grab().save(str(output / f'results_{width}.png'))
    window.new_check()
    settle()
    window.grab().save(str(output / 'check_files.png'))
    window.timer.stop()
    window.devices.shutdown()
    window.close()
    print(output)


if __name__ == '__main__':
    main()
