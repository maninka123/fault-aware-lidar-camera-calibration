"""Experimental fault diagnostics (v2). Kept separate from the production decision policy.

Modules
    cues            decoy-referenced (chance-corrected) cross-modal evidence: oriented edges and intensity NID
    evidence        per-fold counterfactual evidence for every fitted hypothesis, with an explicit
                    chance-alignment (nuisance) counterfactual
    policy          experimental accept / reject / abstain rules over that evidence
    sequential      persistence monitoring of timestamped captures (temporary vs persistent change)
    perturbations   known calibration perturbations and sensor nuisances for verification only
    runner          runs the unchanged production assessment and adds the experimental diagnostics

Nothing here alters a production result, threshold or file written by ``assess``.
"""
from .config import DiagnosticsConfig

__all__ = ['DiagnosticsConfig']
