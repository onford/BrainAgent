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
