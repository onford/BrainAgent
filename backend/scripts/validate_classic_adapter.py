"""Run a complete native graph operation and compare an independent native run."""
import argparse
from pathlib import Path
import time

import numpy as np
from scipy.io import loadmat

from app.preprocessing.assets import freeze_native, verify_native
from app.preprocessing.artifact_codec import fingerprint
from app.preprocessing.graph_runtime import GraphExecutor, Packet
from app.preprocessing.inputs import read_record, validate_record_files
from app.preprocessing.schemas import PreprocessInput, Step
from app.preprocessing.storage import file_hash, write_json
from app.preprocessing.units import engine_hash


def execute(args):
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("validation output must be a new directory")
    source = PreprocessInput.model_validate_json(Path(args.input).read_text(encoding="utf8"))
    record = next(r for r in source.collection.records if r.id == args.record)
    if record.id not in source.collection.selected_record_ids:
        raise ValueError("record not selected in immutable input")
    root = Path(source.collection.root).resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("validation output must be disjoint from source data")
    validate_record_files(root, record)
    raw, events, mapping = read_record(root, record, source.survey.event_id, source.survey.context_event_id)
    params = dict(source_root=args.source_root, eeglab_root=args.eeglab_root,
        matlab_path=args.matlab_path, line_freq=args.line_frequency, seed=args.seed,
        timeout_seconds=args.timeout, adaptation_scope="record_unlabeled")
    if args.pipeline == "automagic":
        params["prep_root"] = args.prep_root
        params['ica_random_policy'] = args.ica_random_policy
    step = Step(id="native", unit_id="EEG-CLASSIC-NATIVE", op=args.pipeline + "_native",
        params=params, implementation_version="2", evidence_indices=[0], adaptation_scope="record_unlabeled",
        profile=('ica_random_policy='+args.ica_random_policy) if args.pipeline=='automagic' else 'source')
    engine = engine_hash()
    native = freeze_native([step])
    output.mkdir(parents=True)
    before = fingerprint(raw)
    write_json(output / "inputs.json", dict(record=record.id, input_sha256=file_hash(Path(args.input)),
        engine_sha256=engine, native_files=native, independent_reference_sha256=file_hash(Path(args.reference)),
        recipe=step.model_dump(mode="json"), original_signal_sha256=before))
    packet = Packet(raw, events, np.arange(len(events)), [m["trial_id"] for m in mapping], record.reference)
    executor = GraphExecutor(record, [step], packet, output / "graph")
    started = time.monotonic()
    actual = executor.execute(step)
    reference = loadmat(args.reference, simplify_cells=True)
    if "signal_V" in reference:
        expected = reference["signal_V"]
    else:
        native_channels = [c['labels'] for c in reference['output']['chanlocs']]
        if len(native_channels) != len(set(native_channels)):
            raise ValueError('independent reference contains duplicate channels')
        expected = np.asarray(reference['output']['data'], float)[[native_channels.index(c) for c in raw.ch_names]] * 1e-6
    array = actual.data.get_data()
    if array.shape != expected.shape:
        raise ValueError("independent native output shape mismatch")
    difference = float(np.max(np.abs(array - expected)))
    verify_native(native)
    validate_record_files(root, record)
    if engine_hash() != engine or fingerprint(raw) != before:
        raise ValueError("engine or immutable input changed during validation")
    receipt = dict(status="passed" if difference <= args.atol_V else "failed", pipeline=args.pipeline,
        max_abs_difference_V=difference, atol_V=args.atol_V, exact=np.array_equal(array, expected),
        shape=list(array.shape), physical_unit=actual.unit, channel_order=actual.data.ch_names,
        native_channels=np.atleast_1d(executor.nodes[step.id]["artifacts"]["native_channels"]).tolist(),
        event_identity_preserved=np.array_equal(events, actual.events), original_unchanged=True,
        engine_sha256=engine, wall_seconds=time.monotonic()-started,
        scope="One real record, full author entrypoint and graph/codec equivalence. Not independent algorithm validity or final-agent acceptance.")
    write_json(output / "verification.json", receipt)
    if receipt["status"] != "passed":
        raise ValueError("native graph output differs from independent native reference")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("input", "record", "source-root", "eeglab-root", "matlab-path", "reference", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--pipeline", choices=("prep", "automagic"), required=True)
    parser.add_argument("--prep-root")
    parser.add_argument('--ica-random-policy', choices=('author_clock','fixed_loop_seed_zero'), default='author_clock')
    parser.add_argument("--line-frequency", type=float, required=True)
    parser.add_argument("--seed", type=int, default=321)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--atol-V", dest="atol_V", type=float, default=1e-12)
    execute(parser.parse_args())
