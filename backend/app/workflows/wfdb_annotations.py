"""Read EEGMMIDB WFDB notes without discarding a real sample-zero event."""
import hashlib
import importlib.metadata
import math
import re
from typing import Literal

from app.preprocessing.schemas import Contract
from app.preprocessing.storage import file_hash
from pydantic import Field


class WFDBEvent(Contract):
    sample: int = Field(ge=0)
    label: str
    duration_s: float = Field(ge=0)
    original_note: str


class WFDBComparison(Contract):
    status: Literal['not_found','not_checked','read_error','mismatch','matched']
    reason: str | None = None
    file: str
    sha256: str | None = None
    bytes: int = 0
    reader_version: str | None = None
    decoder_source_sha256: str | None = None
    declared_sfreq: float | None = None
    edf_count: int
    wfdb_count: int = 0
    annotations: list[WFDBEvent] = Field(default_factory=list)
    discrepancies: list[dict] = Field(default_factory=list)
    maximum_onset_difference_samples: float | None = None
    maximum_duration_difference_samples: float | None = None
    tolerance_samples: float = .5
    interpretation: str = 'EEGMMIDB note syntax and decoded time/label comparison only; no task class reinterpretation'


def compare_events(path, relative, edf_events, sfreq):
    result=WFDBComparison(status='not_found',reason='no_matching_edf_event_sidecar',file=relative,edf_count=len(edf_events))
    if not path.exists():return result
    if path.stat().st_size > 2*1024**2:
        return result.model_copy(update={'status':'not_checked','reason':'annotation_file_exceeds_2MiB_limit'})
    payload=path.read_bytes()
    result.sha256=hashlib.sha256(payload).hexdigest();result.bytes=len(payload)
    try:
        import numpy as np
        import wfdb.io.annotation as annotation
        from pathlib import Path
        version=importlib.metadata.version('wfdb')
        result.reader_version=version
        if version!='4.3.1':
            result.status='not_checked';result.reason='requires_pinned_WFDB_4.3.1_decoder';return result
        result.decoder_source_sha256=file_hash(Path(annotation.__file__))
        if len(payload)%2 or not payload:
            raise ValueError('WFDB byte pairs are empty or incomplete')
        # rdann removes all sample=0 NOTE annotations as possible definitions.
        # Use the pinned author's byte decoder, then classify exact note syntax;
        # never replace a missing event from the EDF comparison input.
        samples,kinds,subtypes,channels,numbers,notes=annotation.proc_ann_bytes(
            np.frombuffer(payload,dtype=np.uint8).reshape(-1,2),None)
        resolutions=[];unknown=[];events=[]
        for index,(sample,kind,note) in enumerate(zip(samples,kinds,notes,strict=True)):
            text=str(note)
            if int(kind)==0 and not text:
                continue
            resolution=re.fullmatch(r'## time resolution: ([0-9]+(?:\.[0-9]+)?)',text)
            if int(kind)==22 and int(sample)==0 and resolution:
                resolutions.append(float(resolution[1]));continue
            match=re.fullmatch(r'(T[012]) duration: ([0-9]+(?:\.[0-9]+)?)',text)
            if int(kind)!=22 or not match:
                unknown.append(dict(index=index,sample=int(sample),kind=int(kind),note=text));continue
            events.append(WFDBEvent(sample=int(sample),label=match[1],duration_s=float(match[2]),original_note=text))
        result.annotations=events;result.wfdb_count=len(events)
        if unknown:
            result.status='not_checked';result.reason='unrecognized_annotation_syntax';result.discrepancies=unknown;return result
        if len(resolutions)!=1 or not math.isfinite(resolutions[0]) or resolutions[0]<=0:
            result.status='not_checked';result.reason='unique_positive_declared_time_resolution_required';return result
        result.declared_sfreq=resolutions[0]
        if resolutions[0]!=sfreq:
            result.status='mismatch';result.reason='declared_time_resolution_differs_from_EDF';return result
        if any(a.sample>b.sample for a,b in zip(events,events[1:])):
            result.status='mismatch';result.reason='annotation_samples_not_ordered';return result
        if len(events)!=len(edf_events):
            result.status='mismatch';result.reason='annotation_counts_differ';return result
        onset_errors=[];duration_errors=[]
        for index,(a,b) in enumerate(zip(events,edf_events,strict=True)):
            onset=abs(a.sample-b['onset_s']*sfreq)
            duration=abs(a.duration_s-b['duration_s'])*sfreq
            onset_errors.append(onset);duration_errors.append(duration)
            if a.label!=b['label'] or onset>.5 or duration>.5:
                result.discrepancies.append(dict(index=index,wfdb=a.model_dump(),edf=b,
                    onset_difference_samples=onset,duration_difference_samples=duration))
        result.maximum_onset_difference_samples=max(onset_errors,default=0.)
        result.maximum_duration_difference_samples=max(duration_errors,default=0.)
        result.status='mismatch' if result.discrepancies else 'matched'
        result.reason='decoded_annotations_differ' if result.discrepancies else None
    except ImportError:
        result.status='not_checked';result.reason='optional_WFDB_dependency_unavailable'
    except (OSError,ValueError,IndexError,TypeError) as exc:
        result.status='read_error';result.reason=type(exc).__name__+': '+str(exc)
    finally:
        if file_hash(path)!=result.sha256:
            raise ValueError('WFDB source sidecar changed during observation')
    return result
