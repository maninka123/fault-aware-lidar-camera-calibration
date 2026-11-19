# UNSW project sync

The personal repository is the source of truth. Each push to `main` automatically updates `fault-aware-lidar-camera-calibration/` in [UNSW AMT-project](https://github.com/unsw-edu-au/AMT-project). Feature branches sync after merging into `main`. You can also run **Actions > Sync fault-aware-lidar-camera-calibration to UNSW** manually.

The workflow copies committed tracked files, preserves exact Git bytes and executable permissions, and transfers referenced Git LFS objects. It updates only this project folder and its entry in `PROJECT_SOURCES.json`. Concurrent collection updates are retried in fresh temporary checkouts without force-pushing or replacing sibling projects. A dedicated write-enabled deploy key for AMT-project is stored as the encrypted `AMT_PROJECT_DEPLOY_KEY` Actions secret in this repository.

## Your existing working folder on another computer

Keep using your existing checkout of `https://github.com/maninka123/fault-aware-lidar-camera-calibration.git`. Run `git remote -v` to confirm its origin. Before new work, run `git pull --ff-only origin main` on a clean `main` branch. Commit and push your changes with `git push origin main`; GitHub Actions then updates UNSW automatically. Uncommitted files and unpushed commits stay on that computer. Other clones receive remote changes when you pull them.

This is a one-way mirror from personal `main` to UNSW. Make changes in the personal repository; edits directly in the UNSW project folder are replaced by subsequent sync. Failed runs remain visible in Actions and can be rerun. GitHub Actions does not modify local files on your computers.
