import json
from pathlib import Path

import pytest

from app.workflows.local_metadata import inspect_metadata
from app.workflows.wfdb_annotations import compare_events


def inventory(root):
    return [{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size} for p in root.rglob('*') if p.is_file()]


def test_structured_metadata_keeps_declarations_paths_and_unknown_coordinates(tmp_path):
    files={
        'nested/dataset_description.json':json.dumps({'Name':'Declared dataset','BIDSVersion':'1.10.0','License':'n/a'}),
        'nested/participants.tsv':'participant_id\tage\tsex\nsub-01\tn/a\tF\nsub-02\t26\tn/a\n',
        'nested/sub-01/eeg/sub-01_task-rest_eeg.json':json.dumps({'EEGReference':'Cz','EEGGround':'AFz','Manufacturer':'Example','PowerLineFrequency':50}),
        'nested/sub-01/eeg/sub-01_coordsystem.json':json.dumps({'EEGCoordinateSystemDescription':'standard template positions','EEGCoordinateUnits':'m'}),
        'nested/sub-01/eeg/sub-01_electrodes.tsv':'name\tx\ty\tz\nC3\t0.1\t0.2\t0.3\n',
        'nested/sub-01/beh/sub-01_task-rest_beh.tsv':'onset\tresponse\n1.0\tn/a\n'}
    for name,text in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
    result=inspect_metadata(tmp_path,inventory(tmp_path))
    assert result.discovered_bids_roots==['nested']
    rows={r.kind:r for r in result.structured_files}
    assert rows['participants'].rows[0]['age']=='n/a'
    assert rows['acquisition'].values['EEGGround']=='AFz'
    assert 'ManufacturersModelName' in rows['acquisition'].unavailable_fields
    assert rows['coordinates'].coordinate_provenance=='declared_template'
    assert rows['electrodes'].coordinate_provenance=='unverified'
    assert rows['dataset'].unavailable_fields==['License']
    assert all(r.sha256 for r in rows.values())
    assert result.input_bytes==sum(p.stat().st_size for p in tmp_path.rglob('*') if p.is_file())


@pytest.mark.parametrize('text',['{"Name":"A","Name":"B"}','{"SamplingFrequency":NaN}'])
def test_ambiguous_or_nonfinite_json_is_not_an_observed_fact(tmp_path,text):
    (tmp_path/'dataset_description.json').write_text(text,encoding='utf-8')
    row=inspect_metadata(tmp_path,inventory(tmp_path)).structured_files[0]
    assert row.status=='read_error' and not row.values


def test_large_file_and_malformed_table_do_not_get_partial_facts_silently(tmp_path):
    (tmp_path/'participants.tsv').write_text('participant_id\tage\nsub-01\t20\textra\n',encoding='utf-8')
    (tmp_path/'dataset_description.json').write_bytes(b' '*(4*1024**2+1))
    rows={r.kind:r for r in inspect_metadata(tmp_path,inventory(tmp_path)).structured_files}
    assert rows['participants'].status=='read_error'
    assert rows['dataset'].status=='not_checked' and rows['dataset'].sha256 is None


def event_file(path, *, first='T0 duration: 1.0',second='T1 duration: 1.0'):
    # WFDB NOTE/AUX byte pairs, written independently of the decoder.
    def note(delta,text):
        body=text.encode('ascii');n=len(body)
        return bytes([delta&255,(22<<2)|(delta>>8),n,63<<2])+body+b'\0'*(n%2)
    path.write_bytes(note(0,'## time resolution: 160')+note(0,first)+note(160,second)+b'\0\0')


def test_byte_decoding_retains_sample_zero_note_and_compares_duration(tmp_path):
    pytest.importorskip('wfdb')
    path=tmp_path/'record.edf.event';event_file(path)
    edf=[dict(label='T0',onset_s=0.,duration_s=1.),dict(label='T1',onset_s=1.,duration_s=1.)]
    result=compare_events(path,path.name,edf,160.)
    assert result.status=='matched' and result.wfdb_count==2
    assert result.annotations[0].sample==0 and result.annotations[0].label=='T0'
    assert result.maximum_onset_difference_samples==0
    assert result.maximum_duration_difference_samples==0
    edf[1]['duration_s']=2.
    result=compare_events(path,path.name,edf,160.)
    assert result.status=='mismatch' and result.discrepancies[0]['index']==1


def test_unknown_note_is_preserved_and_missing_dependency_is_not_success(tmp_path,monkeypatch):
    pytest.importorskip('wfdb')
    path=tmp_path/'record.edf.event';event_file(path,first='unknown note')
    result=compare_events(path,path.name,[],160.)
    assert result.status=='not_checked' and result.reason=='unrecognized_annotation_syntax'
    assert result.discrepancies[0]['note']=='unknown note'
    monkeypatch.setattr('app.workflows.wfdb_annotations.importlib.metadata.version',lambda n:'99.0')
    result=compare_events(path,path.name,[],160.)
    assert result.status=='not_checked' and result.reason=='requires_pinned_WFDB_4.3.1_decoder'
