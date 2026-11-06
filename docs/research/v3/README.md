# Fault Diagnostics V3 research

V3 is an offline experimental sidecar. Production assessment and V2 remain executable. Start with [baseline audit](BASELINE_AUDIT.md), [method](MATHEMATICAL_METHOD.md), [protocol](PREREGISTRATION_V3.md), [literature](LITERATURE_REVIEW.md) and [readiness](RESEARCH_READINESS.md). Actual experiments are reported in [experimental results](EXPERIMENTAL_RESULTS.md).

From the repository root:

```powershell
python -B -m research_calibration diagnose-v3 --dataset october_device_one --output research_artifacts/my_new_v3_run
python -B -m research_calibration diagnose-v3 --dataset october_device_one --signature-config research_configs/fault_diagnostics_v3.json --output research_artifacts/my_configured_v3_run
python -B -m research_calibration diagnose-v3 --calibration current.json --captures paired_data --output research_artifacts/my_explicit_v3_run
python -B tools/evaluate_fault_diagnostics_v3.py --datasets october_device_one enclosure_off_ten --replicates 1 --output research_artifacts/my_matched_development_run
python -B tools/evaluate_signature_geometry_v3.py --output research_artifacts/my_known_correspondence_run
python -B tools/evaluate_active_selection_v3.py --output research_artifacts/my_selection_run
python -B tools/verify_research.py --output research_artifacts/my_verification_run
```

Use a new output folder each time. `fault_diagnostics_v3.json` contains the V3 decision, unchanged V2/production comparison, geometry diagnostics, ambiguity, proposed observations and validation status. `baseline/` preserves the original assessment and V2 files. The V3 package exports `diagnose_v3`, `diagnose_from_records`, `infer_signatures` and `SignatureConfig`. The recorded runner uses the existing data loader and selective optimizer; the exact-correspondence API is a distinct mathematical-verification path.

The shared-fit evaluation is diagnosis-only. It does not fit and independently validate a V3 update, so zero reported updates there cannot establish safe useful acceptance. The full `diagnose_v3` API has a separate candidate/outer-validation contract. Hardware writes are never authorized by V3.

All existing recordings, including V2's historical held-out recordings, are V3 development data. Numerical oracle-correspondence success does not establish automatic edge-matching performance or physical accuracy. The prior-art review does not certify novelty. See the [simulator export contract](SIMULATOR_INTEGRATION.md) for independent validation inputs.

| Implemented decision | Meaning |
|---|---|
| `KEEP_CONFIRMED` | No replicated candidate gain and the current reference beats the existing negative controls on informative comparison captures; conditional on these cues, not a physical correctness certificate. |
| `DRIFT_SUPPORTED` | Held-out evidence supports one minimal explanation, the baseline attribution gate supports it, and the geometric effect check retains the same explanation. No update follows automatically. |
| `DRIFT_AMBIGUOUS` | Replicated degradation evidence exists, but fault explanations or their directional support remain unresolved. A singleton ambiguity list can still lack attribution support. |
| `REFERENCE_NOT_CONFIRMED` | Some evidence is informative, but no supported candidate or reference confirmation exists; the local initialization may be inadequate. |
| `NUISANCE_SUSPECTED` | An apparent production-loss improvement lacks replicated corrected cue support. Timing or other specific nuisance causes are not thereby identified. |
| `INSUFFICIENT_EVIDENCE` | Too few comparison/informative captures support the declared decision. Missing geometric support after detection instead preserves `DRIFT_AMBIGUOUS`. |
| `UPDATE_CANDIDATE_VALIDATED` | A uniquely diagnosed, selectively fitted offline candidate passes directional support, conditional uncertainty and disjoint reserved evidence checks. Hardware writing remains unauthorized. |

Data requests are returned in `recommended_observations`; they do not relabel an unresolved detected change as no change. Compatible nested models remain reported alongside minimal explanations. For the recorded default, geometric analysis is a veto/explanation layer, because experiments did not support promoting conditional local separability into unique physical attribution.


## Improved V3: correspondence study

Start with [ROOT_CAUSE_ANALYSIS.md](ROOT_CAUSE_ANALYSIS.md) and [PROTOCOL_CORRESPONDENCE.md](PROTOCOL_CORRESPONDENCE.md). New code: `correspondence.py` (pairing with responsibility, visibility, balancing) and `joint_estimation.py`
(alternating estimation, a documented negative result, plus `diagnose_pairs`). Tools: `tools/analyze_attribution_root_cause_v3.py`, `tools/evaluate_pairing_v3.py`, `tools/run_research_tests.py` (one process per test module; use it
instead of a single `unittest discover` run in a clean checkout, see IMPLEMENTATION_LOG.md item 17). The summary of what this achieved is in [RESEARCH_READINESS.md](RESEARCH_READINESS.md): safer pairing and a measured explanation of
why recorded attribution fails; exact recorded attribution is not solved.

## Generalization audit

[GENERALIZATION_AUDIT.md](GENERALIZATION_AUDIT.md) reports the dataset audit, leakage-free grouped framework, frozen protocol ([PROTOCOL_GENERALIZATION.md](PROTOCOL_GENERALIZATION.md)), per-group results for all methods and the datasets still needed. Conclusion: generalization is **not established**. A pipeline for genuinely new data is `tools/unseen_pipeline_v3.py`.
