# Fault-aware camera–LiDAR calibration research

An offline backend that compares constrained parameter changes, checks measurement support and retains the reference when evidence is insufficient. It reuses this repository's input readers, edge extractors and targetless geometry.

**Current outcome:** verified numerical/backend prototype. Recorded tests do not establish a new physical-fault classifier, calibrated confidence or an A* contribution. See [results](docs/research/VERIFICATION_RESULTS.md) and [novelty assessment](docs/research/NOVELTY_ASSESSMENT.md).

The original `Calibration maintenance` project outside this checkout remains separate. This checkout is on `research/fault-aware-calibration`, based on `d0931889bf2f2a5ecb2cca9dd3c8a77c9fa8c763`. No commits were pushed and no device calibration was applied.

## Run from this folder

Use the existing Python 3.10/3.11 environment with the repository requirements. No system-wide dependency upgrade is needed for the verified environment. All commands below use new output directories.

```powershell
# Sequential legacy regression and research numerical tests
python -B verify_research.py

# Hash-check the accessible local recordings and assess the current calibration
python -B -m research_calibration assess --dataset creep_three --output research_artifacts/my_check

# Five methods on identical recorded evaluation partitions
python -B -m research_calibration benchmark --dataset enclosure_off_ten --output research_artifacts/my_comparison

# Explicit inputs, independently of the desktop app
python -B -m research_calibration assess --calibration "current.json" --captures "my_captures" --output research_artifacts/my_data
```

`research_data/manifest.json` references existing recordings; it does not distribute them. For another machine, supply explicit paths or update a local manifest and hashes. Supported input layouts are described in [DATA_FORMAT.md](docs/DATA_FORMAT.md). The research camera adapter currently implements the existing OpenCV equidistant projection, preserving fixed higher distortion terms. Other camera projection models require an adapter and separate verification.

## Python interface

```python
from research_calibration import assess
from research_calibration.config import ResearchConfig

result = assess(
    calibration="current.json",
    captures="my_captures",
    strategy="fault_aware",
    output="research_artifacts/python_check",
    config=ResearchConfig(),
)
print(result.status, result.recommended_action)
print(result.updated_calibration)
```

Outputs are `assessment.json`, `report.md` and `updated_calibration.json`. A rejected update retains the exact input calibration and reports zero accepted parameter updates. Proposed values remain under `diagnostics.candidate_calibration` and `candidate_parameter_updates`. Supported combinations and null directions are reported separately. Candidate exports separate historical reference scores from current evidence.

`KEEP_CURRENT` means the configured evidence policy does not support an update; it does not prove the reference physically correct. `INSUFFICIENT_EVIDENCE` covers failed fits, ambiguous explanations or unavailable independent validation. `UPDATE_SUPPORTED` remains a recommendation to review an offline candidate.

## Modes and ablations

| Strategy | Purpose |
|---|---|
| `fault_aware` | Stable conditional support, directional attribution and training-only contrast selection |
| `joint` | Unconditional joint candidate, with KEEP comparator and the shared evaluation policy |
| `no_observability` | Remove reduced support and attribution gating; retain constrained hypothesis comparisons |
| `no_selection` | Fit all training captures |
| `single_variant` | Conditional support with one association gate; the conditional-only ablation |
| `legacy_optimizer` | Frozen legacy refine routine inside the common new input/evaluation protocol |
| `legacy` | Original cloned maintenance workflow, its own outputs and validation semantics |

```powershell
python -B -m research_calibration benchmark --dataset enclosure_off_ten --methods single_variant --output research_artifacts/single_gate
python -B -m research_calibration benchmark --dataset enclosure_off_ten --methods fault_aware --config research_configs/random_selection.json --output research_artifacts/random
```

`research_configs/` also supplies feature-count, D-proxy and E-proxy selection. All compared test partitions stay fixed by seed. Selection budgets and configurations are recorded; changing them after seeing outer results invalidates a claim that those results remain untouched.

## Existing desktop and initialization

Start this checkout's `start_app.bat`. In **Manual check**, choose a calibration and at least two stacked captures, then click **Research check…**. Its small progress window runs the same CLI and opens the reports folder on request. It has no accept/device-write control and refuses to start while a normal app check is running. The existing **Check calibration** path remains available. Research desktop entry currently enables only stacked captures; other supported readers are accessible through the API/CLI.

```powershell
# Optional offscreen real-recording test of desktop -> CLI execution
python -B verify_desktop_bridge.py

# Original maintenance pipeline in the isolated clone
python -B -m research_calibration assess --dataset creep_three --strategy legacy --output research_artifacts/original_workflow
```

`calibrate_from_scratch(captures=..., output=...)` and CLI `initialize` preserve the inherited targetless coarse initializer, then produce an initial-candidate assessment. It requires stacked NPZ inputs and cannot diagnose a historical fault without a reference. The complete three-capture route finished in about 189 seconds under the watchdog; accuracy remains unvalidated. Use `python -B verify_initialization.py --output research_artifacts/my_initial_run` for the guarded route. Inherited automatic mounting assumes a camera looking along LiDAR +x and tries four rolls.

## Resource use and interpretation

Runs are sequential, with one numerical/OpenCV thread. Windows memory checks stop at stage boundaries below 4 GiB available memory or above 2 GiB Python usage. These are soft checks and cannot guarantee protection from an underlying Windows/driver fault. No drivers, services, Windows settings or live devices are changed.

Reported error is capped nearest-image-edge distance on fixed test support, not known-correspondence reprojection RMSE. Projection movement is a different quantity. Same-session static recordings do not supply independent ground-truth fault labels or calibrated uncertainty.

## Research documents

- [Final technical report](docs/research/FINAL_TECHNICAL_REPORT.md)
- [Source and data audit](docs/research/CURRENT_SYSTEM_AUDIT.md)
- [Paper-to-algorithm comparison](docs/research/PAPER_TO_ALGORITHM.md) and [prior-art review](docs/research/PRIOR_ART_REVIEW.md)
- [Implemented equations and decision policy](docs/research/MATHEMATICAL_METHOD.md)
- [Verification and recorded results](docs/research/VERIFICATION_RESULTS.md)
- [Originality and remaining experiments](docs/research/NOVELTY_ASSESSMENT.md)
- [Implementation log](docs/research/IMPLEMENTATION_LOG.md)
