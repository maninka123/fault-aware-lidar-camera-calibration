"""Declared constants of the experimental diagnostics.

These values were fixed on the development recordings (creep_three, enclosure_off_ten) and recorded in
docs/research/PREREGISTRATION_V2.md before any held-out recording was evaluated. Changing one after seeing
held-out results invalidates that evaluation.
"""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class DiagnosticsConfig:
    # Decoy (chance) reference: the same capture with the image displaced by fixed offsets.
    decoy_radius_px: float = 8.
    decoy_count: int = 8
    # Oriented edge agreement (same definitions as the maintenance lift measure).
    edge_gate_px: float = 1.5
    edge_orientation_deg: float = 15.
    # Intensity cue: normalised information distance between LiDAR reflectivity and image intensity.
    intensity_points: int = 20000
    intensity_bins: int = 32
    intensity_min_points: int = 1000
    # A capture is informative for a cue when some evaluated calibration beats its decoys by this margin.
    edge_informative_contrast: float = .02
    intensity_informative_contrast: float = .003
    # The current calibration is confirmed by a cue when its median contrast reaches the same margin and
    # at least `consistency` of the informative captures beat their decoys.
    consistency: float = 2/3
    # A candidate's per-capture change counts as a gain / loss beyond these margins.
    edge_gain_margin: float = .01
    intensity_gain_margin: float = .0005
    # Edge margin when the intensity cue is uninformative for the recording. A doubled margin (.02) was tried in
    # development and removed: it cut detection on enclosure_off_ten from 8/15 to 1/15 without any false alarm
    # to prevent there (see VERIFICATION_RESULTS.md, development round 3).
    single_cue_edge_margin: float = .01
    min_informative_captures: int = 3
    # Production loss threshold re-used for the "apparent improvement" test (not re-tuned).
    production_min_relative_gain: float = .01
    # Sequential persistence monitor (dimensionless robust scores).
    monitor_reference_window: int = 4
    monitor_drift_allowance: float = .5
    monitor_threshold: float = 4.
    # Each capture's score is clipped below the threshold, so one capture alone can never raise an alarm
    # (at least ceil(threshold / (clip - allowance)) degraded captures are needed).
    monitor_score_clip: float = 2.
    # Robust spread floor as a fraction of the reference median (the window is only a few captures).
    monitor_scale_floor: float = .25
    monitor_alpha: float = .05

    def __post_init__(self):
        values = list(asdict(self).values())
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError('Diagnostics constants must be finite numbers')
        if self.decoy_count < 4 or self.decoy_radius_px <= 2 * self.edge_gate_px:
            raise ValueError('Use at least four decoys displaced well beyond the edge gate')
        if not .5 < self.consistency <= 1 or self.min_informative_captures < 2:
            raise ValueError('Invalid consistency rule')
        if self.monitor_reference_window < 2 or not 0 < self.monitor_alpha < 1:
            raise ValueError('Invalid monitor settings')
        if not self.monitor_drift_allowance < self.monitor_score_clip < self.monitor_threshold:
            raise ValueError('The score clip must lie between the allowance and the threshold')

    def to_dict(self):
        return asdict(self)
