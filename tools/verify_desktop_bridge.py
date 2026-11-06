"""Optional offscreen, recorded-data test of the new desktop -> research CLI bridge."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # tools/ runs from the repository root's package
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'): os.environ[name]='1'
import json
from pathlib import Path
import sys
from research_calibration.benchmark import dataset_paths
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Calibration maintenance/code'))
from PyQt5 import QtCore,QtWidgets
from research_dialog import ResearchDialog


def main():
    calibration,captures=dataset_paths('creep_three')
    app=QtWidgets.QApplication([])
    from app import SetupPage
    setup=SetupPage()
    setup.prefill(calibration,captures)
    assert setup.research_go.isEnabled(), 'Research entry point did not enable for valid stacked inputs'
    setup.close()
    dialog=ResearchDialog(calibration,captures)
    code=[]
    dialog.process.finished.connect(lambda value,*args:(code.append(value),app.quit()))
    QtCore.QTimer.singleShot(120000,lambda:(dialog.reject(),app.quit()))
    app.exec_()
    path=dialog.output/'assessment.json'
    success=bool(code==[0] and path.exists())
    result=dict(success=success,entry_point_enabled=True,exit_codes=code,output=str(dialog.output),status=json.loads(path.read_text(encoding='utf-8'))['status'] if path.exists() else None)
    (ROOT/'research_artifacts/desktop_bridge.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result))
    dialog.reject()
    if not success: raise SystemExit(1)


if __name__=='__main__': main()
