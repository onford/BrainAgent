"""Reproducible source-equivalence audit; every failure remains in the denominator.

Run from backend: python -m scripts.validate_units_v2 --output PATH [--only OP]
This is numerical adapter validation, not a claim of independent validation of
the upstream algorithm. Each case saves actual data, diagnostics and receipts.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import argparse
import contextlib
import importlib.metadata
import json
import platform
import time
import traceback
import numpy as np
import mne
from scipy import signal
from app.preprocessing.units.operations_v2 import inventory, DEFINITIONS
from app.preprocessing.units.contracts_v2 import validate_parameters, invoke_source
from app.preprocessing.schemas import Step, MethodSpec, DecisionPolicy, ArtifactPort
from app.preprocessing.graph_runtime import Packet, GraphExecutor, identity, values
from app.preprocessing.artifact_codec import fingerprint, Codec
from app.preprocessing.storage import file_hash, write_json


def fixture():
    sf=400.;rng=np.random.default_rng(719);t=np.arange(24000)/sf
    names='Fp1 Fpz Fp2 AF3 AF4 F3 F1 Fz F2 F4 FC1 FC2 C3 Cz C4 CP1 CP2 P3 Pz P4 PO3 PO4 O1 Oz O2 F7 F8 T7 T8 P7 P8 FCz'.split()
    sources=np.stack([np.sin(2*np.pi*f*t+.3*i) for i,f in enumerate([7.7,10.3,13.1,19.7])])
    a=(rng.normal(size=(len(names),4))@sources+signal.lfilter([1],[1,-.7],rng.normal(size=(len(names),len(t)))))*8e-6
    blink=sum(np.exp(-((t-v)/.08)**2) for v in [5,13,25,39,49])*100e-6
    ecg=np.exp(-(np.mod(t,1.)-.3)**2/.0002)*200e-6
    a[:5]+=blink;a+=.04*ecg
    raw=mne.io.RawArray(np.vstack([a,blink+rng.normal(0,1e-6,len(t)),ecg]),mne.create_info(names+['VEOG','ECG'],sf,['eeg']*len(names)+['eog','ecg']),first_samp=37,verbose='ERROR')
    raw.set_montage('standard_1020',on_missing='ignore');raw.filter(1.,100.,verbose='ERROR')
    ev=np.array([[37+int(s*sf),0,1+i%2] for i,s in enumerate(range(2,58,2))])
    ids=['trial-'+str(i) for i in range(len(ev))]
    return Packet(raw,ev,np.arange(len(ev)),ids,'acquisition')


def epoch_packet(packet):
    x=mne.Epochs(packet.data,packet.events,{'a':1,'b':2},tmin=-.5,tmax=1.,baseline=None,preload=True,picks='all',reject_by_annotation=False,verbose='ERROR')
    return Packet(x,x.events.copy(),packet.event_indices[x.selection],[packet.trial_ids[i] for i in x.selection],packet.reference,epoch_template=x)


def config(row,packet):
    """Explicit non-arbitrary examples; unknown cases fail visibly."""
    x=packet.data;eeg=x.copy().pick('eeg').ch_names;n=len(packet.events);sf=x.info['sfreq'];op=row['op'];nt=len(x.times)
    p=deepcopy(row['profile_parameters'])
    common={'reference_id':'$reference_id','scope':'$scope','trial_ids':'$trial_ids','events':'$events','axes':'$axes','times':'$times'}
    examples={
      'crop':dict(tmin=1.,tmax=55.),
      'crop_join':dict(keep_intervals=[[0,8000],[10000,24000]],decision_id='audit-retain'),
      'detrend':dict(picks=eeg),
      'filter':dict(l_freq=2.,h_freq=40.,picks=eeg),
      'butter':dict(l_freq=2.,h_freq=40.,prototype_order=4,picks=eeg,padlen=None),
      'notch':dict(freqs=[50.],picks=eeg),
      'spectrum_fit':dict(freqs=[50.],picks=eeg),
      'resample':dict(sfreq=200.),
      'resample_fft':dict(sfreq=200.,npad='auto',window='boxcar',pad='reflect_limited'),
      'resample_fir':dict(sfreq=200.,kernel=signal.firwin(41,.45).tolist()),
      'resample_eeglab':dict(sfreq=200.,cutoff=.9,transition=.1,ripple=.01,beta=5.),
      'decimate':dict(decim=2,offset=1),
      'reference':dict(ref_channels='average'),
      'relax_car':dict(original_channels=eeg,confirmed_bad_channels=[eeg[-1]]),
      'reference_estimate':dict(donors=eeg),
      'reference_apply':dict(targets=eeg),
      'csd':dict(sphere=[0.,0.,0.,.09],lambda2=1e-5,stiffness=4.,n_legendre_terms=50),
      'lof_detect':dict(n_neighbors=10,threshold=1.5,metric='euclidean'),
      'amplitude_detect':dict(peak={'eeg':150e-6},flat={'eeg':1e-8},bad_percent=10.,min_duration=.005,picks=eeg),
      'flat_detect':{},'amplitude_windows':{},'absolute_voltage':{},
      'muscle_detect':dict(threshold=4.,filter_freq=[70.,95.],min_length_good=.2),
      'mark_channels':dict(bads=[eeg[-1]],max_fraction=.1),
      'mark_repaired':dict(repaired_channels=[eeg[-1]],decision_id='audit-repaired'),
      'mark_segments':dict(annotations=mne.Annotations([2.],[.2],['BAD_audit']),frame=dict(first_samp=int(getattr(x,'first_samp',0)),n_times=int(nt),sfreq=float(sf),meas_date=str(x.info['meas_date']))),
      'drop':dict(channels=[eeg[-1]],reason='audit confirmed noisy electrode'),
      'bridge_detect':dict(lm_cutoff=16.,epoch_threshold=.5,l_freq=.5,h_freq=30.,epoch_duration=2.),
      'bridge_repair':dict(bridged_idx=[[0,1]],bad_limit=4),
      'interpolate':dict(max_fraction=.1,origin=[0.,0.,.04]),
      'spherical':dict(bad_channels=[eeg[-1]],origin=[0.,0.,.04],regularization=1e-5,stiffness=4,terms=50,max_fraction=.1),
      'interpolate_native':dict(random_state=0),
      'trial_interpolate':dict(mask=[[i==0 and j==0 for j in range(len(eeg))] for i in range(n)],decision_id='audit-trial-interpolate'),
      'epoch':dict(event_id={'a':1,'b':2},tmin=-.5,tmax=1.,picks=eeg),
      'epoch_with_nonfinite':dict(event_id={'a':1,'b':2},tmin=-.5,tmax=1.,picks=eeg),
      'reject_trials':dict(reject={'eeg':120e-6},flat=None,max_fraction=.5),
      'drop_mask':dict(reject_mask=[i==0 for i in range(n)],decision_id='audit-drop'),
      'baseline':dict(baseline=[-.5,0.]),
      'prep_detect':dict(random_state=0), 'prep_detect_native':dict(random_state=0),
      'deviation_detect':{},'correlation_detect':{},'hf_ratio_detect':{},'line_noise_detect':{},
      'window_mad':{},'blink_upper_bound':{},'spectral_slope':dict(frequencies_Hz=list(range(1,76)),fit_range_Hz=[7.,75.]),
      'eog_step':dict(channels=['VEOG']),'joint_probability':{},'kurtosis':{},
      'blink_iqr':dict(reference_evidence=dict(original_channel_names=list(x.ch_names),interpolated_channel_names=[],zero_reference_included=True,reference_denominator=len(x.ch_names)+1)),
      'relax_budget':dict(channel_epoch_mask=np.zeros((len(eeg),n),bool).tolist(),muscle_slopes=np.full((len(eeg),n),-1.).tolist(),window_starts=list(range(0,n*400,400)),window_samples=400,original_channels=eeg),
      'relax_muscle_trials':dict(slopes=[[-.5 if i else 0. for _ in eeg] for i in range(n)]),
      'detect_bad_channels':dict(adaptation_scope='record_unlabeled'),
      'interpolate_bad_channels':{},'asr_clean':dict(adaptation_scope='record_unlabeled'),
      'ica_fit':dict(n_components=5,seed=0,max_iter=1000),
      'eog_assess':dict(ch_name='VEOG',threshold=3.,l_freq=1.,h_freq=10.),
      'ecg_assess':dict(ch_name='ECG',threshold='auto'),
      'muscle_assess':{},'ica_apply':dict(exclude=[0]),
      'eog_fit':dict(picks=eeg,picks_artifact=['VEOG']), 'eog_apply':{},
      'cca_fit':{},'cca_apply':dict(exclude=[0],decision_id='audit-cca'),
      'mwf_fit':dict(mask=(np.arange(nt)%1600<400).tolist(),mask_id='audit-mwf',rankopt=.9 if p.get('rank')=='pct' else 1), 'mwf_apply':{},
      'asr_fit':dict(start=0,stop='$n_samples'), 'asr_apply':{},
      'autoreject_fit':dict(cv=[[[i for i in range(n) if i%3!=j],[i for i in range(n) if i%3==j]] for j in range(3)],**(dict(n_interpolate=[1,2],consensus=[.5,.75,1.]) if p.get('mode')=='local' else {})),'autoreject_apply':{},
      'regression_baseline_fit':dict(baseline=[-.5,0.],factors=[[] for _ in range(n)],factor_names=[]),
      'regression_baseline_epochs_fit':dict(picks=eeg,baseline=[-.5,0.],factors=[[] for _ in range(n)],factor_names=[]),
      'regression_baseline_apply':{},'regression_baseline_epochs_apply':dict(picks=eeg),
      'iclabel_assess':{},'faster_ic_assess':{},'sasica_assess':dict(criteria={'autocorr':{},'focalcomp':{}}),
      'prep_reference_fit':dict(ref_chs=eeg,reref_chs=eeg,random_state=0),'prep_reference_finalize':{},
      'ssp_apply':dict(projs=x.copy().set_eeg_reference(projection=True,verbose='ERROR').info['projs']),
      'eye_weights':dict(eye_components=[True,False,False,False,False],raw_blink_mask=(np.arange(nt)%1600<300).tolist(),component_id='pending-model'),
      'wica_apply':dict(probabilities=[[0.,0.,1.,0.,0.,0.,0.]]*5,component_id='pending-model',decision_id='audit-wica',**(dict(eye_weights=np.ones((5,nt)).tolist()) if p.get('variant')=='targeted' else {})),
      'cleanline':dict(picks=eeg[:5],line_frequencies=[50.],bandwidth=2.,scan_bandwidth=None,window_seconds=4.,step_seconds=2.,alpha=.01,pad=0,smoothing=100,max_iterations=3,timeout_seconds=180.,tail_policy='preserve'),
      'zapline_plus':dict(picks=eeg,noise_frequencies=[50.],chunk_seconds=20,min_chunk_seconds=10,prominence_quantile=.95,chunk_filter_order=4,adaptive_sigma=False,fixed_remove=1,sigma=3.,min_sigma=2.,max_sigma=5.,detection_width=4.,spectrum_window_seconds=4,timeout_seconds=240.),
      'mara_assess':{},'adjust_assess':{},'rest':{},
    }
    if op not in examples:raise NotImplementedError('no validated fixture for '+op)
    p={**examples[op],**p}
    if op in ('cleanline','zapline_plus','mara_assess','adjust_assess'):
        assets=Path(__file__).resolve().parents[2]/'.local/unit-assets'
        p['source_root']=str(assets/('cleanline' if op=='cleanline' else 'zapline' if op=='zapline_plus' else 'classification'))
        p['octave_path' if op in ('cleanline','zapline_plus') else 'octave']=str(assets/'octave/octave-11.3.0-w64/mingw64/bin/octave-cli.exe')
    if op=='rest':
        sphere=mne.make_sphere_model(r0=(0.,0.,.04),head_radius=.09,verbose='ERROR')
        src=mne.setup_volume_source_space(pos=35.,sphere=(0.,0.,.04,.075),sphere_units='m',exclude=10.,verbose='ERROR')
        p['forward']=mne.make_forward_solution(x.info,trans=None,src=src,bem=sphere,eeg=True,meg=False,verbose='ERROR')
    if op=='butter':
        if p['kind']=='highpass':p['h_freq']=None
        if p['kind']=='lowpass':p['l_freq']=None
    if op=='interpolate_native':p.pop('random_state')
    for k in row['required']:
        if k in common:p[k]=common[k]
    return p


def one(row,base,directory,fit_override=None,force_epochs=False):
    op=row['op'];packet=deepcopy(base)
    criteria=row['profile_parameters'].get('criteria',{})
    if force_epochs or row['input_kind'] in ('epochs','array') or op=='sasica_assess' and set(criteria)&{'trialfoc','snr'}:packet=epoch_packet(packet)
    if op=='decimate':packet.data.filter(None,60.,verbose='ERROR')
    if op in ('interpolate','interpolate_native','interpolate_bad_channels','mark_repaired','drop','relax_car'):packet.data.info['bads']=[packet.data.copy().pick('eeg').ch_names[-1]]
    if row['model_kind']=='eog' or op=='iclabel_assess':packet.data.set_eeg_reference('average',verbose='ERROR');packet.reference='average'
    if row['model_kind']=='prep_reference' or op in ('relax_budget','relax_muscle_trials') or row['input_kind']=='array':packet.data.pick('eeg')
    if op=='trial_interpolate':packet.data.pick('eeg');packet.epoch_template=packet.data
    if op=='blink_iqr':
        # Construct the declared RELAX reference, including the zero electrode.
        packet.data._data-=packet.data.get_data().sum(0)/(len(packet.data.ch_names)+1)
    p=config(row,packet)
    if p.get('reject_by_annotation')=='omit':packet.data.set_annotations(mne.Annotations([10.],[.5],['BAD_audit']))
    if row['profile_parameters'].get('nonfinite')=='propagate':
        channel=packet.data.ch_names.index(packet.data.info['bads'][0]) if op=='interpolate_native' else 0
        if isinstance(packet.data,mne.BaseEpochs):packet.data._data[0,channel,100]=np.nan
        else:packet.data._data[channel,100]=np.nan
    if op=='epoch_with_nonfinite':packet.data._data[0,int(packet.events[0,0]-packet.data.first_samp)+20]=np.nan
    if op=='mwf_fit' and 'treatnans' in row['profile_parameters']:
        p['mask']=np.asarray(p['mask'],float);p['mask'][300:320]=np.nan
    bound={};literal={}
    for k,v in p.items():
        if isinstance(v,(np.ndarray,mne.Annotations,mne.Forward)) or k=='projs':bound[k]=ArtifactPort(step='raw',path=[k])
        else:literal[k]=v
    external={k:p[k] for k in bound}
    p=validate_parameters(row['unit_id'],op,literal,row['profile'],bound=bound)
    s=Step(id='operation',unit_id=row['unit_id'],op=op,params=p,implementation_version='2',profile=row['profile'],artifact_inputs=bound,
           adaptation_scope='record_unlabeled' if row['fit'] or op in ('detect_bad_channels','asr_clean') else 'none',input_representation='array' if row['input_kind']=='array' else 'native',evidence_indices=[0])
    record=SimpleNamespace(id='synthetic-719',intervals=[],sfreq=base.data.info['sfreq'])
    engine=GraphExecutor(record,[s],packet,directory)
    engine.nodes['raw']['artifacts']=external
    reference_packet=deepcopy(packet);scope=None
    if row['fit']:
        # The executor and reference both disclose whole-record unlabeled fitting.
        reference_packet,scope=engine.scoped_packet(s)
    if s.input_representation=='array':reference_packet.epoch_template=reference_packet.data;reference_packet.data=reference_packet.data.get_data().copy()
    model=None
    if row['model_kind'] and row['effect'] not in ('model','reference_model'):
        fitrow=fit_override or next(r for r in inventory() if r['model_kind']==row['model_kind'] and r['effect'] in ('model','reference_model'))
        fitparams=config(fitrow,packet)
        if row['model_kind']=='reference' and s.params.get('nonfinite')=='propagate':fitparams['nonfinite']='propagate'
        fp=validate_parameters(fitrow['unit_id'],fitrow['op'],fitparams,fitrow['profile'])
        fit=Step(id='fit',unit_id=fitrow['unit_id'],op=fitrow['op'],params=fp,implementation_version='2',profile=fitrow['profile'],adaptation_scope='record_unlabeled' if fitrow['fit'] else 'none',input_representation='array' if fitrow['input_kind']=='array' else 'native',evidence_indices=[0])
        engine.steps['fit']=fit;engine.execute(fit);s.model_from='fit';model=engine.nodes['fit']['model']
        if row['model_kind']=='prep_reference':
            s.input='fit';reference_packet=deepcopy(engine.nodes['fit']['packet'])
        if op in ('eye_weights','wica_apply'):
            from app.preprocessing.units.source.eeg_iclabel import _component_id
            s.params['component_id']=_component_id(model['estimator'])
    if row['decision']:
        s.decision=DecisionPolicy(mode='manual',status='confirmed',reason='Synthetic validation fixture; not a human EEG finding',input_sha256=identity(reference_packet),model_sha256=fingerprint(model) if model is not None else None)
    from app.preprocessing.graph_planner import compile_graph
    compiled_steps=[];data_input='raw'
    if isinstance(packet.data,mne.BaseEpochs):
        data_input='ep'
        compiled_steps.append(Step(id='ep',unit_id='EEG-EPOCH',op='epoch',implementation_version='2',evidence_indices=[0],params=dict(events='$events',event_id={'a':1,'b':2},tmin=-.5,tmax=1.,picks=list(packet.data.ch_names))))
    if model is not None:
        fitted=fit.model_copy(deep=True);fitted.input=data_input;compiled_steps.append(fitted)
    compiled=s.model_copy(deep=True)
    if compiled.input=='raw':compiled.input=data_input
    compiled_steps.append(compiled)
    recipe=MethodSpec(id='source-equivalence',version='2',title=row['identity'],source='classic',mechanism='Numerical adapter audit',recipe=compiled_steps,output=s.id,evidence=[dict(source_url='brainagent:unit-audit:source',source_version='2',locator=row['identity'],text='Pinned source equivalence with explicit synthetic inputs.')])
    facts=SimpleNamespace(id=record.id,channel_order=list(packet.data.ch_names),channels=dict(zip(packet.data.ch_names,packet.data.get_channel_types())),sfreq=float(packet.data.info['sfreq']),reference=packet.reference,intervals=[])
    compile_graph(recipe,facts,SimpleNamespace(survey=SimpleNamespace(event_id={'a':1,'b':2})),{})
    params=engine.runtime_params(s,reference_packet,scope)
    before=identity(reference_packet)
    np.random.seed(719)
    expected=invoke_source(s.unit_id,s.op,reference_packet.data,model=deepcopy(model),**params)
    assert identity(reference_packet)==before,'source mutated reference input'
    np.random.seed(719)
    actual=engine.execute(s)
    np.testing.assert_allclose(values(actual.data),values(expected['data']),rtol=1e-11,atol=1e-16,equal_nan=True)
    assert fingerprint(actual.data)==fingerprint(expected['data']),'numerical data or full MNE state differs'
    def scientific(v):
        if isinstance(v,dict):return {k:scientific(x) for k,x in v.items() if k not in ('runtime_log','stdout','stderr')}
        if isinstance(v,list):return [scientific(x) for x in v]
        if isinstance(v,tuple):return tuple(scientific(x) for x in v)
        return v
    assert fingerprint(scientific(engine.nodes[s.id]['artifacts']))==fingerprint(scientific(expected['artifacts'])),'numerical diagnostics differ from direct source'
    assert fingerprint(engine.nodes[s.id]['model'])==fingerprint(expected['model']),'model differs from direct source'
    invalid=deepcopy(reference_packet.data)
    if isinstance(invalid,np.ndarray):invalid.flat[0]=np.inf
    else:invalid._data.flat[0]=np.inf
    invalid_before=fingerprint(invalid)
    if op=='epoch_with_nonfinite':
        invalid._data[0,int(reference_packet.events[1,0]-invalid.first_samp)+20]=np.inf
        invalid_before=fingerprint(invalid)
        boundary=invoke_source(s.unit_id,s.op,invalid,model=deepcopy(model),**params)
        assert 1 not in boundary['data'].selection and 'BAD_nonfinite' in boundary['data'].drop_log[1]
        assert np.isfinite(boundary['data'].get_data()).all()
    else:
        try:
            boundary=invoke_source(s.unit_id,s.op,invalid,model=deepcopy(model),**params)
            # Some legacy PyPREP detectors remove the invalid channel from
            # their internal statistics but return the original Raw unchanged.
            # The graph's declared finite-output guard must reject that Raw.
            from app.preprocessing.graph_runtime import transition
            transition(reference_packet,boundary['data'],boundary['artifacts'],row,params)
        except (ValueError,TypeError):pass
        else:raise AssertionError('nonfinite boundary input was accepted')
    assert fingerprint(invalid)==invalid_before,'failed operation mutated input'
    a=values(actual.data);b=values(expected['data']);diff=np.abs(a-b)
    return dict(compiled_parameters=True,compiled_graph=True,executed=True,numerical_verified=True,real_verified=False,boundary_passed=True,boundary_inf_rejected=op!='epoch_with_nonfinite',boundary_policy='drop contaminated trials' if op=='epoch_with_nonfinite' else 'reject infinite input',
        numerical_basis='same pinned source invoked directly, independent of graph; exact diagnostics/model comparison; lossless readback',
        max_abs_error=float(np.nanmax(diff)),shape=list(a.shape),input_sha256=before,output_sha256=identity(actual),
        model_sha256=fingerprint(expected['model']),diagnostics_sha256=fingerprint(expected['artifacts']),
        event_indices=actual.event_indices.tolist(),trial_ids=actual.trial_ids)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--only',nargs='*');args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);mne.set_log_level('ERROR');base=fixture();rows=inventory();results=[]
    from app.preprocessing.units import engine_hash,environment
    import os
    from threadpoolctl import threadpool_info
    code_stamp={'engine_sha256':engine_hash(),'environment':environment(),'validation_script_sha256':file_hash(Path(__file__)),'runtime_context':{'platform':platform.platform(),'threadpools':threadpool_info(),'thread_environment':{k:os.environ.get(k) for k in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')}}}
    for i,row in enumerate(rows):
        if args.only and row['op'] not in args.only:continue
        directory=args.output/f'{i:03}-{row["op"]}';directory.mkdir(exist_ok=True)
        receipt=dict(**code_stamp,identity=row['identity'],source_sha256=row['source']['source']['code_sha256'],started=time.time(),fixture_seed=719,python=platform.python_version(),status='failed')
        try:
            with (directory/'runtime.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):receipt.update(one(row,base,directory))
            receipt['status']='passed'
        except Exception as exc:
            receipt.update(error=str(exc),exception=type(exc).__name__,traceback=traceback.format_exc())
        receipt['elapsed_seconds']=time.time()-receipt['started'];receipt['files']=[dict(path=p.relative_to(args.output).as_posix(),sha256=file_hash(p),bytes=p.stat().st_size) for p in directory.rglob('*') if p.is_file() and p.name!='receipt.json']
        write_json(directory/'receipt.json',receipt);results.append(receipt)
        write_json(args.output/'results.json',dict(total_inventory=len(rows),attempted=len(results),passed=sum(r['status']=='passed' for r in results),results=results))
        print(row['identity'],receipt['status'],receipt.get('error',''),flush=True)


if __name__=='__main__':main()
