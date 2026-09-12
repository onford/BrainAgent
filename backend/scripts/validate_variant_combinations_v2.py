"""Supplement the immutable profile denominator with input-kind/model combinations."""
from pathlib import Path
import argparse,contextlib,time,traceback
import mne
from scripts.validate_units_v2 import fixture,one
from app.preprocessing.units.operations_v2 import inventory
from app.preprocessing.units import engine_hash,environment
from app.preprocessing.storage import write_json,file_hash


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True);mne.set_log_level('ERROR')
    rows=inventory();base=fixture();cases=[]
    for row in rows:
        if row['op'] in ('ica_apply','mwf_apply','autoreject_apply','reference_apply','prep_reference_finalize'):
            for fit in rows:
                if fit['model_kind']==row['model_kind'] and fit['effect'] in ('model','reference_model'):
                    if row['op']=='reference_apply' and ('propagate' in row['profile'])!=('propagate' in fit['profile']):continue
                    cases.append((row,fit,False))
        if row['input_kind']=='either' or row['op']=='filter' or row['op']=='ecg_assess' and row['profile_parameters'].get('method')=='ctps':
            # EOG is explicitly fitted on Raw, then applied to Epochs in the
            # separate cross-kind graph test; do not refit it on Epochs.
            if row['op']=='eog_apply':continue
            cases.append((row,None,True))
    results=[];stamp=dict(engine_sha256=engine_hash(),environment=environment(),script_sha256=file_hash(Path(__file__)))
    for i,(row,fit,epochs) in enumerate(cases):
        directory=args.output/f'{i:03}-{row["op"]}';directory.mkdir();receipt=dict(**stamp,identity=row['identity'],fit_profile=fit['identity'] if fit else None,input_kind='epochs' if epochs else row['input_kind'],status='failed',started=time.time())
        try:
            with (directory/'runtime.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):receipt.update(one(row,base,directory,fit_override=fit,force_epochs=epochs))
            receipt['status']='passed'
        except Exception as e:
            expected_rejection=epochs and (row['op']=='filter' or row['op']=='ecg_assess' and row['profile_parameters'].get('method')=='ctps')
            if expected_rejection and isinstance(e,ValueError) and ('requires raw' in str(e) or 'CTPS requires Raw' in str(e)):
                receipt.update(status='passed',executed=False,numerical_verified=False,applicability_rejection_verified=True,expected_failure=str(e))
            else:receipt.update(error=str(e),traceback=traceback.format_exc())
        receipt['files']=[dict(path=p.relative_to(args.output).as_posix(),sha256=file_hash(p)) for p in directory.rglob('*') if p.is_file()]
        write_json(directory/'receipt.json',receipt);results.append(receipt);write_json(args.output/'results.json',dict(planned=len(cases),attempted=len(results),passed=sum(r['status']=='passed' for r in results),results=results))
        print(i,row['op'],receipt['input_kind'],receipt['status'],receipt.get('error',''),flush=True)


if __name__=='__main__':main()
