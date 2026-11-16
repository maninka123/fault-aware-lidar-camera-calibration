"""Real SSH adapter behavior with mocked command responses; no sensor is contacted."""
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from device_ssh import DeviceSSH, SSHError


class WriteVerificationTests(unittest.TestCase):
    def test_empty_checksum_output_uses_actual_file_readback(self):
        client = DeviceSSH('test')
        with patch.object(client, 'run', side_effect=[(0, '', ''), (0, '', ''), (0, 'new values\n', '')]) as run:
            client.write('/pipeline.yaml', 'new values\n')
        self.assertEqual(run.call_count, 3)
        self.assertTrue(run.call_args.args[0].startswith('cat --'))

    def test_checksum_unavailable_or_malformed_still_requires_matching_readback(self):
        for checksum in ((127, '', 'not found'), (0, 'invalid output', '')):
            client = DeviceSSH('test')
            with self.subTest(checksum=checksum), patch.object(client, 'run', side_effect=[(0, '', ''), checksum, (0, 'different', '')]):
                with self.assertRaises(SSHError):
                    client.write('/pipeline.yaml', 'requested')

    def test_matching_checksum_succeeds_and_mismatching_checksum_is_rejected(self):
        for text, succeeds in (('requested', True), ('other', False)):
            checksum = hashlib.sha256(text.encode()).hexdigest()
            client = DeviceSSH('test')
            with self.subTest(text=text), patch.object(client, 'run', side_effect=[(0, '', ''), (0, checksum + '  /pipeline.yaml\n', '')]):
                if succeeds:
                    client.write('/pipeline.yaml', 'requested')
                else:
                    with self.assertRaises(SSHError):
                        client.write('/pipeline.yaml', 'requested')

    def test_failed_write_command_does_not_proceed_to_verification(self):
        client = DeviceSSH('test')
        with patch.object(client, 'run', return_value=(1, '', 'permission denied')) as run:
            with self.assertRaisesRegex(SSHError, 'permission denied'):
                client.write('/pipeline.yaml', 'requested')
            self.assertEqual(run.call_count, 1)


class OutputCollectionTests(unittest.TestCase):
    def test_exit_status_before_stdout_does_not_discard_late_output(self):
        class Channel:
            eof_received = False
            closed = False
            ready = False
            consumed = False
            def settimeout(self, value): pass
            def exec_command(self, value): pass
            def recv_ready(self): return self.ready and not self.consumed
            def recv_stderr_ready(self): return False
            def exit_status_ready(self): return True
            def recv(self, size):
                self.consumed = True
                return b'late checksum output\n'
            def recv_exit_status(self): return 0
            def close(self): self.closed = True
        channel = Channel()
        client = DeviceSSH('test'); client.transport = Mock()
        client.transport.open_session.return_value = channel
        def arrive(_):
            channel.ready = channel.eof_received = True
        with patch('device_ssh.time.sleep', side_effect=arrive):
            self.assertEqual(client.run('sha256sum file'), (0, 'late checksum output\n', ''))
        self.assertTrue(channel.closed)

    def test_unfinished_output_times_out_and_closes_the_channel(self):
        channel = Mock(eof_received=False, closed=False)
        channel.recv_ready.return_value = channel.recv_stderr_ready.return_value = False
        channel.exit_status_ready.return_value = True
        client = DeviceSSH('test'); client.transport = Mock()
        client.transport.open_session.return_value = channel
        with patch('device_ssh.time.monotonic', side_effect=[0., 2.]), self.assertRaisesRegex(SSHError, 'timed out'):
            client.run('command', timeout=1.)
        channel.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
