"""Connection configuration checks for physical sensors and WSL, without hardware writes."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import devices
import ros_link


class DeviceConnectionTests(unittest.TestCase):
    def test_physical_and_wsl_addresses_stay_independent_and_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'device_configs').mkdir()
            physical = root / 'device_configs/physical.env'
            physical.write_text('DEVICE_ID=1\nROS_MASTER_URI=http://10.20.0.21:11311\n'
                                'ROSBRIDGE_IP=10.20.0.21\nROSBRIDGE_PORT=9090\n')
            (root / 'device_configs/wsl.env').write_text(
                'DEVICE_ID=2\nROS_MASTER_URI=http://127.0.0.1:11312\n'
                'ROSBRIDGE_IP=127.0.0.1\nROSBRIDGE_PORT=9091\n')
            (root / 'config.json').write_text(json.dumps({'devices': {'list': [
                {'configFile': 'device_configs/physical.env'},
                {'configFile': 'device_configs/wsl.env'}]}}))
            local = root / 'local.json'
            local.write_text(json.dumps({'platform_dir': str(root), 'settings': {
                'cmp:1': {'image_topic': '/camera/image_raw'}}}))
            with patch.object(devices, 'LOCAL', local):
                real, sim = devices.load()
                self.assertEqual(real['master_uri'], 'http://10.20.0.21:11311')
                self.assertEqual(real['ssh_host'], '10.20.0.21')
                self.assertEqual(sim['bridge_url'], 'ws://127.0.0.1:9091')
                physical.write_text(physical.read_text().replace('10.20.0.21', '10.20.0.22'))
                self.assertEqual(devices.load()[0]['master_uri'], 'http://10.20.0.22:11311')
                self.assertEqual(devices.load()[1]['master_uri'], sim['master_uri'])

    def test_legacy_bridge_only_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'config.json').write_text(json.dumps({'devices': {'list': [
                {'id': 7, 'serverUrl': 'ws://10.20.0.51:9090', 'enabled': True}]}}))
            real, = devices.cmp_devices(root)
            self.assertEqual(real['master_uri'], '')
            self.assertEqual(real['bridge_url'], 'ws://10.20.0.51:9090')

    def test_native_ros_connection_for_physical_address(self):
        with patch.object(ros_link, 'NativeLink') as native, patch.object(ros_link, 'BridgeLink') as bridge:
            result = ros_link.open_link({'master_uri': 'http://10.20.0.21:11311',
                                         'bridge_url': 'ws://10.20.0.21:9090'})
            self.assertIs(result, native.return_value)
            native.assert_called_once_with('http://10.20.0.21:11311', 3.0)
            native.return_value.topics.assert_called_once_with()
            bridge.assert_not_called()

    def test_unavailable_master_falls_back_to_same_devices_bridge(self):
        with patch.object(ros_link, 'NativeLink', side_effect=OSError('unreachable')), \
                patch.object(ros_link, 'BridgeLink') as bridge:
            result = ros_link.open_link({'master_uri': 'http://10.20.0.21:11311',
                                         'bridge_url': 'ws://10.20.0.21:9090'})
            self.assertIs(result, bridge.return_value)
            bridge.assert_called_once_with('ws://10.20.0.21:9090', 3.0)

    def test_unavailable_device_reports_failure_without_using_localhost(self):
        with patch.object(ros_link, 'NativeLink', side_effect=OSError('offline')), \
                patch.object(ros_link, 'BridgeLink', side_effect=OSError('offline')) as bridge:
            with self.assertRaisesRegex(ros_link.LinkError, '10.20.0.21'):
                ros_link.open_link({'master_uri': 'http://10.20.0.21:11311',
                                    'bridge_url': 'ws://10.20.0.21:9090'})
            bridge.assert_called_once_with('ws://10.20.0.21:9090', 3.0)


if __name__ == '__main__':
    unittest.main()
