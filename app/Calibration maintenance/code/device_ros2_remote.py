"""Host-side helper run through the device's authenticated SSH session."""
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

UNIT = 'sensor-computer-jazzy.service'
CONTAINER = 'sensor-computer-jazzy'
HOST_CONFIG = Path('/etc/sensor-computer/host.env')
INSTALL_ROOT = PurePosixPath('/workspace/ros2/install')
YAML_SUFFIX = ('share', 'node_pc', 'config', 'pipeline.yaml')
COLORIZER_SUFFIX = ('lib', 'node_pc', 'pointcloud_colorize_node')


def command(*args):
    p = subprocess.run(args, capture_output=True, text=True, timeout=12)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or f'{args[0]} exited with status {p.returncode}')
    return p.stdout


def service_info():
    properties = ('ActiveState', 'InvocationID', 'ExecStart', 'FragmentPath')
    return dict(line.split('=', 1) for line in command(
        'systemctl', 'show', UNIT, *(f'--property={p}' for p in properties)).splitlines())


def managed_unit_present():
    init = Path('/proc/1/comm')
    if init.is_file() and init.read_text().strip() != 'systemd':
        return False
    probe = subprocess.run(('systemctl', 'show', UNIT, '--property=LoadState', '--value'),
                           capture_output=True, text=True, timeout=12)
    if probe.stdout.strip() == 'not-found':
        return False
    if probe.returncode or probe.stdout.strip() != 'loaded':
        raise RuntimeError(probe.stderr.strip() or f'Could not inspect {UNIT}.')
    return True


def package_path(path, suffix):
    path = PurePosixPath(path)
    return path.is_relative_to(INSTALL_ROOT) and '..' not in path.parts and path.parts[-len(suffix):] == suffix


def installed_file(root, runtime_path):
    if not package_path(runtime_path, YAML_SUFFIX):
        raise RuntimeError('The running colorizer does not load an installed node_pc pipeline.yaml.')
    path = (root / PurePosixPath(runtime_path).relative_to('/workspace').as_posix()).resolve(strict=True)
    if not path.is_relative_to(root / 'ros2') or not path.is_file():
        raise RuntimeError('The installed calibration must resolve inside the active ROS 2 workspace.')
    return str(path)


def discover(allow_inactive=False, require_source=True):
    unit = service_info()
    if ('/usr/local/lib/sensor-computer/run-container.sh' not in unit.get('ExecStart', '')
            or not unit.get('FragmentPath')):
        raise RuntimeError(f'Could not verify the managed ROS 2 service {UNIT}.')
    configuration = HOST_CONFIG.read_text()
    workspaces = re.findall(r'^\s*(?:export\s+)?WORKSPACE\s*=(.*)$', configuration, re.MULTILINE)
    values = shlex.split(workspaces[0], comments=True) if len(workspaces) == 1 else []
    if len(values) != 1 or not Path(values[0]).is_absolute() or '$' in values[0]:
        raise RuntimeError('Could not resolve the configured ROS 2 workspace.')
    root = Path(values[0]).resolve(strict=True)
    workspace = root / 'ros2'
    deployment = dict(unit=UNIT, workspace=str(workspace),
                      invocation=unit.get('InvocationID', ''), container=None, overrides=[])
    if require_source:
        cmake = (workspace / 'src/node_pc/CMakeLists.txt').read_text()
        if not re.search(r'install\(\s*DIRECTORY\s+config\s+launch\s+DESTINATION\s+share/\$\{PROJECT_NAME\}\s*\)', cmake):
            raise RuntimeError('The source package does not declare the expected installation of config/pipeline.yaml.')
        source = (workspace / 'src/node_pc/config/pipeline.yaml').resolve(strict=True)
        if not source.is_relative_to(workspace) or not source.is_file():
            raise RuntimeError('The source calibration must resolve inside the active ROS 2 workspace.')
        deployment['source'] = str(source)
    if unit.get('ActiveState') != 'active':
        if allow_inactive and not command('docker', 'ps', '--filter', f'name=^/{CONTAINER}$', '-q').strip():
            locations = [INSTALL_ROOT.joinpath(*prefix, *YAML_SUFFIX) for prefix in ((), ('node_pc',))]
            available = [path for path in locations if (root / path.relative_to('/workspace').as_posix()).is_file()]
            if len(available) != 1:
                raise RuntimeError('Could not identify a single installed pipeline.yaml for recovery.')
            return dict(deployment, installed=installed_file(root, available[0]))
        raise RuntimeError(f'The managed ROS 2 service {UNIT} is not active or is starting.')
    container, = json.loads(command('docker', 'inspect', '--type=container', CONTAINER))
    if not container['State']['Running'] or not deployment['invocation']:
        raise RuntimeError('The ROS 2 sensor container is not running under the managed service.')
    processes = []
    for line in command('docker', 'top', container['Id'], '-eo', 'pid,args').splitlines()[1:]:
        columns = line.split(None, 1)
        if len(columns) == 2 and package_path(columns[1].split(None, 1)[0], COLORIZER_SUFFIX):
            processes.append(columns[0])
    if len(processes) != 1 or not processes[0].isdigit():
        raise RuntimeError('Could not identify exactly one running pointcloud_colorizer process.')
    executable, *args = Path(f'/proc/{processes[0]}/cmdline').read_bytes().decode().rstrip('\0').split('\0')
    if (not package_path(executable, COLORIZER_SUFFIX) or len(args) < 5
            or args[:4] != ['--ros-args', '-r', '__node:=pointcloud_colorizer', '--params-file']):
        raise RuntimeError('The running colorizer does not point to an installed pipeline.yaml.')
    runtime_path = args[4]
    for container_path in (runtime_path, executable):
        mounts = [m for m in container['Mounts'] if container_path.startswith(m['Destination'].rstrip('/') + '/')]
        if (len(mounts) != 1 or mounts[0]['Type'] != 'bind' or mounts[0]['Destination'] != '/workspace'
                or Path(mounts[0]['Source']).resolve(strict=True) != root):
            raise RuntimeError('The installed colorizer and YAML must be mounted from the configured ROS 2 workspace.')
    extra = args[5:]
    if len(extra) % 2 or any(flag != '--params-file' or not re.fullmatch(r'/tmp/launch_params_\w+', path)
                             for flag, path in zip(extra[::2], extra[1::2])):
        raise RuntimeError('The running colorizer has unsupported parameter arguments.')
    overrides = [command('docker', 'exec', container['Id'], 'cat', '--', path) for path in extra[1::2]]
    return dict(deployment, installed=installed_file(root, runtime_path),
                container=container['Id'], overrides=overrides)


def active_calibration():
    """Read the installed file of the running deployment. Legacy hosts have no managed unit."""
    if not managed_unit_present():
        return None
    deployment = discover(require_source=False)
    path = deployment['installed']
    return dict(path=path, text=Path(path).read_bytes().decode('utf-8'), overrides=deployment['overrides'])


def stage(path, data, metadata):
    fd, name = tempfile.mkstemp(prefix='.calibration-', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            if hasattr(os, 'fchown'):
                current = os.fstat(stream.fileno())
                if (current.st_uid, current.st_gid) != (metadata.st_uid, metadata.st_gid):
                    os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def sync_directories(paths):
    if hasattr(os, 'O_DIRECTORY'):
        for directory in {path.parent for path in paths}:
            fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)


def commit(files, stamp):
    """Back up both files before replacing either, and roll back completed replacements on error."""
    paths = [Path(entry['path']) for entry in files]
    old = [entry['before'].encode('utf-8') for entry in files]
    new = [entry['after'].encode('utf-8') for entry in files]
    backups = [Path(f'{path}.calib_backup_{stamp}') for path in paths]
    originals, replacements, changed = [], [], []
    try:
        for path, expected, desired in zip(paths, old, new):
            if path.resolve(strict=True) != path or path.read_bytes() != expected:
                raise RuntimeError(f'{path} changed after review. Open a fresh review.')
            metadata = path.stat()
            originals.append(stage(path, expected, metadata))
            replacements.append(stage(path, desired, metadata))
        for temp, backup, expected in zip(originals, backups, old):
            os.link(temp, backup)
            if backup.read_bytes() != expected:
                raise RuntimeError(f'Could not verify backup {backup}.')
        sync_directories(paths)
        for i, (path, temp, expected, desired) in enumerate(zip(paths, replacements, old, new)):
            if path.resolve(strict=True) != path or path.read_bytes() != expected:
                raise RuntimeError(f'{path} changed after review.')
            if expected != desired:
                os.replace(temp, path)
                changed.append(i)
        readback = [path.read_bytes() for path in paths]
        if readback != new:
            raise RuntimeError('The device files did not match the reviewed update.')
        sync_directories(paths)
        return [data.decode('utf-8') for data in readback]
    except Exception as error:
        failed = []
        for i in reversed(changed):
            try:
                if paths[i].resolve(strict=True) != paths[i] or paths[i].read_bytes() != new[i]:
                    raise RuntimeError('file changed again')
                os.replace(originals[i], paths[i])
                if paths[i].read_bytes() != old[i]:
                    raise RuntimeError('rollback read-back mismatch')
                sync_directories([paths[i]])
            except Exception as rollback_error:
                failed.append(f'{paths[i]} ({rollback_error})')
        detail = ('Rollback could not be verified for ' + ', '.join(failed)
                  if failed else 'No replacements from this attempt remain.')
        raise RuntimeError(f'{error} {detail}') from error
    finally:
        for path in originals + replacements:
            path.unlink(missing_ok=True)


def apply(payload):
    import fcntl

    reviewed = payload['deployment']
    files, stamp = payload['files'], payload['stamp']
    if not re.fullmatch(r'\d{8}_\d{6}_[0-9a-f]{12}', stamp):
        raise RuntimeError('Invalid backup identifier.')
    # Lock the workspace directory without creating a file. Other app sessions use the same lock.
    fd = os.open(reviewed['workspace'], os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        live = discover(allow_inactive=reviewed['container'] is None)
        if live != reviewed:
            raise RuntimeError('The running deployment changed after review. Open a fresh review.')
        if [entry['path'] for entry in files] != list(dict.fromkeys((live['source'], live['installed']))):
            raise RuntimeError('Reviewed paths do not match the running deployment.')
        return commit(files, stamp)
    finally:
        os.close(fd)


if __name__ == '__main__':
    try:
        operation = sys.argv[1]
        if operation in ('discover', 'recover'):
            result = discover(allow_inactive=operation == 'recover')
        elif operation == 'discover-managed':
            result = discover() if managed_unit_present() else None
        elif operation == 'active-calibration':
            result = active_calibration()
        elif operation == 'apply':
            result = apply(json.load(sys.stdin))
        else:
            raise RuntimeError('Unknown ROS 2 deployment operation.')
        print(json.dumps(result))
    except Exception as error:
        sys.exit(str(error))
