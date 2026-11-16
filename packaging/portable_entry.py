"""Bundled runtime entry point for the GUI and its calibration subprocesses."""
import json
import os
from pathlib import Path
import runpy
import sys
import traceback


def main():
    root = Path(sys.executable).parent / "app" if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    for folder in (root, root / "app" / "gui", root / "app" / "Calibration maintenance" / "code"):
        sys.path.insert(0, str(folder))
    # A windowed executable still needs the pipes supplied by QProcess/Popen for backend logs.
    if os.name == "nt" and getattr(sys, "frozen", False):
        import ctypes
        import msvcrt
        for name, handle in (("stdout", -11), ("stderr", -12)):
            if getattr(sys, name) is None:
                raw = ctypes.windll.kernel32.GetStdHandle(handle)
                try:
                    stream = os.fdopen(msvcrt.open_osfhandle(raw, os.O_WRONLY), "w", encoding="utf-8", buffering=1)
                except (OSError, ValueError):
                    stream = open(os.devnull, "w")
                setattr(sys, name, stream)
    args = sys.argv[1:]
    if args[:1] == ["--diagnose"]:
        report = {"ok": False, "root": str(root), "python": sys.version}
        try:
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            import research_gui
            from research_calibration.legacy_adapter import legacy_modules
            import device_ui, device_capture, ros_link, pypcd4, cbor2, keyring, paramiko, websocket, websockets
            legacy_modules().settings.load_config()
            from PyQt5 import QtWidgets
            app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
            win = research_gui.MainWindow()
            win.close()
            report["ok"] = True
        except Exception:
            report["error"] = traceback.format_exc()
        Path(args[1]).write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if report["ok"] else 1
    # Accept the same interpreter flags used by the GUI's existing child commands.
    while args and args[0].startswith("-") and args[0] != "-m":
        flag = args.pop(0)
        if flag in ("-X", "-W"):
            args.pop(0)
    if args[:1] == ["-m"]:
        module = args[1]
        sys.argv = [module] + args[2:]
        runpy.run_module(module, run_name="__main__")
    elif args and args[0].endswith(".py"):
        script = Path(args[0]).resolve()
        sys.path.insert(0, str(script.parent))
        sys.argv = args
        runpy.run_path(str(script), run_name="__main__")
    else:
        sys.argv = [str(root / "app" / "gui" / "research_gui.py")] + args
        runpy.run_path(sys.argv[0], run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
