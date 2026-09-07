"""RELAX 2.0.1 numerical decision. GPL-3.0-or-later; volts, explicit axes."""
import numpy as np
import mne

def _number(v,name,lo=None,hi=None):
 if isinstance(v,(bool,np.bool_)) or not isinstance(v,(float,int,np.floating,np.integer)) or not np.isfinite(v) or (lo is not None and v<lo) or (hi is not None and v>hi):raise ValueError(name+' outside finite bounds')
 return float(v)

def _parameters(p,defaults,required):
 if set(p)-set(defaults) or set(required)-set(p):raise ValueError('unknown or missing parameters')
 return dict(defaults,**p)

def _input(x,model,kind):
 if model is not None:raise ValueError('decision does not accept a fitted model')
 if not isinstance(x,kind) or not x.preload:raise TypeError('preloaded '+kind.__name__+' required')
 if not x.ch_names or set(x.get_channel_types())!={'eeg'} or x.info['bads']:raise ValueError('current unmarked EEG channels only')
 if not np.isfinite(x.get_data()).all():raise ValueError('finite EEG required')

def muscle_epoch_rejection(slopes,threshold=-.31,maximum=.5):
 s=np.asarray(slopes,float)
 if s.ndim!=2 or not np.isfinite(s).all():raise ValueError('finite epoch x channel slopes required')
 mask=np.any(s>threshold,axis=1);severity=np.sum(np.maximum(s-threshold,0),axis=1);cut=0.
 if mask.mean()>maximum:cut=float(np.percentile(severity,100*(1-maximum),method='hazen'));mask=severity>cut
 return {'epoch_mask':mask,'severity':severity,'severity_threshold':cut,'maximum_fraction':maximum}

def eeg_muscle_trial_decision(op,x,model=None,**p):
 if op!='relax_muscle_trials':raise ValueError('operation=relax_muscle_trials')
 _input(x,model,mne.BaseEpochs)
 p=_parameters(p,dict(slopes=None,trial_ids=None,threshold=-.31,maximum=.5),['slopes','trial_ids'])
 s=np.asarray(p['slopes']);ids=p['trial_ids']
 if not len(x) or s.shape!=(len(x),len(x.ch_names)) or s.dtype.kind not in 'fiu' or not np.isfinite(s).all():raise ValueError('nonempty finite epoch x channel slopes required')
 if not isinstance(ids,(list,tuple)) or len(ids)!=len(x) or any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):raise ValueError('unique Trial ID per current epoch required')
 _number(p['threshold'],'threshold');_number(p['maximum'],'maximum',0,1)
 out=muscle_epoch_rejection(s,p['threshold'],p['maximum']);out.update(trial_ids=list(ids),channel_names=list(x.ch_names),epoch_selection=x.selection.copy(),events=x.events.copy(),axis_order='epoch, channel')
 return dict(data=x.copy(),model=None,artifacts=out)
