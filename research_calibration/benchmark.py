"""Sequential identical-input recorded-data comparisons with reproducible provenance."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import numpy as np
import scipy
import cv2
from .legacy_adapter import REPOSITORY,load_capture_bundle
from .calibration_pipeline import assess
from .reporting import serializable
from .resources import check_resources

DEFAULT_METHODS=('legacy_optimizer','joint','fault_aware','no_observability','no_selection')


def dataset_paths(dataset,manifest=None):
    path=Path(manifest) if manifest else REPOSITORY/'research_data/manifest.json'
    data=json.loads(path.read_text(encoding='utf-8'))
    root=(REPOSITORY/data['workspace_root_relative_to_repository']).resolve()
    row=next((d for d in data['datasets'] if d['id']==dataset),None)
    if row is None or not row.get('reference_calibration'):
        raise ValueError('Dataset needs a manifest entry with reference_calibration')
    # Check hashes before using a recording; never infer a fault label from the filename.
    for item in row['files']+[row['reference_calibration']]:
        source=root/item['path']
        if hashlib.sha256(source.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Manifest hash mismatch: '+str(source))
    return root/row['reference_calibration']['path'],root/row['data_directory']


def environment():
    files=list((REPOSITORY/'research_calibration').glob('*.py'))
    files += list((REPOSITORY/'Targetless calibration/code').glob('*.py'))
    files += list((REPOSITORY/'Calibration maintenance/code').glob('*.py'))
    files += list((REPOSITORY/'Calibration maintenance/code').glob('*.yaml'))
    files += list((REPOSITORY/'Targetless calibration/code').glob('*.yaml'))
    return dict(python=sys.version,platform=platform.platform(),numpy=np.__version__,scipy=scipy.__version__,
        opencv=cv2.__version__,threads='Sequential; OMP/MKL/OpenBLAS/OpenCV limited to one thread',
        source_sha256={str(p.relative_to(REPOSITORY)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
        memory=check_resources())


def run_benchmark(calibration,captures,output,config,methods=DEFAULT_METHODS):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Benchmark needs a new empty output directory')
    output.mkdir(parents=True,exist_ok=True)
    provenance=environment()
    started=time.perf_counter()
    bundle=load_capture_bundle(captures,output/'inputs',config.max_features_per_capture,config.seed)
    rows=[]; shared_folds=None
    for method in methods:
        check_resources()
        print('Starting '+method,flush=True)
        begin=time.perf_counter()
        result=assess(calibration,captures,method,output=output/method,config=config,progress=lambda s:print(s,flush=True),_bundle=bundle)
        partitions=[(r['test_id'],tuple(r['training_ids'])) for r in result.validation['folds']['KEEP']]
        # Training subsets intentionally differ by selection ablation; test identities must not.
        test_ids=[r[0] for r in partitions]
        outer_ids=result.validation['outer_test']['test_ids']
        if shared_folds is None: shared_folds=(test_ids,outer_ids)
        if shared_folds!=(test_ids,outer_ids): raise RuntimeError('Methods used different test partitions')
        comparison={}
        for name,folds in result.validation['folds'].items():
            values=[f['metrics'].get('loss') for f in folds]
            complete=all(v is not None and np.isfinite(v) for v in values)
            comparison[name]=dict(complete=complete,mean_loss=float(np.mean(values)) if complete else None,
                pooled_capped_edge_rmse_px=float(np.sqrt(sum(f['metrics']['capped_edge_rmse_px']**2*f['metrics']['points'] for f in folds)/sum(f['metrics']['points'] for f in folds))) if complete else None,
                minimum_rank=min(f['rank'] for f in folds))
        rows.append(dict(method=method,status=result.status,selected=result.selected_hypothesis,
            candidate=result.diagnostics['decision'].get('candidate_hypothesis'),
            reason=result.diagnostics['decision']['reason'],comparison=comparison,
            outer_test=result.validation['outer_test'],seconds=time.perf_counter()-begin,memory=check_resources()))
        payload=dict(environment=provenance,configuration=config.to_dict(),methods=rows,seconds=time.perf_counter()-started,
            limitations=['Unlabelled real recordings: no fault-classification accuracy or physical calibration truth.',
                'CV comparisons select models; only the separately reserved outer captures test the chosen candidate.',
                'legacy_optimizer reuses legacy refine inside the common new protocol; strict legacy is a separate API mode.',
                'All methods use the same fixed-support capped nearest-edge test proxy; correspondence ground truth absent.'])
        (output/'benchmark.json').write_text(json.dumps(serializable(payload),indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(f"Finished {method}: {result.status} ({rows[-1]['seconds']:.1f} s)",flush=True)
    lines=['# Recorded-data method comparison','','| Method | Decision | Candidate | Seconds |','|---|---|---|---:|']
    lines += [f"| {r['method']} | {r['status']} | {r['candidate']} | {r['seconds']:.1f} |" for r in rows]
    lines += ['','Capped nearest-edge error is a geometric proxy, not true correspondence reprojection error.',
              'See each method/report.md and benchmark.json for all folds, ranks, candidates, provenance and rejection reasons.']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return payload
