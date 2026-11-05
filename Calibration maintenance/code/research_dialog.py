"""Small offline research entry point; reports have no accept/device-write controls."""
from datetime import datetime
import json
from pathlib import Path
import sys
from PyQt5 import QtCore,QtGui,QtWidgets

REPOSITORY=Path(__file__).resolve().parents[2]


class ResearchDialog(QtWidgets.QDialog):
    def __init__(self,calibration,captures,parent=None):
        super().__init__(parent)
        self.setWindowTitle('Offline research assessment')
        self.resize(660,380)
        self.output=REPOSITORY/'research_artifacts'/datetime.now().strftime('desktop_%Y%m%d_%H%M%S_%f')
        layout=QtWidgets.QVBoxLayout(self)
        self.status=QtWidgets.QLabel('Comparing constrained camera and alignment changes…')
        self.status.setWordWrap(True); layout.addWidget(self.status)
        note=QtWidgets.QLabel('Recorded data only · reference retained unless validation supports a candidate')
        note.setWordWrap(True); layout.addWidget(note)
        self.log=QtWidgets.QPlainTextEdit(); self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000); layout.addWidget(self.log,1)
        actions=QtWidgets.QHBoxLayout()
        self.open_button=QtWidgets.QPushButton('Open reports folder'); self.open_button.setEnabled(False)
        self.open_button.clicked.connect(lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(self.output))))
        self.done=QtWidgets.QPushButton('Stop'); self.done.clicked.connect(self.reject)
        actions.addWidget(self.open_button); actions.addStretch(); actions.addWidget(self.done); layout.addLayout(actions)
        self.process=QtCore.QProcess(self)
        self.process.setWorkingDirectory(str(REPOSITORY))
        environment=QtCore.QProcessEnvironment.systemEnvironment()
        for name in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'): environment.insert(name,'1')
        environment.insert('PYTHONUTF8','1'); environment.insert('PYTHONDONTWRITEBYTECODE','1')
        self.process.setProcessEnvironment(environment)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished_run)
        self.process.errorOccurred.connect(lambda error:self.status.setText('Unable to complete the assessment. See the log.'))
        executable=Path(sys.executable)
        if executable.name.lower()=='pythonw.exe': executable=executable.with_name('python.exe')
        self.process.start(str(executable),['-X','utf8','-B','-m','research_calibration','assess',
            '--calibration',str(calibration),'--captures',str(captures),'--output',str(self.output)])

    def read_output(self):
        self.log.appendPlainText(bytes(self.process.readAllStandardOutput()).decode('utf-8',errors='replace').rstrip())

    def finished_run(self,code,*args):
        self.read_output(); self.done.setText('Done'); self.open_button.setEnabled(self.output.exists())
        path=self.output/'assessment.json'
        if code==0 and path.exists():
            result=json.loads(path.read_text(encoding='utf-8'))
            self.status.setText(result['status'].replace('_',' ').capitalize()+' · '+result['recommended_action'].replace('_',' ').lower())
        else: self.status.setText('Assessment stopped. The reference calibration is unchanged. See the log.')

    def reject(self):
        if self.process.state()!=QtCore.QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(1000): self.process.kill(); self.process.waitForFinished(1000)
        super().reject()

    def closeEvent(self,event):
        self.reject(); event.accept()
