from types import SimpleNamespace
import pytest
from app.search.metric_claims import inference_contract,spectral_facts,validate_claim_basis


def test_total_variance_does_not_authorize_frequency_or_neural_claims():
    evidence={'metric:covariance_trace':{'status':'ok','value':123},'execution':{'profiles':[{'unit':'V'}]},'missing':{}}
    ctx={'inference_contract':inference_contract(evidence,'covariance_trace')}
    for basis in ('frequency_distribution','paired_change','neural_preservation','normative_judgment','exact_covariance_singularity'):
        claim=SimpleNamespace(basis=[basis],evidence_ids=['metric:covariance_trace'],epistemic_status='measurement_description')
        with pytest.raises(ValueError,match='依据'):validate_claim_basis(claim,ctx)


def test_spectral_facts_bind_to_actual_frequency_axes_and_keep_scope():
    row={'status':'ok','unit':'µV²/Hz','axes':{'frequencies_hz':[0,10,20]},'value':[1,4,1]}
    facts=spectral_facts(row)
    assert facts['maximum_bin_hz']==10 and facts['integral_on_saved_grid']==50
    assert facts['frequency_grid_hz']==[0,20]
    assert spectral_facts({**row,'value':{'array_summary_only':True,'maximum':4}}) is None
    assert spectral_facts({**row,'value':[0,0,0]}) is None
    assert spectral_facts({**row,'status':'partial'}) is None
    assert spectral_facts({**row,'axes':{'frequencies_hz':[0,20,10]}}) is None


def test_hypothesis_requires_assumptions_alternative_and_prediction():
    ctx={'inference_contract':inference_contract({'metric:covariance_trace':{'status':'ok'}},'covariance_trace')}
    claim=SimpleNamespace(basis=['recorded_measurement'],evidence_ids=['metric:covariance_trace'],
        epistemic_status='unverified_hypothesis',assumptions=[],competing_explanation=None,testable_prediction=None)
    with pytest.raises(ValueError,match='假设'):validate_claim_basis(claim,ctx)
    claim.assumptions=['example unverified premise']
    claim.competing_explanation='example alternative'
    claim.testable_prediction='example observation to measure'
    validate_claim_basis(claim,ctx)
    claim.epistemic_status='measurement_description'
    with pytest.raises(ValueError,match='假设'):validate_claim_basis(claim,ctx)
