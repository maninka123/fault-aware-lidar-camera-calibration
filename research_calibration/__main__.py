"""python -B -m research_calibration --help"""
import argparse
import json
from pathlib import Path
from .config import ResearchConfig
from .calibration_pipeline import assess,calibrate_from_scratch,STRATEGIES
from .benchmark import dataset_paths,run_benchmark,DEFAULT_METHODS


def main():
    parser=argparse.ArgumentParser(description='Offline fault-aware calibration research backend; sequential CPU execution')
    parser.add_argument('command',choices=('assess','benchmark','initialize'))
    parser.add_argument('--dataset',help='Hash-verified local dataset ID in research_data/manifest.json')
    parser.add_argument('--calibration',type=Path)
    parser.add_argument('--captures',type=Path)
    parser.add_argument('--output',required=True,type=Path,help='New run folder; existing assessments are never overwritten')
    parser.add_argument('--strategy',choices=STRATEGIES,default='fault_aware')
    parser.add_argument('--methods',nargs='+',choices=[m for m in STRATEGIES if m!='legacy'],default=list(DEFAULT_METHODS))
    parser.add_argument('--cloud-units',choices=('m','mm'),default='m',help='Units of image+PCD clouds')
    parser.add_argument('--confirm-cloud-units',action='store_true',help='Accept unusual coordinate ranges after review')
    parser.add_argument('--config',type=Path,help='JSON overrides for ResearchConfig')
    args=parser.parse_args()
    # Legacy decoders resolve relative paths against their own folders; always hand them absolute paths.
    for name in ('output','calibration','captures'):
        if getattr(args,name): setattr(args,name,getattr(args,name).resolve())
    cfg=ResearchConfig(**(json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}))
    calibration,captures=args.calibration,args.captures
    if args.dataset:
        if calibration or captures: parser.error('Choose --dataset or explicit paths')
        calibration,captures=dataset_paths(args.dataset)
    if not captures or (args.command!='initialize' and not calibration): parser.error('Capture and reference paths are required')
    if args.command=='benchmark':
        run_benchmark(calibration,captures,args.output,cfg,args.methods)
    else:
        result=calibrate_from_scratch(captures,output=args.output,config=cfg) if args.command=='initialize' else assess(
            calibration,captures,args.strategy,output=args.output,config=cfg,cloud_units=args.cloud_units,allow_unusual_units=args.confirm_cloud_units,progress=lambda s:print(s,flush=True))
        print(result.status+': '+result.recommended_action)
    print('Reports: '+str(args.output.resolve()))


if __name__=='__main__': main()
