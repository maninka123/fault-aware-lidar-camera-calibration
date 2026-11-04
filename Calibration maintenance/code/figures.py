"""Images for a maintenance run: existing vs refined calibration.

images/<capture>.png         top: LiDAR edges on the image under the existing and the refined calibration
                             (green on an image edge, yellow 1-3 px off, red further);
                             bottom: shift map (how far each LiDAR point moves) and zooms by range
images/<capture>_flicker.gif the LiDAR depth overlay of the two calibrations, alternating
images/shift_by_range.png    median shift by range with the decision thresholds
"""
from __future__ import annotations

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

import step4_images as s4  # noqa: E402  (Targetless calibration, read-only)
from step1_calibrate import depth_overlay  # noqa: E402

BLUE_HEX, INK, INK2, GRID, SURFACE = "#007aff", "#1d1d1f", "#6e6e73", "#e5e5ea", "#ffffff"


def imwrite(path, img):
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(path.suffix, img)
    if ok:
        path.write_bytes(buf.tobytes())


def save(path, img):
    """Write an image and return its path (for the live progress)."""
    imwrite(path, img)
    return path


# ------------------------------------------------------------------ live stage images
def lidar_edge_map(edges, aux):
    """LiDAR edges in the LiDAR's own angular view (red depth jumps, green creases, blue reflectivity)."""
    import lidar_edges as le
    img = cv2.resize(le.figure(edges, aux), None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.putText(img, "LiDAR edges (LiDAR view): red depth jump, green crease, blue reflectivity", (8, 18),
                s4.FONT, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def image_edge_map(image, ied):
    """Camera edges (Canny, sub-pixel) on the stacked image."""
    img = (image * 0.55).astype(np.uint8)
    img[ied["mask"]] = (0, 230, 255)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    cv2.putText(img, f"image edges: {len(ied['q'])} edge pixels", (8, 18), s4.FONT, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def alignment(frame, cap, model, p, label):
    """LiDAR edges projected with a calibration, coloured by distance to the nearest image edge."""
    return s4.alignment_panel(frame, cap, model, p, label)[0]


def regions_map(frame, cap, model, p, region, blocks, circle, nb):
    """The image regions left out one at a time: green = the refinement (fitted without it) fits it better."""
    img = (cv2.cvtColor(cv2.cvtColor(frame.image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) * 0.6).astype(np.uint8)
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    res = {int(r["left_out"].split()[2]) - 1: r for r in blocks}
    u, v, ok, _ = s4.project_edges(model, cap, p)
    for bi in range(nb):
        r = res.get(bi)
        col = (90, 90, 90) if r is None else (s4.GOOD if r["improved"] else s4.BAD)
        m = ok & (region == bi)
        for x, y in zip(u[m], v[m]):
            cv2.circle(img, (int(round(x * 2)), int(round(y * 2))), 2, col, -1, cv2.LINE_AA)
        if m.any() and r is not None:
            cx, cy = int(np.median(u[m]) * 2), int(np.median(v[m]) * 2)
            txt = f"{bi + 1}: {r['heldout_existing_share'] * 100:.0f}% -> {r['heldout_refined_share'] * 100:.0f}%"
            (tw, th), _ = cv2.getTextSize(txt, s4.FONT, 0.45, 1)
            cv2.rectangle(img, (cx - 4, cy - th - 6), (cx + tw + 4, cy + 4), (255, 255, 255), -1)
            cv2.putText(img, txt, (cx, cy), s4.FONT, 0.45, (11, 11, 11), 1, cv2.LINE_AA)
    cc, rr = (int(circle["cx"] * 2), int(circle["cy"] * 2)), int(circle["radius"] * 2)
    for k in range(nb - 1):
        a = -np.pi + 2 * np.pi * k / (nb - 1)
        cv2.line(img, (cc[0] + int(0.35 * rr * np.cos(a)), cc[1] + int(0.35 * rr * np.sin(a))),
                 (cc[0] + int(rr * np.cos(a)), cc[1] + int(rr * np.sin(a))), (200, 200, 200), 1, cv2.LINE_AA)
    cv2.circle(img, cc, int(0.35 * rr), (200, 200, 200), 1, cv2.LINE_AA)
    cv2.rectangle(img, (0, 0), (img.shape[1], 30), (255, 255, 255), -1)
    cv2.putText(img, "Held-out regions | green: improved | red: no improvement", (8, 20),
                s4.FONT, 0.46, (29, 29, 31), 1, cv2.LINE_AA)
    return img


def zooms(frame, cap, model, p_a, p_b, size=48, out=366):
    """One crop per range band on real structure: existing (blue dots) and refined (orange rings)."""
    ua, va, oka, r = s4.project_edges(model, cap, p_a)
    ub, vb, okb, _ = s4.project_edges(model, cap, p_b)
    dist = lambda u, v: cap.img["dist"][np.clip(np.rint(v).astype(int), 0, model.h - 1), np.clip(np.rint(u).astype(int), 0, model.w - 1)]
    real = (dist(ua, va) <= 2) | (dist(ub, vb) <= 2)
    tiles, used = [], []
    for lo, hi in ((1.5, 3.0), (3.0, 5.0), (5.0, 10.0), (1.5, 10.0)):
        m = oka & okb & (r >= lo) & (r < hi) & real
        tile = np.full((out, out, 3), 245, np.uint8)
        txt = f"{lo:g}-{hi:g} m: no LiDAR edges"
        if m.sum() >= 15:
            keys, counts = np.unique(np.c_[np.floor(ub[m] / size * 2).astype(int), np.floor(vb[m] / size * 2).astype(int)],
                                     axis=0, return_counts=True)
            cx = cy = None
            for kk in np.argsort(-counts):
                x, y = (keys[kk] + 1) * size / 2
                if all(abs(x - a) > size or abs(y - b) > size for a, b in used):
                    cx, cy = x, y
                    break
            if cx is None:
                cx, cy = (keys[np.argmax(counts)] + 1) * size / 2
            used.append((cx, cy))
            x0 = int(np.clip(cx - size / 2, 0, model.w - size)); y0 = int(np.clip(cy - size / 2, 0, model.h - size))
            sc = out / size
            tile = (cv2.resize(frame.image[y0:y0 + size, x0:x0 + size], (out, out), interpolation=cv2.INTER_CUBIC) * 0.75 + 64).astype(np.uint8)
            sel = np.flatnonzero(oka & okb & (r >= lo) & (r < hi) & (np.abs(ub - cx) < size) & (np.abs(vb - cy) < size))
            to = lambda u, v: (int(round((u - x0 + 0.5) * sc - 0.5)), int(round((v - y0 + 0.5) * sc - 0.5)))
            for k in sel:
                cv2.circle(tile, to(ua[k], va[k]), 4, s4.BLUE, -1, cv2.LINE_AA)
            for k in sel:
                cv2.circle(tile, to(ub[k], vb[k]), 6, s4.ORANGE, 2, cv2.LINE_AA)
            txt = f"{lo:g}-{hi:g} m   shift {np.median(np.hypot(ua[sel] - ub[sel], va[sel] - vb[sel])):.1f} px"
        cv2.rectangle(tile, (0, 0), (out, 24), (255, 255, 255), -1)
        cv2.putText(tile, txt, (8, 17), s4.FONT, 0.5, (11, 11, 11), 1, cv2.LINE_AA)
        cv2.rectangle(tile, (0, 0), (out - 1, out - 1), (200, 200, 200), 1)
        tiles.append(tile)
    grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
    pad = np.full((grid.shape[0], model.w * s4.S - grid.shape[1], 3), 255, np.uint8)
    s4.legend(pad, [(s4.BLUE, "existing", "dot"), (s4.ORANGE, "refined", "ring")], y0=8)
    cv2.putText(pad, "zoom x7.6", (12, 80), s4.FONT, 0.45, (78, 81, 82), 1, cv2.LINE_AA)
    return np.hstack([grid, pad])


def compare(frame, cap, model, p_old, p_new, p_exist, title, verdict):
    left, on_o = s4.alignment_panel(frame, cap, model, p_old, "Previous")
    right, on_n = s4.alignment_panel(frame, cap, model, p_new, "Refined")
    for panel, name, share in ((left, 'Previous', on_o), (right, 'Refined', on_n)):
        panel[:30] = 255
        cv2.putText(panel, f'{name}  |  {share:.0f}% aligned', (12, 21), s4.FONT, 0.55,
                    (29, 29, 31), 1, cv2.LINE_AA)
    gap = np.full((left.shape[0], 8, 3), 255, np.uint8)
    top = np.hstack([left, gap, right])
    difference = s4.difference_panel(frame, model, p_exist, p_new)
    difference[:30] = 255
    cv2.putText(difference, 'Point shift (px)', (12, 21), s4.FONT, 0.55, (29, 29, 31), 1, cv2.LINE_AA)
    bottom = np.hstack([difference, gap, zooms(frame, cap, model, p_old, p_new)])
    body = np.vstack([top, np.full((8, top.shape[1], 3), 255, np.uint8), bottom])
    head = np.full((34, body.shape[1], 3), 255, np.uint8)
    cv2.putText(head, title, (12, 23), s4.FONT, 0.58, (29, 29, 31), 1, cv2.LINE_AA)
    return np.vstack([head, body])


def flicker(frame, model, p_a, p_b, path):
    a = depth_overlay(frame, model, p_a, "Previous", step=2)
    b = depth_overlay(frame, model, p_b, "Refined", step=2)
    for img, col in ((a, s4.BLUE), (b, s4.ORANGE)):
        cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), col, 6)
    ims = [Image.fromarray(cv2.cvtColor(x, cv2.COLOR_BGR2RGB)) for x in (a, b)]
    path.parent.mkdir(parents=True, exist_ok=True)
    ims[0].save(path, save_all=True, append_images=ims[1:], duration=900, loop=0)


def shift_chart(summary, cfg, path):
    bands = [(k, v) for k, v in summary["shift_by_range_px"].items() if v is not None]
    dc = cfg["decision"]
    fig, ax = plt.subplots(figsize=(6.4, 3.0), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    x = np.arange(len(bands))
    vals = [v for _, v in bands]
    ax.bar(x, vals, 0.55, color=BLUE_HEX, zorder=3)
    for xi, v in zip(x, vals):
        ax.text(xi, v, f"{v:.2f} px", ha="center", va="bottom", fontsize=9, color=INK)
    top = max(max(vals, default=0) * 1.3, dc["negligible_px"] * 1.6)
    for y, lab in ((dc["negligible_px"], "error margin: below = no update"), (dc["large_px"], "large change")):
        if y <= top:
            ax.axhline(y, color=INK2, lw=1, ls=(0, (4, 3)), zorder=2)
            ax.text(len(bands) - 0.45, y, f" {lab}", va="bottom", ha="right", fontsize=8, color=INK2)
    ax.set_ylim(0, top)
    ax.set_xticks(x); ax.set_xticklabels([k for k, _ in bands], fontsize=9, color=INK2)
    ax.set_ylabel("median shift (px)", fontsize=9, color=INK2)
    ax.set_title('Point shift by distance', loc="left", fontsize=11, color=INK)
    ax.grid(axis="y", color=GRID); ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(GRID)
    ax.tick_params(length=0, colors=INK2)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)


def make_all(out, frames, caps, model, p_old, p_new, p_exist, summary, cfg):
    for f, c in zip(frames, caps):
        imwrite(out / "images" / f"{f.short}.png",
                compare(f, c, model, p_old, p_new, p_exist, f"Capture {f.short}",
                        summary["verdict"]))
        flicker(f, model, p_exist, p_new, out / "images" / f"{f.short}_flicker.gif")
    shift_chart(summary, cfg, out / "images" / "shift_by_range.png")
