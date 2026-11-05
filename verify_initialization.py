"""Watchdog for one inherited initializer run; controls only its own child process."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from research_calibration.resources import check_resources,memory_status

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--dataset',default='creep_three')
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise FileExistsError('Use a new output directory')
    args.output.mkdir(parents=True,exist_ok=True)
    check_resources()
    command=[sys.executable,'-X','utf8','-B','-m','research_calibration','initialize','--dataset',args.dataset,'--output',str(args.output/'run')]
    env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONUTF8='1')
    start=time.perf_counter(); readings=[]; stopped=None
    flags=getattr(subprocess,'CREATE_NO_WINDOW',0)|getattr(subprocess,'BELOW_NORMAL_PRIORITY_CLASS',0)
    with (args.output/'initializer.txt').open('w',encoding='utf-8') as log:
        child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        try:
            while child.poll() is None:
                state=memory_status(child.pid); readings.append(dict(seconds=time.perf_counter()-start,**state))
                if (state['available_mb'] is not None and state['available_mb']<4096 or
                    state['process_mb'] is not None and state['process_mb']>1536):
                    stopped='Memory watchdog'; break
                if time.perf_counter()-start>args.timeout:
                    stopped='Timeout watchdog'; break
                time.sleep(2)
        finally:
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
    result=dict(command=command,exit_code=child.returncode,seconds=time.perf_counter()-start,stopped=stopped,memory_samples=readings)
    (args.output/'verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='memory_samples'}))
    if child.returncode or stopped: raise SystemExit(1)


if __name__=='__main__': main()
