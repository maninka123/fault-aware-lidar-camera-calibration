# Repository layout

## Folders

| Folder / file | What it holds |
| --- | --- |
| `start_research_gui.bat` | Start the desktop app (fault-aware assessment) |
| `start_app.bat` | Start the original calibration maintenance app |
| `gui/` | The desktop app (see below) |
| `research_calibration/` | The assessment engine: observability, hypotheses, decision policy, reporting |
| `Calibration maintenance/` | The maintenance analysis and app, reused by the Calibration review tab and the Devices page |
| `Targetless calibration/` | Edge extraction and the targetless initializer, read by both apps |
| `research_tests/` | Tests for the engine and the app |
| `tools/` | Verification, ablation, report-building and screenshot scripts |
| `docs/` | Guides, method, results, data formats and the research report |
| `research_configs/`, `research_data/` | Settings and dataset manifests (recordings are not distributed) |
| `examples/` | A sample calibration |
| `multi_capture_calibration/` | Multi-capture helpers used by the engine |
| `research_artifacts/` | Your checks. Created on first use; not committed |

## The desktop app (`gui/`)

| Module | Role |
| --- | --- |
| `research_gui.py` | The main window: New check, tabs, history, running a check |
| `processing_view.py` | The Processing tab: stage timeline, live results, the maintenance comparison stage |
| `result_visuals.py` | The Result figures: decision checklist, image overlay, explanation chart, observability |
| `calibration_review.py`, `review_adapter.py` | The Calibration review tab and its link to the maintenance backend |
| `report_view.py` | The Report tab and its PDF export |
| `use_result.py` | Accept, write to a device, restore, check again |
| `matrix_view.py`, `settings_store.py` | Matrices shown on load; what the app remembers |
| `app_icon.py`, `assets/`, `version.py` | Icon, drawn in code, and the version number |

The maintenance dialogs and widgets that the app reuses live in `Calibration maintenance/code/`, so there is one
implementation of each.

## What a saved check contains

```text
research_artifacts/
  <check>.gui.json            what the check was started with (calibration, captures, options)
  <check>/
    assessment.json           the full result: verdict, comparisons, observability, changes
    report.md                 the raw written report
    updated_calibration.json  the calibration after the check (the input one when nothing changed)
    progress.jsonl            progress events written while it ran
    inputs/                   decoded and stacked captures
    review/                   the maintenance comparison (when it was run), saved here
      link.json, history.csv
      run/                    its results: summary.json, images, refined calibration, report
    use/                      accepted.json, device_writes.json and device backups (when used)
```

The maintenance comparison runs in a short scratch folder under `%LOCALAPPDATA%\FaultAwareReview` (Windows rejects paths over
260 characters) and only the finished results are copied into `review/`.

## Tests and tools

`python -B tools/verify_research.py` runs both test suites (`Calibration maintenance/code/tests` and `research_tests`).
`tools/make_screenshots.py` regenerates the images in `docs/images/app/` from a saved check.
