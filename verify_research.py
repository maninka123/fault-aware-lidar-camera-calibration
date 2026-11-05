"""Sequential verification with conservative per-process threads and saved evidence."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--recorded',choices=('creep_three','enclosure_off_ten'),help='Optional local five-method real-data comparison')
    parser.add_argument('--output',type=Path,default=ROOT/'research_artifacts'/datetime.now(timezone.utc).strftime('verification_%Y%m%d_%H%M%S'))
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise FileExistsError('Use a new output directory')
    args.output.mkdir(parents=True,exist_ok=True)
    env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    from research_calibration.resources import check_resources
    results=[]
    tasks=[('legacy_tests',['-m','unittest','discover','-s','Calibration maintenance/code/tests','-v']),
           ('research_tests',['-m','unittest','discover','-s','research_tests','-v'])]
    if args.recorded:
        tasks.append(('recorded',['-m','research_calibration','benchmark','--dataset',args.recorded,'--output',str(args.output/'recorded')]))
    for label,arguments in tasks:
        check_resources(); print('Running '+label,flush=True); start=time.perf_counter()
        command=[sys.executable,'-X','utf8','-B',*arguments]
        with (args.output/(label+'.txt')).open('w',encoding='utf-8') as log:
            process=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
        results.append(dict(name=label,command=command,exit_code=process.returncode,seconds=time.perf_counter()-start))
        print(label+': '+str(process.returncode),flush=True)
        if process.returncode: break
    (args.output/'verification.json').write_text(json.dumps(dict(results=results,memory=check_resources()),indent=2)+'\n',encoding='utf-8')
    if any(r['exit_code'] for r in results): raise SystemExit(1)


if __name__=='__main__': main()
