import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('sync_project', Path(__file__).with_name('sync_amt_project.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source, self.target = [Path(self.temp.name) / name for name in ('source', 'collection')]
        for root, remote in [(self.source, module.SOURCE_REPO), (self.target, module.TARGET_REPO)]:
            root.mkdir()
            subprocess.run(['git', 'init', '-q', '--initial-branch=main', str(root)], check=True)
            for key, value in [('user.name', 'Sync Test'), ('user.email', 'test@example.invalid'), ('core.autocrlf', 'false')]:
                module.git(root, 'config', key, value)
            module.git(root, 'remote', 'add', 'origin', remote + '.git')
        (self.source / 'app.py').write_text('print("app")\n')
        (self.target / 'README.md').write_text('AMT collection\n')
        (self.target / 'Another_Project').mkdir()
        (self.target / 'Another_Project/important.txt').write_text('preserve me\n')
        (self.target / module.FOLDER).mkdir()
        (self.target / module.FOLDER / 'obsolete.py').write_text('old version\n')
        (self.target / 'PROJECT_SOURCES.json').write_text(json.dumps({'projects': [{'folder': 'Another_Project', 'source_commit': 'keep'}]}))
        for root in (self.source, self.target):
            module.git(root, 'add', '.')
            module.git(root, 'commit', '-qm', 'Fixture')

    def test_only_app_folder_changes_and_sibling_content_and_metadata_survive(self):
        self.assertTrue(module.sync(self.source, self.target))
        self.assertEqual((self.target / 'Another_Project/important.txt').read_text(), 'preserve me\n')
        self.assertEqual((self.target / 'README.md').read_text(), 'AMT collection\n')
        self.assertFalse((self.target / module.FOLDER / 'obsolete.py').exists())
        self.assertEqual((self.target / module.FOLDER / 'app.py').read_text(), 'print("app")\n')
        info = json.loads((self.target / 'PROJECT_SOURCES.json').read_text())
        self.assertEqual(info['projects'][0]['source_commit'], 'keep')
        module.git(self.target, 'commit', '-qm', 'Sync')
        self.assertFalse(module.sync(self.source, self.target))

    def test_dirty_target_or_wrong_origin_is_rejected_before_deletion(self):
        (self.target / 'README.md').write_text('uncommitted work')
        with self.assertRaises(ValueError):
            module.sync(self.source, self.target)
        self.assertTrue((self.target / module.FOLDER / 'obsolete.py').exists())
        module.git(self.target, 'restore', 'README.md')
        module.git(self.target, 'remote', 'set-url', 'origin', 'https://github.com/example/wrong.git')
        with self.assertRaises(ValueError):
            module.sync(self.source, self.target)
        self.assertTrue((self.target / module.FOLDER / 'obsolete.py').exists())


    def test_exact_committed_bytes_and_executable_mode_are_preserved(self):
        raw = b'#!/bin/sh\r\necho sensor\r\n'
        (self.source / 'run.sh').write_bytes(raw)
        (self.source / 'run.sh').chmod(0o755)
        module.git(self.source, 'add', 'run.sh')
        module.git(self.source, 'update-index', '--chmod=+x', 'run.sh')
        module.git(self.source, 'commit', '-qm', 'Executable fixture')
        self.assertTrue(module.sync(self.source, self.target))
        actual = subprocess.check_output(['git', '-C', str(self.target), 'show', ':' + module.FOLDER + '/run.sh'])
        self.assertEqual(actual, raw)
        self.assertTrue(module.git(self.target, 'ls-files', '--stage', module.FOLDER + '/run.sh').startswith('100755 '))

    def test_symlink_is_copied_without_dereferencing(self):
        data = b'/opt/ros/noetic/share/catkin/cmake/toplevel.cmake'
        blob = subprocess.check_output(['git', '-C', str(self.source), 'hash-object', '-w', '--stdin'], input=data).decode().strip()
        (self.source / 'catkin-link').write_bytes(data)
        module.git(self.source, 'config', 'core.symlinks', 'false')
        module.git(self.source, 'update-index', '--add', '--cacheinfo', '120000', blob, 'catkin-link')
        module.git(self.source, 'commit', '-qm', 'Symlink fixture')
        self.assertTrue(module.sync(self.source, self.target))
        self.assertTrue(module.git(self.target, 'ls-files', '--stage', module.FOLDER + '/catkin-link').startswith('120000 '))
        actual = subprocess.check_output(['git', '-C', str(self.target), 'show', ':' + module.FOLDER + '/catkin-link'])
        self.assertEqual(actual, data)

    def test_dirty_source_is_rejected_before_destination_changes(self):
        (self.source / 'app.py').write_text('uncommitted source')
        with self.assertRaises(ValueError):
            module.sync(self.source, self.target)
        self.assertTrue((self.target / module.FOLDER / 'obsolete.py').exists())


if __name__ == '__main__':
    unittest.main()
