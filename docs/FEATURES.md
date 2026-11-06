# Features

This app contains everything the calibration maintenance app does, plus the fault-aware assessment. The table is also
enforced by `research_tests/test_parity.py`: if a control disappears, that test fails.

## From the calibration maintenance app

| Capability | Where it is here |
|---|---|
| Check an existing calibration on saved captures (**Check files**) | **New check** |
| Calibration from a `.json`, a `.txt` export, typed values, or the example | New check, step 1: *Open file…*, *Enter values…*, *Use example values* |
| Captures as raw bags, stacked `.npz` or image + PCD pairs | New check, step 2; *Capture format* explains each layout |
| PCD unit selection and confirmation, matched-pair report | PCD units, the confirmation box and **View pairs** (one dialog shared with the maintenance app) |
| The four update choices with scores, RMSE and shifts | **Calibration review** → Update comparison |
| Calibration quality, shift gauge, parameter table with uncertainty and a 3D pose view | Calibration review → Quality, Parameters |
| Previous vs refined images, side by side or alternating, enlarge | Calibration review → Images |
| Leave-one-capture / region-out evidence | Calibration review → Evidence (click a capture to see its images) |
| Matrices with the changes marked | Calibration review → top of the tab (option / current / difference) |
| Save calibration TXT, save refined JSON, open results folder, show report | Calibration review → Export and review; **Report** tab |
| Follow a run stage by stage | **Processing** tab (with live results, Stop and Replay) |
| History of checks | Sidebar list, with *accepted* and *written to device* marks |
| **Accept** a calibration into the accepted history | Result → **Use the result** |
| **Write** a calibration to a connected device | Result → Use the result (only for checks captured from a device) |
| **Restore** the previous calibration on the device | Result → Use the result |
| **Check again** with the same inputs | Result → Use the result |
| Calibrate from scratch | New check → *What to do* |
| Connect to a device, read its calibration, capture and check | **Devices** (the maintenance page, embedded; read-only until you choose Write) |

## Added by the fault-aware work

Fault-aware assessment with seven methods; held-out comparison of every explanation; observability and
confusability views; the interactive overlay of the LiDAR points on the photo; a decision checklist that states
what could not be validated; live Processing; the review run automatically for new checks; a Stop button, crash
log and path-length check.

## How Accept, Write and Restore are protected

* Nothing happens without a click and a confirmation. If the fault-aware verdict does not support changing the
  calibration, the app says so and asks again, with *No* as the default.
* **Accept** saves a new dated file in `accepted/` (it never replaces a file) and records it in the check. The
  calibration the check started from is never changed.
* **Write** reuses the maintenance app's dialog: review of the change, the exact file diff, a backup on the device
  and a copy in the check, a checksum-verified write, and a separate confirmation before the sensor pipeline restarts.
  Only the `pointcloud_colorizer` calibration keys change; a failed write is not recorded as done.
* **Restore** puts back the file the last write replaced, after showing the difference and asking.
* Write and Restore work only for a check that was captured from a connected device, and only to that device.

**Tested how:** the write and restore dialogs are exercised end to end against an in-memory stand-in for the device
(read, backup, verified write, restart) holding a realistic `pipeline.yaml`. They have not been run against real
hardware from this repository; try the first write on a spare or non-production device.
