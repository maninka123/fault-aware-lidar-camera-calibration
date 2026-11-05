"""Build an inspectable summary and scientific plot from actual benchmark JSON only."""
from pathlib import Path
import json
from research_calibration.legacy_adapter import REPOSITORY
from research_calibration.reporting import serializable
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    primary=REPOSITORY/'research_artifacts/final_verification/recorded/benchmark.json'
    data=json.loads(primary.read_text(encoding='utf-8'))
    additional=json.loads((REPOSITORY/'research_artifacts/additional_ablations/index.json').read_text(encoding='utf-8'))
    small=json.loads((REPOSITORY/'research_artifacts/creep_three_final/benchmark.json').read_text(encoding='utf-8'))
    output=REPOSITORY/'docs/research/evaluation'; output.mkdir(parents=True,exist_ok=True)
    summary=dict(primary_dataset='enclosure_off_ten',configuration=data['configuration'],environment=data['environment'],
                 methods=data['methods'],additional_ablations=additional,small_dataset=small['methods'],limitations=data['limitations'])
    initialization=json.loads((REPOSITORY/'research_artifacts/guarded_initialization_v2/verification.json').read_text(encoding='utf-8'))
    samples=initialization['memory_samples']
    scope=json.loads((REPOSITORY/'research_artifacts/initialization_scope_verified/assessment/assessment.json').read_text(encoding='utf-8'))
    summary['initialization']=dict(exit_code=initialization['exit_code'],seconds=initialization['seconds'],stopped=initialization['stopped'],
        max_sampled_process_mb=max(s['process_mb'] for s in samples if s['process_mb'] is not None),
        min_sampled_available_mb=min(s['available_mb'] for s in samples if s['available_mb'] is not None),
        status=scope['status'],uncertainty_status=scope['uncertainty']['status'],independent_validation=False,
        inherited_heuristic_label=scope['diagnostics']['initialization']['inherited_heuristic_label'])
    (output/'results_summary.json').write_text(json.dumps(serializable(summary),indent=2,allow_nan=False)+'\n',encoding='utf-8')
    names=['KEEP','R','T','I','RT','RI','TI','RTI']
    labels={'legacy_optimizer':'Legacy refine','joint':'Joint','fault_aware':'Fault-aware',
            'no_observability':'No observability','no_selection':'All training'}
    fig,axes=plt.subplots(1,2,figsize=(12.2,4.6),gridspec_kw={'width_ratios':[1.35,1]})
    colors=['#667085','#7b61a8','#1460cf','#d18622','#1b8c6f']
    gains=[]
    for row,color in zip(data['methods'],colors):
        values=[row['comparison'].get(name,{}).get('pooled_capped_edge_rmse_px',np.nan) for name in names]
        values=[np.nan if value is None else value for value in values]
        axes[0].plot(range(len(names)),values,marker='o',markersize=4,linewidth=1.2,label=labels[row['method']],color=color)
        comp=row['comparison']
        complete=all(v['complete'] for v in comp.values())
        gain=100*(1-min(v['mean_loss'] for v in comp.values())/comp['KEEP']['mean_loss']) if complete else np.nan
        gains.append(gain)
    axes[0].set(xticks=range(len(names)),xticklabels=names,ylabel='Pooled capped nearest-edge RMSE (px)',
                xlabel='Allowed parameter-change model',title='Recorded comparison · same 7 CV captures')
    axes[0].legend(fontsize=8,loc='upper left',ncol=2)
    axes[0].grid(axis='y',alpha=.18)
    axes[1].bar(range(5),gains,color=colors,width=.6)
    axes[1].axhline(1,color='#b32b32',linestyle='--',linewidth=1,label='Declared minimum: 1%')
    for i,gain in enumerate(gains):
        axes[1].text(i,.03 if not np.isfinite(gain) else gain+.025,'Incomplete' if not np.isfinite(gain) else f'{gain:.2f}%',
                     ha='center',fontsize=8,rotation=90 if not np.isfinite(gain) else 0)
    axes[1].set(xticks=range(5),xticklabels=['Legacy','Joint','Fault-aware','No obs.','All train.'],ylim=(0,1.18),xlim=(-.7,4.7),
                ylabel='Best CV mean squared-loss reduction (%)',title='No method supports an accepted update')
    axes[1].tick_params(axis='x',labelrotation=20); axes[1].legend(fontsize=8,loc='upper right')
    axes[1].grid(axis='y',alpha=.18); axes[1].set_axisbelow(True)
    for ax in axes:
        ax.spines[['top','right']].set_visible(False)
    fig.text(.05,.018,'No fault/correspondence ground truth. Legacy RTI has one invalid fold: its aggregate is unavailable. Error is capped at 30 px.',fontsize=8,color='#475467')
    fig.tight_layout(rect=(0,.07,1,1))
    fig.savefig(output/'recorded_comparison.png',dpi=160)
    plt.close(fig)
    print('Wrote '+str(output))


if __name__=='__main__': main()
