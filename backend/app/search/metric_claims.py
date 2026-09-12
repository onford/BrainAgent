"""Deterministic evidence affordances; these checks do not certify prose semantics."""
import math
from typing import Literal

ClaimBasis=Literal['recorded_measurement','recorded_execution','recorded_missingness','frequency_distribution',
                   'paired_change','neural_preservation','normative_judgment','exact_covariance_singularity']


def spectral_facts(row):
    import numpy as np
    if row.get('status')!='ok':
        return None
    try:
        frequencies=np.asarray(row.get('axes',{}).get('frequencies_hz'),dtype=float)
        values=np.asarray(row.get('value'),dtype=float)
        if frequencies.ndim!=1 or len(frequencies)<2 or values.ndim<1 or values.shape[-1]!=len(frequencies):
            return None
        if not np.isfinite(values).all() or not np.isfinite(frequencies).all() or np.any(np.diff(frequencies)<=0) or np.any(values<0):
            return None
        spectrum=values.reshape(-1,len(frequencies)).mean(axis=0)
        peak=int(spectrum.argmax())
        total=float(np.sum((spectrum[:-1]+spectrum[1:])*.5*np.diff(frequencies)))
        if not math.isfinite(total) or total<=0:return None
        return dict(status='computed',scope='equal mean over the saved PSD non-frequency axes; saved aggregate only',
            frequency_grid_hz=[float(frequencies[0]),float(frequencies[-1])],frequency_bins=len(frequencies),
            maximum_bin_hz=float(frequencies[peak]),maximum_bin_psd=float(spectrum[peak]),psd_unit=row.get('unit'),
            minimum_bin_psd=float(spectrum.min()),maximum_bin_count=int(np.count_nonzero(spectrum==spectrum[peak])),
            maximum_bin_tie_policy='first saved frequency; a maximum is not necessarily unique or a physiological oscillation',
            integral_on_saved_grid=total,integration='trapezoid on saved frequency grid',
            within_record_reduction=row.get('within_record_reduction','not_recorded'),
            limitations='A sampled aggregate PSD maximum does not establish neural origin, temporal localization, or every subject having that maximum.')
    except (ValueError,TypeError,OverflowError):
        return None


def inference_contract(evidence,metric_id):
    main='metric:'+metric_id
    return {
        'recorded_measurement':dict(available=evidence[main].get('status')=='ok',requires=[main]),
        'recorded_execution':dict(available=bool(evidence.get('execution',{}).get('profiles')),requires=['execution']),
        'recorded_missingness':dict(available=bool(evidence.get('missing',{}).get('record_reason_counts')),requires=['missing']),
        'frequency_distribution':dict(available=bool(evidence.get('spectral_facts')),requires=['spectral_facts'],
            limitation='Total variance, amplitude, rank or a bandpass setting alone cannot establish frequency dominance.'),
        'paired_change':dict(available=False,requires=[],limitation='This is a single candidate/stage reading; no verified paired change was supplied.'),
        'neural_preservation':dict(available=False,requires=[],limitation='These measurements do not provide neural ground truth.'),
        'normative_judgment':dict(available=False,requires=[],limitation='No independently validated normative population or physiological cutoff is supplied.'),
        'exact_covariance_singularity':dict(available=False,requires=[],limitation='Numerical tolerance and averaged rank cannot prove an exactly zero eigenvalue.'),
    }


def validate_claim_basis(claim,ctx):
    contract=ctx['inference_contract']
    for basis in claim.basis:
        row=contract[basis]
        if not row['available'] or not set(row['requires'])<=set(claim.evidence_ids):
            raise ValueError('解读所声明的推断依据未提供或未引用：'+basis)
    if claim.epistemic_status=='unverified_hypothesis':
        if not claim.assumptions or not all(s.strip() for s in claim.assumptions) or not claim.competing_explanation or not claim.testable_prediction:
            raise ValueError('待验证假设必须列明前提、竞争解释与可检验预测')
    elif claim.assumptions or claim.competing_explanation or claim.testable_prediction:
        raise ValueError('假设内容必须显式标为待验证假设')
    if claim.epistemic_status=='measurement_description' and 'recorded_measurement' not in claim.basis:
        raise ValueError('测量描述必须引用实际可用测量')
