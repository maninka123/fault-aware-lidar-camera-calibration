# External workspace layout migration (17 November 2026)

Earlier workspace projects now live under `reference_projects/`. Raw `data/` and shared `results/` remain at the workspace root. The app repository stays in its original location.

`manifest.json`, `groups_v3.json` and the dataset audit use `../../reference_projects` as their base; references to shared results use `../results/`. The development anchor lookup follows that base. Dataset contents, recorded hashes, group roles, algorithm settings and numerical constants are unchanged.

`FROZEN_LAYOUT_20261117.json` preserves the preceding freeze's hash and updates only the anchor lookup source hash. Both earlier freezes remain intact. This administrative migration does not create new scientific results. Historical reports retain the paths recorded when they were generated.
