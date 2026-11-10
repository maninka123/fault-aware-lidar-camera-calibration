"""Local image/overlay browser. No Blender, web server, GPU renderer or ROS startup."""
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk
from .adapters import sequence_entries
from .io import capture_dir


def show_dataset(run):
    run=Path(run).resolve()
    inf,captures=sequence_entries(run)
    ev=inf.parent/"evaluation"
    root=tk.Tk()
    root.title("Camera–LiDAR Simulation Lab — dataset")
    container=ttk.Frame(root,padding=16)
    container.pack(fill="both",expand=True)
    selection=tk.StringVar(value=captures[0]["capture_id"])
    ids={c["capture_id"]:c for c in captures}
    ttk.Label(container,text=str(run),wraplength=1000).grid(row=0,column=0,columnspan=2,sticky="w")
    combo=ttk.Combobox(container,textvariable=selection,values=list(ids),state="readonly")
    combo.grid(row=1,column=0,columnspan=2,sticky="w",pady=10)
    panels=[ttk.Label(container),ttk.Label(container)]
    for i,panel in enumerate(panels):
        panel.grid(row=3,column=i,padx=4,pady=4)
    ttk.Label(container,text="RGB measurement").grid(row=2,column=0)
    ttk.Label(container,text="Ground-truth projection overlay (evaluation only)").grid(row=2,column=1)
    status=tk.StringVar()
    ttk.Label(container,textvariable=status).grid(row=4,column=0,columnspan=2,sticky="w",pady=8)
    def update(_event=None):
        cid=selection.get()
        capture=ids[cid]
        paths=[capture["directory"]/"image.png",capture_dir(ev.parent, "evaluation", cid)/"calibration_overlay.png"]
        for panel,path in zip(panels,paths):
            if not path.is_file():
                panel.configure(image="",text="Image not available")
                panel.image=None
                continue
            with Image.open(path) as img:
                img=img.convert("RGB")
                img.thumbnail((600,450))
                photo=ImageTk.PhotoImage(img)
            panel.configure(image=photo,text="")
            panel.image=photo
        status.set(f"{cid} — timestamp {capture['timestamp']:.6f} s — {len(captures)} captures")
    combo.bind("<<ComboboxSelected>>",update)
    update()
    root.mainloop()
