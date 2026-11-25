"""Exercise ROS 2 review, deployment, recovery and verification without a sensor."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5 import QtWidgets
import device_model as dm
import device_ros2 as ros2
import device_ros2_remote as host
import device_ui as ui
import device_yaml as dy

APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
ROS2 = """camera:
  ros__parameters:
    camera_matrix: [55.0]
pointcloud_colorizer:
  ros__parameters:
    # Preserve comments and non-calibration settings
    camera_matrix:
      [224.5, 0.0, 243.3,
       0.0, 224.3, 181.7, # row two
       0.0, 0.0, 1.0]
    dist_coeffs:
      - -0.2
      - 0.08
      - 0.0
      - 0.0
      - 0.0
    extrinsic_matrix: [1.0, 0.0, 0.0, 0.02,
                       0.0, 1.0, 0.0, 0.03,
                       0.0, 0.0, 1.0, 0.24,
                       0.0, 0.0, 0.0, 1.0]
    image_width: 484
    image_height: 366
"""


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve()
        self.source, self.installed = (self.folder / f'{kind}.yaml' for kind in ('source', 'installed'))
        for path in (self.source, self.installed):
            path.write_bytes(ROS2.encode())
        self.deployment = dict(source=str(self.source), installed=str(self.installed), workspace=str(self.folder),
                               invocation='old', container='old-container', overrides=['/**: {ros__parameters: {}}'])
        self.ssh = Mock(password='example')
        self.ssh.read.side_effect = lambda path: Path(path).read_bytes().decode()
        self.device = dict(key='example', name='Device 8', bridge_url='ws://example')
        self.previous = dm.file_params(dy.read_params(ROS2))
        self.new = dy.ros2_values(self.previous)
        self.new['camera_matrix'][0] = 225.123456789123
        self.new['dist_coeffs'][2] = 1e-12
        self.new['extrinsic_matrix'][3] = 0.04
        self.calls = patch.object(ros2, 'remote_call', side_effect=self.local_deployment)
        self.calls.start()
        self.addCleanup(self.calls.stop)

    def local_deployment(self, _ssh, operation, payload=None):
        if operation in ('discover', 'recover'):
            return self.deployment
        return host.commit(payload['files'], payload['stamp'])

    def test_review_preserves_layout_comments_other_nodes_and_number_precision(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        after = plan['files'][-1]['after']
        self.assertEqual(dy.ros2_values(dy.read_params(after)), self.new)
        self.assertIn('# row two', after)
        self.assertIn('camera_matrix: [55.0]', after)
        self.assertIn('1.0e-12', after)
        self.assertEqual(after.replace('225.123456789123', '224.5').replace('1.0e-12', '0.0')
                         .replace('1.0, 0.0, 0.0, 0.04', '1.0, 0.0, 0.0, 0.02'), ROS2)
        for path in (self.source, self.installed):
            self.assertIn(str(path), ros2.plan_diff(plan))
            self.assertEqual(path.read_bytes(), ROS2.encode())
        crlf = ROS2.replace('\n', '\r\n')
        self.assertEqual(dy.update_ros2(crlf, self.new), after.replace('\n', '\r\n'))

    def test_modes_keep_the_unselected_live_values_and_reject_conflicting_copies(self):
        previous = dy.ros2_values(self.previous)
        for mode, kept in (('extrinsic', ('camera_matrix', 'dist_coeffs')), ('intrinsic', ('extrinsic_matrix',))):
            plan = ros2.prepare(self.ssh, self.new, mode)
            actual = dy.ros2_values(dy.read_params(plan['files'][-1]['after']))
            self.assertEqual(actual, {key: previous[key] if key in kept else value for key, value in self.new.items()})
        self.source.write_bytes(dy.update_ros2(ROS2, self.new).encode())
        with self.assertRaisesRegex(ValueError, 'source and installed calibrations differ'):
            ros2.prepare(self.ssh, self.new, 'full')

    def test_launch_override_blocks_review(self):
        self.deployment['overrides'] = ['/**: {ros__parameters: {camera_matrix: [9.0]}}']
        with self.assertRaisesRegex(ValueError, 'launch override'):
            ros2.prepare(self.ssh, self.new, 'full')

    def test_write_and_restore_use_both_backups_and_preserve_newer_unrelated_settings(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        record = ros2.write_recorded(self.ssh, plan, self.folder, self.device, self.previous, 'full')
        from device_update_review import saved_comparison

        self.assertTrue(saved_comparison(self.folder)['verified'])
        self.assertEqual(len(record['files']), 2)
        self.assertTrue(record['file_verified'])
        for entry in record['files']:
            self.assertEqual(Path(entry['backup']).read_bytes(), ROS2.encode())
            self.assertEqual(dy.ros2_values(dy.read_params(Path(entry['path']).read_bytes().decode())), self.new)
        self.source.write_bytes(self.source.read_bytes().replace(b'image_width: 484', b'image_width: 485'))
        self.deployment.update(container=None, invocation='')
        restore = ros2.prepare(self.ssh, restore=record)
        restored = ros2.write_recorded(self.ssh, restore, self.folder, self.device, self.previous, 'restore', record['backup'])
        self.assertTrue(restored['file_verified'])
        self.assertEqual(self.source.read_bytes(), ROS2.replace('image_width: 484', 'image_width: 485').encode())
        self.assertEqual(self.installed.read_bytes(), ROS2.encode())
        self.ssh.run.assert_not_called()

    def test_changed_file_after_review_prevents_writes_and_backups(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        self.installed.write_bytes(ROS2.encode() + b'# concurrent edit\n')
        with self.assertRaisesRegex(RuntimeError, 'changed after review'):
            ros2.apply(self.ssh, plan)
        self.assertEqual(self.source.read_bytes(), ROS2.encode())
        self.assertFalse(list(self.folder.glob('*.calib_backup_*')))

    def test_failed_second_file_rolls_back_first_and_keeps_verified_backups(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        replace = os.replace

        def fail(source, target):
            if target == self.installed:
                raise OSError('injected second-file failure')
            return replace(source, target)

        with patch.object(host.os, 'replace', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'No replacements from this attempt remain'):
                ros2.write_recorded(self.ssh, plan, self.folder, self.device, self.previous, 'full')
        self.assertEqual([path.read_bytes() for path in (self.source, self.installed)], [ROS2.encode()] * 2)
        record, = json.loads((self.folder / 'device_writes.json').read_text())
        self.assertFalse(record['file_verified'])
        self.assertEqual(len(list(self.folder.glob('*.calib_backup_*'))), 2)
        self.ssh.run.assert_not_called()

    def test_backup_collision_stops_before_replacing_either_file(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        backup = Path(f"{self.installed}.calib_backup_{plan['stamp']}")
        backup.write_bytes(b'existing backup')
        with self.assertRaises(RuntimeError):
            ros2.apply(self.ssh, plan)
        self.assertEqual(backup.read_bytes(), b'existing backup')
        self.assertEqual([path.read_bytes() for path in (self.source, self.installed)], [ROS2.encode()] * 2)

    def test_restart_refusal_preserves_files_and_never_queries_runtime(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        ros2.apply(self.ssh, plan)
        self.ssh.run.return_value = (1, '', 'sudo denied')
        with patch.object(ros2, 'verify_runtime') as verify:
            with self.assertRaisesRegex(RuntimeError, 'restart failed: sudo denied'):
                ros2.restart_and_verify(self.ssh, plan, self.device['bridge_url'])
        verify.assert_not_called()
        self.ssh.run.assert_called_once()
        self.assertIn(host.UNIT, self.ssh.run.call_args.args[0])
        self.assertEqual(self.installed.read_bytes(), plan['files'][-1]['after'].encode())

    def test_restart_failure_is_recorded_and_restore_remains_available(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        record = ros2.write_recorded(self.ssh, plan, self.folder, self.device, self.previous, 'full')
        self.ssh.run.return_value = (1, '', 'sudo denied')
        with patch.object(ui, 'ask', return_value=True), \
                patch.object(ui, 'busy', side_effect=lambda _parent, _text, fn, *args: fn(*args)):
            steps = ui.offer_ros2_restart(None, self.device, self.ssh, plan, self.folder, record)
        self.assertIn('sudo denied', steps[0])
        saved, = json.loads((self.folder / 'device_writes.json').read_text())
        self.assertTrue(saved['file_verified'])
        self.assertFalse(saved['restarted'])
        self.assertIsNone(saved['verified'])
        self.deployment.update(container=None, invocation='')
        recovery = ros2.prepare(self.ssh, restore=saved)
        self.assertEqual([e['after'] for e in recovery['files']], [ROS2, ROS2])

    def test_restart_checks_new_generation_and_compares_exact_arrays(self):
        plan = ros2.prepare(self.ssh, self.new, 'full')
        ros2.apply(self.ssh, plan)
        self.ssh.run.return_value = (0, '', '')
        new_generation = dict(self.deployment, container='new-container', invocation='new')
        response = {'values': [{'type': 8, 'double_array_value': self.new[key]} for key in dy.KEYS]}
        with patch.object(ros2, 'discover', side_effect=[self.deployment, new_generation]), \
                patch('ros_link.BridgeLink') as bridge:
            bridge.return_value._service.return_value = response
            self.assertEqual(ros2.restart_and_verify(self.ssh, plan, self.device['bridge_url']), (True, True, ''))
            bridge.return_value._service.assert_called_once_with(
                '/pointcloud_colorizer/get_parameters', {'names': list(dy.KEYS)}, timeout=3.0)
        response['values'][2] = {'type': 8, 'double_array_value': dy.ros2_values(self.previous)['extrinsic_matrix']}
        with patch('ros_link.BridgeLink') as bridge:
            bridge.return_value._service.return_value = response
            matched, detail = ros2.verify_runtime(self.device['bridge_url'], self.new, wait_s=.03)
        self.assertFalse(matched)
        self.assertIn('extrinsic_matrix', detail)

    def test_write_dialog_requires_separate_confirmation_before_restart(self):
        info = dict(name='manual', out=self.folder, manual=True,
                    device=dict(device=self.device, params=self.previous, theta_max_deg=55),
                    summary=dict(mode='full', verdict='UPDATE RECOMMENDED'), device_params_override=self.new)
        with patch.object(ui.devreg, 'load', return_value=[]), patch.object(ui.devreg, 'save_settings'), \
                patch.object(ui, 'ssh_session', return_value=self.ssh), \
                patch.object(ui, 'read_device_yaml', return_value=('/other-checkout/pipeline.yaml', ROS2)), \
                patch.object(ui, 'busy', side_effect=lambda _parent, _text, fn, *args: fn(*args)), \
                patch.object(ui, 'warn') as warn, patch.object(ui.core, 'mark_history'), \
                patch.object(QtWidgets.QDialog, 'exec_', return_value=QtWidgets.QDialog.Accepted):
            dialog = ui.WriteDialog(None, info)
            self.addCleanup(dialog.close)
            dialog.connect_and_diff()
            self.assertEqual(dialog.pages.currentIndex(), 1)
            self.assertIn(str(self.installed), dialog.diff.toPlainText())
            self.assertNotIn('/other-checkout', dialog.diff.toPlainText())
            with patch.object(ui, 'ask', return_value=False):
                dialog.write()
                self.assertFalse((self.folder / 'device_writes.json').exists())
            with patch.object(ui, 'ask', side_effect=[True, False]) as ask:
                dialog.write()
            self.assertEqual(ask.call_count, 2)
            self.assertTrue(dialog.written_record['file_verified'])
            self.assertFalse(dialog.written_record['restarted'])
            self.ssh.run.assert_not_called()
            warn.assert_not_called()


class RecoveryDiscoveryTests(unittest.TestCase):
    def test_offline_restore_requires_configured_workspace_and_no_starting_container(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            config = root / 'host.env'
            config.write_text(f'WORKSPACE="{root.as_posix()}"\n')
            source = root / 'ros2/src/node_pc'
            installed = root / 'ros2/install/node_pc/share/node_pc'
            for folder in (source, installed):
                (folder / 'config').mkdir(parents=True)
                (folder / 'config/pipeline.yaml').write_text(ROS2)
            (source / 'CMakeLists.txt').write_text('install(DIRECTORY config launch DESTINATION share/${PROJECT_NAME})\n')
            unit = dict(ActiveState='failed', InvocationID='', FragmentPath='/etc/systemd/system/sensor-computer-jazzy.service',
                        ExecStart='/usr/local/lib/sensor-computer/run-container.sh')
            with patch.object(host, 'HOST_CONFIG', config), patch.object(host, 'service_info', return_value=unit), \
                    patch.object(host, 'command', return_value='') as command:
                with self.assertRaisesRegex(RuntimeError, 'not active'):
                    host.discover()
                deployment = host.discover(allow_inactive=True)
                self.assertIsNone(deployment['container'])
                self.assertEqual(Path(deployment['installed']), installed / 'config/pipeline.yaml')
                command.return_value = 'new-container'
                with self.assertRaisesRegex(RuntimeError, 'starting'):
                    host.discover(allow_inactive=True)


if __name__ == '__main__':
    unittest.main()
