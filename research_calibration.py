"""Compatibility entry point for the engine now grouped under research/."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import runpy
import sys

folder = Path(__file__).resolve().parent / 'research' / 'research_calibration'
spec = spec_from_file_location('research_calibration', folder / '__init__.py', submodule_search_locations=[str(folder)])
package = module_from_spec(spec)
sys.modules['research_calibration'] = package
spec.loader.exec_module(package)
if __name__ == '__main__':
    runpy.run_module('research_calibration', run_name='__main__')
else:
    globals().update(package.__dict__)
