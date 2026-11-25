"""Review, deploy and verify the calibration for the managed ROS 2 sensor."""
import hashlib
import json
import shlex
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import yaml

import device_model as dm
import device_yaml as dy
import device_ros2_remote as remote

MODEL_KEYS = ('camera_model', 'distortion_model')
PARAMETER_SERVICE = '/pointcloud_colorizer/get_parameters'


def remote_call(ssh, operation, payload=None):
    script = Path(remote.__file__).with_suffix('.py').read_text(encoding='utf-8')
    command = f'python3 -c {shlex.quote(script)} {shlex.quote(operation)}'
    if operation in ('active-calibration', 'discover-managed'):
        command = f"if command -v python3 >/dev/null 2>&1; then {command}; else printf 'null\\n'; fi"
    code, output, error = ssh.run(command, stdin=json.dumps(payload) if payload is not None else None, timeout=85)
    if code:
        raise RuntimeError(error.strip() or f'ROS 2 {operation} failed.')
    try:
        return json.loads(output)
    except ValueError as e:
        raise RuntimeError(f'The device sent an invalid ROS 2 {operation} response.') from e


def discover(ssh, allow_inactive=False, optional=False):
    operation = 'recover' if allow_inactive else 'discover-managed' if optional else 'discover'
    deployment = remote_call(ssh, operation)
    if deployment is not None:
        check_overrides(deployment['overrides'])
    return deployment


def check_overrides(overrides):

    def has_override(value):
        if isinstance(value, dict):
            return any(key in dy.KEYS + MODEL_KEYS or has_override(child) for key, child in value.items())
        return isinstance(value, list) and any(has_override(child) for child in value)

    for text in overrides:
        try:
            override = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError('An active launch override could not be read as YAML.') from error
        if has_override(override):
            raise ValueError('A launch override supplies calibration parameters. The installed file alone cannot establish the calibration.')


def read_active(ssh):
    """Return the running deployment's installed YAML, or None on a legacy host."""
    result = remote_call(ssh, 'active-calibration')
    if result is None:
        return None
    check_overrides(result['overrides'])
    try:
        if not dy.is_ros2(result['text']):
            raise ValueError('The active pipeline.yaml does not have a ROS 2 colourizer parameter mapping.')
    except ValueError as error:
        raise ValueError(f"{result['path']}\n{error}") from error
    return result['path'], result['text']


def validate_projection(params):
    for key in MODEL_KEYS:
        model = params.get(key)
        if model is not None and model not in dm.PINHOLE_MODELS:
            raise ValueError(f'The managed ROS 2 colourizer requires OpenCV pinhole values. Unsupported {key}: {model}.')


def query_runtime(link):
    return runtime_values(link._service(PARAMETER_SERVICE, {'names': list(dy.KEYS)}), strict=False)


def check_running_projection(bridge_url):
    from ros_link import BridgeLink

    link = BridgeLink(bridge_url)
    try:
        query_runtime(link)
        # The supported node_pc colourizer uses the five-coefficient pinhole projector.
        # If a deployment declares a model, require it to agree with that contract.
        models = {}
        for name in MODEL_KEYS:
            values = link._service(PARAMETER_SERVICE, {'names': [name]})['values']
            if values and values[0]['type'] != 0:
                if len(values) != 1 or values[0]['type'] != 4:
                    raise ValueError(f'The running colourizer reports an invalid {name}.')
                models[name] = values[0]['string_value']
        validate_projection(models)
    finally:
        link.close()


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prepare(ssh, params=None, mode=None, restore=None, *, optional=False, bridge_url=None):
    deployment = discover(ssh, allow_inactive=restore is not None, optional=optional)
    if deployment is None:
        return None
    files = [{'path': path, 'before': ssh.read(path)}
             for path in dict.fromkeys((deployment['source'], deployment['installed']))]
    if not all(dy.is_ros2(entry['before']) for entry in files):
        raise ValueError('Both deployment files must have a ROS 2 pointcloud_colorizer parameter mapping.')
    file_values = [dy.read_params(entry['before']) for entry in files]
    for values in file_values:
        validate_projection(values)
    before = dy.ros2_values(file_values[-1])
    if bridge_url and deployment['container']:
        check_running_projection(bridge_url)
    if restore is not None:
        records = restore['files']
        if [r['path'] for r in records] != [entry['path'] for entry in files]:
            raise ValueError('The backup belongs to a different ROS 2 deployment.')
        backed_up = []
        for record in records:
            expected = f"{record['path']}.calib_backup_{restore['stamp']}"
            if record['backup'] != expected:
                raise ValueError('The stored ROS 2 backup path is invalid.')
            text = ssh.read(expected)
            if digest(text) != record['before_sha256'] or not dy.is_ros2(text):
                raise ValueError(f'Backup verification failed for {expected}.')
            values = dy.read_params(text)
            validate_projection(values)
            backed_up.append(dy.ros2_values(values))
        params = backed_up[-1]
        if any(values != params for values in backed_up):
            raise ValueError('The backups contain different calibrations. Review them before restoring.')
    else:
        if any(dy.ros2_values(values) != before for values in file_values):
            raise ValueError('The source and installed calibrations differ. Resolve the drift or restore a verified backup first.')
        validate_projection(params)
        params = dy.ros2_values(params)
        kept = {'extrinsic': ('camera_matrix', 'dist_coeffs'), 'intrinsic': ('extrinsic_matrix',)}.get(mode, ())
        for key in kept:
            params[key] = before[key]
    for entry in files:
        entry['after'] = dy.update_ros2(entry['before'], params)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid4().hex[:12]
    return dict(deployment=deployment, files=files, stamp=stamp)


def plan_diff(plan):
    return '\n'.join(dy.diff(e['before'], e['after'], e['path']) or f"{e['path']}\n  Already matches.\n"
                     for e in plan['files'])


def apply(ssh, plan):
    readback = remote_call(ssh, 'apply', plan)
    if readback != [entry['after'] for entry in plan['files']]:
        raise RuntimeError('The ROS 2 read-back could not be verified. Check the backups and both files before retrying.')
    return readback


def _save_record(out, record):
    log = out / 'device_writes.json'
    records = json.loads(log.read_text(encoding='utf-8')) if log.exists() else []
    index = next((i for i, entry in enumerate(records) if entry.get('stamp') == record['stamp']), len(records))
    records[index:index + 1] = [record]
    temporary = out / f".device_writes_{record['stamp']}.tmp"
    temporary.write_text(json.dumps(records, indent=2), encoding='utf-8')
    temporary.replace(log)


def write_recorded(ssh, plan, out, device, previous, mode, restored_from=None):
    """Record recovery paths before applying, then retain exact per-file evidence."""
    stamp = plan['stamp']
    files = []
    for i, entry in enumerate(plan['files'], 1):
        paths = {kind: f'device_{kind}_{stamp}_{i}_pipeline.yaml' for kind in ('backup', 'written', 'readback')}
        (out / paths['backup']).write_bytes(entry['before'].encode('utf-8'))
        files.append(dict(path=entry['path'], backup=f"{entry['path']}.calib_backup_{stamp}",
                          before_sha256=digest(entry['before']),
                          **{f'local_{name}': path for name, path in paths.items()}))
    primary = files[-1]
    record = dict(date=datetime.now().isoformat(timespec='seconds'), device=device['name'], key=device['key'],
                  ros_version=2, stamp=stamp, files=files, path=primary['path'], backup=primary['backup'],
                  previous=previous, mode=mode, restarted=False, verified=None, file_verified=False)
    if restored_from:
        record['restored_from'] = restored_from
    _save_record(out, record)
    readback = apply(ssh, plan)
    record['file_verified'] = True
    for entry, evidence, actual in zip(plan['files'], files, readback):
        evidence.update(written_sha256=digest(entry['after']), readback_sha256=digest(actual))
    record.update({key: value for key, value in primary.items() if key not in ('path', 'backup')})
    record['new'] = dm.file_params(dy.read_params(readback[-1]),
                                   image_size=(previous['image_width'], previous['image_height']))
    for entry, evidence, actual in zip(plan['files'], files, readback):
        (out / evidence['local_written']).write_bytes(entry['after'].encode('utf-8'))
        (out / evidence['local_readback']).write_bytes(actual.encode('utf-8'))
    _save_record(out, record)
    return record


def runtime_values(response, *, strict=True):
    arrays = response.get('values') if isinstance(response, dict) else None
    if not isinstance(arrays, list) or len(arrays) != len(dy.KEYS):
        raise ValueError('The running node did not return three double arrays.')
    values = {}
    for key, array in zip(dy.KEYS, arrays):
        if not isinstance(array, dict) or array.get('type') != 8 or 'double_array_value' not in array:
            raise ValueError(f'The running node did not return {key} as a double array.')
        values[key] = array['double_array_value']
    return dy.ros2_values(values) if strict else dm.file_arrays(values)


def verify_runtime(bridge_url, expected, wait_s=150):
    from ros_link import BridgeLink

    deadline = time.monotonic() + wait_s
    detail = 'The colorizer did not respond.'
    while time.monotonic() < deadline:
        try:
            with_timeout = min(3.0, max(0.1, deadline - time.monotonic()))
            link = BridgeLink(bridge_url, timeout=with_timeout)
            try:
                response = link._service(PARAMETER_SERVICE,
                                         {'names': list(dy.KEYS)}, timeout=with_timeout)
                actual = runtime_values(response)
                differences = [key for key in dy.KEYS if actual[key] != expected[key]]
                if not differences:
                    return True, ''
                detail = 'The running node differs for ' + ', '.join(differences) + '.'
            finally:
                link.close()
        except Exception as error:
            detail = f'Could not query /pointcloud_colorizer/get_parameters: {error}'
        time.sleep(min(3.0, max(0., deadline - time.monotonic())))
    return False, detail


def restart_and_verify(ssh, plan, bridge_url):
    reviewed = plan['deployment']
    if not bridge_url:
        raise ValueError('A ROSBridge URL is needed to verify the running ROS 2 colorizer.')
    if (discover(ssh, allow_inactive=reviewed['container'] is None) != reviewed
            or any(ssh.read(e['path']) != e['after'] for e in plan['files'])):
        raise RuntimeError('The deployment or written files changed. The app did not restart the pipeline.')
    unit = reviewed['unit']
    code, _, error = ssh.run(f"sudo -S -p '' systemctl restart {shlex.quote(unit)}",
                             stdin=ssh.password + '\n', timeout=180)
    if code:
        raise RuntimeError(f'{unit} restart failed: {error.strip() or f"exit status {code}"}')
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            active = discover(ssh)
            if (active['invocation'] != reviewed['invocation'] and active['container'] != reviewed['container']
                    and all(active[key] == reviewed[key] for key in ('unit', 'source', 'installed', 'workspace'))):
                break
        except (RuntimeError, ValueError):
            pass
        time.sleep(2)
    else:
        return False, False, 'The new managed ROS 2 pipeline generation could not be confirmed.'
    expected = dy.ros2_values(dy.read_params(plan['files'][-1]['after']))
    verified, detail = verify_runtime(bridge_url, expected)
    return True, verified, detail


def record_restart(out, record, restarted, verified, error=''):
    record.update(restarted=restarted, verified=verified)
    if error:
        record['restart_error'] = error
    _save_record(out, record)
