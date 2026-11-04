"""SSH to a sensor device, only to update its calibration file (and restart its pipeline when asked).

  credentials   the password the Central Monitoring Platform saved for this device (Windows DPAPI,
                read-only), else one typed in the app (kept only if "remember" is ticked, in the
                Windows Credential Manager)
  host key      checked against the fingerprint the platform or this app trusted before; a first
                connection asks the user to confirm the fingerprint
  commands      locate pipeline.yaml, read it, back it up next to itself, write the new file, check
                its checksum, and (only when asked) restart node-pc.service with sudo
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shlex
from pathlib import Path

import paramiko

CMP_CREDENTIALS = Path(os.environ.get("APPDATA", "")) / "CentralMonitoringPlatform" / "ssh-credentials"
KEYRING_SERVICE = "calibration-maintenance-ssh"
SERVICE = "node-pc.service"
YAML_CANDIDATES = ["~/catkin_ws_actual/src/node_pc/config/pipeline.yaml", "~/catkin_ws/src/node_pc/config/pipeline.yaml"]


class SSHError(RuntimeError):
    pass


def address(host, user, port):
    return f"{user}@{host}:{port}"


def cmp_credential(host, user, port):
    """{password, hostFingerprint} saved by the Central Monitoring Platform for this device, or None."""
    f = CMP_CREDENTIALS / (hashlib.sha256(address(host, user, port).encode()).hexdigest() + ".bin")
    if not f.exists():
        return None
    data = f.read_bytes()
    head = b"CMP-DPAPI-1\n"
    if not data.startswith(head):
        return None
    try:
        import win32crypt
        return json.loads(win32crypt.CryptUnprotectData(data[len(head):], None, None, None, 0)[1].decode())
    except Exception:
        return None


def saved_password(host, user, port):
    """(password, where it came from) or (None, None)."""
    c = cmp_credential(host, user, port)
    if c and c.get("password"):
        return c["password"], "saved by the Central Monitoring Platform"
    try:
        import keyring
        p = keyring.get_password(KEYRING_SERVICE, address(host, user, port))
        if p:
            return p, "saved by this app"
    except Exception:
        pass
    return None, None


def remember_password(host, user, port, password):
    import keyring
    keyring.set_password(KEYRING_SERVICE, address(host, user, port), password)


def fingerprint(key):
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


class DeviceSSH:
    def __init__(self, host, user="rock", port=22, timeout=10.0):
        self.host, self.user, self.port, self.timeout = host, user, int(port), timeout
        self.transport = None

    def open(self, trusted_fingerprint=None):
        """Connect (no login yet). Returns (fingerprint, 'trusted' | 'new'); a changed key is refused."""
        try:
            t = paramiko.Transport((self.host, self.port))
            t.banner_timeout = t.auth_timeout = self.timeout
            t.start_client(timeout=self.timeout)
        except (OSError, paramiko.SSHException) as e:
            raise SSHError(f"cannot reach {self.host}:{self.port} over SSH ({e})") from e
        fp = fingerprint(t.get_remote_server_key())
        trusted = trusted_fingerprint or (cmp_credential(self.host, self.user, self.port) or {}).get("hostFingerprint")
        if trusted and trusted != fp:
            t.close()
            raise SSHError(f"the SSH host key of {self.host} changed ({fp}; trusted {trusted}). "
                           "Verify the device before trusting it again. Nothing was changed.")
        self.transport = t
        return fp, "trusted" if trusted else "new"

    def login(self, password):
        try:
            self.transport.auth_password(self.user, password)
        except paramiko.AuthenticationException as e:
            self.close()
            raise SSHError(f"SSH password rejected for {self.user}@{self.host}") from e
        except paramiko.SSHException as e:
            self.close()
            raise SSHError(f"SSH login failed ({e})") from e

    def run(self, cmd, stdin=None, timeout=60.0):
        """(exit code, stdout, stderr)."""
        ch = self.transport.open_session(timeout=self.timeout)
        ch.settimeout(timeout)
        ch.exec_command(cmd)
        if stdin is not None:
            ch.sendall(stdin if isinstance(stdin, bytes) else stdin.encode())
            ch.shutdown_write()
        out, err = bytearray(), bytearray()
        while True:
            if ch.recv_ready():
                out += ch.recv(65536)
            if ch.recv_stderr_ready():
                err += ch.recv_stderr(65536)
            if ch.exit_status_ready() and not ch.recv_ready() and not ch.recv_stderr_ready():
                break
            ch.status_event.wait(0.05)
        code = ch.recv_exit_status()
        ch.close()
        return code, out.decode(errors="replace"), err.decode(errors="replace")

    # ---- the calibration file
    def find_yaml(self, hint=None):
        cands = ([hint] if hint else []) + YAML_CANDIDATES
        script = "for p in " + " ".join(c.replace("~", '"$HOME"', 1) if c.startswith("~") else shlex.quote(c) for c in cands) \
                 + '; do [ -f "$p" ] && { echo "$p"; exit 0; }; done; ' \
                 "find \"$HOME\" -maxdepth 6 -path '*node_pc/config/pipeline.yaml' 2>/dev/null | head -n 1"
        code, out, _ = self.run(script)
        path = out.strip().splitlines()[0] if out.strip() else ""
        if not path:
            raise SSHError("pipeline.yaml of the sensor pipeline (node_pc/config) was not found on the device")
        return path

    def read(self, path):
        code, out, err = self.run(f"cat -- {shlex.quote(path)}")
        if code:
            raise SSHError(f"cannot read {path}: {err.strip()}")
        return out

    def backup(self, path, stamp):
        dst = f"{path}.calib_backup_{stamp}"
        code, _, err = self.run(f"cp -p -- {shlex.quote(path)} {shlex.quote(dst)}")
        if code:
            raise SSHError(f"backup failed: {err.strip()}")
        return dst

    def write(self, path, text):
        """Write via a temporary file, then copy over the original (keeps its owner and permissions),
        and compare checksums."""
        tmp = f"{path}.calib_new"
        q, qt = shlex.quote(path), shlex.quote(tmp)
        code, _, err = self.run(f"cat > {qt} && cat -- {qt} > {q} && rm -f -- {qt}", stdin=text)
        if code:
            raise SSHError(f"writing {path} failed: {err.strip()}")
        code, out, _ = self.run(f"sha256sum -- {q}")
        if code or out.split()[0] != hashlib.sha256(text.encode()).hexdigest():
            raise SSHError(f"{path} on the device does not match what was written")

    # ---- the pipeline service
    def service_state(self):
        code, out, _ = self.run(f"systemctl is-active {SERVICE}")
        return out.strip() or "unknown"

    def restart(self, sudo_password):
        """Restart the sensor pipeline so the colorizer loads the new calibration."""
        code, _, err = self.run(f"sudo -n systemctl restart {SERVICE}", timeout=120)
        if code:
            code, _, err = self.run(f"sudo -S -p '' systemctl restart {SERVICE}", stdin=sudo_password + "\n", timeout=180)
        if code:
            raise SSHError("restart refused: " + (err.strip().splitlines() or ["sudo failed"])[-1])
        return self.service_state()

    def close(self):
        if self.transport:
            self.transport.close()
