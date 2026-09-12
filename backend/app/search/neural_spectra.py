"""IRASA-style spectral descriptions with explicit resampling support; no fitting."""
from fractions import Fraction
import math

import numpy as np
from scipy.signal import resample_poly, welch


def irasa_components(values, *, sfreq, nominal_band_hz, channels, window_ids, check=lambda: None):
    """Fixed 2 s Hann Welch windows, nine reciprocal factor pairs, no peak fit.

    Output is an approximate decomposition of observed PSD, not a classification
    into neural and artifact sources. Negative differences are retained.
    """
    x = np.asarray(values)
    if x.dtype.kind != 'f':
        raise ValueError('spectral decomposition requires real floating voltage')
    if x.ndim != 3 or len(channels) != x.shape[1] or len(window_ids) != x.shape[0] or not len(window_ids):
        raise ValueError('spectral decomposition needs window/channel/sample identities')
    if len(set(channels)) != len(channels) or len(set(window_ids)) != len(window_ids):
        raise ValueError('spectral decomposition identities must be unique')
    if type(sfreq) not in (int, float) or not math.isfinite(sfreq) or sfreq <= 0:
        raise ValueError('invalid spectral sampling rate')
    factors = [Fraction(i, 10) for i in range(11, 20)]
    result = dict(schema_version='irasa-description-1', status='not_applicable', channels=list(channels),
        window_ids=list(window_ids), expected_windows=len(window_ids), available_windows=0,
        unit='uV^2/Hz', requested_analysis_band_hz=[2., 30.], nominal_input_band_hz=nominal_band_hz,
        parameters=dict(factors=[float(h) for h in factors], window_seconds=2., overlap_fraction=.5,
            minimum_welch_segments=2, welch_window='hann', detrend='constant', scaling='density',
            resampling='scipy.signal.resample_poly, Kaiser beta 5, constant extension; discard the FIR half-support',
            frequency_interpretation='retain original nominal sfreq for resampled sequences',
            estimator='median over reciprocal-pair PSD geometric means; mixed minus aperiodic without clipping',
            fitting='none; no individual peak, slope or preprocessing parameter fit'),
        limitations=['IRASA separates approximately scale-free and frequency-specific statistical components, not neural versus artifact sources.',
            'Nominal band support is not a calibrated transfer function; unknown acquisition filters remain unknown.',
            'Welch segment counts differ after reciprocal resampling; nonstationarity and broad/multiple peaks can bias separation.',
            'Across-factor quantiles describe estimator sensitivity, not a confidence interval or independent repetitions.',
            'Signed mixed-minus-aperiodic values can be negative and are retained; no nonnegative clipping or inferred missing bandwidth.'])
    if not np.isfinite(x).all():
        return {**result, 'reason': 'nonfinite_input_windows'}
    if not x.shape[-1] or np.any(np.ptp(x, axis=-1) == 0):
        return {**result, 'reason': 'constant_or_empty_window_channel'}
    try:
        lo, hi = nominal_band_hz
        valid_band = all(type(v) in (int, float) and math.isfinite(v) for v in (lo, hi)) and 0 <= lo < hi <= sfreq / 2
    except (TypeError, ValueError):
        valid_band = False
    if not valid_band:
        return {**result, 'reason': 'declared_nominal_passband_required'}
    nperseg = int(round(2 * sfreq))
    if nperseg < 8 or not math.isclose(nperseg, 2 * sfreq, abs_tol=1e-8):
        return {**result, 'reason': 'invalid_welch_sample_grid'}
    noverlap = nperseg // 2
    def segment_count(n): return 0 if n < nperseg else 1 + (n-nperseg) // (nperseg-noverlap)
    # Bound support before resampling or PSD computation.
    support = [max(2., lo * float(max(factors))), min(30., hi / float(max(factors)), sfreq / (2 * float(max(factors))))]
    result['supported_analysis_band_hz'] = support
    frequencies = np.fft.rfftfreq(nperseg, 1 / sfreq)
    mask = (frequencies >= support[0]) & (frequencies <= support[1]) & (frequencies > 0)
    if np.count_nonzero(mask) < 3:
        return {**result, 'reason': 'insufficient_supported_frequency_bins_after_resampling'}
    counts = []
    for factor in factors:
        row = []
        for up, down in [(factor.numerator, factor.denominator), (factor.denominator, factor.numerator)]:
            trim = math.ceil(10 * max(up, down) / down)
            n = math.ceil(x.shape[-1] * up / down) - 2 * trim
            row.append(dict(up=up, down=down, discarded_edge_samples_each_side=trim, welch_segments=segment_count(n)))
        counts.append(row)
    result['resampling_support'] = counts
    if segment_count(x.shape[-1]) < 2 or any(r['welch_segments'] < 2 for pair in counts for r in pair):
        return {**result, 'reason': 'insufficient_contiguous_resampled_welch_support'}
    if not np.isfinite(x * 1e6).all():
        return {**result, 'reason': 'voltage_scale_overflow'}
    def spectrum(a):
        return welch(a, fs=sfreq, window='hann', nperseg=nperseg, noverlap=noverlap,
            nfft=nperseg, detrend='constant', scaling='density', axis=-1, average='mean')[1][..., mask]
    check()
    mixed = spectrum(x * 1e6)
    pairs = []
    for pair in counts:
        powers = []
        for resampling in pair:
            check()
            up, down = resampling['up'], resampling['down']
            y = resample_poly(x * 1e6, up, down, axis=-1, window=('kaiser', 5.), padtype='constant')
            trim = resampling['discarded_edge_samples_each_side']
            powers.append(spectrum(y[..., trim:-trim]))
        # Separate square roots avoid avoidable overflow of a PSD product.
        pairs.append(np.sqrt(powers[0]) * np.sqrt(powers[1]))
    ensemble = np.stack(pairs)
    aperiodic = np.median(ensemble, axis=0)
    periodic = mixed - aperiodic
    if not all(np.isfinite(a).all() for a in (mixed, aperiodic, periodic)):
        return {**result, 'reason': 'nonfinite_spectral_estimate'}
    complete_band = support[0] == 2. and support[1] == 30.
    result.update(status='evaluated' if complete_band else 'partial', reason=None if complete_band else 'requested_band_partially_supported',
        frequencies_hz=frequencies[mask].tolist(), available_windows=len(window_ids),
        mixed_psd=mixed.mean(axis=(0, 1)).tolist(), aperiodic_psd=aperiodic.mean(axis=(0, 1)).tolist(),
        periodic_difference_psd=periodic.mean(axis=(0, 1)).tolist(),
        factor_sensitivity_q10_q90=np.quantile(ensemble.mean(axis=(1, 2)), [.1, .9], axis=0).tolist(),
        aggregation='equal supplied windows and channels; not a human population estimate',
        source_url='https://pmc.ncbi.nlm.nih.gov/articles/PMC4706469/',
        implementation_scope='IRASA-style engineering estimator; fixed Welch/factor/support settings, not a claim of exact author implementation')
    return result


def spectral_components_diagnostic(quality, stage, context):
    from .diagnostic_windows import verified_windows
    rows = []
    complete = False
    for rid, values, contract, reason, inventory_complete in verified_windows(quality, stage, context):
        complete = inventory_complete
        if values is None:
            rows.append(dict(record_id=rid, status='unavailable', reason=reason))
            continue
        r = irasa_components(values, sfreq=contract['sfreq'], channels=contract['channels'],
            window_ids=contract['window_ids'], nominal_band_hz=(contract.get('history') or {}).get('nominal_band_hz'),
            check=context['check'])
        r.update(record_id=rid, window_contract=contract)
        r['signed_periodic_fraction'] = None
        if r['status'] in ('evaluated', 'partial'):
            f = np.array(r['frequencies_hz'])
            def integral(a):
                a = np.asarray(a)
                return float(np.sum(np.diff(f) * (a[1:] + a[:-1]) * .5))
            total = integral(r['mixed_psd'])
            if total > 0:
                r['signed_periodic_fraction'] = integral(r['periodic_difference_psd']) / total
        rows.append(r)
    available = [r for r in rows if r['status'] == 'evaluated' and r.get('signed_periodic_fraction') is not None]
    valid = complete and bool(rows) and len(available) == len(rows)
    return dict(status='evaluated' if valid else 'unavailable', spectral_components=dict(
        status='ok' if valid else 'unavailable', records=rows,
        signed_periodic_fraction=dict(status='ok' if valid else 'unavailable',
            value=math.fsum(r['signed_periodic_fraction'] for r in available) / len(rows) if valid else None,
            expected_records=quality.get('coverage', {}).get('records_expected'), available_records=len(available),
            unit='signed_ratio', band_hz=[2., 30.]),
        scope='first up to 16 seconds per verified continuous stage; equal records; no full-record representativeness or neural protection claim',
        missing_policy='partial bands, missing windows and unvisited records never silently removed from aggregate'))
