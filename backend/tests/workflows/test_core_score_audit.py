"""Independent audit must reject altered identities and subject weighting."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def scorer():
    path = Path(__file__).resolve().parents[2] / 'scripts/audit_core_scores.py'
    spec = importlib.util.spec_from_file_location('core_score_audit_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.subject_scores


@pytest.fixture
def predictions():
    rows = []
    # A has eight balanced trials and always predicts left (BA .5).
    # B has two balanced trials and predicts both correctly (BA 1).
    # The subject mean is .75; pooling ten predictions would yield .6.
    for subject, labels in [('A', ['left_hand'] * 4 + ['right_hand'] * 4), ('B', ['left_hand', 'right_hand'])]:
        for i, label in enumerate(labels):
            rows.append(dict(event_id=f'{subject}:{i}', record_id=subject, subject=subject,
                             label=label, prediction='left_hand' if subject == 'A' else label, fold_id=subject))
    frozen = {r['event_id']: {k: r[k] for k in ('record_id', 'subject', 'label')} for r in rows}
    folds = {subject: {'development_subjects': [subject], 'train_subjects': [other]}
             for subject, other in [('A', 'B'), ('B', 'A')]}
    return rows, frozen, folds


def test_subjects_receive_equal_weight(scorer, predictions):
    subjects, score = scorer(*predictions)
    assert subjects == {'A': .5, 'B': 1} and score == .75


@pytest.mark.parametrize('damage', ['duplicate', 'wrong_label', 'training_group', 'wrong_probability'])
def test_altered_predictions_are_rejected(scorer, predictions, damage):
    rows, frozen, folds = deepcopy(predictions)
    seed = None
    if damage == 'duplicate':
        rows[-1] = rows[0]
    elif damage == 'wrong_label':
        rows[0]['label'] = 'right_hand'
    elif damage == 'training_group':
        rows[0]['fold_id'] = 'B'
    else:
        seed = 17
        for row in rows:
            row.update(seed=seed, proba_left=.9 if row['prediction'] == 'left_hand' else .1,
                       proba_right=.1 if row['prediction'] == 'left_hand' else .9)
        rows[0].update(proba_left=.1, proba_right=.9)
    with pytest.raises(ValueError):
        scorer(rows, frozen, folds, seed)
