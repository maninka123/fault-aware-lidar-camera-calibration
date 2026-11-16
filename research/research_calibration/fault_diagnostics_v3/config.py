"""Declared dimensionless whitened-RMS tolerances, not calibrated test thresholds.

pixel_sigma is the fallback pixel standard deviation; at its default one pixel,
the normalized RMS tolerances numerically coincide with pixels. A supplied
covariance defines its own whitening metric and does not change these tolerances.
"""
from dataclasses import dataclass, asdict
import math


@dataclass(frozen=True)
class SignatureConfig:
    pixel_sigma: float = 1.0
    separation_rms: float = .35
    detection_rms: float = .25
    rank_rtol: float = 1e-7
    min_rows: int = 30
    min_captures: int = 4
    association_gate_px: float = 6.
    max_rows_per_capture: int = 400
    geometric_signatures: bool = True
    scene_quality: bool = True
    chance_correction: bool = True

    def __post_init__(self):
        for key in ('pixel_sigma', 'separation_rms', 'detection_rms', 'rank_rtol', 'association_gate_px'):
            if not math.isfinite(getattr(self, key)) or getattr(self, key) <= 0:
                raise ValueError(key + ' must be positive and finite')
        for key in ('min_rows', 'min_captures', 'max_rows_per_capture'):
            if type(getattr(self, key)) is not int or getattr(self, key) < 2:
                raise ValueError(key + ' must be an integer >= 2')
        if any(type(getattr(self, key)) is not bool for key in ('geometric_signatures', 'scene_quality', 'chance_correction')):
            raise ValueError('Ablation switches must be boolean')

    def to_dict(self):
        return asdict(self)
