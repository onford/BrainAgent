from copy import deepcopy

from app.search.conclusions import qualify
from app.search.method_space import BASELINE_ID
from tests.search.test_reporting import make_report_case


def test_complete_measurement_does_not_establish_scientific_claims(tmp_path, monkeypatch):
    _, state, _ = make_report_case(tmp_path, monkeypatch)
    result = qualify(state)
    claims = {c['id']: c['status'] for c in result['claims']}
    assert claims['development_predictability'] == 'supported_within_scope'
    assert claims['physical_proxy_measurements'] == 'supported_within_scope'
    for name in ('neural_preservation', 'independent_generalization', 'preprocessing_specific_benefit'):
        assert claims[name] == 'not_established'
    reference = deepcopy(state['candidates'][0])
    reference['id'] = BASELINE_ID
    state['candidates'].append(reference)
    assert qualify(state)['paired_development_score_difference'] == 0
    reference['receipt']['assessment']['bindings']['panel_hash'] = '0' * 64
    assert qualify(state)['paired_development_score_difference'] is None


def test_missing_seed_and_failed_candidate_never_get_a_primary_claim(tmp_path, monkeypatch):
    _, state, _ = make_report_case(tmp_path, monkeypatch, missing=True)
    state['selected_candidate_id'] = state['candidates'][0]['id']
    assert qualify(state)['primary_development_score'] is None
    state['candidates'][0]['status'] = 'failed'
    result = qualify(state)
    assert all(c['status'] != 'supported_within_scope' for c in result['claims'])
