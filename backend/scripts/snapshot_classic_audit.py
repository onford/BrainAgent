"""Bind complete native pipeline evidence to immutable sources and actual inputs."""
import argparse
import json
from pathlib import Path

from app.preprocessing.classic_pipelines import catalog
from app.preprocessing.storage import digest, file_hash, write_json


def snapshot(sources, runs, input_directory, runtime_path, output):
    if output.exists():
        raise ValueError('Native audit snapshots are immutable; select a new output')
    runtime=json.loads(runtime_path.read_text(encoding='utf-8'))
    products={p['Name'] for p in runtime['products']}
    target=json.loads((input_directory/'input.json').read_text(encoding='utf-8'))
    sfreq=target['record']['sfreq']
    rows=[]
    for contract in catalog()['pipelines']:
        root=sources/contract['id']; entry=root/contract['entrypoint']
        if file_hash(entry)!=contract['sha256']:
            raise ValueError('Source entrypoint differs from the pinned contract: '+contract['id'])
        files={p.relative_to(root).as_posix():file_hash(p) for p in sorted(root.rglob('*')) if p.is_file()}
        row={'source_contract':contract,'source_tree_sha256':digest(files),'source_files':files,
             'missing_toolboxes':sorted(set(contract['required_toolboxes'])-products),
             'complete_native_execution':False,'production_graph_integration':False,
             'native_adapter_equivalence':False,'blockers':[]}
        run_name={'prep':'prep-4','automagic':'am-3'}.get(contract['id'])
        receipt_path=runs/run_name/'native-receipt.json' if run_name else None
        if receipt_path and receipt_path.exists():
            receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
            row.update(native_receipt={'path':str(receipt_path.resolve()),'sha256':file_hash(receipt_path)},
                       native_status=receipt['status'], complete_native_execution=receipt['status']=='executed')
            row['run_files']={p.relative_to(receipt_path.parent).as_posix():file_hash(p)
                              for p in sorted(receipt_path.parent.rglob('*')) if p.is_file()}
            if contract['id']=='prep':
                row['repeat_max_abs_difference_V']=receipt.get('max_abs_repeat_difference_V')
                row['mandatory_stages']=receipt.get('first_status')
                row['full_robust_reference']=receipt.get('full_reference_info',False)
            else:
                row['output_shape']=receipt.get('output_shape')
                row['output_channels']=receipt.get('output_channels')
                row['stage_statuses']={k:v['performed'] for k,v in receipt.get('native_qc',{}).items()
                                       if isinstance(v,dict) and 'performed' in v}
                row['shared_panel_blocker']='Native output channel grid requires a declared source-specific adapter before shared EEGNet comparison'
        if row['missing_toolboxes']:
            row['blockers'].append('missing_native_toolboxes')
        if contract['id']=='relax':
            row['source_default_lowpass_Hz']=80
            if 80>=sfreq/2:
                row['blockers'].append('author_default_lowpass_at_or_above_target_Nyquist')
            row['blockers'].append('complete_native_dependency_bundle_and_configuration_not_validated')
        if contract['id']=='happe':
            row['blockers'].append('headless_author_configuration_and_complete_native_run_not_validated')
        row['blockers'].extend(['production_graph_adapter_not_implemented','native_vs_adapter_comparison_not_completed'])
        rows.append(row)
    write_json(output, {'schema_version':'1','runtime':runtime,'input':target,
        'pipelines':rows,'scope':'Complete native entrypoints are a separate evidence level from primitive operation coverage. '
        'Executed native pipelines do not establish production graph integration or final-agent acceptance.'})


def publish(audit_path, destination):
    """Publish portable configuration/readiness evidence, retaining raw-file refs."""
    if destination.exists():
        raise ValueError('Published evidence directory must be new')
    audit=json.loads(audit_path.read_text(encoding='utf-8'))
    destination.mkdir(parents=True)
    def compact(value):
        if isinstance(value,dict):
            return {k:compact(v) for k,v in value.items()}
        if isinstance(value,list):
            if len(json.dumps(value,ensure_ascii=False))>16000:
                return {'omitted_array_length':len(value),'canonical_sha256':digest(value),
                        'location':'Full value is retained in the hash-bound native receipt.'}
            return [compact(v) for v in value]
        return value
    rows=[]
    for row in audit['pipelines']:
        value={k:v for k,v in row.items() if k not in ('source_files','run_files')}
        value['source_file_count']=len(row['source_files'])
        value['run_file_count']=len(row.get('run_files',{}))
        if row.get('native_receipt'):
            path=Path(row['native_receipt']['path'])
            if file_hash(path)!=row['native_receipt']['sha256']:
                raise ValueError('Native receipt changed after audit')
            receipt=json.loads(path.read_text(encoding='utf-8'))
            name=row['source_contract']['id']+'-configuration-and-qc.json'
            write_json(destination/name,{'native_receipt':row['native_receipt'],
                'evidence_level':'Native entrypoint execution; no production adapter equivalence claim',
                'receipt':compact(receipt)})
            value['configuration_and_qc']={'path':name,'sha256':file_hash(destination/name)}
        rows.append(value)
    write_json(destination/'manifest.json',{'schema_version':'1','audit_sha256':file_hash(audit_path),
        'audit_path':str(audit_path.resolve()),'input':audit['input'],'runtime':audit['runtime'],
        'pipelines':rows,'scope':audit['scope']})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('sources','runs','input','runtime','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--publish',type=Path)
    args=parser.parse_args()
    snapshot(args.sources,args.runs,args.input,args.runtime,args.output)
    if args.publish:
        publish(args.output,args.publish)
