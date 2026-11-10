"""Evaluation of supplied calibrations/decisions only. No calibration inference algorithm."""
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from .camera import Camera
from .geometry import apply, validate_transform
from .io import capture_dir, json_read


def change_from_nominal(T_nominal, camera_nominal, T, camera):
    """How far a true calibration (mount + intrinsics) sits from the nominal one. Ground truth only.

    Rotation/translation are of the LiDAR->camera transform; focal changes are in percent, principal point in pixels,
    k1 as an absolute difference. Used to record the simulated drift next to every batch.
    """
    Tn, Tt = validate_transform(T_nominal), validate_transform(T)
    cn = camera_nominal if isinstance(camera_nominal, Camera) else Camera.from_dict(camera_nominal)
    ct = camera if isinstance(camera, Camera) else Camera.from_dict(camera)
    return dict(rotation_deg=float(np.rad2deg(Rotation.from_matrix(Tt[:3, :3] @ Tn[:3, :3].T).magnitude())),
                translation_mm=float(np.linalg.norm(Tt[:3, 3]-Tn[:3, 3])*1000),
                fx_percent=float((ct.K[0, 0]/cn.K[0, 0]-1)*100), fy_percent=float((ct.K[1, 1]/cn.K[1, 1]-1)*100),
                cx_px=float(ct.K[0, 2]-cn.K[0, 2]), cy_px=float(ct.K[1, 2]-cn.K[1, 2]),
                k1=float(ct.D[0]-cn.D[0]) if ct.D.shape == cn.D.shape else None)


def calibration_errors(estimated, truth, points=None):
    T = validate_transform(estimated["extrinsics"]["transform_lidar_to_camera"])
    G = validate_transform(truth["T_CL"])
    a = estimated["intrinsics"]
    model = a.get("model", a.get("distortion_model", ""))
    model = "fisheye" if model in ("fisheye", "opencv_fisheye", "k1-k2", "k1") else model
    if model in ("plumb_bob",):
        model = "pinhole"
    ref = Camera.from_dict(truth["camera"])
    camera = Camera(model, ref.width, ref.height, a["camera_matrix"], a["distortion_coefficients"])
    out = dict(rotation_error_deg=float(np.rad2deg(Rotation.from_matrix(T[:3, :3] @ G[:3, :3].T).magnitude())),
               translation_error_m=float(np.linalg.norm(T[:3, 3]-G[:3, 3])),
               focal_error_px=(np.diag(camera.K)[:2]-np.diag(ref.K)[:2]).tolist(),
               principal_point_error_px=(camera.K[:2, 2]-ref.K[:2, 2]).tolist(),
               distortion_error=(camera.D-ref.D).tolist() if camera.D.shape == ref.D.shape else None,
               camera_model_matches=camera.model == ref.model)
    if points is not None:
        u, avalid = camera.project(apply(T, points))
        v, bvalid = ref.project(apply(G, points))
        common = avalid & bvalid
        out["common_projection_points"] = int(common.sum())
        out["reprojection_rmse_px"] = float(np.sqrt(np.mean(np.sum((u[common]-v[common])**2, axis=1)))) if common.any() else None
    return out


def evaluate(run, estimates_path):
    """JSON records: capture_id, calibration, optional detected/update_accepted booleans."""
    run = Path(run)
    truth = {x["capture_id"]: x for x in json_read(run/"evaluation"/"ground_truth.json")}
    estimates = json_read(estimates_path)
    if not isinstance(estimates, list):
        raise ValueError("Estimates must be a list of {capture_id,calibration,...} records")
    rows = []
    seen = set()
    for item in estimates:
        cid = item["capture_id"]
        if cid in seen or cid not in truth:
            raise ValueError("Duplicate or unknown estimate capture_id: "+cid)
        seen.add(cid)
        gt = truth[cid]
        with np.load(capture_dir(run, "evaluation", cid)/"ideal_lidar.npz", allow_pickle=False) as f:
            metrics = calibration_errors(item["calibration"], gt, f["xyz"])
        rows.append(dict(capture_id=cid, timestamp=gt["timestamp"], physical_fault=bool(gt["physical_fault"]),
                         detected=item.get("detected"), update_accepted=item.get("update_accepted"), **metrics))
    classified = [x for x in rows if isinstance(x["detected"], bool)]
    for item in estimates:
        for field in ("detected", "update_accepted"):
            if field in item and not isinstance(item[field], bool):
                raise ValueError(field+" must be boolean when supplied")
    stable = [x for x in classified if not x["physical_fault"]]
    fault = [x for x in classified if x["physical_fault"]]
    delays = []
    events = json_read(run/"evaluation"/"events.json")
    for i, event in enumerate(events):
        if not event["fault"]:
            continue
        end = events[i+1]["time"] if i+1 < len(events) else np.inf
        detected = [x["timestamp"] for x in classified if event["time"] <= x["timestamp"] < end and x["detected"]]
        delays.append(dict(change_timestamp=event["time"], detection_delay_s=min(detected)-event["time"] if detected else None))
    return dict(captures=rows, evaluated_captures=len(rows), total_captures=len(truth),
                false_alarm_rate=sum(x["detected"] for x in stable)/len(stable) if stable else None,
                fault_detection_rate=sum(x["detected"] for x in fault)/len(fault) if fault else None,
                stable_accepted_updates=sum(x["update_accepted"] is True for x in rows if not x["physical_fault"]),
                detection_delays=delays,
                limitations="Supplied decisions only; no optimizer convergence or uncertainty metric is inferred")
