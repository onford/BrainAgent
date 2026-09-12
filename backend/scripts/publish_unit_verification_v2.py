"""Publish only current, hash-verified evidence; preserve every initial identity."""
from pathlib import Path
import argparse,json,collections
from app.preprocessing.units import engine_hash,ROOT
from app.preprocessing.units.operations_v2 import inventory
from app.preprocessing.units.contracts_v2 import parameter_schema
from app.preprocessing.storage import file_hash,write_json
from app.preprocessing.runner import verify_result


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def href(path,label):return '['+label+']('+path.resolve().as_posix()+')'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--synthetic',type=Path,required=True);parser.add_argument('--real',type=Path,required=True);parser.add_argument('--variants',type=Path,required=True);parser.add_argument('--compositions',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    for name in ('synthetic','real','variants','compositions','output'):setattr(args,name,getattr(args,name).resolve())
    args.output.mkdir(parents=True,exist_ok=True);rows=inventory();current=engine_hash();initial=read(args.output/'initial-inventory.json')
    assert {r['identity'] for r in initial['rows']}<={r['identity'] for r in rows},'initial denominator was reduced'
    evidence={};all_receipts=[]
    for receipt_path in sorted(args.synthetic.glob('*/receipt.json')):
        receipt=read(receipt_path);all_receipts.append({'path':str(receipt_path.resolve()),'sha256':file_hash(receipt_path),'status':receipt['status']})
        assert receipt['engine_sha256']==current,'stale implementation: '+str(receipt_path)
        for asset in receipt['files']:
            assert file_hash(args.synthetic/asset['path'])==asset['sha256'],'receipt artifact changed: '+asset['path']
        identity=receipt['identity'];row=next(r for r in rows if r['identity']==identity)
        assert receipt['source_sha256']==row['source']['source']['code_sha256']
        evidence[identity]=dict(source_sha256=receipt['source_sha256'],engine_sha256=current,compiled_passed=receipt.get('compiled_graph',False),execution_passed=receipt.get('executed',False),numerical_passed=receipt.get('numerical_verified',False),real_data_passed=False,boundary_passed=receipt.get('boundary_passed',False),receipt=str(receipt_path.resolve()),receipt_sha256=file_hash(receipt_path),numerical_basis=receipt.get('numerical_basis'),max_abs_error=receipt.get('max_abs_error'),failure=receipt.get('error'),real_receipts=[])
    assert set(evidence)=={r['identity'] for r in rows},'missing profile receipt'
    real=read(args.real/'real-data-receipt.json');plan=read(args.real/'plan.json');assert plan['engine_sha256']==current
    from app.preprocessing.storage import Storage
    from app.preprocessing.schemas import Ref
    store=Storage(args.real)
    write_json(args.output/'representative-execution-plan.json',plan)
    examples={r['method_ref']['id']:store.get('unit-integration-audit',Ref(**r['method_ref']),'method') for r in plan['records']}
    write_json(args.output/'representative-methods.json',list(examples.values()))
    for record in real['records']:
        assert record['verified'] and verify_result(args.real,record['result'])
        artifact=next(a for a in record['result']['artifacts'] if a['name']=='provenance.json');provenance=read(args.real/artifact['path'])
        config=next(r for r in plan['records'] if r['record_id']==record['record_id'] and r['method_ref']==provenance['method_ref'])
        for s in config['steps']:
            matched=[r for r in rows if r['unit_id']==s['unit_id'] and r['op']==s['op'] and all(s['params'].get(k,r['defaults'].get(k))==v for k,v in r['profile_parameters'].items())]
            for row in matched:
                if s['profile']!='source' and row['profile']!=s['profile']:continue
                item=evidence[row['identity']];item['real_data_passed']=True
                item['real_receipts'].append(dict(job_id=real['job_id'],record_id=record['record_id'],provenance=str((args.real/artifact['path']).resolve()),sha256=artifact['sha256'],step_id=s['id'],parameters=s['params']))
    supplements=[]
    for directory in (args.variants,args.compositions):
        for path in sorted(directory.glob('*/receipt.json')):
            receipt=read(path);assert receipt['engine_sha256']==current,'stale supplemental evidence'
            for asset in receipt['files']:assert file_hash(directory/asset['path'])==asset['sha256'],'supplemental artifact changed'
            supplements.append({k:v for k,v in receipt.items() if k not in ('files','environment','traceback')}|{'receipt':str(path.resolve()),'receipt_sha256':file_hash(path)})
    write_json(ROOT/'verification_v2.json',evidence)
    count={'units':len({r['unit_id'] for r in rows}),'operations':len({(r['unit_id'],r['op']) for r in rows}),'profiles':len(rows)}
    counts={**count,**{key:sum(bool(v.get(key)) for v in evidence.values()) for key in ('compiled_passed','execution_passed','numerical_passed','boundary_passed','real_data_passed')}}
    matrix=[{**row,'parameter_contract':parameter_schema(row),'initial_identity':row['identity'] in {r['identity'] for r in initial['rows']},'integration':evidence[row['identity']]} for row in rows]
    write_json(args.output/'matrix.json',dict(schema_version='2',initial_inventory_sha256=file_hash(args.output/'initial-inventory.json'),engine_sha256=current,counts=counts,rows=matrix,supplemental_cases=supplements))
    write_json(args.output/'current-inventory.json',dict(schema_version='2',counts=count,rows=rows))
    write_json(args.output/'final-receipt-index.json',dict(engine_sha256=current,counts=counts,synthetic=all_receipts,real_receipt={'path':str((args.real/'real-data-receipt.json').resolve()),'sha256':file_hash(args.real/'real-data-receipt.json')},supplemental=supplements))
    write_json(args.output/'inventory-amendment-final.json',dict(initial_profiles=initial['profiles'],current_profiles=len(rows),removed_identities=[],added_identities=[r['identity'] for r in rows if r['identity'] not in {x['identity'] for x in initial['rows']}],contract_corrections=['filter accepts Raw only in current source','CTPS accepts Raw only; correlation accepts Raw/Epochs','prep_reference_fit declares explicit fit scope','legacy PyPREP diagnostics preserve NaN for subsequent bound repair; infinite output rejected'],reason='Source branch audit and executed input-kind checks. No source identity removed or substituted.'))
    lines=['# BrainAgent 全量单元接入与验证矩阵','',f"当前源码：{count['units']} 单元 / {count['operations']} op / {count['profiles']} profile；原始 {initial['profiles']} 个身份全部保留。",'',f"编译 {counts['compiled_passed']}，运行 {counts['execution_passed']}，来源数值一致性 {counts['numerical_passed']}，边界行为 {counts['boundary_passed']}，真实数据覆盖 {counts['real_data_passed']}。",'', '数值证据指独立调用冻结来源函数与图适配器结果的逐元素/模型/诊断比较及无损回读，不代表对作者算法的独立科学验证。真实数据列仅对应收据中的具体参数及记录。','',href(args.output/'matrix.json','完整机器可读合同、输入输出、来源、依赖和验证收据'),'', '| 单元 | op | profile（完整身份） | 编译 | 运行 | 数值 | 边界 | 真实 EEG | 收据 |','|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        e=evidence[r['identity']];mark=lambda k:'通过' if e.get(k) else '未通过/未执行'
        lines.append('| '+' | '.join([r['unit_id'],r['op'],r['profile'].replace('|','\\|'),*[mark(k) for k in ('compiled_passed','execution_passed','numerical_passed','boundary_passed','real_data_passed')],href(Path(e['receipt']),'运行收据')])+' |')
    lines+=['','## 按单元汇总（全量 52 个）','','| 单元 | op 数 | profile 数 | 数值通过 | 真实 EEG 覆盖 |','|---|---|---|---|---|']
    for unit in dict.fromkeys(r['unit_id'] for r in rows):
        members=[r for r in rows if r['unit_id']==unit]
        lines.append('| '+unit+' | '+str(len({r['op'] for r in members}))+' | '+str(len(members))+' | '+str(sum(evidence[r['identity']]['numerical_passed'] for r in members))+' | '+str(sum(evidence[r['identity']]['real_data_passed'] for r in members))+' |')
    lines+=['','## 每个操作的输入、输出与依赖','']
    grouped=collections.defaultdict(list)
    for r in rows:grouped[(r['unit_id'],r['op'])].append(r)
    for (unit,op),variants in grouped.items():
        r=variants[0];lines.extend([f'### {unit} / {op}','',f"输入 `{r['input_kind']}`；状态效应 `{r['effect']}`；模型 `{r['model_kind']}`；拟合 `{r['fit']}`；显式决定 `{r['decision']}`。",'',f"依赖：`{json.dumps(r['dependencies'],ensure_ascii=False)}`；资产：`{r['assets']}`。",'', '```json',json.dumps(parameter_schema(r),ensure_ascii=False,indent=2),'```',''])
        for key in ('输入合同','输出合同','参数合同','前置条件','模型合同','状态合同'):
            if key in r['source']['source']['fields']:lines.extend([key+'：'+str(r['source']['source']['fields'][key]),''])
    (args.output/'matrix.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(counts),flush=True)


if __name__=='__main__':main()
