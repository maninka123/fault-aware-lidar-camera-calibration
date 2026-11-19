"""Copy this source repository into its fixed UNSW project folder."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import os
import tempfile
import time

FOLDER = 'fault-aware-lidar-camera-calibration'
SOURCE_REPO = 'https://github.com/maninka123/fault-aware-lidar-camera-calibration'
TARGET_REPO = 'https://github.com/unsw-edu-au/AMT-project'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE).decode().strip()


def check_repository(root, expected):
    if Path(git(root, 'rev-parse', '--show-toplevel')).resolve() != root:
        raise ValueError('Expected the repository root')
    remote = git(root, 'remote', 'get-url', 'origin').removesuffix('.git')
    allowed = {expected, expected.replace('https://github.com/', 'git@github.com:')}
    if remote not in allowed:
        raise ValueError('Unexpected repository origin')
    if git(root, 'status', '--porcelain'):
        raise ValueError('Commit or remove unrelated work before running sync')


def sync(source, collection):
    source, collection = Path(source).resolve(), Path(collection).resolve()
    check_repository(source, SOURCE_REPO)
    check_repository(collection, TARGET_REPO)
    project = collection / FOLDER
    # All recursive deletion is confined to the named project in an isolated
    # clean checkout. A symlink or overlapping source is rejected first.
    if project.is_symlink() or project.resolve().parent != collection or source == collection or source.is_relative_to(project.resolve()):
        raise ValueError('Unsafe or overlapping project directory')
    records = git(source, 'ls-files', '--stage', '-z').split('\0')
    modes = {}
    names = []
    for record in filter(None, records):
        info, name = record.split('\t', 1)
        mode, blob, stage = info.split()
        if mode not in {'100644', '100755', '120000'} or stage != '0':
            raise ValueError('Only regular tracked source files can be synchronized')
        modes[name] = mode
        names.append(name)
    payloads = []
    for name in filter(None, names):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
            raise ValueError('Unsafe source path')
        file = source / relative
        if modes[name] != '120000' and (file.is_symlink() or not file.is_file()):
            raise ValueError('Expected a regular tracked file')
        data = subprocess.check_output(['git', '-C', str(source), 'show', 'HEAD:' + name])
        payloads.append((name, data))
    manifest_path = collection / 'PROJECT_SOURCES.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {'projects': []}
    entries = manifest.setdefault('projects', [])
    entry = next((item for item in entries if item.get('folder') == FOLDER), None)
    commit = git(source, 'rev-parse', 'HEAD')
    files = [dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()) for name, data in payloads]
    if entry and entry.get('source_commit') == commit and entry.get('files') == files:
        return False
    if project.exists():
        shutil.rmtree(project)
    project.mkdir()
    for name, data in payloads:
        target = project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if modes[name] == '120000' and os.name != 'nt':
            target.symlink_to(data.decode('utf-8'))
        else:
            target.write_bytes(data)
            target.chmod(0o755 if modes[name] == '100755' else 0o644)
    replacement = dict(folder=FOLDER, source_repository=SOURCE_REPO, source_branch='main',
        source_commit=commit, includes_local_changes=False,
        synchronized_utc=datetime.now(timezone.utc).isoformat(), files=files)
    if entry is None:
        entries.append(replacement)
    else:
        entry.clear()
        entry.update(replacement)
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    git(collection, 'add', '-A', '--', FOLDER, 'PROJECT_SOURCES.json')
    for name, data in payloads:
        blob = subprocess.check_output(['git', '-C', str(collection), 'hash-object', '-w', '--stdin'], input=data).decode().strip()
        git(collection, 'update-index', '--add', '--cacheinfo', modes[name], blob, FOLDER + '/' + name)
    changed = git(collection, 'diff', '--cached', '--name-only').splitlines()
    if any(path != 'PROJECT_SOURCES.json' and not path.startswith(FOLDER + '/') for path in changed):
        raise ValueError('Sync attempted to stage another project')
    return bool(changed)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--collection', required=True)
    parser.add_argument('--push', action='store_true')
    args = parser.parse_args()
    source, collection = Path(args.source).resolve(), Path(args.collection).resolve()
    if not args.push:
        changed = sync(source, collection)
    else:
        check_repository(source, SOURCE_REPO)
        check_repository(collection, TARGET_REPO)
        remote = git(collection, 'remote', 'get-url', 'origin')
        ssh = subprocess.run(['git', '-C', str(collection), 'config', '--get', 'core.sshCommand'], capture_output=True, text=True)
        if ssh.returncode == 0:
            os.environ['GIT_SSH_COMMAND'] = ssh.stdout.strip()
        os.environ['GIT_LFS_SKIP_SMUDGE'] = '1'
        # Transfer referenced LFS objects as well as their Git pointer files.
        if git(source, 'lfs', 'ls-files'):
            git(source, 'lfs', 'fetch', 'origin', 'HEAD')
            git(source, 'lfs', 'push', remote, 'HEAD')
        changed = False
        for attempt in range(8):
            # Retry in a new isolated checkout. Never reset a user's checkout
            # or rebase two competing edits to the shared JSON manifest.
            with tempfile.TemporaryDirectory(prefix='amt-project-sync-') as temp:
                target = Path(temp) / 'collection'
                git(collection, 'clone', '--shared', '--no-checkout', str(collection), str(target))
                git(target, 'remote', 'set-url', 'origin', remote)
                git(target, 'fetch', 'origin', 'main')
                git(target, 'checkout', '-B', 'main', 'FETCH_HEAD')
                git(target, 'config', 'user.name', 'github-actions[bot]')
                git(target, 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com')
                changed = sync(source, target)
                if not changed:
                    break
                commit = git(source, 'rev-parse', '--short', 'HEAD')
                git(target, 'commit', '-m', 'Sync ' + FOLDER + ' from personal main (' + commit + ')')
                result = subprocess.run(['git', '-C', str(target), 'push', 'origin', 'HEAD:main'], capture_output=True, text=True)
                if result.returncode == 0:
                    break
                print(result.stderr, flush=True)
            if attempt == 7:
                raise RuntimeError('UNSW push failed after eight fresh-checkout attempts')
            time.sleep(min(2 ** attempt, 20))
    print(json.dumps(dict(changed=changed, source_commit=git(source, 'rev-parse', 'HEAD'))))


if __name__ == '__main__':
    main()
