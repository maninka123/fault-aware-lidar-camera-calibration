"""App icon: a camera lens with a small "verified" tick badge on a flat blue tile.

Drawn in code so it stays sharp at every size.  `python app_icon.py` writes
assets/app_icon.png and assets/app_icon.ico (used by the desktop shortcut).
"""
import math
import sys
from pathlib import Path

from PyQt5 import QtCore, QtGui

SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw_icon(size):
    """Return a size x size QImage of the icon: a flat blue tile, a lens and a small tick badge."""
    n = 1024.0
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.scale(size / n, size / n)
    c = QtCore.QPointF(n / 2 - 30, n / 2 - 30)

    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(QtGui.QColor("#1565d8"))
    p.drawRoundedRect(QtCore.QRectF(40, 40, n - 80, n - 80), 230, 230)

    p.setBrush(QtGui.QColor("white"))
    p.drawEllipse(c, 300, 300)
    p.setBrush(QtGui.QColor("#0a2f7a"))
    p.drawEllipse(c, 215, 215)
    p.setBrush(QtGui.QColor("white"))
    p.drawEllipse(QtCore.QPointF(c.x() - 75, c.y() - 80), 45, 45)

    bc = QtCore.QPointF(c.x() + 290, c.y() + 290)
    p.setBrush(QtGui.QColor("#1565d8"))
    p.drawEllipse(bc, 150, 150)
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawEllipse(bc, 122, 122)
    pen = QtGui.QPen(QtGui.QColor("#1565d8"), 34)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(QtCore.Qt.NoBrush)
    path = QtGui.QPainterPath(QtCore.QPointF(bc.x() - 56, bc.y() + 2))
    path.lineTo(bc.x() - 14, bc.y() + 46)
    path.lineTo(bc.x() + 62, bc.y() - 40)
    p.drawPath(path)
    p.end()
    return img


def app_icon():
    icon = QtGui.QIcon()
    for s in SIZES:
        icon.addPixmap(QtGui.QPixmap.fromImage(draw_icon(s)))
    return icon


def logo_pixmap(size, scale=2):
    pm = QtGui.QPixmap.fromImage(draw_icon(size * scale))
    pm.setDevicePixelRatio(scale)
    return pm


def write_files(folder):
    folder.mkdir(exist_ok=True)
    draw_icon(512).save(str(folder / "app_icon.png"))
    # PNG-compressed ICO (Windows Vista+), one entry per size
    entries, blobs, offset = [], [], 6 + 16 * len(SIZES)
    for s in SIZES:
        buf = QtCore.QBuffer()
        buf.open(QtCore.QIODevice.WriteOnly)
        draw_icon(s).save(buf, "PNG")
        data = bytes(buf.data())
        entries.append(bytes([s % 256, s % 256, 0, 0]) + (1).to_bytes(2, "little") + (32).to_bytes(2, "little")
                       + len(data).to_bytes(4, "little") + offset.to_bytes(4, "little"))
        blobs.append(data)
        offset += len(data)
    header = (0).to_bytes(2, "little") + (1).to_bytes(2, "little") + len(SIZES).to_bytes(2, "little")
    (folder / "app_icon.ico").write_bytes(header + b"".join(entries) + b"".join(blobs))


if __name__ == "__main__":
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication(sys.argv[:1])
    write_files(Path(__file__).resolve().parent / "assets")
    print("wrote assets/app_icon.png and assets/app_icon.ico")
