"""Cross-check registered operations against source dispatch, without executing code."""
import ast
from pathlib import Path
from collections import defaultdict
from app.preprocessing.units.operations_v2 import inventory,ROOT
from app.preprocessing.storage import write_json,file_hash


def main():
    rows=inventory();modules=defaultdict(list)
    for row in rows:
        module=row['source']['implementation']['module']
        if (row['unit_id'],row['op']) not in modules[module]:modules[module].append((row['unit_id'],row['op']))
    report=[]
    for module,assignments in modules.items():
        path=ROOT/'source'/f'{module}.py';tree=ast.parse(path.read_text(encoding='utf-8'));found=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Compare) and isinstance(node.left,ast.Name) and node.left.id=='op':
                for value in node.comparators:
                    if isinstance(value,ast.Constant) and isinstance(value.value,str):found.add(value.value)
                    elif isinstance(value,(ast.List,ast.Tuple,ast.Set)):found.update(v.value for v in value.elts if isinstance(v,ast.Constant) and isinstance(v.value,str))
            if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Dict) and isinstance(node.slice,ast.Name) and node.slice.id=='op':found.update(k.value for k in node.value.keys if isinstance(k,ast.Constant) and isinstance(k.value,str))
        missing=found-{op for _,op in assignments}
        report.append(dict(module=module,source_sha256=file_hash(path),registered=assignments,source_dispatch_labels=sorted(found),unregistered_labels=sorted(missing)))
        if missing:raise ValueError('source dispatch labels absent from registry: '+str(missing))
    out=Path(__file__).resolve().parents[2]/'docs/sources/full-unit-integration-20260912/source-dispatch-audit.json'
    write_json(out,dict(units=len({r['unit_id'] for r in rows}),operations=len({(r['unit_id'],r['op']) for r in rows}),profiles=len(rows),modules=report,note='automatic_cleaning.py is shared: its explicit unit selection assigns asr_clean to EEG-ASR-AUTO and the other two operations to EEG-AUTO-BAD-CHANNEL. AST dispatch comparison supplements, rather than replaces, per-source contract and numerical verification.'))
    print('source dispatch coverage verified:',len(report),'modules')


if __name__=='__main__':main()
