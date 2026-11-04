"""Calibration maintenance: check an existing camera + LiDAR calibration on new captures, refine it,
and decide whether the change is real and worth an update.

  1. data      stacked captures (*.npz), or raw captures (capture_*/rig_0.bag) decoded first
               (target-free still window);
  2. health    the existing calibration on the new data: share of LiDAR edges that land on an image
               edge, median edge residual (only the LiDAR beam-widening nuisance angle is fitted);
  3. refine    edge alignment started FROM the existing calibration: R, t (mode "extrinsic") or also
               the intrinsics (mode "full", principal point held near the existing value);
  4. change    parameter changes and, what matters, how far projected LiDAR points move (px);
  5. evidence  leave one capture out: refine on the others, compare existing vs refined on the
               capture left out (does the refinement generalise?); the spread of these runs gives the
               uncertainty (jackknife) of every change;
  6. verdict   no update needed / borderline / update recommended / large change / inconclusive;
  7. outputs   results/<run>/: summary.json, report.md, refined_calibration.json (a candidate - the
               existing calibration is never overwritten), images, and a line in results/history.csv.

Usage:  python maintain.py --calibration <existing calibration.json> --data <folder> --name <run>
                           [--mode compare|extrinsic|intrinsic|full] [--device <label>]
"""
from __future__ import annotations

import argparse
import copy
import csv
import shutil
from datetime import datetime
from pathlib import Path

from settings import (Calibration, load_calibration, load_config, load_stacked, log, results_dir,  # noqa: I001
                      write_json)

import numpy as np  # noqa: E402
from scipy.spatial.transform import Rotation  # noqa: E402

import calib as cb  # noqa: E402  (Targetless calibration, read-only)
import image_edges as ie  # noqa: E402
import lidar_edges as le  # noqa: E402
import update_options

BANDS = ((1.5, 3.0), (3.0, 5.0), (5.0, 10.0))
FIELD_ANGLE = np.radians(35.0)


# ------------------------------------------------------------------ data
def get_frames(data, out, cfg):
    """Stacked captures from a folder of *.npz, or decoded from capture_*/rig_0.bag."""
    data = Path(data)
    bags = sorted(p for p in data.glob("capture_*") if (p / "rig_0.bag").exists())
    if not bags:
        frames = load_stacked(data)
        if not frames:
            raise SystemExit(f"no stacked captures (*.npz) or raw captures (capture_*/rig_0.bag) in {data}")
        log(f"data: {len(frames)} stacked captures from {data}")
        return frames, None
    import decode_bags  # Targetless calibration, read-only
    dcfg = copy.deepcopy(cfg)
    dcfg["stacked_dir"] = str(out / "stacked")      # absolute paths: outputs land in this run's folder
    dcfg["output_dir"] = str(out / "decode")
    rows, circle = [], None
    for b in bags:
        row, circle = decode_bags.decode_capture(b, "data", dcfg, circle)
        rows.append(row)
        log(f"decoded {row['capture']}: still window {row['window_s']:.1f} s, {row['images_stacked']} images, "
            f"{row['lidar_frames_stacked']} LiDAR frames")
    return load_stacked(out / "stacked" / "data"), rows


def params_of(cal: Calibration, R0):
    p = np.zeros(13)
    p[:3] = Rotation.from_matrix(cal.T[:3, :3] @ R0.T).as_rotvec()
    p[3:6] = cal.T[:3, 3]
    p[6:10] = cal.K[0, 0], cal.K[1, 1], cal.K[0, 2], cal.K[1, 2]
    p[10:12] = cal.D[:2]
    return p


# ------------------------------------------------------------------ measures
def alignment(caps, model, p, cfg, gate=2.0):
    """Share of LiDAR edge points (in view) on a parallel image edge within `gate` px, their median
    residual, and the edge-alignment lift (vs chance)."""
    cc = cfg["calib"]
    cos_min = np.cos(np.radians(cc["orientation_max_deg"]))
    tw = np.array([cc["weights"][t] for t in cb.TYPES])
    corr = cb.associate(caps, model, p, gate, cos_min, tw)
    n_match = sum(len(a["i"]) for a in corr)
    n_view = 0
    for c in caps:
        _, _, ok = model.project(model.to_camera(c.xyz, c.sgn, p), p)
        n_view += int(ok.sum())
    X, S, T, Q, N, W = cb._stack(caps, corr)
    r = cb.edge_residuals(model, p, X, S, Q, N) if len(X) else np.array([np.inf])
    s = cfg["calib"]["selection"]
    return dict(on_edge_share=n_match / max(n_view, 1), matches=n_match, median_residual_px=float(np.nanmedian(np.abs(r))),
                lift=cb.lift(caps, model, p, s["gate_px"], s["orientation_deg"], s["shift_px"])[0])


def shift_px(model, p_a, p_b, pts):
    """Pixel distance between where two calibrations put the same LiDAR points."""
    z = np.zeros(len(pts))
    ua, va, oka = model.project(model.to_camera(pts, z, p_a), p_a)
    ub, vb, okb = model.project(model.to_camera(pts, z, p_b), p_b)
    ok = oka & okb
    return np.hypot(ua - ub, va - vb), ok


def jackknife(values):
    v = np.asarray(values, float)
    n = len(v)
    return float(np.sqrt((n - 1) / n * np.sum((v - v.mean()) ** 2))) if n > 2 else float("nan")


def word_stat(z):
    return "–" if not np.isfinite(z) else "within noise" if z < 2 else "borderline" if z < 3 else "significant"


def word_px(px):
    return "negligible" if px < 1 else "small" if px < 3 else "large"


# ------------------------------------------------------------------ verdict
def decide(dc, shift, z, improved, n_loo, new, old):
    """n_loo / improved: left-out image regions, and how many of them the refinement fits better."""
    """The update decision and the reason for it."""
    if old["lift"] < dc["min_lift"] <= new["lift"] and shift >= dc["negligible_px"]:
        return ("LARGE CHANGE", f"the existing calibration no longer lines up with the scene (edge alignment {old['lift']:.2f} x "
                f"chance) and the refinement moves points by {shift:.1f} px - the mounting has probably shifted; check the "
                "hardware, then review the candidate or recalibrate from scratch")
    if new["matches"] < dc["min_matches"] or new["lift"] < dc["min_lift"]:
        return ("INCONCLUSIVE", "the new captures do not show enough scene structure to judge the calibration "
                f"({new['matches']} edge matches, lift {new['lift']:.2f}); capture a scene with edges at several depths")
    frac = improved / n_loo if n_loo else float("nan")
    gen = f"; the refinement fits {improved} of {n_loo} image regions it was not fitted on better" if n_loo else ""
    if shift < dc["negligible_px"]:
        return ("NO UPDATE NEEDED", f"the refined calibration moves points by only {shift:.2f} px (median) - within the "
                f"error margin of the method{gen}")
    if shift > dc["large_px"] and (not np.isfinite(z) or z >= dc["significant_z"]):
        return ("LARGE CHANGE", f"points move by {shift:.1f} px - the mounting has probably shifted; check the hardware "
                "and recalibrate from scratch")
    if np.isfinite(z) and z >= dc["significant_z"] and (not n_loo or frac >= dc["heldout_majority"]):
        return ("UPDATE RECOMMENDED", f"points move by {shift:.2f} px, {z:.1f} times the uncertainty (statistically "
                f"significant){gen}")
    if (np.isfinite(z) and z >= dc["borderline_z"]) or (n_loo and frac >= 0.5):
        return ("BORDERLINE", f"points move by {shift:.2f} px, {z:.1f} times the uncertainty{gen}; keep the existing "
                "calibration, collect more captures and check again")
    return ("NO UPDATE NEEDED", f"points move by {shift:.2f} px but this is not statistically supported "
            f"({z:.1f} times the uncertainty{gen})")


# ------------------------------------------------------------------ main
KEEP = ("run.log", "inputs.json", "progress.json", "captures", "from_scratch")     # + device*: the connected-device files


def run(calibration, data, name, mode=None, device=None, starts=()):
    """starts: extra (label, calibration.json) refinement starts, e.g. a calibration from scratch."""
    starts_extra = list(starts)
    calibration, data = str(Path(calibration).resolve()), str(Path(data).resolve())
    cfg = load_config()
    mc = cfg["refine"]
    mode = mode or mc["mode"]
    out = results_dir() / name
    earlier = [s for s in ((read_progress(out) or {}).get("stages") or []) if s.get("stage") == "scratch"]
    for p in (out.iterdir() if out.exists() else ()):   # an earlier run of this name; keep the app's log, inputs and captured data
        if p.name in KEEP or p.name.startswith("device"):
            continue
        try:
            shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
        except OSError:
            pass                                     # OneDrive can hold a file briefly; files are replaced below
    out.mkdir(parents=True, exist_ok=True)
    import figures
    progress = list(earlier)                          # e.g. the from-scratch calibration done before this run

    def stage(key, message, images=(), table=None):
        """Live progress for the app: results/<run>/progress.json (+ images in stages/)."""
        progress.append(dict(stage=key, message=message, images=[str(Path(i).relative_to(out)) for i in images],
                             table=table, time=datetime.now().isoformat(timespec="seconds")))
        write_json(out / "progress.json", dict(run=name, finished=False, stages=progress))

    cal = load_calibration(calibration)
    log(f"existing calibration: {calibration} ({cal.model})")
    stage("start", f"existing calibration {calibration} ({cal.model}); mode: {mode}")
    frames, decode_rows = get_frames(data, out, cfg)
    from common import image_circle  # Targetless common (read-only)
    circle = image_circle(frames)
    st = out / "stages"
    imgs = [figures.save(st / f"data_{f.short}.png", f.image) for f in frames]
    if decode_rows:
        imgs += sorted((out / "decode").rglob("motion_*.png"))
    windows = ", ".join("%.1f s" % r["window_s"] for r in decode_rows or [])
    npts = ", ".join(f"{len(f.xyz):,}" for f in frames)
    stage("data", f"{len(frames)} captures" + (f" decoded from bags (still windows {windows})" if decode_rows else " (stacked)")
          + f"; LiDAR points per capture {npts}", imgs)
    rng = np.random.default_rng(cfg["seed"])
    caps, imgs = [], []
    for f in frames:
        edges, aux = le.extract(f, cfg["lidar"], cfg["seed"])
        ied = ie.extract(f.image, circle, cfg["image"])
        c = cb.from_edges(f.short, edges, ied)
        cb.prepare_nid(c, f, cfg["calib"]["nid"]["points_per_capture"], cfg["calib"]["nid"]["bins"], rng)
        caps.append(c)
        imgs += [figures.save(st / f"lidar_edges_{f.short}.png", figures.lidar_edge_map(edges, aux)),
                 figures.save(st / f"image_edges_{f.short}.png", figures.image_edge_map(f.image, ied))]
    log(f"features: LiDAR edges {[len(c.xyz) for c in caps]}")
    stage("features", "edges detected - LiDAR (its own view; red depth jumps, green plane creases, blue reflectivity) "
          f"and image (sub-pixel Canny): LiDAR edge points per capture {', '.join(str(len(c.xyz)) for c in caps)}, "
          f"image edge pixels {', '.join(str(len(c.img['q'])) for c in caps)}", imgs)
    model = cb.Model(cal.T[:3, :3], frames[0].image.shape[1::-1], circle)
    p_exist = params_of(cal, model.R0)

    rcfg = copy.deepcopy(cfg)
    rcfg["calib"]["gates_px"] = mc["gates_px"]
    rcfg["prior"]["principal_point_sigma_px"] = mc["principal_point_sigma_px"]
    prior_centre = dict(cx=cal.K[0, 2], cy=cal.K[1, 2])       # full mode: principal point held near the existing value
    requested_mode = mode
    free = update_options.free_parameters('full' if mode == 'compare' else mode, cal.model)
    quiet = lambda *a: None

    # 1. health of the existing calibration (only the LiDAR beam-widening nuisance is fitted)
    p_old, _ = cb.refine(caps, model, p_exist, [12], rcfg, prior_centre, log=quiet, gates=[4, 3, 2, 2], passes=2)
    old = alignment(caps, model, p_old, cfg)
    log(f"existing calibration on the new data: {old['on_edge_share'] * 100:.1f} % of LiDAR edges on image edges, "
        f"median residual {old['median_residual_px']:.2f} px, lift {old['lift']:.2f}")
    stage("health", f"existing calibration on the new data: {old['on_edge_share'] * 100:.1f} % of LiDAR edges on image "
          f"edges, median residual {old['median_residual_px']:.2f} px, edge alignment {old['lift']:.2f} x chance",
          [figures.save(st / f"existing_{f.short}.png", figures.alignment(f, c, model, p_old, "Existing calibration"))
           for f, c in zip(frames, caps)])

    # 2. refinement: from the existing calibration and from a local search around it (+-4 deg, starts
    # proposed by edge distance and by NID), so a drift too big for a purely local refinement is still
    # followed; the start whose refinement aligns the edges best (lift) wins.
    starts = [("existing calibration", p_old)]
    for label, path in starts_extra:
        q = params_of(load_calibration(path), model.R0)
        q[12] = p_old[12]
        starts.append((label, q))
    cc = dict(cfg["calib"]["coarse"], per_focal=mc["search_starts"])
    for proposer, _, q in cb.coarse(caps, model, p_old, cc, rng, quiet, fixed_intrinsics=True):
        q = q.copy(); q[7] = p_old[7]; q[12] = p_old[12]            # coarse() sets fy = fx; keep the existing fy
        starts.append((f"search ({proposer})", q))
    strategy_comparison = None
    if mode == 'compare':
        log('Comparing keep current, alignment only, camera settings only, and both on held-out data')
        strategy_comparison = update_options.compare(caps, model, p_exist, cal.model, cfg, rcfg,
                                                     prior_centre, alignment, progress=log)
        mode = strategy_comparison['selected'] or 'extrinsic'
        free = update_options.free_parameters(mode, cal.model)
        stage('options', strategy_comparison['reason'], table=[
            dict(option=update_options.LABELS[key],
                 heldout_alignment=(f'{value * 100:.1f} %' if value is not None else 'Not enough evidence'),
                 selected=key == strategy_comparison['selected'])
            for key, value in strategy_comparison['scores'].items()])
    cands = []
    for label, q in starts:
        q = update_options.constrained_start(q, p_exist, mode)
        pq, iq = cb.refine(caps, model, q, free, rcfg, prior_centre, log=quiet, passes=mc["passes"])
        if not update_options.valid_solution(pq):
            continue
        cands.append(dict(start=label, p=pq, info=iq, lift=alignment(caps, model, pq, cfg)["lift"]))
    if not cands:
        raise ValueError('No valid calibration fit. Collect more captures with edges at different distances.')
    best = max(cands, key=lambda c: c["lift"])
    p_new, info = best["p"], best["info"]
    new = alignment(caps, model, p_new, cfg)
    log(f"refined ({len(cands)} starts, best from {best['start']}): {new['on_edge_share'] * 100:.1f} % on image edges, "
        f"median residual {new['median_residual_px']:.2f} px, lift {new['lift']:.2f}")
    stage("search", f"{len(cands)} refinements: from the existing calibration and from a local search around it "
          "(starts proposed by edge distance and by NID); the best edge alignment wins",
          table=[dict(start=c["start"], edge_alignment_lift=round(c["lift"], 3), chosen=c is best) for c in cands])
    stage("refined", f"refined calibration: {new['on_edge_share'] * 100:.1f} % of LiDAR edges on image edges, median "
          f"residual {new['median_residual_px']:.2f} px, edge alignment {new['lift']:.2f} x chance",
          [figures.save(st / f"refined_{f.short}.png", figures.alignment(f, c, model, p_new, "Refined calibration"))
           for f, c in zip(frames, caps)])

    # 3. how far points move, measured on the scene
    pts = np.concatenate([f.xyz[::15] for f in frames])
    rr = np.linalg.norm(pts, axis=1)
    lo, hi = cfg["decision"]["probe_range_m"]
    probe = pts[(rr >= lo) & (rr <= hi)]
    d, ok = shift_px(model, p_exist, p_new, probe)
    shift = float(np.median(d[ok]))
    pr = np.linalg.norm(probe, axis=1)
    bands = {f"{a:g}-{b:g} m": float(np.median(d[ok & (pr >= a) & (pr < b)])) if (ok & (pr >= a) & (pr < b)).sum() > 50 else None
             for a, b in BANDS}

    # 4. evidence and uncertainty: leave one capture out, and leave one image region out.
    # Captures of a static rig are nearly identical, so the capture spread alone underestimates the
    # uncertainty; leaving out one region of the image at a time shows how much the answer depends on
    # which scene structures are used, and tests the refinement on structures it was not fitted on.
    def refit_and_test(fit_caps, test_caps, label):
        pk, _ = cb.refine(fit_caps, model, p_new, free, rcfg, prior_centre, log=quiet, passes=2)
        ho_old = alignment(test_caps, model, p_old, cfg)
        ho_new = alignment(test_caps, model, pk, cfg)
        dk, okk = shift_px(model, p_exist, pk, probe)
        return dict(left_out=label, p=pk, shift_px=float(np.median(dk[okk])), heldout_matches=max(ho_old["matches"], ho_new["matches"]),
                    heldout_existing_share=ho_old["on_edge_share"], heldout_refined_share=ho_new["on_edge_share"],
                    heldout_existing_residual_px=ho_old["median_residual_px"], heldout_refined_residual_px=ho_new["median_residual_px"],
                    improved=ho_new["on_edge_share"] > ho_old["on_edge_share"])

    loo = [refit_and_test(caps[:k] + caps[k + 1:], [caps[k]], caps[k].name) for k in range(len(caps))] if len(caps) >= 2 else []
    nb = cfg["decision"]["regions"]
    region = []                                  # image region of every LiDAR edge point (existing calibration)
    for c in caps:
        u, v, okc = model.project(model.to_camera(c.xyz, c.sgn, p_old), p_old)
        ang = np.arctan2(v - circle["cy"], u - circle["cx"])
        rad = np.hypot(u - circle["cx"], v - circle["cy"])
        reg = np.where(rad < 0.35 * circle["radius"], nb - 1, np.floor((ang + np.pi) / (2 * np.pi) * (nb - 1)).astype(int) % (nb - 1))
        region.append(np.where(okc, reg, -1))
    sub = lambda c, m: cb.Capture(c.name, c.xyz[m], c.dir[m], c.typ[m], c.sgn[m], c.img)
    blocks = []
    for bi in range(nb):
        keep = [sub(c, (g != bi) & (g >= 0)) for c, g in zip(caps, region)]
        only = [sub(c, g == bi) for c, g in zip(caps, region)]
        if sum(len(c.xyz) for c in only) >= 50:
            blocks.append(refit_and_test(keep, only, f"image region {bi + 1}" + (" (centre)" if bi == nb - 1 else "")))
    blocks = [r for r in blocks if r["heldout_matches"] >= cfg["decision"]["min_region_matches"]]   # regions without structure say nothing
    sd_cap = jackknife([r["shift_px"] for r in loo]) if len(loo) > 2 else float("nan")
    sd_blk = jackknife([r["shift_px"] for r in blocks]) if len(blocks) > 2 else float("nan")
    sd_shift = float(np.nanmax([sd_cap, sd_blk, 1e-9]))
    improved = sum(r["improved"] for r in blocks)
    z = shift / sd_shift
    verdict, reason = decide(cfg["decision"], shift, z, improved, len(blocks), new, old)
    if strategy_comparison:
        if strategy_comparison['status'] == 'inconclusive':
            verdict, reason = 'INCONCLUSIVE', strategy_comparison['reason']
        elif strategy_comparison['status'] == 'keep':
            verdict, reason = 'NO UPDATE NEEDED', strategy_comparison['reason']
        strategy_comparison['recommendation'] = (
            strategy_comparison['reason'] if verdict == 'UPDATE RECOMMENDED' else
            'Check the mounting before updating.' if verdict == 'LARGE CHANGE' else
            'Collect more captures before updating.' if verdict in ('INCONCLUSIVE', 'BORDERLINE') else
            'Keep the current calibration.')
    log(f"shift {shift:.2f} px (uncertainty {sd_shift:.2f} px: captures {sd_cap:.2f}, image regions {sd_blk:.2f}; z {z:.1f}); "
        f"left-out regions fitted better: {improved}/{len(blocks)}, left-out captures: {sum(r['improved'] for r in loo)}/{len(loo)}")
    stage("evidence", f"left out one image region at a time (and one capture at a time): shift {shift:.2f} px, "
          f"uncertainty {sd_shift:.2f} px (z {z:.1f}); the refinement fits {improved} of {len(blocks)} unseen regions better",
          [figures.save(st / "regions.png", figures.regions_map(frames[0], caps[0], model, p_old, region[0], blocks, circle, nb))],
          table=[dict(left_out=r["left_out"], shift_px=round(r["shift_px"], 2),
                      existing=f"{r['heldout_existing_share'] * 100:.1f} %", refined=f"{r['heldout_refined_share'] * 100:.1f} %",
                      better=r["improved"]) for r in loo + blocks])
    log(f"VERDICT: {verdict} - {reason}")

    # 5. parameter changes (uncertainty: the larger of the two leave-one-out spreads)
    Kn, Dn, Tn = model.matrices(p_new)
    f_ = cal.K[0, 0]
    rng_m = cfg["decision"]["report_range_m"]
    dR = Rotation.from_matrix(Tn[:3, :3] @ cal.T[:3, :3].T).as_rotvec()          # in the camera frame
    runs = {"captures": loo, "regions": blocks}
    rot_of = lambda r: Rotation.from_matrix(model.unpack(r["p"])[0] @ cal.T[:3, :3].T).as_rotvec()
    params = []

    def add(name, unit, old_v, new_v, value_of, px_per_unit):
        dv = new_v - old_v
        sds = [jackknife([value_of(r) for r in rs]) for rs in runs.values() if len(rs) > 2]
        sd = float(np.nanmax(sds)) if sds else float("nan")
        zz = abs(dv) / sd if sd and np.isfinite(sd) else float("nan")
        px = abs(dv) * px_per_unit
        params.append(dict(parameter=name, unit=unit, existing=old_v, refined=new_v, change=dv, uncertainty=sd, z=zz,
                           statistical=word_stat(zz), pixel_effect_px=px, practical=word_px(px)))

    for i, ax in enumerate(("tilt (about camera x)", "pan (about camera y)", "roll (about camera z)")) if mode != 'intrinsic' else []:
        add(f"rotation {ax}", "deg", 0.0, np.degrees(dR[i]), lambda r, i=i: np.degrees(rot_of(r)[i]),
            np.radians(1) * f_ * (1 if i < 2 else np.tan(FIELD_ANGLE)))
    for i, ax in enumerate("xyz") if mode != 'intrinsic' else []:
        add(f"translation {ax}", "mm", cal.T[i, 3] * 1000, Tn[i, 3] * 1000, lambda r, i=i: r["p"][3 + i] * 1000,
            f_ / rng_m / 1000 * (1 if i < 2 else np.tan(FIELD_ANGLE)))
    if mode in ('full', 'intrinsic'):
        for i, (n, kk) in enumerate((("fx", (0, 0)), ("fy", (1, 1)), ("cx", (0, 2)), ("cy", (1, 2)))):
            add(n, "px", cal.K[kk], Kn[kk], lambda r, i=i: r["p"][6 + i], FIELD_ANGLE if n in ("fx", "fy") else 1.0)
        add("k1", "", cal.D[0], Dn[0], lambda r: r["p"][10], f_ * FIELD_ANGLE ** 3)
        if cal.model == 'k1-k2':
            add("k2", "", cal.D[1], Dn[1], lambda r: r["p"][11], f_ * FIELD_ANGLE ** 5)

    # 6. outputs
    refined = copy.deepcopy(cal.raw)
    refined["intrinsics"].update(camera_matrix=Kn, distortion_coefficients=np.r_[Dn[:2], 0.0, 0.0] if cal.model == "k1-k2"
                                 else np.r_[Dn[0], 0.0, 0.0, 0.0])
    refined["extrinsics"] = dict(transform_lidar_to_camera=Tn)
    refined["maintenance"] = dict(refined_from=str(calibration), data=str(data), run=name, mode=mode, verdict=verdict,
                                  date=datetime.now().isoformat(timespec="seconds"))
    write_json(out / "refined_calibration.json", refined)
    summary = dict(run=name, device=device or "", date=datetime.now().isoformat(timespec="seconds"), existing=str(calibration),
                   data=str(data), mode=mode, requested_mode=requested_mode, strategy_comparison=strategy_comparison,
                   captures=[c.name for c in caps], verdict=verdict, reason=reason,
                   shift_median_px=shift, shift_p90_px=float(np.percentile(d[ok], 90)), shift_by_range_px=bands,
                   shift_uncertainty_px=sd_shift, uncertainty_captures_px=sd_cap, uncertainty_regions_px=sd_blk,
                   uncertainty_method="jackknife, the larger of leave-one-capture-out and leave-one-image-region-out",
                   z=z, heldout_improved=improved, heldout_total=len(blocks),
                   existing_on_new_data=old, refined_on_new_data=new, beam_widening_deg=float(np.degrees(p_new[12])),
                   parameters=params, leave_one_out=[{k: v for k, v in r.items() if k != "p"} for r in loo],
                   leave_one_region_out=[{k: v for k, v in r.items() if k != "p"} for r in blocks],
                   decode=decode_rows)
    write_json(out / "summary.json", summary)
    figures.make_all(out, frames, caps, model, p_old, p_new, p_exist, summary, cfg)
    write_report(out, summary)
    append_history(summary)
    stage("verdict", f"{verdict}: {reason}", [out / "images" / "shift_by_range.png"])
    write_json(out / "progress.json", dict(run=name, finished=True, verdict=verdict, stages=progress))
    log(f"wrote {out}")
    return summary


def write_report(out, s):
    f = lambda v, n=2: "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{n}f}"
    md = [f"# Calibration maintenance: {s['run']}\n",
          f"**{s['verdict']}**: {s['reason']}.\n",
          f"Existing calibration: `{s['existing']}`  \nNew data: `{s['data']}` ({len(s['captures'])} captures)  \n"
          f"Refined: {update_options.LABELS[s['mode']]}, started from the existing calibration.\n",
          "## How much it changed\n",
          "| | value |", "|---|---:|",
          f"| points move by (median, LiDAR points at 1.5-10 m) | **{f(s['shift_median_px'])} px** |",
          f"| 90 % of points move by less than | {f(s['shift_p90_px'])} px |",
          f"| uncertainty of the median shift ({s['uncertainty_method']}) | {f(s['shift_uncertainty_px'])} px |",
          f"| shift / uncertainty (z) | {f(s['z'], 1)} |",
          f"| image regions fitted better when left out of the refinement | {s['heldout_improved']} of {s['heldout_total']} |"]
    for k, v in s["shift_by_range_px"].items():
        md.append(f"| shift at {k} | {f(v)} px |")
    md += ["", "Rules: < 1 px = within the error margin (no update); significant = shift > 3 × its uncertainty and the "
           "refinement also fits most image regions it was not fitted on better; > 5 px = large change (check the mounting).\n",
           "## Existing vs refined on the new data\n", "| | existing | refined |", "|---|---:|---:|"]
    o, n = s["existing_on_new_data"], s["refined_on_new_data"]
    md += [f"| LiDAR edges on an image edge (≤ 2 px) | {o['on_edge_share'] * 100:.1f} % | {n['on_edge_share'] * 100:.1f} % |",
           f"| median edge residual | {o['median_residual_px']:.2f} px | {n['median_residual_px']:.2f} px |",
           f"| edge-alignment lift (vs chance) | {o['lift']:.2f} | {n['lift']:.2f} |", "",
           "## Parameter changes\n",
           "| parameter | existing | refined | change | uncertainty | statistical | pixel effect | practical |",
           "|---|---:|---:|---:|---:|---|---:|---|"]
    for p in s["parameters"]:
        u = f" {p['unit']}" if p["unit"] else ""
        zt = "" if not np.isfinite(p["z"]) else f" ({p['z']:.1f})"
        md.append(f"| {p['parameter']} | {f(p['existing'], 3)} | {f(p['refined'], 3)} | {p['change']:+.3f}{u} | {f(p['uncertainty'], 3)} | "
                  f"{p['statistical']}{zt} | {f(p['pixel_effect_px'], 1)} px | {p['practical']} |")
    md += ["", "Pixel effect = how far that change alone moves a point (rotation everywhere, translation at 3 m, focal "
           "length at 35° off-axis). Statistical: change / uncertainty, < 2 within noise, 2-3 borderline, > 3 significant.\n",
           "## Leave one out\n", "Each row: refine without that capture / image region, then compare existing and refined "
           "on what was left out (share of LiDAR edges on image edges).\n",
           "| left out | shift (px) | existing on it | refined (without it) on it | better |",
           "|---|---:|---:|---:|---|"]
    for r in s["leave_one_out"] + s["leave_one_region_out"]:
        md.append(f"| {r['left_out']} | {r['shift_px']:.2f} | {r['heldout_existing_share'] * 100:.1f} % | "
                  f"{r['heldout_refined_share'] * 100:.1f} % | {'yes' if r['improved'] else 'no'} |")
    md += ["", "## Files\n", "- `refined_calibration.json`: the candidate (same layout as the existing one). The existing "
           "calibration is not changed; accept the update in the app or with `accept.py`.",
           "- `images/<capture>.png`: existing vs refined (LiDAR edges on image edges), the shift map and zooms; "
           "`images/<capture>_flicker.gif`: the two alternating; `images/shift_by_range.png`."]
    if s.get('strategy_comparison'):
        comparison = s['strategy_comparison']
        md += ['', '## Update options', '', comparison['recommendation'], '',
               '| Option | Held-out alignment |', '|---|---:|']
        md += [f'| {update_options.LABELS[key]} | {value * 100:.1f}% |' if value is not None
               else f'| {update_options.LABELS[key]} | Insufficient evidence |'
               for key, value in comparison['scores'].items()]
        md += ['', f'{comparison["folds"]} paired checks; {comparison["method"]}.', '',
               'Extra freedom needs a consistent gain of at least one percentage point and two standard errors. '
               'This is a decision heuristic, not a confidence interval.', '', comparison['limitation']]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")


def append_history(s):
    path = results_dir() / "history.csv"
    row = dict(date=s["date"], run=s["run"], device=s["device"], verdict=s["verdict"], shift_px=round(s["shift_median_px"], 3),
               uncertainty_px=round(s["shift_uncertainty_px"], 3) if np.isfinite(s["shift_uncertainty_px"]) else "",
               z=round(s["z"], 2) if np.isfinite(s["z"]) else "", heldout=f"{s['heldout_improved']}/{s['heldout_total']}",
               existing=s["existing"], data=s["data"], accepted="")
    rows = []
    if path.exists():
        with path.open(newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r["run"] != s["run"]]
    rows.append(row)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader(); w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--calibration", required=True, help="existing calibration.json")
    ap.add_argument("--data", required=True, help="folder with stacked captures (*.npz) or raw captures (capture_*/rig_0.bag)")
    ap.add_argument("--name", required=True, help="run name (results/<name>/)")
    ap.add_argument("--mode", choices=["extrinsic", "intrinsic", "full", "compare"])
    ap.add_argument("--device", help="device label for the history")
    ap.add_argument("--start", action="append", default=[], help="extra refinement start: another calibration.json (repeatable)")
    a = ap.parse_args()
    run(a.calibration, a.data, a.name, a.mode, a.device, [("calibration from scratch", s) for s in a.start])


def read_progress(out):
    try:
        import json
        return json.loads((Path(out) / "progress.json").read_text())
    except Exception:
        return None


if __name__ == "__main__":
    main()
