# Troubleshooting

## Reporting a problem

Include the **version** (bottom of the sidebar) and the **log**: `%LOCALAPPDATA%\FaultAwareCalibration\app.log`. The log
contains file paths from your machine. If the app hits an unexpected error it shows a message, saves the details to that
log, and leaves your calibration files untouched.

## The app

| Problem | What to do |
| --- | --- |
| *"Windows stops at 260 characters"* when starting a check | The repository sits too deep. Move it to a short folder such as `C:\FaultAware`, or turn on long paths in Windows. The message appears before anything runs. |
| The window does not start | Run `python gui/research_gui.py` in a terminal to see the error, and check that `pip install -r requirements.txt` finished. `start_research_gui.bat` looks for `.venv`, then Anaconda, then `pythonw` on the path. |
| It restored the wrong calibration or captures | Choose the right ones (that replaces them), or press *Forget* on New check. To clear everything, delete `%LOCALAPPDATA%\FaultAwareCalibration\settings.json`. |

## Checks

| Problem | What to do |
| --- | --- |
| A check shows **Stopped** or **Could not finish** | The last line of the log (Processing → *Show log*) says why. The partial folder stays in `research_artifacts/` and is marked in the list. Your calibration is unchanged. |
| "At least two recorded captures are needed" | The held-out comparison needs several captures. Add more, from different viewpoints. |
| Closing the window during a check | The app asks first and stops the check cleanly. |
| The result says *Not enough evidence* | The captures could not separate the explanations, or no explanation helped consistently. Collect more varied captures (turn the rig a little between them). That is an answer, not a failure. |

## Calibration review

| Problem | What to do |
| --- | --- |
| It says the comparison did not finish | Its log is shown on the card. Press **Run the comparison again…**; an earlier saved comparison is only replaced when the new one finishes. |
| *"The check now points at different files than this comparison used"* | The calibration or captures changed since it ran. Run it again if you want it to match. |
| Another window is already running it | Only one window can run the comparison for a check at a time. Wait for it, or stop it there. |
| Temporary files | The comparison works in `%LOCALAPPDATA%\FaultAwareReview` and removes it when it finishes. If a run was interrupted, that folder can be deleted. |

## Devices

| Problem | What to do |
| --- | --- |
| A device shows *offline* | Check the address and that the device is on the network; use *Refresh*. Devices come from the Central Monitoring Platform folder (*Platform folder…*). |
| Writing failed | The dialog reports the step that failed. The device's file is either unchanged or the backup is in place. A failed write is not recorded as done. |
| *Restore* is greyed out | Nothing has been written for this check yet. |

## Reset everything the app stored

Delete `%LOCALAPPDATA%\FaultAwareCalibration` (settings and log) and `%LOCALAPPDATA%\FaultAwareReview` (temporary
comparison files). Your checks in `research_artifacts/` and your calibration files are separate and are not touched.
