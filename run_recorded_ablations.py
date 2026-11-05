"""Additional one-factor ablations, sequentially on the same recorded partitions."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
from research_calibration.config import ResearchConfig
from research_calibration.benchmark import dataset_paths,run_benchmark


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dataset',default='enclosure_off_ten')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()): raise FileExistsError('Use a new output directory')
    calibration,captures=dataset_paths(args.dataset)
    cfg=ResearchConfig(); experiments=[('single_variant',cfg,'single_variant')]
    experiments += [('selection_'+s,replace(cfg,selection_strategy=s),'fault_aware') for s in ('random','feature_count','d_optimal','e_optimal')]
    index=[]
    for label,config,strategy in experiments:
        payload=run_benchmark(calibration,captures,args.output/label,config,(strategy,))
        index.append(dict(label=label,configuration=config.to_dict(),result=payload['methods'][0]))
        (args.output/'index.json').write_text(json.dumps(index,indent=2,allow_nan=False)+'\n',encoding='utf-8')


if __name__=='__main__': main()
