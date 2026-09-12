from app.workflows.artifacts import local_files


def test_published_artifacts_exclude_hidden_directories_and_editor_residue(tmp_path):
    names = [
        "survey/local-inspection.json",
        "survey/reports/data-information.html",
        "survey/.history/record.json",
        ".git/config",
        "survey/report.html.bak",
        "survey/record.json.orig",
        "survey/record.json.rej",
        "survey/record.json~",
        "survey/.record.tmp",
        "survey/reports/.cache/report.html",
    ]
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test", encoding="utf-8")
    published = local_files(
        tmp_path, {"stages": [{"name": "data_survey", "status": "completed"}]}
    )
    assert {a["name"] for a in published} == set(names[:2])


def test_validator_outputs_publish_only_after_receipt_while_collection_active(tmp_path):
    root = tmp_path / 'collection/official-validator/attempt'
    root.mkdir(parents=True)
    (root / 'result.json').write_text('{"issues":{}}', encoding='utf-8')
    (root / 'stdout.log').write_text('', encoding='utf-8')
    state = {'stages': [{'name': 'data_collection', 'status': 'running'}]}
    assert local_files(tmp_path, state) == []
    (root / 'receipt.json').write_text('{"status":"failed"}', encoding='utf-8')
    published = local_files(tmp_path, state)
    assert {a['name'] for a in published} == {
        'collection/official-validator/attempt/' + name
        for name in ['result.json', 'stdout.log', 'receipt.json']}
    assert all(a['sha256'] for a in published)
    state['stages'][0]['status'] = 'cancelled'
    assert local_files(tmp_path, state, published) == published
