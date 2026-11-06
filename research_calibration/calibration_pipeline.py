"""Training-only observability, constrained fits, independent checks, and abstention."""
import copy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import numpy as np
from .config import ResearchConfig
from .legacy_adapter import REPOSITORY, legacy_modules, load_capture_bundle, read_calibration, io_path
from .geometry import ProjectionModel, parameters, retract, calibration_from_parameters
from .parameter_hypotheses import HYPOTHESES, GROUPS, NUISANCE, PARAMETERS, parameter_scales
from .observability import numerical_jacobian, analyze_observability, hypothesis_basis, ensemble_attribution
from .selective_optimizer import optimize_selective
from .residuals import associate, evaluate_capture
from .uncertainty import cluster_uncertainty
from .evidence_selection import select_captures
from .decision_policy import decide
from .reporting import AssessmentResult, serializable
from .resources import check_resources
from .progress_events import Events, number


STRATEGIES = ('fault_aware','joint','no_observability','no_selection','single_variant','legacy_optimizer','legacy')


def _variants(caps,model,p,scales,cfg,ensemble=True):
    gates = cfg.association_gates if ensemble else (cfg.association_gates[1 if len(cfg.association_gates)>1 else 0],)
    batches = [associate(caps,model,p,gate,max_rows=cfg.max_association_rows) for gate in gates]
    matrices = [numerical_jacobian(lambda q,b=batch:b.residual(model,q),p,scales,retract) for batch in batches]
    return batches,matrices


def _training_selection(caps,model,baseline,scales,cfg,strategy):
    if strategy in ('no_selection','joint','legacy_optimizer') or len(caps)<=cfg.training_budget:
        return list(caps),dict(selected_ids=[c.name for c in caps],strategy='all',training_only=True)
    values = [_variants([cap],model,baseline,scales,cfg)[1] for cap in caps]
    selection = select_captures(values,scales,GROUPS,capture_ids=[c.name for c in caps],
                                training_ids=[c.name for c in caps],budget=cfg.training_budget,
                                strategy=cfg.selection_strategy,seed=cfg.seed)
    return [caps[i] for i in selection['selected_indices']],selection


def fit_hypothesis(caps,model,baseline,hypothesis,cfg,strategy):
    scales = parameter_scales(baseline)
    p = baseline.copy(); last = None; traces=[]
    ensemble = strategy not in ('single_variant','legacy_optimizer')
    for iteration in range(cfg.iterations):
        check_resources()
        batches,Js = _variants(caps,model,p,scales,cfg,ensemble)
        if min(len(batch.xyz) for batch in batches)<30:
            return dict(success=False,reason='Too few training edge associations',parameters=baseline.copy(),rank=0)
        if strategy in ('joint','no_observability','legacy_optimizer'):
            B = np.eye(13)[:,list(hypothesis.indices)]
            support = dict(basis=B,rank=B.shape[1],calibration_rank=len(hypothesis.indices)-1,
                           unobservable_directions=np.eye(13)[:,[i for i in range(13) if i not in hypothesis.indices]])
        else:
            support = hypothesis_basis(Js,hypothesis.indices,NUISANCE,scales,ensemble=ensemble,
                                       rank_rtol=cfg.rank_rtol,minimum_singular=cfg.minimum_singular,
                                       support_floor=cfg.support_floor)
            B = support['basis']
        batch = batches[len(batches)//2]
        if strategy=='legacy_optimizer':
            # Explicit frozen legacy optimizer comparator, evaluated by the same new test loss.
            legacy=legacy_modules(); rcfg=copy.deepcopy(legacy.settings.load_config())
            rcfg['calib']['gates_px']=[9.,6.,3.,2.]
            try:
                value,_=legacy.cb.refine(caps,model,p,list(hypothesis.indices),rcfg,
                                         dict(cx=baseline[8],cy=baseline[9]),log=lambda *args:None,passes=2,
                                         gates=[4,3,2,2] if hypothesis.name=='KEEP' else None)
                valid=model.valid(value)
                solution=dict(parameters=value,success=valid,message='Frozen legacy refine' if valid else
                              'Legacy candidate violates the research camera/domain bounds')
            except (ValueError,np.linalg.LinAlgError) as error:
                solution=dict(parameters=p,success=False,message=str(error))
        else:
            solution=optimize_selective(lambda q:batch.residual(model,q),p,hypothesis.indices,scales,B,
                                        retract,model.valid,max_nfev=cfg.max_nfev)
        traces.append(dict(iteration=iteration,rows=[len(b.xyz) for b in batches],rank=support['rank'],
                           success=solution['success'],message=solution['message']))
        if not solution['success']:
            return dict(success=False,reason=solution['message'],parameters=baseline.copy(),rank=support['rank'],traces=traces)
        p=solution['parameters']; last=(batch,Js,support)
    # Diagnostics describe the final point, not the pre-update linearization.
    batches,Js=_variants(caps,model,p,scales,cfg,ensemble)
    batch=batches[len(batches)//2]
    if strategy not in ('joint','no_observability','legacy_optimizer'):
        support=hypothesis_basis(Js,hypothesis.indices,NUISANCE,scales,ensemble=ensemble,
                                 rank_rtol=cfg.rank_rtol,minimum_singular=cfg.minimum_singular,
                                 support_floor=cfg.support_floor)
    attribution=ensemble_attribution(Js,scales,GROUPS,NUISANCE,rank_rtol=cfg.rank_rtol,
                                     minimum_singular=cfg.minimum_singular,support_floor=cfg.support_floor)
    normalized=(p-baseline)/scales
    unique_support={}
    for key,value in attribution.items():
        update=normalized[list(GROUPS[key])]
        energy=float(update@update)
        fraction=float(np.linalg.norm(value['basis'].T@update)**2/energy) if energy>1e-12 else 0.
        value['candidate_update_supported_fraction']=fraction
        unique_support[key]=bool(value['rank']>0 and fraction>=cfg.support_floor)
    calibration_update=normalized.copy(); calibration_update[list(NUISANCE)]=0.
    energy=float(calibration_update@calibration_update)
    fraction=float(np.linalg.norm(support['basis'].T@calibration_update)**2/energy) if energy>1e-12 else 1.
    support['candidate_update_supported_fraction']=fraction
    supported_update=bool(fraction>=cfg.support_floor)
    uncertainty=cluster_uncertainty(Js[len(Js)//2],batch.residual(model,p),batch.cluster_ids,scales,support['basis'],
                                    rank_rtol=cfg.rank_rtol,min_clusters=cfg.min_capture_blocks)
    return dict(success=True,parameters=p,rank=support['rank'],support=support,attribution=attribution,
                attribution_support=unique_support,uncertainty=uncertainty,traces=traces,
                supported_update=supported_update,
                diagnostics=analyze_observability(Js[len(Js)//2],scales,GROUPS,NUISANCE,
                                                  rank_rtol=cfg.rank_rtol,minimum_singular=cfg.minimum_singular))


def assess(calibration,captures,strategy='fault_aware',*,output=None,config=None,cloud_units='m',allow_unusual_units=False,progress=None,_bundle=None):
    cfg=config if isinstance(config,ResearchConfig) else ResearchConfig(**(config or {}))
    if strategy not in STRATEGIES:
        raise ValueError('Unknown strategy: '+strategy)
    output=Path(output) if output else REPOSITORY/'research_artifacts'/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Use a new empty output folder; existing files will not be overwritten')
    output.mkdir(parents=True,exist_ok=True)
    original=read_calibration(calibration)
    if strategy=='legacy':
        return _legacy_assess(original,calibration,captures,output)
    events=Events(output)
    events.emit('data',message='Decoding and stacking the captures')
    bundle=_bundle or load_capture_bundle(captures,output/'inputs',cfg.max_features_per_capture,cfg.seed,cloud_units,allow_unusual_units)
    events.emit('features',captures=bundle.metadata,max_features=cfg.max_features_per_capture)
    if original.get('image_size') and list(original['image_size'])!=list(bundle.size):
        raise ValueError('Calibration and capture image resolutions differ')
    model=ProjectionModel(original,bundle.size,bundle.circle,cfg.max_angle_rad)
    baseline=parameters(original)
    if not model.valid(baseline):
        raise ValueError('Reference camera model is invalid over the declared angular domain')
    caps=bundle.caps
    if len(caps)<2:
        raise ValueError('At least two recorded captures are needed')
    permutation=np.random.default_rng(cfg.seed).permutation(len(caps))
    outer_count=max(2,int(np.ceil(len(caps)*cfg.outer_fraction))) if len(caps)>=cfg.min_capture_blocks+3 else 0
    outer_indices=set(int(i) for i in permutation[:outer_count])
    train=[c for i,c in enumerate(caps) if i not in outer_indices]
    outer=[c for i,c in enumerate(caps) if i in outer_indices]
    hypotheses=HYPOTHESES
    if strategy=='joint':
        hypotheses=tuple(h for h in HYPOTHESES if h.name in ('KEEP','RTI'))
    if strategy=='legacy_optimizer':
        hypotheses=tuple(h for h in HYPOTHESES if h.name in ('KEEP','RT','I','RTI'))
    losses={h.name:[] for h in hypotheses}; folds={h.name:[] for h in hypotheses}
    ranks={h.name:[] for h in hypotheses}; supports={h.name:[] for h in hypotheses}
    selections=[]
    events.emit('folds',total=len(train),outer=len(outer),hypotheses=[h.name for h in hypotheses],
                min_relative_gain=cfg.min_relative_gain)
    for index,test in enumerate(train):
        check_resources()
        if progress:
            progress(f'{strategy}: comparison fold {index+1}/{len(train)} ({test.name})')
        events.emit('fold',index=index,total=len(train),test=test.name)
        available=train[:index]+train[index+1:]
        selected,selection=_training_selection(available,model,baseline,parameter_scales(baseline),cfg,strategy)
        selections.append(dict(test_id=test.name,**selection))
        for h in hypotheses:
            fitted=fit_hypothesis(selected,model,baseline,h,cfg,strategy)
            metric=evaluate_capture(test,model,fitted['parameters'],baseline,cfg.evaluation_cap_px) if fitted['success'] else dict(valid=False,loss=None)
            value=metric.get('loss')
            events.emit('fit',fold=index,test=test.name,hypothesis=h.name,loss=number(value),success=bool(fitted['success']),
                        rank=int(fitted['rank']))
            losses[h.name].append(value if value is not None else float('nan'))
            ranks[h.name].append(fitted['rank'])
            supports[h.name].append(all(fitted.get('attribution_support',{}).get(group,False) for group in h.groups))
            folds[h.name].append(dict(test_id=test.name,training_ids=[c.name for c in selected],metrics=metric,
                                       fitting_success=fitted['success'],fitting_reason=fitted.get('reason'),rank=fitted['rank']))
    attribution={h.name:bool(supports[h.name] and all(supports[h.name])) for h in hypotheses}
    if strategy in ('joint','no_observability','legacy_optimizer'):
        # Ablations intentionally omit attribution gating; reports identify this explicitly.
        attribution={h.name:True for h in hypotheses}
    decision=decide(losses,{name:int(max(values,default=0)) for name,values in ranks.items()},
                    {h.name:h.groups for h in hypotheses},attribution,min_captures=cfg.min_capture_blocks,
                    min_relative_gain=cfg.min_relative_gain,bootstrap_reps=cfg.bootstrap_reps,seed=cfg.seed)
    candidate_name=decision.get('candidate_hypothesis') or 'KEEP'
    events.emit('decision',status=decision.get('status'),candidate=candidate_name,best_relative_gain=number(decision.get('best_relative_gain')),
                min_relative_gain=cfg.min_relative_gain,reason=decision.get('reason'),mean_losses=decision.get('mean_losses'))
    candidate_h=next(h for h in hypotheses if h.name==candidate_name)
    events.emit('candidate',hypothesis=candidate_name)
    selected,final_selection=_training_selection(train,model,baseline,parameter_scales(baseline),cfg,strategy)
    candidate=fit_hypothesis(selected,model,baseline,candidate_h,cfg,strategy)
    outer_metrics=[]
    if candidate['success']:
        for cap in outer:
            outer_metrics.append(dict(id=cap.name,baseline=evaluate_capture(cap,model,baseline,baseline,cfg.evaluation_cap_px),
                                      candidate=evaluate_capture(cap,model,candidate['parameters'],baseline,cfg.evaluation_cap_px)))
    valid_outer=bool(len(outer_metrics)>=3 and all(row['baseline']['valid'] and row['candidate']['valid'] for row in outer_metrics))
    gain=None
    if valid_outer:
        before=np.mean([row['baseline']['loss'] for row in outer_metrics]); after=np.mean([row['candidate']['loss'] for row in outer_metrics])
        gain=float((before-after)/before) if before>0 else 0.
        valid_outer=bool(gain>=cfg.min_relative_gain and all(row['candidate']['coverage']>=cfg.min_coverage for row in outer_metrics)
                         and sum(row['candidate']['loss']<row['baseline']['loss'] for row in outer_metrics)/len(outer_metrics)>=2/3)
    events.emit('outer',count=len(outer),gain=number(gain),passed=bool(valid_outer))
    uncertainty=candidate.get('uncertainty',dict(status='UNAVAILABLE'))
    accepted=bool(decision['status']=='CANDIDATE_SUPPORTED' and candidate['success'] and valid_outer
                  and uncertainty.get('status')=='CONDITIONAL_ONLY'
                  and (candidate.get('supported_update',False) or strategy in ('joint','no_observability','legacy_optimizer'))
                  and (all(candidate.get('attribution_support',{}).get(g,False) for g in candidate_h.groups)
                       or strategy in ('joint','no_observability','legacy_optimizer')))
    status='UPDATE_SUPPORTED' if accepted else 'KEEP_CURRENT' if decision['status']=='KEEP_CURRENT' else 'INSUFFICIENT_EVIDENCE'
    updated=calibration_from_parameters(original,model,candidate['parameters']) if accepted else copy.deepcopy(original)
    candidate_cal=calibration_from_parameters(original,model,candidate['parameters']) if candidate['success'] else None
    scale=parameter_scales(baseline)
    support=candidate.get('support',{})
    basis=support.get('basis',np.zeros((13,0)))
    diagnostics=dict(input=dict(reference_sha256=hashlib.sha256(json.dumps(original,sort_keys=True).encode()).hexdigest(),
                                captures=bundle.metadata,source=bundle.source,camera_model='OpenCV equidistant polynomial with fixed higher terms',
                                evaluation_domain=dict(circle=bundle.circle,max_angle_rad=cfg.max_angle_rad,
                                                       rule='Predeclared inscribed image circle; no test appearance used')),
                     strategy=strategy,configuration=cfg.to_dict(),decision=decision,selections=selections,
                     final_training_selection=final_selection,observability=candidate.get('diagnostics',{}),
                     stable_support=support,attribution=candidate.get('attribution',{}),optimization=candidate.get('traces',[]),
                     candidate_calibration=candidate_cal,
                     candidate_parameter_updates={name:float(value) for name,value in zip(PARAMETERS,candidate['parameters']-baseline)},
                     limitations=['No verified physical drift/fault labels exist for these recordings.',
                         'Nearest-edge loss can match the wrong scene edge; it is not ground-truth reprojection error.',
                         'Finite correspondence variants are stress tests, not a distribution over every possible association.',
                         'Bootstrap and sandwich quantities are conditional, not calibrated fault probabilities or guaranteed intervals.',
                         'Static captures within one scene/session may remain dependent.',
                         'No simulator, hardware write or publication was performed.',
                         'Novelty is provisional; TSVD, conditional information and maximin design are established.'])
    result=AssessmentResult(status,candidate_name if accepted else 'KEEP',
        [PARAMETERS[i] for i in range(13) if np.sum(basis[i]**2)>1-1e-6],support.get('unobservable_directions',np.eye(13)),
        {name:float(value) if accepted else 0. for name,value in zip(PARAMETERS,candidate['parameters']-baseline)},uncertainty,
        dict(folds=folds,outer_test=dict(training_ids=[c.name for c in train],test_ids=[c.name for c in outer],
             metrics=outer_metrics,relative_gain=gain,passed=valid_outer,
             note='Outer test not used by selection/optimization; three independent capture blocks required.')),
        'REVIEW_SUPPORTED_CANDIDATE' if accepted else 'KEEP_REFERENCE_AND_COLLECT_MORE_DIVERSE_CAPTURES' if status!='KEEP_CURRENT' else 'KEEP_REFERENCE',
        updated,diagnostics)
    result.save(output)
    events.emit('verdict',status=status,action=result.recommended_action)
    return result


def _legacy_assess(original,path,captures,output):
    legacy=legacy_modules()
    reference=output/'legacy_reference.json'
    reference.write_text(json.dumps(original,indent=2),encoding='utf-8')
    run_name=datetime.now(timezone.utc).strftime('research_legacy_%Y%m%d_%H%M%S_%f')
    summary=legacy.maintain.run(reference,captures,run_name,'compare','research')
    result=AssessmentResult('LEGACY_COMPLETED','legacy',[],[],{},dict(status='LEGACY_CONDITIONAL'),
                             dict(legacy_summary=summary),'REVIEW_LEGACY_REPORT',copy.deepcopy(original),
                             dict(strategy='legacy',limitations=['Frozen original workflow; no new attribution or calibrated confidence claim.']))
    result.save(output)
    return result


def calibrate_from_scratch(captures,*,output=None,config=None):
    """Run the existing targetless initializer, then assess without historical fault attribution."""
    cfg=config if isinstance(config,ResearchConfig) else ResearchConfig(**(config or {}))
    output=Path(output) if output else REPOSITORY/'research_artifacts'/datetime.now(timezone.utc).strftime('initial_%Y%m%d_%H%M%S')
    if output.exists() and any(output.iterdir()):
        raise FileExistsError('Initialization needs a new empty output directory')
    output.mkdir(parents=True,exist_ok=True)
    legacy=legacy_modules()
    import importlib
    scratch=importlib.import_module('step1_calibrate')
    settings=copy.deepcopy(legacy.settings.load_config())
    source=Path(captures).resolve()
    if not next(source.glob('*.npz'),None):
        # Raw capture_*/rig_0.bag folders are decoded by the existing decoder into stacked captures first.
        if not any((p/'rig_0.bag').exists() for p in source.glob('capture_*')):
            raise ValueError('Calibration from scratch needs stacked captures (.npz) or raw capture_*/rig_0.bag folders; image + PCD pairs are only supported for checking an existing calibration')
        legacy.maintain.get_frames(source,output/'decoded',legacy.settings.load_config())
        source=output/'decoded'/'stacked'/'data'
        captures=source
    settings['stacked_dir']=str(source.parent)
    settings['output_dir']=str(io_path(output/'initialization'))
    settings['prior']['rotation_lidar_to_camera']='auto'
    scratch.run_device(settings,source.name)
    initial=output/'initialization'/source.name/'calibration.json'
    return _initialization_assessment(initial,captures,output,cfg)


def _initialization_assessment(initial,captures,output,cfg):
    """Keep conditional maintenance diagnostics distinct from initialization evidence."""
    output=Path(output)
    initial_cal=read_calibration(initial)
    conditional=assess(initial_cal,captures,'joint',output=output/'assessment',config=cfg)
    assessment_folder=io_path(output/'assessment')
    assessment_folder.mkdir(parents=True,exist_ok=True)
    (assessment_folder/'conditional_assessment.json').write_text(
        json.dumps(conditional.to_dict(),indent=2,allow_nan=False)+'\n',encoding='utf-8')
    diagnostics=dict(strategy='inherited_initializer_then_conditional_assessment',input=conditional.diagnostics['input'],
        historical_fault_attribution='Not applicable: no trustworthy historical reference',
        initialization=dict(source=str(Path(initial).resolve()),
            inherited_heuristic_label=initial_cal.get('confidence',{}).get('verdict'),
            independent_validation=False,conditional_report='conditional_assessment.json',
            support_scope='Initial scalar support and nullspace are not inferred from the later maintenance candidate.'),
        limitations=conditional.diagnostics['limitations']+[
            'Initializer used all captures; subsequent holdouts cannot independently validate that initialization.'])
    result=AssessmentResult('INITIAL_CALIBRATION_CANDIDATE','INITIAL_JOINT_ESTIMATION',[],None,{},
        dict(status='UNVALIDATED_INITIALIZATION',calibrated_coverage=False,
             inherited_conditional_diagnostics=initial_cal.get('uncertainty',{})),
        dict(initialization=dict(all_captures_used=True,independent_validation=False),
             post_initialization_assessment=conditional.validation),
        'REVIEW_INITIAL_CALIBRATION_WITH_INDEPENDENT_MEASUREMENTS',initial_cal,diagnostics)
    result.save(output/'assessment')
    return result
