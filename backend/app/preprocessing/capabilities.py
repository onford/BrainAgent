"""Source inventory, availability and evidence levels are separate facts."""
from pathlib import Path
import json

from .units.operations_v2 import inventory
from .units.contracts_v2 import parameter_schema, dependency_status
from .storage import file_hash

RECEIPTS=Path(__file__).parent/'units'/'verification_v2.json'


def capabilities(data=None):
    from .units import engine_hash
    implementation=engine_hash()
    evidence=json.loads(RECEIPTS.read_text(encoding='utf-8')) if RECEIPTS.exists() else {}
    records=[] if data is None else [r for r in data.collection.records if r.id in data.collection.selected_record_ids]
    rows=[]
    for item in inventory():
        receipt=evidence.get(item['identity'],{})
        source_file=Path(__file__).parent/'units/source'/f'{item["source"]["implementation"]["module"]}.py'
        current=file_hash(source_file)
        valid=receipt.get('source_sha256')==current and receipt.get('engine_sha256')==implementation
        verified=valid and receipt.get('numerical_passed') is True
        unavailable=[]
        for record in records:
            types=set(record.channels.values())
            if item['op'] in ('eog_fit','eog_step') and 'eog' not in types:unavailable.append(record.id+': real EOG channel missing')
            if item['op'] in ('interpolate','spherical','interpolate_native','trial_interpolate','csd','bridge_repair') and not any(p.endswith('electrodes.tsv') for p in record.files):unavailable.append(record.id+': electrode geometry missing')
        missing=dependency_status(item,item['profile_parameters'])
        rows.append({k:item[k] for k in ('identity','unit_id','op','profile','implementation_version','input_kind','effect','model_kind','fit','decision','dependencies','assets','profile_parameters')} | {
            'parameters':parameter_schema(item),'status':{'collected':True,'adapter_implemented':True,'adapted':bool(valid and receipt.get('execution_passed')),
                'compiled':bool(valid and receipt.get('compiled_passed')),
                'executed':bool(valid and receipt.get('execution_passed')),
                'numerically_verified':verified,'real_data_verified':bool(valid and receipt.get('real_data_passed')),
                'current_input_applicable':False if unavailable else None,
                'dependency_missing':missing,'requires_decision':item['decision']},
            'unavailable_reasons':unavailable,'verification':receipt if valid else {'historical':receipt,'stale_implementation':True} if receipt else {},
            'availability_note':'Metadata can rule out some inputs; Planner and runtime validate the selected recipe, data, artifacts and dependencies.',
            'source_sha256':current,'source_fields':item['source']['source']['fields']})
    return {'schema_version':'2','counts':{'units':len({r['unit_id'] for r in rows}),'operations':len({(r['unit_id'],r['op']) for r in rows}),'profiles':len(rows)},'rows':rows}
