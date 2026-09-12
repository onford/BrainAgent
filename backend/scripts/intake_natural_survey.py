"""Real-model MethodLibrary intake from previously frozen natural survey sources.

An explicitly targeted I01/I04 acceptance, not a fresh I03 workflow. The model
selects documents, then the public method library extracts/reviews every branch.
"""
import argparse
import asyncio
import json
import shutil
from pathlib import Path

import app as app_package
from pydantic import Field
from app.core.config import Settings
from app.main import create_app
from app.preprocessing.schemas import Contract, Evidence, Paper, PreprocessInput, SurveyLiteratureBundle
from app.preprocessing.literature_verification import observed_preparation
from app.preprocessing.storage import digest, file_hash
from app.search.io import read, write


class Selection(Contract):
    source_ids: list[str] = Field(max_length=2)
    reason: str
    unselected_reasons: dict[str, str]


async def main(args):
    output=Path(args.output).resolve()
    if output.exists():
        raise ValueError('Acceptance output must be new')
    output.mkdir(parents=True)
    documents={}; origins={}; entries=[]; source_paths={}
    for run in map(lambda p:Path(p).resolve(),args.run):
        identity=read(run/'active.json')['workflow_id']
        folder=run/'workflows'/identity
        review=read(folder/'survey/literature.json')
        for name in ('survey/sources.json','survey/literature.json','collection/input.json'):
            source_paths[str(folder/name)]=file_hash(folder/name)
        included={e['source_id'] for e in review['entries'] if e['decision']=='included' and e['reading_scope']!='abstract'}
        for doc in read(folder/'survey/sources.json')['documents']:
            if doc['id'] not in included:
                continue
            key='natural-'+digest([doc['url'],doc['sha256']])[:20]
            documents[key]={**doc,'id':key}
            origins.setdefault(key,[]).append({'run':str(run),'workflow_id':identity,'source_id':doc['id']})
            for entry in review['entries']:
                if entry['source_id']==doc['id'] and entry['decision']=='included':
                    entries.append({**entry,'id':key+'-'+entry['id'],'source_id':key})
    first=Path(args.run[0]).resolve()
    workflow_id=read(first/'active.json')['workflow_id']
    folder=first/'workflows'/workflow_id
    data=PreprocessInput.model_validate(read(folder/'collection/input.json'))
    copied=output/'workflows'/workflow_id
    for path in folder.rglob('*.json'):
        relative=path.relative_to(folder)
        if 'bids' not in relative.parts and 'literature-methods' not in relative.parts:
            target=copied/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    # This is a derived source pool with explicit provenance, not a rewritten
    # upstream survey or a claim that its workflow ran again.
    write(copied/'survey/sources.json',{'documents':list(documents.values()),'observations':[],'source_origins':origins})
    write(copied/'survey/literature.json',{'entries':entries,'scope':'frozen natural surveys; targeted method-library acceptance'})
    settings=Settings(_env_file=args.config).model_copy(update={'workflow_root':str(output/'workflows'),
        'preprocessing_root':str(output/'methods'),'preprocessing_input_roots':[data.collection.root],
        'log_dir':output/'logs','db_create_tables':False,'database_url_override':args.database_url})
    app=create_app(settings)
    owner=read(folder/'workflow.json')['owner']
    code=Path(app_package.__file__).resolve().parent
    code_hashes={p.relative_to(code).as_posix():file_hash(p) for p in code.rglob('*') if p.is_file() and p.suffix in {'.py','.json'}}
    write(output/'design.json',{'scope':__doc__,'source_hashes':source_paths,'source_origins':origins,
        'code_hashes':code_hashes,'selection_budget':{'max_calls':3,'max_seconds':300},
        'intake_budget':{'max_recovery_actions':6,'max_seconds':900},'model':settings.llm_model,
        'source_selection':{'mode':'explicit_replay' if args.source_url else 'real_model_selection',
                            'requested_urls':args.source_url or []},
        'driver_sha256':file_hash(Path(__file__)),'injected_method_recipes':[]})
    result={'status':'failed','methods':[]}
    try:
        preparation=observed_preparation(data)
        context={'target':{'dataset_id':data.survey.dataset_id,'task':data.survey.task,
            'observed_preparation':preparation,'output':{'sfreq':160,'tmin':0,'tmax':2}},
            'sources':[{'id':key,'url':d['url'],'text':d['text'][:20000]} for key,d in documents.items()]}
        messages=[{'role':'system','content':'选择最多两个具有明确且可执行预处理方法的不同来源文档，用于真实方法库接入与组合验收。'
            '所有来源均来自既有自然调研；不添加论文，不编造参数，不把下载器当方法。优先考虑资料中的具体信号步骤、参数及依赖是否充分，'
            '不要求复杂清洗胜过简单方法。标准化通道名/模板坐标可以是已核实的输入前提；下游 CSP/分类器不属于预处理缺项。'
            '不能把两个描述同一流水线的 README/代码副本当作独立方法。若没有足够来源，明确保留缺项。JSON Schema:\n'+
            json.dumps(Selection.model_json_schema(),ensure_ascii=False)},
            {'role':'user','content':json.dumps(context,ensure_ascii=False)}]
        selection=None
        if args.source_url:
            by_url={doc['url']:key for key,doc in documents.items()}
            if len(set(args.source_url)) != len(args.source_url) or any(url not in by_url for url in args.source_url):
                raise ValueError('Targeted source replay must use distinct URLs already present in the frozen natural survey')
            selection=Selection(source_ids=[by_url[url] for url in args.source_url],
                reason='Explicit I01 targeted replay of sources from actual natural surveys; this source selection is not a new autonomous model decision.',
                unselected_reasons={})
            write(output/'selection/targeted-replay.json',selection.model_dump(mode='json'))
        async with asyncio.timeout(300):
            for attempt in range(3):
                if selection is not None:
                    break
                write(output/f'selection/{attempt}/request.json',messages)
                try:
                    candidate=await app.state.workflows.llm.structured_output(messages,Selection)
                    write(output/f'selection/{attempt}/response.json',candidate.model_dump(mode='json'))
                    if len(set(candidate.source_ids))!=len(candidate.source_ids) or any(k not in documents for k in candidate.source_ids):
                        raise ValueError('Select distinct IDs from the supplied source pool')
                    selection=candidate;break
                except ValueError as exc:
                    write(output/f'selection/{attempt}/rejection.json',{'error':str(exc),'content':getattr(exc,'content',None)})
                    messages.append({'role':'user','content':'修正选择合同错误：'+str(exc)[:5000]})
        if selection is None or not selection.source_ids:
            raise ValueError('No supported document selection')
        prep=app.state.preprocessing
        inp=prep.register_input(owner,data)
        papers=[]
        for key in selection.source_ids:
            doc=documents[key]
            ref=prep.store.put(owner,'evidence',{**doc,'content':doc['text'],'source_origins':origins[key]})
            evidence=[Evidence(source_url=doc['url'],source_version=doc['sha256'],artifact_ref=ref,
                locator=f'read-text offsets {offset}:{min(offset+1400,len(doc["text"]))}; frozen natural source {key}',
                text=doc['text'][offset:offset+1400]) for offset in range(0,len(doc['text']),1250)]
            papers.append(Paper(paper_id=key,title=doc['title'],survey_bucket='preprocessing_papers',
                relation_to_dataset='Selected from actual included natural-survey documents',inclusion_reason=selection.reason,
                landing_url=doc['url'],fulltext_ref=ref,evidence=evidence,
                retrieval_status='partial' if doc.get('truncated') else 'complete',quality_metadata={'origins':origins[key]}))
        bundle=SurveyLiteratureBundle(survey_run_id='targeted-'+output.name,dataset_id=data.survey.dataset_id,
            dataset_version=data.survey.dataset_version,papers=papers,input_ref=inp)
        write(output/'bundle.json',bundle.model_dump(mode='json'))
        response=await prep.methods.intake(owner,bundle)
        refs=[r.model_dump() for r in response['methods']]
        write(copied/'preprocessing/literature-methods/manifest.json',{'schema_version':'3','methods':refs,
            'sources':[{'source_id':k,'origin':origins[k]} for k in selection.source_ids],
            'shared_output':bundle.shared_output,'absence_reasons':[x['blocking_reason'] for x in response['supplement_requests']],
            'entry':'MethodLibrary.intake; '+('explicit replay of previously natural sources' if args.source_url
                else 'model-selected frozen natural sources')+', not a fresh workflow'})
        write(output/'active.json',{'workflow_id':workflow_id})
        result.update(status='completed',methods=refs,supplement_requests=response['supplement_requests'])
        print('INTAKE',len(refs),'methods',flush=True)
    except Exception as exc:
        result['error']=f'{type(exc).__name__}: {exc}';print(result['error'],flush=True)
    finally:
        result['upstream_metadata_unchanged']=all(file_hash(Path(p))==h for p,h in source_paths.items())
        result['code_unchanged']=code_hashes=={p.relative_to(code).as_posix():file_hash(p) for p in code.rglob('*') if p.is_file() and p.suffix in {'.py','.json'}}
        write(output/'result.json',result)
        await app.state.database.dispose()
    return 0 if result['status']=='completed' and result['upstream_metadata_unchanged'] and result['code_unchanged'] else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',nargs='+',required=True)
    parser.add_argument('--source-url',action='append',help='Replay an explicitly selected URL already in the natural survey, for targeted I01 validation; not autonomous selection')
    for name in ('output','config','database-url'):
        parser.add_argument('--'+name,required=True)
    raise SystemExit(asyncio.run(main(parser.parse_args())))
