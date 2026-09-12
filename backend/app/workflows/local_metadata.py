"""Bounded structured metadata discovery, with exact file/field provenance."""
import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Literal

from pydantic import Field
from app.preprocessing.schemas import Contract
from app.preprocessing.storage import within,file_hash
from .wfdb_annotations import WFDBComparison


class MetadataFile(Contract):
    path: str
    kind: Literal['dataset','participants','electrodes','coordinates','acquisition','behavior','stimulus']
    status: Literal['not_checked','observed','partial','read_error']
    sha256: str | None = None
    bytes: int
    values: dict = Field(default_factory=dict)
    columns: list[str] = Field(default_factory=list)
    rows: list[dict] = Field(default_factory=list)
    reason: str | None = None
    coordinate_provenance: str | None = None
    unavailable_fields: list[str] = Field(default_factory=list)


class MetadataInspection(Contract):
    schema_version: Literal['local-metadata-1'] = 'local-metadata-1'
    discovered_bids_roots: list[str] = Field(default_factory=list)
    structured_files: list[MetadataFile] = Field(default_factory=list)
    wfdb_comparisons: dict[str,WFDBComparison] = Field(default_factory=dict)
    input_bytes: int = 0
    max_input_bytes: int = 64*1024**2
    max_file_bytes: int = 4*1024**2
    max_table_rows: int = 10000
    limitations: list[str] = Field(default_factory=lambda:[
        'Structured values are explicit file declarations, not independently measured facts or full BIDS validation.',
        'Metadata inheritance and record applicability are not inferred; retain source paths and original field names.',
        'Coordinates without explicit provenance are unverified; standard/template descriptions never become individual measurements.',
        'Free-text documents/images/PDFs and unspecified demographic/behavioral fields remain unparsed, not absent.',
        'No demographic fact is inferred from EDF patient free text or a filename.'])


JSON_KEYS={'Name','BIDSVersion','DatasetType','License','DatasetDOI','Authors','GeneratedBy',
    'Manufacturer','ManufacturersModelName','SoftwareVersions','EEGReference','EEGGround','EEGPlacementScheme',
    'EEGCoordinateSystem','EEGCoordinateUnits','EEGCoordinateSystemDescription','EEGChannelCount','EOGChannelCount',
    'ECGChannelCount','EMGChannelCount','PowerLineFrequency','HardwareFilters','SoftwareFilters','SamplingFrequency',
    'TaskName','TaskDescription','Instructions','CogAtlasID','RecordingType','RecordingDuration',
    'CapManufacturer','CapManufacturersModelName','EEGPositionDescription','InstitutionName'}


def inspect_metadata(root, inventory):
    root=Path(root).resolve();result=MetadataInspection()
    for entry in inventory:
        relative=entry['path'];name=Path(relative).name
        if name=='dataset_description.json':
            result.discovered_bids_roots.append(Path(relative).parent.as_posix())
        kind=('dataset' if name=='dataset_description.json' else 'participants' if name=='participants.tsv' else
              'electrodes' if name.endswith('_electrodes.tsv') else 'coordinates' if name.endswith('_coordsystem.json') else
              'acquisition' if name.endswith('_eeg.json') else 'behavior' if name.endswith('_beh.tsv') else
              'stimulus' if name.endswith('_stim.tsv') else None)
        if kind is None:continue
        original=root/relative
        path=within(root,relative);size=path.stat().st_size
        row=MetadataFile(path=relative,kind=kind,status='not_checked',bytes=size)
        result.structured_files.append(row)
        if original.is_symlink() or any(p.is_symlink() for p in original.parents if p!=root and p.is_relative_to(root)):
            row.reason='symbolic_metadata_path_not_supported';continue
        if size>result.max_file_bytes or size>result.max_input_bytes-result.input_bytes:
            row.reason='metadata_read_budget_exhausted';continue
        with path.open('rb') as stream:payload=stream.read(size+1)
        result.input_bytes+=len(payload);row.sha256=hashlib.sha256(payload).hexdigest()
        if len(payload)!=size:raise ValueError('metadata size changed while reading')
        try:
            text=payload.decode('utf-8-sig')
            if name.endswith('.json'):
                def unique(pairs):
                    result={}
                    for key,value in pairs:
                        if key in result:raise ValueError('duplicate metadata JSON field: '+key)
                        result[key]=value
                    return result
                def invalid_constant(value):raise ValueError('nonfinite JSON constant: '+value)
                data=json.loads(text,object_pairs_hook=unique,parse_constant=invalid_constant)
                if not isinstance(data,dict):raise ValueError('metadata JSON object required')
                row.values={k:v for k,v in data.items() if k in JSON_KEYS}
                expected={'dataset':{'Name','BIDSVersion','License'},
                    'acquisition':{'Manufacturer','ManufacturersModelName','EEGReference','EEGGround','PowerLineFrequency'},
                    'coordinates':{'EEGCoordinateSystem','EEGCoordinateUnits','EEGCoordinateSystemDescription'}}.get(kind,set())
                row.unavailable_fields=sorted(k for k in expected if k not in data or data[k] is None
                    or isinstance(data[k],str) and data[k].strip().lower() in {'','n/a','unknown'})
                if kind=='coordinates':
                    description=str(data.get('EEGCoordinateSystemDescription','')).lower()
                    row.coordinate_provenance='declared_template' if 'template' in description else 'unverified'
            else:
                table=csv.DictReader(io.StringIO(text),delimiter='\t')
                row.columns=list(table.fieldnames or [])
                if not row.columns or len(set(row.columns))!=len(row.columns):raise ValueError('unique TSV header required')
                for index,record in enumerate(table):
                    if index>=result.max_table_rows:
                        row.status='partial';row.reason='table_row_budget_exhausted';break
                    if None in record or any(v is None for v in record.values()):raise ValueError('TSV row width differs from header')
                    row.rows.append(record)
                if kind=='electrodes':row.coordinate_provenance='unverified'
            if row.status!='partial':row.status='observed'
        except (ValueError,UnicodeError,csv.Error) as exc:
            row.status='read_error';row.reason=str(exc);row.values={};row.rows=[]
        if file_hash(path)!=row.sha256:raise ValueError('structured metadata changed during observation')
    result.discovered_bids_roots=sorted(set(result.discovered_bids_roots))
    return result
