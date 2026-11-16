Fault-Aware Calibration - Windows portable application

Extract the ENTIRE ZIP to a short writable folder, for example C:\FaultAware.
Double-click FaultAwareCalibration.exe. Keep the app and _internal folders beside it.
Python, Anaconda, ROS and pip are not required on the destination PC.
Do not copy only the executable. Do not install inside Program Files: the app saves recordings and checks beside its sources.

Each PC has its own device connections, SSH credentials and app settings.
Choose that PC's Central Monitoring Platform folder in Devices, or add its devices manually.
No recordings, device configuration, passwords or research results are included.
Device calibration changes always require review and confirmation. Backups enable restore.

For installation diagnostics run:
FaultAwareCalibration.exe --diagnose installation-check.json
The JSON report should contain "ok": true.

This is a research prototype. Testing the package is not a validation of physical calibration accuracy.
