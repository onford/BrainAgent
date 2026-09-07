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

def channel_budget(mask,muscle_slopes,starts,window,n_samples,initial_count,channel_names,maximum=.1,extreme_fraction=.25,muscle_fraction=.5,muscle_threshold=-.31,profile='relax_2_0_1'):
 m=np.asarray(mask,bool).copy();sl=np.asarray(muscle_slopes,float);starts=np.asarray(starts,int)
 if m.shape!=sl.shape or m.shape!=(len(channel_names),len(starts)):raise ValueError('channel-window axes mismatch')
 if profile not in ('relax_2_0_1','repaired_units_indices'):raise ValueError('profile')
 C,E=m.shape;budget=int(np.floor(maximum*initial_count))-(initial_count-C)
 if budget<=0:return dict(extreme_bad=[],muscle_bad=[],initial_budget=budget,remaining_budget=budget,extreme_proportions=None,muscle_proportions=None)
 m[:,np.sum(m,axis=0)>budget]=False
 full=np.zeros((C,n_samples));covered=np.zeros(n_samples,bool)
 for e,s in enumerate(starts):
  if s<0 or s+window>n_samples:raise ValueError('diagnostic window out of range')
  covered[s:s+window]=True;full[m[:,e],s:s+window]=1
 if profile=='relax_2_0_1':
  flat=full.ravel(order='F');flat[np.flatnonzero(~covered)]=np.nan;full=flat.reshape(full.shape,order='F')
 else:full[:,~covered]=np.nan
 props=np.nanmean(full,axis=1);threshold=extreme_fraction;recommended=int(np.sum(props>threshold))
 if recommended>budget:threshold=np.percentile(props,100*(1-budget/C),method='hazen')
 reject=np.flatnonzero(props>threshold) if recommended else np.array([],int);remaining=np.setdiff1d(np.arange(C),reject);next_budget=budget-len(reject)
 muscle_bad=np.array([],int);mprops=None;mthreshold=muscle_fraction
 if next_budget>0:
  ignored=np.any(m[remaining],axis=0);scores=sl[remaining].copy();scores[:,ignored]=np.nan;mprops=np.sum(scores>muscle_threshold,axis=1)/E
  recommended_m=int(np.sum(mprops>muscle_fraction))
  if recommended_m>next_budget:mthreshold=np.sort(mprops)[::-1][next_budget-1]
  if recommended_m:
   selected=mprops>=mthreshold
   if np.sum(selected)>next_budget:selected=mprops>mthreshold
   muscle_bad=remaining[selected]
 return dict(extreme_bad=[channel_names[k] for k in reject],muscle_bad=[channel_names[k] for k in muscle_bad],initial_budget=budget,remaining_budget=next_budget-len(muscle_bad),extreme_proportions=props,muscle_proportions=mprops,extreme_threshold=threshold,muscle_threshold=mthreshold,profile=profile)

def eeg_channel_rejection_budget(op,x,model=None,**p):
 if op!='relax_budget':raise ValueError('operation=relax_budget')
 _input(x,model,mne.io.BaseRaw)
 p=_parameters(p,dict(channel_epoch_mask=None,muscle_slopes=None,window_starts=None,window_samples=None,original_channels=None,maximum=.1,extreme_fraction=.25,muscle_fraction=.5,muscle_threshold=-.31,profile='relax_2_0_1'),['channel_epoch_mask','muscle_slopes','window_starts','window_samples','original_channels'])
 m=np.asarray(p['channel_epoch_mask']);s=np.asarray(p['muscle_slopes']);starts=np.asarray(p['window_starts']);win=p['window_samples'];names=p['original_channels']
 if m.dtype.kind!='b' or m.ndim!=2 or m.shape!=(len(x.ch_names),len(starts)) or m.shape[1]<1:raise ValueError('boolean channel x epoch mask required')
 if s.shape!=m.shape or s.dtype.kind not in 'fiu' or not np.isfinite(s).all():raise ValueError('finite channel x epoch slopes required')
 if starts.ndim!=1 or starts.dtype.kind not in 'iu' or np.any(starts[1:]<=starts[:-1]):raise ValueError('strictly increasing integer window starts required')
 if isinstance(win,(bool,np.bool_)) or not isinstance(win,(int,np.integer)) or win<1 or np.any(starts<0) or np.any(starts>x.n_times-win):raise ValueError('window samples outside Raw')
 if not isinstance(names,(list,tuple)) or not names or any(not isinstance(n,str) or not n for n in names) or len(set(names))!=len(names) or not set(x.ch_names)<=set(names):raise ValueError('unique original channel names containing current channels required')
 for k in ['maximum','extreme_fraction','muscle_fraction']:_number(p[k],k,0,1)
 _number(p['muscle_threshold'],'muscle_threshold')
 out=channel_budget(m,s,starts,win,x.n_times,len(names),x.ch_names,**{k:p[k] for k in ['maximum','extreme_fraction','muscle_fraction','muscle_threshold','profile']})
 out.update(channel_names=list(x.ch_names),original_channels=list(names),window_starts=starts.copy(),window_samples=int(win),axis_order='channel, epoch')
 return dict(data=x.copy(),model=None,artifacts=out)
