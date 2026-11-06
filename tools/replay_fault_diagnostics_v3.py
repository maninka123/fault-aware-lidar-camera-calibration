"""Outcome-informed conservative policy replay of saved V3 development evidence.

No captures are reloaded and no calibration or geometric fits are recomputed.
This is not a fresh experiment or an independent validation set.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tools'))
from evaluate_fault_diagnostics import score
from evaluate_fault_diagnostics_v3 import summarize, markdown
from research_calibration.fault_diagnostics.config import DiagnosticsConfig
from research_calibration.fault_diagnostics.policy import decide_experimental, PolicySwitches
from research_calibration.reporting import serializable
from research_calibration.fault_diagnostics_v3.update_policy import conservative_attribution


def conservative_policy(row, name, diagnostics, min_captures):
    """Geometry can veto a held-out attribution, never promote an ambiguous one."""
    old = row['decisions'][name]
    cfg = old['configuration']
    base = decide_experimental(row['v2_evidence'],
        dict(status=row['production']['decision_status'],
             best_relative_gain=row['production'].get('best_relative_gain')),
        diagnostics, PolicySwitches(chance_correction=cfg.get('chance_correction', False),
                                    intensity_cue=False, quality_gating=cfg['scene_quality']),
        min_captures=min_captures)
    out = conservative_attribution(base, copy.deepcopy(old))
    out.update(candidate_calibration=None, policy_replayed=True,
               replay_previous_status=old['status'], replay_previous_hypothesis=old.get('hypothesis'))
    return out


def run(args):
    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    state = json.loads((source/'run_status.json').read_text(encoding='utf-8'))
    if state.get('status') != 'complete' or state.get('trial_errors'):
        raise ValueError('Replay requires a complete error-free source run; defective interrupted rounds are excluded')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new empty replay output folder')
    original_protocol = json.loads((source/'protocol.json').read_text(encoding='utf-8'))
    rows = [json.loads(line) for line in (source/'trials.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    if len(rows) != state['completed_trials']:
        raise ValueError('Source run status and saved trial count disagree')
    diagnostics = DiagnosticsConfig(**original_protocol['diagnostics'])
    code = [Path(__file__), ROOT/'tools/evaluate_fault_diagnostics.py',
            ROOT/'tools/evaluate_fault_diagnostics_v3.py',
            ROOT/'research_calibration/fault_diagnostics/config.py',
            ROOT/'research_calibration/fault_diagnostics/policy.py',
            ROOT/'research_calibration/parameter_hypotheses.py',
            ROOT/'research_calibration/fault_diagnostics_v3/update_policy.py',
            ROOT/'research_calibration/fault_diagnostics_v3/runner.py',
            ROOT/'research_calibration/fault_diagnostics_v3/config.py']
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    # V2 evidence semantics must remain those used by the stored experiment.
    for path in code[3:6]:
        rel = str(path.relative_to(ROOT))
        expected = original_protocol['source_sha256'].get(rel)
        if expected is not None and digest(path) != expected:
            raise ValueError('Cached evidence policy dependency changed: '+rel)
    protocol = dict(mode='outcome_informed_development_policy_replay',
                    source_folder=str(source), source_completed_trials=len(rows),
                    source_files_sha256={name: digest(source/name) for name in
                                         ('trials.jsonl', 'protocol.json', 'src.zip', 'run_status.json')},
                    replay_code_sha256={str(path.relative_to(ROOT)): digest(path) for path in code},
                    rule='Require base DRIFT_SUPPORTED and the same unique hypothesis under all stored geometric fold effects; geometry is a veto only.',
                    unchanged_signature_configuration=original_protocol['signature'],
                    new_capture_loads=0, new_nonlinear_fits=0, new_geometric_computations=0,
                    independent_validation=False,
                    timing='New method_seconds measure policy replay only; cached geometric/fitting costs remain separately named.')
    output.mkdir(parents=True, exist_ok=True)
    (output/'protocol.json').write_text(json.dumps(protocol, indent=2)+'\n', encoding='utf-8')
    with zipfile.ZipFile(output/'src.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in code:
            archive.writestr(path.relative_to(ROOT).as_posix(), path.read_bytes())
    replayed = []
    with (output/'trials.jsonl').open('w', encoding='utf-8') as log:
        for row in rows:
            begin = time.perf_counter()
            new = copy.deepcopy(row)
            new['cached_method_seconds'] = row.get('method_seconds')
            new['original_trial_seconds'] = row.get('seconds')
            new['method_seconds'] = {}
            changes = {}
            for name in row['decisions']:
                if not name.startswith('v3'):
                    continue
                started = time.perf_counter()
                decision = conservative_policy(row, name, diagnostics, original_protocol['research']['min_capture_blocks'])
                new['method_seconds'][name] = time.perf_counter()-started
                new['decisions'][name] = decision
                normalized = copy.deepcopy(decision)
                if normalized['status'] == 'UPDATE_CANDIDATE_VALIDATED':
                    normalized['status'] = 'DRIFT_SUPPORTED'
                new['score'][name] = score(dict(truth_groups=row['truth_groups'], production=row['production'],
                                                experimental={name: normalized}))[name]
                if decision['status'] != row['decisions'][name]['status'] or decision.get('hypothesis') != row['decisions'][name].get('hypothesis'):
                    changes[name] = dict(before=row['decisions'][name]['status'], before_hypothesis=row['decisions'][name].get('hypothesis'),
                                         after=decision['status'], after_hypothesis=decision.get('hypothesis'))
            new['policy_replay'] = dict(mode=protocol['mode'], changes=changes, sensor_evidence_reused=True)
            new['seconds'] = time.perf_counter()-begin
            replayed.append(new)
            log.write(json.dumps(serializable(new), allow_nan=False)+'\n')
    summary = summarize(replayed)
    summary.update(scope='Outcome-informed conservative policy replay on reused development sensor evidence; not a fresh experiment.',
                   source_trials=len(rows), new_capture_loads=0, new_nonlinear_fits=0, new_geometric_computations=0,
                   changed_trial_count=sum(bool(row['policy_replay']['changes']) for row in replayed),
                   timing_scope='Policy replay seconds only; cached_method_seconds and shared_seconds retain original measured computation costs.')
    (output/'summary.json').write_text(json.dumps(serializable(summary), indent=2)+'\n', encoding='utf-8')
    report = markdown(summary).replace('# V3 matched development evaluation', '# V3 conservative policy replay')
    report += '\nNo sensor data or geometry were recomputed. This policy was selected after reviewing the preceding development experiment.\n'
    (output/'summary.md').write_text(report, encoding='utf-8')
    (output/'run_status.json').write_text(json.dumps(dict(status='complete', completed_trials=len(replayed), trial_errors=0), indent=2)+'\n', encoding='utf-8')
    print(report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='Complete saved recorded experiment folder')
    parser.add_argument('--output', required=True, help='New output folder for policy replay')
    run(parser.parse_args())
