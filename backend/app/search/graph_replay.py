"""Fresh graph execution for independent numerical probes, without cached fits."""
from pathlib import Path
from tempfile import TemporaryDirectory
import numpy as np

from app.preprocessing.schemas import RecordSpec, Step
from app.preprocessing.graph_runtime import Packet, GraphExecutor
from app.preprocessing.artifact_codec import fingerprint


def replay(raw, events, config):
    steps=[Step.model_validate(s) for s in config['steps']]
    record=RecordSpec.model_validate(config['_record'])
    from app.preprocessing.assets import load
    assets={key:load(Path(config['_storage_root']), snapshot) for key,snapshot in config.get('asset_snapshots',{}).items()}
    with TemporaryDirectory(prefix='brainagent-graph-probe-') as folder:
        packet=Packet(raw.copy(),events.copy(),np.arange(len(events)),[str(i) for i in range(len(events))],record.reference)
        executor=GraphExecutor(record,steps,packet,Path(folder),assets=assets)
        for step in steps: executor.execute(step)
        final=executor.nodes[config['output']]['packet']
        chain=[];cursor=config['output']
        while cursor!='raw':chain.append(executor.steps[cursor]);cursor=executor.steps[cursor].input
        epoch=next(s for s in chain if s.op in ('epoch','epoch_with_nonfinite'))
        continuous=executor.nodes[epoch.input]['packet']
        output=final.data.copy()
        if config.get('evaluation_window'):
            output.crop(**config['evaluation_window'])
        trace=[dict(step_id=s.id,unit_id=s.unit_id,op=s.op,parameters=s.params,implementation_version='2',
                    fit_artifact_hashes={'model':fingerprint(executor.nodes[s.id]['model'])} if executor.nodes[s.id]['model'] is not None else {},
                    decision_binding=None) for s in steps]
        return output,output.copy(),continuous.events.copy(),trace
