"""Native save-folder picker in its own UI process; never starts simulation work."""
import json
import sys
import tkinter as tk
from tkinter import filedialog

from launcher import last_output_parent, new_output, PREFERENCES_PATH


def main():
    scene = sys.argv[1] if len(sys.argv) > 1 else "warehouse"
    captures = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    parent_only = len(sys.argv) > 3 and sys.argv[3] == "parent"
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        selected = filedialog.askdirectory(parent=root, title="Save captures — choose a folder",
                                           initialdir=str(last_output_parent()), mustexist=True)
    finally:
        root.destroy()
    if not selected:
        print(json.dumps(dict(cancelled=True)))
        return
    from pathlib import Path
    from simulator.io import json_write
    parent = Path(selected).resolve()
    if not parent.is_dir():
        raise ValueError("Selected save folder no longer exists")
    json_write(PREFERENCES_PATH, dict(last_output_parent=str(parent)))
    if parent_only:
        print(json.dumps(dict(cancelled=False, parent=str(parent))))
        return
    print(json.dumps(dict(cancelled=False, path=str(new_output(parent, scene, captures)))))


if __name__ == "__main__":
    main()
