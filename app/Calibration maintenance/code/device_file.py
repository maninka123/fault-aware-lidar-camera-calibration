"""Read an explicitly configured local WSL device file without an SSH daemon."""
import subprocess


def uses_wsl(device):
    # Bind the local-file mapping to its ROS endpoint. If the profile is changed
    # to a physical sensor, its normal SSH file reader is used instead.
    return (device.get('calibration_transport') == 'wsl'
            and bool(device.get('file_master_uri'))
            and device.get('file_master_uri') == device.get('master_uri'))


def read_wsl(device):
    if not uses_wsl(device):
        raise ValueError('No WSL calibration-file mapping for this device endpoint.')
    distro, path = device.get('wsl_distro'), device.get('yaml_path')
    if not distro or not path or not path.startswith('/'):
        raise ValueError('WSL file access needs a distribution and an absolute calibration file path.')
    result = subprocess.run(['wsl.exe', '--distribution', distro, '--exec', 'cat', '--', path],
                            capture_output=True, encoding='utf-8', errors='replace', timeout=20,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError(f'Cannot read {path} in WSL {distro}: {result.stderr.strip()}')
    return path, result.stdout, f'WSL {distro} — {path}'
