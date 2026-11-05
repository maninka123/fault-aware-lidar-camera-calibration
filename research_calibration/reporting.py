"""Computed-only JSON and Markdown reports; no confidence ratings or invented truth."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import math
import numpy as np
from .legacy_adapter import io_path


def serializable(value):
    if isinstance(value,np.ndarray):
        return serializable(value.tolist())
    if isinstance(value,np.generic):
        return serializable(value.item())
    if isinstance(value,float) and not math.isfinite(value):
        return None
    if isinstance(value,dict):
        return {str(k):serializable(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):
        return [serializable(v) for v in value]
    if isinstance(value,Path):
        return str(value)
    return value


@dataclass
class AssessmentResult:
    status: str
    selected_hypothesis: str
    observable_parameters: list
    unobservable_directions: object
    parameter_updates: dict
    uncertainty: dict
    validation: dict
    recommended_action: str
    updated_calibration: dict
    diagnostics: dict

    def to_dict(self):
        return serializable(asdict(self))

    def save(self,output):
        output = io_path(output); output.mkdir(parents=True,exist_ok=True)
        data = self.to_dict()
        (output/'assessment.json').write_text(json.dumps(data,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        (output/'updated_calibration.json').write_text(json.dumps(data['updated_calibration'],indent=2,allow_nan=False)+'\n',encoding='utf-8')
        lines = ['# Fault-aware calibration assessment','',f'**Status:** {self.status}',
                 f'**Selected allowed-change model:** {self.selected_hypothesis}',
                 f'**Action:** {self.recommended_action}','',
                 'Hypothesis names describe mathematical parameter constraints; they are not verified physical fault labels.','',
                 '## Inputs','',f"- Captures: {self.diagnostics.get('input',{}).get('captures',[])}",
                 f"- Strategy: {self.diagnostics.get('strategy')}",
                 f"- Reference SHA-256: {self.diagnostics.get('input',{}).get('reference_sha256')}",
                 '', '## Model comparison','', '| Model | Mean CV capped edge RMSE (px) | Folds |', '|---|---:|---:|']
        for name, rows in self.validation.get('folds',{}).items():
            values=[r['metrics']['capped_edge_rmse_px'] for r in rows if r.get('metrics',{}).get('valid')]
            lines.append(f'| {name} | {np.mean(values):.4f} | {len(values)} |' if values else f'| {name} | unavailable | 0 |')
        if not self.validation.get('folds'):
            lines.append('| See mode-specific evidence below | unavailable | 0 |')
        lines += ['', 'These are capped nearest-edge proxies on declared test support, not known-point reprojection errors.',
                  '', '## Diagnosis and observability','',f"- Candidate ambiguity set: {self.diagnostics.get('decision',{}).get('ambiguity_set',[])}",
                  f"- Comparison decision: {self.diagnostics.get('decision',{}).get('reason','See mode-specific evidence')}",
                  f"- Fully supported scalar coordinates under the candidate model: {self.observable_parameters}",
                  f"- Conditional uncertainty status: {self.uncertainty.get('status')}",
                  f"- Final directional support: {self.diagnostics.get('stable_support',{}).get('candidate_update_supported_fraction','unavailable')}",
                  '', '## Proposed and accepted changes','',
                  'Proposed changes describe the candidate; accepted changes remain zero when the reference is retained.',
                  '', '| Coordinate | Proposed delta | Accepted delta | Unit |','|---|---:|---:|---|']
        units={**dict.fromkeys(('wx','wy','wz','beam'),'rad'),**dict.fromkeys(('tx','ty','tz'),'m'),
               **dict.fromkeys(('fx','fy','cx','cy'),'px'),'k1':'dimensionless','k2':'dimensionless'}
        proposed=self.diagnostics.get('candidate_parameter_updates',{})
        for name,unit in units.items():
            change=proposed.get(name)
            value=f'{change:+.6g}' if isinstance(change,(int,float)) else 'unavailable'
            accepted=self.parameter_updates.get(name)
            accepted=f'{accepted:+.6g}' if isinstance(accepted,(int,float)) else 'unavailable'
            lines.append(f'| {name} | {value} | {accepted} | {unit} |')
        traces=self.diagnostics.get('optimization',[])
        if traces:
            lines += ['', '## Optimizer','', '| Iteration | Variant rows | Reduced rank | Success |','|---:|---|---:|---|']
            lines += [f"| {row['iteration']+1} | {row['rows']} | {row['rank']} | {row['success']} |" for row in traces]
        legacy=data['validation'].get('legacy_summary')
        if legacy:
            lines += ['', '## Original workflow','',f"- Verdict: {legacy.get('verdict')}",
                      f"- Movement: {legacy.get('shift_median_px')} px (not remaining error)",
                      f"- Sensitivity spread: {legacy.get('shift_uncertainty_px')} px",
                      f"- Original outputs: Calibration maintenance/results/{legacy.get('run')}"]
        initialization=self.diagnostics.get('initialization')
        if initialization:
            lines += ['', '## Initialization scope','',
                f"- Inherited heuristic label: {initialization.get('inherited_heuristic_label')} (not calibrated accuracy).",
                '- All captures were used by the initializer; there is no untouched initialization test.',
                '- No historical fault attribution or initial scalar-support claim is made.',
                '- Later conditional refinement diagnostics: [conditional_assessment.json](conditional_assessment.json).']
        lines += ['', '## Independent outer test','', '```json',json.dumps(data['validation'].get('outer_test',{}),indent=2),'```',
                  '', '## Limits','']
        lines += ['- '+text for text in self.diagnostics.get('limitations',[])]
        lines += ['', 'Maintenance rejections retain their input reference. Initial-calibration outputs remain candidates requiring independent review.',
                  'See docs/research/PAPER_TO_ALGORITHM.md and NOVELTY_ASSESSMENT.md for prior-art and originality limits.']
        (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
