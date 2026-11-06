"""Render the screenshots used in the README and docs from a real saved check.

    python tools/make_screenshots.py --check research_artifacts/<check> [--out docs/images/app]

The check needs its assessment, and for the full set also the saved maintenance comparison (review/) and the stacked captures
(inputs/). Individual widgets are rendered, not the whole window, so the sidebar, file paths and device addresses never
appear in an image. Rendering is offscreen at twice the screen scale and scaled down for sharp text.
"""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_SCALE_FACTOR", "2")
if os.name == "nt" and Path("C:/Windows/Fonts").is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "gui"))
REAL_ARGS = sys.argv[1:]
sys.argv = ["research_gui.py"]     # the GUI module reads sys.argv at import

from PIL import Image  # noqa: E402
from PyQt5 import QtWidgets  # noqa: E402

MAX_WIDTH = 1500


def save(pixmap, path, crop_height=None):
    """Write a QPixmap as an optimised PNG no wider than MAX_WIDTH, optionally cropped to the top crop_height logical px."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.png")
    pixmap.save(str(tmp))
    img = Image.open(tmp).convert("RGB")
    ratio = pixmap.devicePixelRatio() or 1.0
    if crop_height:
        img = img.crop((0, 0, img.width, min(img.height, int(crop_height * ratio))))
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)), Image.LANCZOS)
    img.save(path, optimize=True)
    tmp.unlink()
    print(f"{path.name}: {img.width}x{img.height}, {path.stat().st_size // 1024} KB")


def settle(app, n=10):
    for _ in range(n):
        app.processEvents()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "images" / "app")
    a = ap.parse_args(REAL_ARGS)
    import research_gui as g
    app = QtWidgets.QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(g.QSS)
    win = g.MainWindow()
    win.resize(1500, 1500)
    win.show()
    out = a.out

    # New check: the example calibration and its matrices, then the captures
    win.show_setup()
    win.use_example()
    meta = win.meta_of(a.check)
    if meta.get("captures") and Path(meta["captures"]).is_dir():
        win.load_data(meta["captures"])
    settle(app)
    save(win.pages.widget(0).grab(), out / "new-check.png", 1000)

    # Processing and the result pages of the saved check
    win.open_run(str(a.check))
    win.pager.select(0)
    win.resize(1500, 1100)
    for key, name in (("folds", "processing-testing.png"), ("review", "processing-review.png")):
        if key in win.processing.model.keys:
            win.processing.select_stage(key)
            settle(app)
            save(win.processing.grab(), out / name)

    # Result: the figures
    win.pager.select(1)
    win.resize(1500, 6000)
    settle(app, 20)
    cards = [win.visuals.lay.itemAt(i).widget() for i in range(win.visuals.lay.count())]
    names = {"checklist": 0, "overlay": 1, "explanations": 2, "seen": 3}
    overlay = next((c for c in cards if hasattr(c, "slider")), None)
    if overlay is not None:
        overlay.amp.setCurrentIndex(2)
        overlay.slider.setValue(100)
        overlay.arrows.setChecked(True)
        settle(app)
    for label, index in names.items():
        if index < len(cards):
            save(cards[index].grab(), out / f"result-{label}.png")
    save(win.cards_frame.grab(), out / "result-options.png")
    save(win.use_card.grab(), out / "use-the-result.png")

    # Calibration review and Report
    win.pager.select(2)
    settle(app, 20)
    save(win.review.body.grab(), out / "calibration-review.png", 1500)
    win.pager.select(3)
    settle(app, 20)
    save(win.report_view.body.grab(), out / "report.png", 1500)

    # a gallery for the top of the README
    pieces = [out / n for n in ("processing-testing.png", "result-overlay.png", "calibration-review.png", "report.png")]
    if all(p.exists() for p in pieces):
        tiles = [Image.open(p).convert("RGB") for p in pieces]
        w = 740
        tiles = [t.resize((w, round(t.height * w / t.width)), Image.LANCZOS) for t in tiles]
        tile_h = 520                                   # every tile the same height: the top part of each page
        gap = 24
        canvas = Image.new("RGB", (2 * w + gap, 2 * tile_h + gap), (245, 245, 247))
        for n, t in enumerate(tiles):
            cell = Image.new("RGB", (w, tile_h), (245, 245, 247))
            cell.paste(t.crop((0, 0, w, min(t.height, tile_h))), (0, 0))
            canvas.paste(cell, ((n % 2) * (w + gap), (n // 2) * (tile_h + gap)))
        gallery = out / "gallery.png"
        canvas.save(gallery, optimize=True)
        print(f"{gallery.name}: {canvas.width}x{canvas.height}, {gallery.stat().st_size // 1024} KB")
    win.review.shutdown()


if __name__ == "__main__":
    main()
