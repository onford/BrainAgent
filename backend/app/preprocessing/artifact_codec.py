"""Closed, lossless artifact codecs. No pickle, arbitrary imports or constructors."""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import numpy as np
import mne
from scipy import sparse

from .storage import file_hash, within, digest

ICA_EXACT=('unmixing_matrix_','mixing_matrix_','pca_components_','pca_mean_','pre_whitener_','fit_params','exclude','labels_','n_components_','n_samples_','pca_explained_variance_','info','current_fit','n_pca_components')


def fingerprint(value):
    def encode(v):
        if sparse.issparse(v):
            a=v.tocsr();return ['sparse',list(a.shape),encode(a.data),encode(a.indices),encode(a.indptr)]
        if isinstance(v,np.ndarray):
            if v.dtype.hasobject:return ['object-array',v.shape,[encode(x) for x in v.flat]]
            return ['ndarray',v.dtype.str,list(v.shape),hashlib.sha256(np.ascontiguousarray(v).tobytes()).hexdigest()]
        if isinstance(v,np.generic):return encode(v.item())
        if isinstance(v,bytes):return ['bytes',len(v),hashlib.sha256(v).hexdigest()]
        if isinstance(v,complex):return ['complex',encode(v.real),encode(v.imag)]
        if isinstance(v,float) and not np.isfinite(v):return ['float',str(v)]
        if v is None or isinstance(v,(str,int,float,bool)):return v
        if isinstance(v,datetime):return ['datetime',v.isoformat()]
        if isinstance(v,np.random.RandomState):return ['random_state',encode(v.get_state())]
        if type(v).__module__=='sklearn.model_selection._split' and type(v).__name__=='_CVIterableWrapper':return ['cv_folds',encode(v.cv)]
        if isinstance(v,(list,tuple)):return ['tuple' if isinstance(v,tuple) else 'list',[encode(x) for x in v]]
        if isinstance(v,dict):return ['dict',[[encode(k),encode(x)] for k,x in sorted(v.items(),key=lambda p:str(p[0]))]]
        if isinstance(v,(mne.io.BaseRaw,mne.BaseEpochs)):
            return ['signal',state(v),encode(v.info),encode(v.times),encode(v.get_data()),encode(v.info['projs']),
                    encode([ch['loc'] for ch in v.info['chs']]),
                    encode(v.annotations) if isinstance(v,mne.io.BaseRaw) else encode([v.events,v.selection,v.drop_log,v.baseline])]
        if isinstance(v,mne.Annotations):return ['annotations',encode(v.onset),encode(v.duration),encode(v.description),encode(v.ch_names),encode(v.orig_time)]
        if isinstance(v,mne.preprocessing.ICA):
            return ['ica',encode({k:getattr(v,k) for k in ('method','ch_names',*ICA_EXACT) if hasattr(v,k)})]
        if isinstance(v,mne.preprocessing.EOGRegression):return ['eog',encode(v.__dict__)]
        if type(v).__module__.startswith('asrpy.') and type(v).__name__=='ASR':return ['asr',encode(v.__dict__)]
        if type(v).__module__.startswith('autoreject') and type(v).__name__=='AutoReject':return ['autoreject',encode(v.__getstate__())]
        raise ValueError('unregistered fingerprint type: '+type(v).__name__)
    return digest(encode(value))


def state(x,unit=None):
    if isinstance(x,np.ndarray):return {'kind':'array','shape':list(x.shape),'unit':unit or 'V'}
    types=x.get_channel_types();unit=unit or ('V/m^2' if 'csd' in types else 'V')
    return dict(kind='raw' if isinstance(x,mne.io.BaseRaw) else 'epochs',channels=x.ch_names,
        types=types,bads=list(x.info['bads']),unit=unit,sfreq=float(x.info['sfreq']),
        channel_units={name:'V/m^2' if kind=='csd' else 'V' for name,kind in zip(x.ch_names,types)},
        shape=list(x.get_data().shape),first_sample=int(x.first_samp) if isinstance(x,mne.io.BaseRaw) else None,
        custom_ref_applied=int(x.info['custom_ref_applied']),highpass=float(x.info['highpass']),lowpass=float(x.info['lowpass']))


class Codec:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.index=0

    def file(self,suffix):
        self.index+=1
        return self.root/f'v{self.index:05}{suffix}'

    def file_ref(self,path,kind,**extra):
        return {'codec':kind,'file':path.name,'sha256':file_hash(path),**extra}

    def dump(self,value):
        if sparse.issparse(value):
            a=value.tocsr();return {'codec':'sparse_csr','shape':list(a.shape),'data':self.dump(a.data),'indices':self.dump(a.indices),'indptr':self.dump(a.indptr)}
        if isinstance(value,np.ndarray):
            if value.dtype.hasobject:
                return {'codec':'object_array','shape':list(value.shape),'items':[self.dump(v) for v in value.flat]}
            p=self.file('.npy');np.save(p,value,allow_pickle=False)
            return self.file_ref(p,'ndarray',shape=list(value.shape),dtype=value.dtype.str)
        if isinstance(value,np.generic):return self.dump(value.item())
        if isinstance(value,bytes):
            p=self.file('.bin');p.write_bytes(value)
            return self.file_ref(p,'bytes',size=len(value))
        if isinstance(value,complex):return {'codec':'complex','real':self.dump(value.real),'imag':self.dump(value.imag)}
        if isinstance(value,float) and not np.isfinite(value):return {'codec':'nonfinite','value':str(value)}
        if value is None or isinstance(value,(str,int,float,bool)):return value
        if isinstance(value,datetime):return {'codec':'datetime','value':value.isoformat()}
        if isinstance(value,mne.Annotations):
            return {'codec':'annotations','onset':self.dump(value.onset),'duration':self.dump(value.duration),'description':self.dump(value.description),'ch_names':self.dump(value.ch_names),'orig_time':self.dump(value.orig_time)}
        if isinstance(value,(mne.io.BaseRaw,mne.BaseEpochs)):
            raw=isinstance(value,mne.io.BaseRaw);p=self.file('-raw.fif' if raw else '-epo.fif')
            value.save(p,fmt='double',overwrite=False,verbose='ERROR')
            return self.file_ref(p,'raw' if raw else 'epochs',array=self.dump(value.get_data()),
                info_exact=self.dump(value.info),times=self.dump(value.times),
                loc=self.dump([c['loc'] for c in value.info['chs']]),projs=self.dump(list(value.info['projs'])),
                annotations=self.dump(value.annotations) if raw else None,
                selection=self.dump(value.selection) if not raw else None,
                events=self.dump(value.events) if not raw else None,
                drop_log=self.dump(value.drop_log) if not raw else None,
                baseline=self.dump(value.baseline) if not raw else None,
                highpass=value.info['highpass'],lowpass=value.info['lowpass'],custom_ref_applied=int(value.info['custom_ref_applied']))
        if isinstance(value,mne.preprocessing.ICA):
            p=self.file('-ica.fif');value.save(p,overwrite=False,verbose='ERROR')
            # Preserve bitwise matrices and tuple/dict fit parameters for component IDs.
            fields={k:getattr(value,k) for k in ICA_EXACT if hasattr(value,k)}
            return self.file_ref(p,'ica',exact=self.dump(fields))
        if isinstance(value,mne.preprocessing.EOGRegression):
            p=self.file('-eog.h5');value.save(p,overwrite=False)
            return self.file_ref(p,'eog',exact=self.dump(value.__dict__))
        if type(value).__module__.startswith('asrpy.') and type(value).__name__=='ASR':
            return {'codec':'asr','state':self.dump(value.__dict__)}
        if type(value).__module__.startswith('autoreject') and type(value).__name__=='AutoReject':
            # Upstream HDF5 cannot encode explicitly frozen CV folds. Use the
            # author's state protocol with a closed fold codec, never pickle.
            return {'codec':'autoreject_state','state':self.dump(value.__getstate__())}
        if type(value).__module__=='sklearn.model_selection._split' and type(value).__name__=='_CVIterableWrapper':
            return {'codec':'cv_folds','folds':self.dump(value.cv)}
        if isinstance(value,np.random.RandomState):return {'codec':'random_state','state':self.dump(value.get_state())}
        if isinstance(value,dict):
            return {'codec':'forward' if isinstance(value,mne.Forward) else 'info' if isinstance(value,mne.Info) else 'projection' if isinstance(value,mne.Projection) else 'dict','items':[[self.dump(k),self.dump(v)] for k,v in value.items()]}
        if isinstance(value,(list,tuple)):return {'codec':'source_spaces' if isinstance(value,mne.SourceSpaces) else 'tuple' if isinstance(value,tuple) else 'list','items':[self.dump(v) for v in value]}
        raise ValueError('unregistered artifact serializer: '+type(value).__module__+'.'+type(value).__name__)

    def load(self,value):
        if not isinstance(value,dict):return value
        kind=value['codec'];p=None
        if kind=='sparse_csr':return sparse.csr_matrix((self.load(value['data']),self.load(value['indices']),self.load(value['indptr'])),shape=value['shape'])
        if kind=='complex':return complex(self.load(value['real']),self.load(value['imag']))
        if 'file' in value:
            p=within(self.root,value['file'])
            if file_hash(p)!=value['sha256']:raise ValueError('artifact checksum changed')
        if kind=='ndarray':
            a=np.load(p,allow_pickle=False)
            if a.dtype.str!=value['dtype'] or list(a.shape)!=value['shape']:raise ValueError('array metadata mismatch')
            return a
        if kind=='bytes':
            result=p.read_bytes()
            if len(result)!=value['size']:raise ValueError('byte artifact size mismatch')
            return result
        if kind=='object_array':
            out=np.empty(value['shape'],dtype=object)
            for i,v in enumerate(value['items']):out.flat[i]=self.load(v)
            return out
        if kind=='nonfinite':return float(value['value'])
        if kind=='datetime':return datetime.fromisoformat(value['value'])
        if kind in ('dict','projection','info','forward'):
            d={self.load(k):self.load(v) for k,v in value['items']}
            return mne.Forward(d) if kind=='forward' else mne.Info(d) if kind=='info' else mne.Projection(**d) if kind=='projection' else d
        if kind in ('list','tuple','source_spaces'):
            items=[self.load(v) for v in value['items']]
            return mne.SourceSpaces(items) if kind=='source_spaces' else tuple(items) if kind=='tuple' else items
        if kind=='annotations':return mne.Annotations(**{k:self.load(value[k]) for k in ('onset','duration','description','ch_names','orig_time')})
        if kind in ('raw','epochs'):
            x=mne.io.read_raw_fif(p,preload=True,verbose='ERROR') if kind=='raw' else mne.read_epochs(p,preload=True,verbose='ERROR')
            x._data=self.load(value['array'])
            if 'info_exact' in value:x.info=self.load(value['info_exact'])
            for ch,loc in zip(x.info['chs'],self.load(value['loc'])):ch['loc']=loc
            with x.info._unlock():
                x.info['projs']=self.load(value['projs']);x.info['highpass']=value['highpass'];x.info['lowpass']=value['lowpass']
                x.info['custom_ref_applied']=value['custom_ref_applied']
            if kind=='raw':x._annotations=self.load(value['annotations'])
            else:
                x.selection=self.load(value['selection']);x.baseline=self.load(value['baseline'])
                x.events=self.load(value['events']);x.drop_log=self.load(value['drop_log'])
                if 'times' in value:
                    x._set_times(self.load(value['times']));x._raw_times=x.times.copy()
            return x
        if kind=='ica':
            x=mne.preprocessing.read_ica(p,verbose='ERROR')
            for k,v in self.load(value['exact']).items():setattr(x,k,v)
            return x
        if kind=='eog':
            x=mne.preprocessing.read_eog_regression(p)
            if 'exact' in value:x.__dict__.update(self.load(value['exact']))
            return x
        if kind=='asr':
            from asrpy import ASR
            x=ASR.__new__(ASR);x.__dict__.update(self.load(value['state']));return x
        if kind=='autoreject':
            from autoreject import read_auto_reject
            return read_auto_reject(p)
        if kind=='autoreject_state':
            from autoreject import AutoReject
            x=AutoReject();x.__setstate__(self.load(value['state']));return x
        if kind=='cv_folds':
            from sklearn.model_selection import check_cv
            return check_cv(self.load(value['folds']))
        if kind=='random_state':
            x=np.random.RandomState();x.set_state(self.load(value['state']));return x
        raise ValueError('unregistered artifact codec: '+kind)

    def verified_dump(self,value):
        result=self.dump(value)
        if fingerprint(value)!=fingerprint(self.load(result)):raise ValueError('artifact numerical/state roundtrip differs')
        return result
