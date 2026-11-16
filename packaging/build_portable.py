"""Build a Windows folder with its own runtime and clean application sources."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Choose a new build folder: ' + str(output))
    with tempfile.TemporaryDirectory(prefix='fa_build_') as work:
        subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                        '--distpath', str(Path(work) / 'dist'), '--workpath', str(Path(work) / 'work'),
                        str(ROOT / 'packaging' / 'FaultAware.spec')], check=True)
        package = Path(work) / 'dist' / 'FaultAwareCalibration'
        app = package / 'app'
        for folder in ('app/gui', 'research/research_calibration', 'app/Calibration maintenance/code', 'app/Targetless calibration/code'):
            for source in (ROOT / folder).rglob('*'):
                relative = source.relative_to(ROOT)
                if source.is_file() and source.suffix in ('.py', '.yaml', '.json', '.svg', '.ico', '.png') \
                        and not any(part in ('__pycache__', 'tests', 'research_artifacts', 'results') for part in relative.parts):
                    target = app / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        for name in ('LICENSE', 'requirements.txt'):
            shutil.copy2(ROOT / name, package / name)
        shutil.copy2(ROOT / 'research_calibration.py', app / 'research_calibration.py')
        shutil.copy2(ROOT / 'packaging' / 'PORTABLE_README.txt', package / 'READ ME.txt')
        subprocess.run([str(package / 'FaultAwareCalibration.exe'), '--diagnose', str(package / 'installation-check.json')], check=True)
        output.mkdir(parents=True)
        archive = shutil.make_archive(str(output / 'FaultAwareCalibration-Windows'), 'zip', package.parent, package.name)
        print('Portable package: ' + archive)


if __name__ == '__main__':
    main()
