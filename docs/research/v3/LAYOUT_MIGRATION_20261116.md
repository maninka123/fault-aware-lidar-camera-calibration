# Repository layout migration (16 November 2026)

App code now lives under `app/`; engine, research configuration, dataset manifests, tests and historical outputs are grouped under `research/`.

The original `FROZEN_GENERALIZATION.json` and its historical protocol are preserved. They identify the earlier source layout and published development results.

`FROZEN_LAYOUT_20261116.json` records the relocated sources for subsequent runs, with the original freeze's hash as provenance. Numerical constants are required to match the historical freeze. Path changes do not constitute a new evaluation or validate earlier findings on new software. No experiments or reported scores were rerun or changed during this migration.
