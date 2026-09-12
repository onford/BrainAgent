import asyncio
from copy import deepcopy
import json
from time import monotonic
import pytest

from app.preprocessing.literature import LiteratureExtraction, materialize
from app.preprocessing.literature_verification import verify_extraction, ClaimReview, _numeric_supported, TargetPredicate, target_predicate
from app.preprocessing.research_budget import open_budget, reserve
from tests.search.test_literature_space import branch, EVIDENCE, review_double
from tests.preprocessing.conftest import make_dataset


def test_concurrent_intakes_cannot_reuse_the_same_recovery_slots(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import json
    path = tmp_path / 'budget.json'
    limits = {'max_seconds': 30, 'max_recovery_actions': 3}
    # Model separate API requests that opened the same ledger before anyone
    # reserved an action. Each has a stale in-memory copy with used=0.
    budgets = [open_budget(path, limits, {'source': 'shared'}) for _ in range(8)]
    def attempt(index):
        try:
            reserve(budgets[index], {'request': index})
            return True
        except TimeoutError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(8))) == 3
    saved = json.loads(path.read_text())
    assert saved['used'] == 3
    assert [a['sequence'] for a in saved['actions']] == [1, 2, 3]
    assert len({a['request'] for a in saved['actions']}) == 3


def test_named_montage_requires_actual_template_coordinates_and_review_binding(tmp_path, monkeypatch):
    import mne
    import numpy as np
    from app.preprocessing.literature_verification import verified_claims
    from app.preprocessing import inputs
    data=make_dataset(tmp_path/'bids')
    for r in data.collection.records:
        r.channels={'C3':'eeg','C4':'eeg'}
        r.channel_order=['C3','C4']
    raw=mne.io.RawArray(np.zeros((2, 8000)),mne.create_info(['C3','C4'],160,'eeg'),verbose='ERROR')
    raw.set_montage('standard_1005')
    monkeypatch.setattr(inputs,'read_record',lambda *args:(raw.copy(),None,None))
    predicate=TargetPredicate(kind='geometry',value={'template':'standard_1005'})
    assert target_predicate(predicate,data)[0]=='satisfied'
    assert target_predicate(TargetPredicate(kind='channel_standardization',value='mne_eegbci'),data)[0]=='satisfied'
    b=branch()
    b['prerequisites']=[dict(description='Upstream source montage',status='satisfied',target_basis='must be independently checked',
        evidence_indices=[0],predicate=predicate.model_dump())]
    extraction=LiteratureExtraction.model_validate({'branches':[b]})
    async def ask(op,model,context,instruction):
        assert context['verified_target_prerequisites'][0]['prerequisites'][0]['computed_status']=='satisfied'
        return review_double(model,context)
    review=asyncio.run(verify_extraction(ask,extraction,EVIDENCE,data))
    identity={'semantic_verification':review}
    assert verified_claims(extraction,EVIDENCE,identity,data)
    # Coordinates remain finite, but are no longer the source's named montage.
    raw.info['chs'][0]['loc'][0] += .005
    assert target_predicate(TargetPredicate(kind='geometry',value=True),data)[0]=='satisfied'
    assert target_predicate(predicate,data)[0]=='missing'
    assert not verified_claims(extraction,EVIDENCE,identity,data)
    assert target_predicate(TargetPredicate(kind='geometry',value={'template':'made_up'}),data)[0]=='unknown'
    assert target_predicate(TargetPredicate(kind='geometry',value={'template':''}),data)[0]=='unknown'
    raw.set_montage('standard_1005')
    raw.info['chs'][0]['coord_frame']=0
    assert target_predicate(predicate,data)[0]=='missing'


def test_matching_numeric_token_does_not_bypass_independent_semantic_rejection(tmp_path):
    extraction=LiteratureExtraction.model_validate({'branches':[branch()]})
    async def ask(op,model,context,instruction):
        result=review_double(model,context)
        next(r for r in result.claims if r.claim_id.endswith('.l_freq')).status='unsupported'
        return result
    review=asyncio.run(verify_extraction(ask,extraction,EVIDENCE))
    method,=materialize(extraction,EVIDENCE,make_dataset(tmp_path/'bids'),{'semantic_verification':review})
    assert any(i.code=='source_semantics_unverified' and '.l_freq' in i.message for i in method.issues)
    modified=extraction.model_copy(deep=True);modified.branches[0].method.recipe[0].params['h_freq']=33
    stale,=materialize(modified,EVIDENCE,make_dataset(tmp_path/'another'),{'semantic_verification':review})
    assert sum(i.code=='source_semantics_unverified' for i in stale.issues)==6


def test_wrong_units_other_numbers_and_missing_span_are_rejected():
    review=ClaimReview(claim_id='x',status='supported',quote='Reject windows exceeding 100 µV.',source_unit='uV',target_unit='V',reason='voltage threshold')
    assert _numeric_supported(.0001,review)
    assert not _numeric_supported(100,review)
    review.target_unit='Hz'
    assert not _numeric_supported(.0001,review)
    review=review.model_copy(update={'quote':'8–30 Hz','source_unit':'Hz','target_unit':'Hz'})
    assert _numeric_supported(30,review) and not _numeric_supported(40,review)


def test_prerequisites_use_actual_partition_roles_and_channels(tmp_path):
    data=make_dataset(tmp_path/'bids')
    assert target_predicate(TargetPredicate(kind='partition',value={'id':'heldout','role':'train'}),data)[0]=='missing'
    assert target_predicate(TargetPredicate(kind='partition',value={'id':'calibration','role':'calibration','min_seconds':10}),data)[0]=='satisfied'
    assert target_predicate(TargetPredicate(kind='channel_type',value='emg'),data)[0]=='missing'
    assert target_predicate(None,data)[0]=='unknown'
    b=branch();b['prerequisites']=[dict(description='Real EMG channels',status='satisfied',target_basis='The model says EMG exists',
        evidence_indices=[0],predicate={'kind':'channel_type','value':'emg'})]
    m,=materialize(LiteratureExtraction.model_validate({'branches':[b]}),EVIDENCE,data,{})
    assert any(i.code=='missing_prerequisite' for i in m.issues)
    assert m.lineage['prerequisites'][0]['computed_status']=='missing'


def test_written_filter_order_and_grouped_digits_have_explicit_numeric_basis():
    from app.preprocessing.literature_verification import numeric_evidence
    review = ClaimReview(claim_id='order', status='supported',
        quote='a fifth-order Butterworth band-pass filter (8–30 Hz)', reason='order')
    row, = numeric_evidence(5, review, parameter='prototype_order', operation='butterworth')
    assert row['supported'] and row['basis'] == 'written_filter_order'
    assert not _numeric_supported(5, review, parameter='l_freq')
    for text in ['a twenty fifth-order filter', 'a forty-fifth-order filter', 'a sixth-order filter']:
        assert not _numeric_supported(5, review.model_copy(update={'quote': text}), parameter='order')
    review = review.model_copy(update={'quote':'sampled at 5,000 Hz', 'source_unit':'Hz','target_unit':'Hz'})
    assert _numeric_supported(5000, review)
    assert not _numeric_supported(5, review) and not _numeric_supported(0, review)


def test_event_onset_zero_requires_explicit_epoch_origin_and_semantic_value():
    from app.preprocessing.literature_verification import numeric_evidence
    review = ClaimReview(claim_id='start', status='supported',
        quote='the trials from each run were epoched from the onset to 4.0 s',
        source_value=0.0, source_unit='s', target_unit='s', reason='event-relative origin')
    row, = numeric_evidence(0, review, parameter='tmin', operation='epoch')
    assert row['supported'] and row['basis'] == 'event_relative_onset'
    assert not _numeric_supported(0, review, parameter='tmax', operation='epoch')
    assert not _numeric_supported(0, review, parameter='tmin', operation='crop')
    assert not _numeric_supported(0, review.model_copy(update={'source_value':False}), parameter='tmin', operation='epoch')
    for text in ['epoched from 0.2 s after the onset to 4.0 s', 'epoched before the onset', 'event onset was observed']:
        assert not _numeric_supported(0, review.model_copy(update={'quote': text}), parameter='tmin', operation='epoch')


def test_pdf_filter_order_ligatures_preserve_original_token_without_rewriting_numbers():
    from app.preprocessing.literature_verification import numeric_evidence
    quote = 'The ﬁlter was a ﬁfth-order Butterworth ﬁlter.'
    review = ClaimReview(claim_id='order', status='supported', quote=quote, reason='Synthetic literal order review')
    row, = numeric_evidence(5, review, parameter='prototype_order', operation='butterworth')
    assert row['supported']
    assert row['source_token'] == 'ﬁfth-order'
    assert row['normalized_token'] == 'fifth-order'
    assert review.quote == quote
    for text in ('twenty ﬁfth-order', 'forty-ﬁfth-order', '²-order', 'the order is ²'):
        assert not _numeric_supported(5 if 'ﬁfth' in text else 2,
            review.model_copy(update={'quote':text}), parameter='order')


def test_semantic_refusal_is_not_overridden_by_successful_numeric_checks():
    extraction = LiteratureExtraction.model_validate({'branches':[branch()]})
    async def ask(op, model, context, instruction):
        result = review_double(model, context)
        next(r for r in result.claims if r.claim_id.endswith('.l_freq')).status = 'unknown'
        return result
    review = asyncio.run(verify_extraction(ask, extraction, EVIDENCE))
    row = next(r for r in review['claims'] if r['claim_id'].endswith('.l_freq'))
    assert row['status'] == 'unknown'
    assert row['deterministic_checks']['numeric_evidence'][0]['supported'] is True


def test_action_reservations_and_deadline_survive_restarts(tmp_path):
    path=tmp_path/'budget.json';limits={'max_seconds':60,'max_recovery_actions':1}
    first=open_budget(path,limits,{'source':'test'})
    reserve(first,{'action':'read'})
    resumed=open_budget(path,limits,{'source':'test'})
    assert resumed['used']==1 and resumed['expires_at']==first['expires_at']
    with pytest.raises(TimeoutError):reserve(resumed,{'action':'read'})
    with pytest.raises(ValueError):open_budget(path,limits,{'source':'changed'})


def test_pdf_typography_keeps_exact_original_span_and_rejects_changed_meaning():
    from app.preprocessing.literature_verification import source_span
    source = "  the acquired signal was ﬁrstly down-\nsampled from 5,000 to 250 Hz"
    start, end = source_span(source, "firstly down-sampled from 5,000 to 250 Hz")
    assert source[start:end] == "ﬁrstly down-\nsampled from 5,000 to 250 Hz"
    assert source_span(source, "firstly down-sampled from 5,000 to 260 Hz") is None
    assert source_span(source, "firstly up-sampled from 5,000 to 250 Hz") is None
