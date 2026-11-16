"""One-time dependency installation for a fresh GitHub checkout."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import venv

root = Path(__file__).resolve().parents[1]
if sys.version_info[:2] not in ((3, 10), (3, 11)):
    raise SystemExit('Select Python 3.10 or 3.11, or use the portable Windows package.')
identity = hashlib.sha256(str(root).casefold().encode('utf-8')).hexdigest()[:10]
environment = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'FaultAwareCalibration' / 'envs' / identity
venv.EnvBuilder(with_pip=True).create(environment)
python = environment / 'Scripts' / 'python.exe'
subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(root / 'requirements.txt')], check=True)
subprocess.run([str(python), '-I', str(root / 'packaging' / 'portable_entry.py'), '--diagnose',
                str(environment / 'installation-check.json')], cwd=str(environment), check=True)
(root / '.runtime.json').write_text(json.dumps({'python': str(python)}, indent=2), encoding='utf-8')
print('Setup complete. Start the app with Start.bat. Runtime: ' + str(environment))
