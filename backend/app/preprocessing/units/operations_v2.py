"""Versioned, explicit source operation contracts. Never execute generated code.

The source routines remain the final numerical validators. This registry supplies
the closed parameter vocabulary, graph effects, fit/decision ports and profiles.
V1 deliberately retains its smaller parameter domains for old plans.
"""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path

ROOT = Path(__file__).parent
DEFINITIONS = {}


def define(unit, op, required='', defaults=None, *, stage='raw', effect='preserve',
           model=None, fit=False, decision=False, dependencies=None, variants=None,
           assets=(), same_data=False):
    key = (unit, op)
    if key in DEFINITIONS:
        raise ValueError(f'duplicate operation {key}')
    DEFINITIONS[key] = dict(unit_id=unit, op=op, required=required.split(),
        defaults=defaults or {}, input_kind=stage, effect=effect, model_kind=model,
        fit=fit, decision=decision, dependencies=dependencies or {},
        variants=variants or {}, assets=list(assets), same_data=same_data)


define('EEG-CROP', 'crop', 'tmin tmax events', effect='crop')
define('EEG-CROP', 'crop_join', 'keep_intervals events decision_id', effect='crop_join', decision=True)
define('EEG-DETREND', 'detrend', 'type picks', stage='either', variants={'type':['constant','linear']})
define('EEG-FILTER', 'filter', 'l_freq h_freq method phase picks', dict(fir_design='firwin', fir_window='hamming', filter_length='auto', l_trans_bandwidth='auto', h_trans_bandwidth='auto', pad='reflect_limited', annotation_policy='raw', skip_by_annotation=['edge','bad_acq_skip','boundary'], nonfinite='reject'), variants={'method':['fir','iir']})
define('EEG-FILTER', 'butter', 'kind l_freq h_freq prototype_order phase picks padlen', stage='either', variants={'kind':['highpass','lowpass','bandpass','bandstop']})
define('EEG-FILTER', 'notch', 'freqs picks')
define('EEG-SINE-REGRESSION', 'spectrum_fit', 'freqs picks', dict(mt_bandwidth=2., p_value=.01,filter_length='10s',annotation_policy='array',nonfinite='reject'))
define('EEG-SINE-REGRESSION', 'cleanline', 'source_root octave_path picks line_frequencies bandwidth scan_bandwidth window_seconds step_seconds alpha pad smoothing max_iterations timeout_seconds tail_policy', assets=['source_root','octave_path'])
define('EEG-RESAMPLE', 'resample', 'sfreq events', stage='either', effect='resample')
define('EEG-RESAMPLE', 'resample_fft', 'sfreq events npad window pad', effect='resample')
define('EEG-RESAMPLE', 'resample_fir', 'sfreq events kernel', effect='resample')
define('EEG-RESAMPLE', 'resample_eeglab', 'sfreq events cutoff transition ripple beta', effect='resample')
define('EEG-RESAMPLE', 'decimate', 'decim offset', stage='epochs', effect='decimate')
define('EEG-REREFERENCE', 'reference', 'ref_channels', stage='either', effect='reference')
define('EEG-REREFERENCE', 'relax_car', 'original_channels confirmed_bad_channels reference_id', effect='reference_channels', decision=True)
define('EEG-REREFERENCE', 'reference_estimate', 'donors reference_id', dict(estimator='nanmean',nonfinite='reject'), stage='either', model='reference', effect='model', variants={'estimator':['nanmean','nanmedian']})
define('EEG-REREFERENCE', 'reference_apply', 'targets', dict(nonfinite='reject'), stage='either', model='reference', effect='reference', same_data=True)
define('EEG-REST', 'rest', 'forward', stage='either', effect='reference', assets=['forward'])
define('EEG-CSD', 'csd', 'sphere lambda2 stiffness n_legendre_terms', stage='either', effect='csd')
define('EEG-BAD-CHANNEL-LOF', 'lof_detect', 'n_neighbors threshold metric')
define('EEG-AMPLITUDE-THRESHOLD', 'amplitude_detect', 'peak flat bad_percent min_duration picks')
define('EEG-AMPLITUDE-THRESHOLD', 'flat_detect', defaults=dict(max_flatline_duration=5.,tolerance_V=1e-15,valid_intervals=None))
define('EEG-AMPLITUDE-THRESHOLD', 'amplitude_windows', defaults=dict(window_s=1.,stride_s=.5,tail='drop',valid_intervals=None,min_windows=1,peak_to_peak_limit_V=1e-4,frac_bad=.25))
define('EEG-AMPLITUDE-THRESHOLD', 'absolute_voltage', defaults=dict(limit_V=.001,picks=None))
define('EEG-MUSCLE-DETECT', 'muscle_detect', 'threshold filter_freq min_length_good')
define('EEG-BAD-CHANNEL-MARK', 'mark_channels', 'bads max_fraction', stage='either', effect='mark', decision=True)
define('EEG-BAD-CHANNEL-MARK', 'mark_repaired', 'repaired_channels decision_id', stage='either', effect='mark', decision=True)
define('EEG-BAD-SEGMENT-MARK', 'mark_segments', 'annotations frame', effect='annotations', decision=True)
define('EEG-BAD-CHANNEL-DROP', 'drop', 'channels reason', stage='either', effect='channels', decision=True)
define('EEG-ICA', 'ica_fit', 'method n_components seed max_iter scope reference_id', dict(tol=None,ortho=None,extended=None,reject=None,flat=None,tstep=2.), stage='either', model='ica', fit=True, effect='model', variants={'method':['fastica','picard','infomax']})
define('EEG-ICA', 'eog_assess', 'ch_name threshold l_freq h_freq reference_id', dict(reference_role=None,channel_decision_id=None), stage='either', model='ica')
define('EEG-ICA', 'ecg_assess', 'ch_name method threshold reference_id', dict(l_freq=8.,h_freq=16.,measure='zscore',reference_role=None,channel_decision_id=None), stage='either', model='ica', variants={'method':['ctps','correlation']})
define('EEG-ICA', 'muscle_assess', 'mode reference_id', dict(threshold=.5,l_freq=7.,h_freq=45.,sphere=None), stage='either', model='ica', variants={'mode':['spatial','slope']})
define('EEG-ICA', 'ica_apply', 'exclude reference_id', stage='either', model='ica', decision=True)
define('EEG-EOG-REGRESSION', 'eog_fit', 'picks picks_artifact scope reference_id', model='eog',fit=True,effect='model')
define('EEG-EOG-REGRESSION', 'eog_apply', 'reference_id', stage='either',model='eog')
define('EEG-SSP', 'ssp_apply', 'projs', stage='either',effect='reference',decision=True,assets=['projs'])
define('EEG-BRIDGE-DETECT', 'bridge_detect', 'lm_cutoff epoch_threshold l_freq h_freq epoch_duration')
define('EEG-BRIDGE-REPAIR', 'bridge_repair', 'bridged_idx bad_limit', decision=True)
define('EEG-INTERPOLATE', 'interpolate', 'max_fraction origin', stage='either',effect='mark')
define('EEG-INTERPOLATE', 'spherical', 'bad_channels origin kernel regularization stiffness terms max_fraction', stage='either',effect='mark',decision=True,variants={'kernel':['perrin','eeglab']})
define('EEG-INTERPOLATE', 'interpolate_native', defaults=dict(source_profile='pyprep_071',origin='auto',reset_bads=True,nonfinite='propagate'),effect='mark',dependencies={'pyprep':'0.7.1'})
define('EEG-INTERPOLATE', 'trial_interpolate', 'mask trial_ids decision_id', dict(max_fraction=.1,origin='auto'),stage='epochs',decision=True)
for op in ['epoch','epoch_with_nonfinite']:
    define('EEG-EPOCH',op,'events event_id tmin tmax picks',effect='epoch')
define('EEG-TRIAL-REJECT','reject_trials','reject flat max_fraction',stage='epochs',effect='trials')
define('EEG-TRIAL-REJECT','drop_mask','reject_mask trial_ids decision_id',stage='epochs',effect='trials',decision=True)
define('EEG-BASELINE','baseline','baseline',stage='epochs')
define('EEG-ZAPLINE','zapline_plus','source_root octave_path picks noise_frequencies chunk_seconds min_chunk_seconds prominence_quantile chunk_filter_order adaptive_sigma fixed_remove sigma min_sigma max_sigma detection_width spectrum_window_seconds timeout_seconds',assets=['source_root','octave_path'])
PREP=dict(do_detrend=True,matlab_strict=True,random_state=0,reject_by_annotation=None)
CRITERIA=dict(deviation=dict(deviation_threshold=5.),hfnoise=dict(HF_zscore_threshold=5.),correlation=dict(correlation_secs=1.,correlation_threshold=.4,frac_bad=.01),snr={},ransac=dict(n_samples=50,sample_prop=.25,corr_thresh=.75,frac_bad=.4,corr_window_secs=5.,channel_wise=False,max_chunk_size=None))
define('EEG-BAD-CHANNEL-ENSEMBLE','prep_detect',defaults={**PREP,'retained_bandwidth_policy':'require','criteria':CRITERIA},dependencies={'pyprep':'0.7.1'})
define('EEG-BAD-CHANNEL-ENSEMBLE','prep_detect_native',defaults=dict(do_detrend=True,random_state=None,reject_by_annotation=None,ransac=True,channel_wise=False,max_chunk_size=None,correlation=True,criteria={}),dependencies={'pyprep':'0.7.1'})
for unit,op,params in [('DEVIATION','deviation_detect',dict(deviation_threshold=5.)),('CORRELATION','correlation_detect',dict(correlation_secs=1.,correlation_threshold=.4,frac_bad=.01)),('HF-RATIO','hf_ratio_detect',dict(HF_zscore_threshold=5.))]:
    define('EEG-BAD-CHANNEL-'+unit,op,defaults={**PREP,**params},dependencies={'pyprep':'0.7.1'})
define('EEG-BAD-CHANNEL-LINE-NOISE','line_noise_detect',defaults=dict(window_s=4.,stride_s=2.,tail='drop',valid_intervals=None,min_windows=1,line_bands_Hz=[[49.,51.]],background_bands_Hz=[[40.,48.],[52.,60.]],welch_segment_s=2.,overlap_fraction=.5,n_fft=None,ratio_threshold=5.,frac_bad=.25))
define('EEG-ICLABEL','iclabel_assess','reference_id',dict(backend='torch'),stage='either',model='ica',dependencies={'mne-icalabel':'0.8.1'},variants={'backend':['torch','onnx']})
for unit,op in [('MARA','mara_assess'),('ADJUST','adjust_assess')]:
    define('EEG-'+unit,op,'source_root reference_id',dict(octave='octave',timeout=180.,**(dict(xyz_scale=1000.) if unit=='ADJUST' else {})),stage='epochs' if unit=='ADJUST' else 'either',model='ica',assets=['source_root','octave'])
define('EEG-FASTER-IC','faster_ic_assess','reference_id',dict(metrics=['eog_correlation','kurtosis','power_gradient','hurst','median_gradient'],threshold=3.,max_iter=1,power_range_Hz=None),stage='epochs',model='ica',dependencies={'mne-faster':'1.2.2'})
define('EEG-SASICA','sasica_assess','reference_id criteria',dict(external_assessments={},review=None),stage='either',model='ica')
define('EEG-ASR','asr_fit','scope reference_id start stop',dict(cutoff=20.,blocksize=100,win_len=.5,win_overlap=.66,max_dropout_fraction=.1,min_clean_fraction=.25,max_bad_chans=.1),model='asr',fit=True,effect='model',dependencies={'asrpy':'0.0.8'})
define('EEG-ASR','asr_apply','reference_id',dict(lookahead=.25,stepsize=32,maxdims=.66,mem_splits=1),model='asr',dependencies={'asrpy':'0.0.8'})
define('EEG-WICA','wica_apply','variant probabilities component_id decision_id reference_id',dict(thresholds=[0.]*7,clean_other='no',eye_weights=None,extra_eye=None,line_freq=None,muscle_slope=-.31),model='ica',decision=True,dependencies={'PyWavelets':'1.8.0'},variants={'variant':['ordinary','targeted']})
define('EEG-CCA','cca_fit','scope reference_id',dict(lags=1),model='cca',fit=True,effect='model')
define('EEG-CCA','cca_apply','exclude reference_id decision_id',model='cca',decision=True)
define('EEG-MWF','mwf_fit','mask scope reference_id mask_id',dict(delay=0,delay_spacing=1,singlesided=False,rank='poseig',rankopt=1,treatnans='ignore',mu=1.),model='mwf',fit=True,effect='model',variants={'rank':['poseig','full','pct','first']})
define('EEG-MWF','mwf_apply','reference_id',model='mwf')
define('EEG-AUTOREJECT','autoreject_fit','mode scope reference_id trial_ids cv',dict(seed=0,n_interpolate=[1,4],consensus=[.5,.75,1.],thresh_method='bayesian_optimization'),stage='epochs',model='autoreject',fit=True,effect='model',dependencies={'autoreject':'0.5.0'},variants={'mode':['global','local'],'thresh_method':['bayesian_optimization','random_search']})
define('EEG-AUTOREJECT','autoreject_apply','reference_id trial_ids',stage='epochs',effect='trials',model='autoreject',dependencies={'autoreject':'0.5.0'})
for suffix,stage,axes in [('', 'array','axes times'),('_epochs','epochs','picks')]:
    define('EEG-REGRESSION-BASELINE','regression_baseline'+suffix+'_fit','scope '+axes+' baseline factors factor_names',stage=stage,model='regression_baseline'+suffix,fit=True,effect='model')
    define('EEG-REGRESSION-BASELINE','regression_baseline'+suffix+'_apply',axes+' trial_ids',stage=stage,model='regression_baseline'+suffix)
define('EEG-WINDOW-MAD','window_mad',defaults=dict(mad_multiplier=25.,flat_limit_V=2e-6,blink_upper_bound_V=None),stage='epochs')
define('EEG-WINDOW-MAD','blink_upper_bound',defaults=dict(blink_epochs=None,mad_multiplier=10.,fallback_percentile=80.),stage='epochs')
define('EEG-SPECTRAL-SLOPE','spectral_slope',defaults=dict(mode='fieldtrip_mtmfft',frequencies_Hz=list(range(1,76)),fit_range_Hz=[7.,75.],excluded_bands_Hz=[],slope_threshold=-.31,direction='above',picks=None,retained_bandwidth_policy='require'),stage='either',variants={'mode':['fieldtrip_mtmfft','relax_ic_welch'],'retained_bandwidth_policy':['require','author_attenuated']})
define('EEG-EOG-STEP','eog_step',defaults=dict(channels=None,search_interval_s=[-.2,.3],half_window_s=.1,threshold_V=32e-6,statistic='trimmean95'),stage='epochs',variants={'statistic':['trimmean95','mean']})
define('EEG-JOINT-PROBABILITY','joint_probability',defaults=dict(local_threshold=10.,global_threshold=10.,bins=1000),stage='epochs')
define('EEG-KURTOSIS','kurtosis',defaults=dict(local_threshold=10.,global_threshold=10.),stage='epochs')
define('EEG-BLINK-IQR','blink_iqr','reference_evidence',dict(blink_channels=['Fp1','Fpz','Fp2','AF3','AF4','F3','F1','Fz','F2','F4'],lowpass_Hz=25.,zero_intervals=None,variant='relax_2_0_1'),variants={'variant':['relax_2_0_1','repaired_indices']})
define('EEG-ROBUST-REFERENCE','prep_reference_fit','ref_chs reref_chs',dict(max_iterations=4,ransac=True,channel_wise=False,max_chunk_size=None,random_state=None,reject_by_annotation=None),effect='reference_model',model='prep_reference',fit=True,dependencies={'pyprep':'0.7.1'})
define('EEG-ROBUST-REFERENCE','prep_reference_finalize',model='prep_reference',effect='reference',same_data=True,dependencies={'pyprep':'0.7.1'})
define('EEG-IC-BLINK-WEIGHTS','eye_weights','eye_components raw_blink_mask component_id reference_id',dict(profile='relax_2_0_1'),model='ica',variants={'profile':['relax_2_0_1','repaired_units_indices']})
define('EEG-CHANNEL-REJECTION-BUDGET','relax_budget','channel_epoch_mask muscle_slopes window_starts window_samples original_channels',dict(maximum=.1,extreme_fraction=.25,muscle_fraction=.5,muscle_threshold=-.31,profile='relax_2_0_1'),variants={'profile':['relax_2_0_1','repaired_units_indices']})
define('EEG-MUSCLE-TRIAL-DECISION','relax_muscle_trials','slopes trial_ids',dict(threshold=-.31,maximum=.5),stage='epochs')
# Engineering adapters are separate identities, never aliases for source units.
define('EEG-AUTO-BAD-CHANNEL','detect_bad_channels','adaptation_scope',dict(selection_policy='consensus_v2',window_s=1.,flat_duration_s=5.,flat_ptp_V=1e-7,deviation_z=5.,correlation_threshold=.4,bad_window_fraction=.1,persistent_low_corr_fraction=.5,persistent_low_corr_seconds=5.,shared_correlation_threshold=.7))
define('EEG-AUTO-BAD-CHANNEL','interpolate_bad_channels',defaults=dict(max_fraction=.1),effect='mark')
define('EEG-ASR-AUTO','asr_clean','adaptation_scope',dict(on_insufficient_calibration='error',cutoff=20.,win_len=.5,win_overlap=.66,min_clean_seconds=30.,lookahead=.25,stepsize=32,maxdims=.66,mem_splits=3),dependencies={'asrpy':'0.0.8'},variants={'on_insufficient_calibration':['error','identity']})

for _native_op in ('prep_native', 'automagic_native'):
    define('EEG-CLASSIC-NATIVE', _native_op,
        'source_root eeglab_root matlab_path line_freq seed timeout_seconds adaptation_scope' + (' prep_root ica_random_policy' if _native_op == 'automagic_native' else ''),
        effect='reference', assets=('source_root','eeglab_root','matlab_path') + (('prep_root',) if _native_op == 'automagic_native' else ()),
        variants={'ica_random_policy':['author_clock','fixed_loop_seed_zero']} if _native_op == 'automagic_native' else {})


def _initial_profiles(spec):
    if spec['op'] == 'filter':
        return [dict(method=m,phase=p,annotation_policy=a) for m,ps in
            [('fir',['zero','zero-double','minimum','minimum-half']),('iir',['zero','forward','zero-double'])]
            for p in ps for a in ['raw','array']]
    if spec['op'] == 'butter':
        return [dict(kind=k,phase=p) for k in spec['variants']['kind'] for p in ['zero','forward']]
    if spec['op'] == 'autoreject_fit':
        return [dict(mode='global'),dict(mode='local',thresh_method='bayesian_optimization'),dict(mode='local',thresh_method='random_search')]
    axes = spec['variants']
    return [dict(zip(axes, values)) for values in product(*axes.values())] if axes else [{}]


def profiles(spec):
    """Retain every initial identity; append source-discovered algorithm branches."""
    base=_initial_profiles(spec);extra=[];op=spec['op']
    if op=='filter':
        for phase,design,window,policy in product(['zero','zero-double','minimum','minimum-half'],['firwin','firwin2'],['hamming','hann','blackman'],['raw','array']):
            if design=='firwin' and window=='hamming':continue
            extra.append(dict(method='fir',phase=phase,annotation_policy=policy,fir_design=design,fir_window=window))
        for p in [*base,*extra.copy()]:
            if p.get('annotation_policy')=='array':extra.append({**p,'nonfinite':'propagate'})
    if op=='ica_fit':
        extra=[dict(method='picard',ortho=o,extended=e) for o,e in product([False,True],[False,True]) if not (o and e)] + [dict(method='infomax',extended=False)]
    if op=='ecg_assess':extra=[dict(method='correlation',measure='correlation')]
    if op=='wica_apply':extra=[dict(variant=v,clean_other='yes') for v in ('ordinary','targeted')]
    if op=='blink_iqr':extra=[dict(variant=v,lowpass_Hz=6.) for v in ('relax_2_0_1','repaired_indices')]
    if op=='spectrum_fit':extra=[dict(nonfinite='propagate')]
    if op=='reference_estimate':extra=[dict(estimator=e,nonfinite='propagate') for e in ('nanmean','nanmedian')]
    if op=='reference_apply':extra=[dict(nonfinite='propagate')]
    if op=='interpolate_native':extra=[dict(reset_bads=b,nonfinite=n) for b,n in product([False,True],['reject','propagate']) if not (b and n=='propagate')]
    if op=='cleanline':extra=[dict(scan_bandwidth=2.)]
    if op=='zapline_plus':
        extra=[dict(noise_frequencies=f,chunk_seconds=c,adaptive_sigma=a) for f,c,a in product([[50.],'line',[]],[0,20],[False,True]) if not (f==[50.] and c==20 and not a)]
    if op=='faster_ic_assess':extra=[dict(metrics=[metric]) for metric in ['eog_correlation','kurtosis','power_gradient','hurst','median_gradient','line_noise']]
    if op=='sasica_assess':extra=[dict(criteria={name:{}}) for name in ['autocorr','focalcomp','trialfoc','snr']] + [dict(criteria={'eogcorr':{'vertical_channels':['VEOG']}}),dict(criteria={'chancorr':{'channels':['C3','C4']}})]
    if op=='mwf_fit':extra=[dict(rank=r,delay=1,singlesided=b,treatnans=n) for r,b,n in product(['poseig','full','pct','first'],[False,True],['ignore','artifact','clean'])]
    if op=='reference':extra=[dict(ref_channels=['Cz']),dict(ref_channels=['C3','C4'])]
    if op in ('prep_detect','deviation_detect','correlation_detect','hf_ratio_detect'):
        extra=[dict(do_detrend=d,matlab_strict=m,reject_by_annotation=a) for d,m,a in product([True,False],[True,False],[None,'omit']) if not (m and a=='omit') and not (d and m and a is None)]
    if op=='prep_detect':
        extra += [dict(criteria=c) for c in [{'deviation':{}},{'hfnoise':{}},{'correlation':{}},{'hfnoise':{},'correlation':{},'snr':{}},{'deviation':{},'correlation':{},'ransac':{'channel_wise':True}}]]
        extra += [dict(retained_bandwidth_policy='author_attenuated')]
    if op=='prep_detect_native':
        extra=[dict(do_detrend=d,ransac=r,correlation=c,channel_wise=w) for d,r,c,w in product([True,False],[True,False],[True,False],[False,True]) if not (not r and w) and not (d and r and c and not w)]
        extra += [dict(reject_by_annotation='omit')]
    if op=='prep_reference_fit':extra=[dict(ransac=r,channel_wise=w,reject_by_annotation=a) for r,w,a in product([True,False],[False,True],[None,'omit']) if not (not r and w) and not (r and not w and a is None)]
    return base+extra


def inventory():
    source = {r['id']:r for r in json.loads((ROOT/'catalog.json').read_text(encoding='utf-8'))}
    rows = []
    for key, spec in DEFINITIONS.items():
        for selection in profiles(spec):
            profile = ','.join(f'{k}={v}' for k,v in selection.items()) or 'source'
            rows.append({**deepcopy(spec), 'profile':profile,'profile_parameters':selection,
                'identity':'/'.join((*key,profile)), 'source':deepcopy(source[key[0]]),
                'implementation_version':'2'})
            if spec['op']=='ecg_assess' and selection.get('method')=='ctps':rows[-1]['input_kind']='raw'
    return rows
