"""Hash-bound scientific assets read with a closed set of data readers."""
from pathlib import Path
from typing import Literal
import json
import shutil
import mne
from pydantic import Field
from .schemas import Contract
from .artifact_codec import Codec,fingerprint
from .storage import file_hash,within,write_json


class AssetRegistration(Contract):
    path:str=Field(min_length=1)
    sha256:str=Field(pattern='^[a-f0-9]{64}$')
    kind:Literal['forward','projections','annotations']
    provenance:str=Field(min_length=1)


def register(service,owner,request):
    path=Path(request.path).resolve()
    if not any(path.is_relative_to(root) for root in service.allowed_roots):raise ValueError('asset path is outside configured input roots')
    if file_hash(path)!=request.sha256:raise ValueError('asset file hash differs from registration')
    readers={'forward':mne.read_forward_solution,'projections':mne.read_proj,'annotations':mne.read_annotations}
    value=readers[request.kind](path);content=fingerprint(value)
    directory=service.store.root/'unit-assets'/content;descriptor=directory/'asset.json'
    if not descriptor.exists():write_json(descriptor,Codec(directory).verified_dump(value))
    actual=Codec(directory).load(json.loads(descriptor.read_text(encoding='utf-8')))
    if fingerprint(actual)!=content:raise ValueError('stored asset differs')
    return service.store.put(owner,'unit_asset',{'kind':request.kind,'content_sha256':content,'source_sha256':request.sha256,'provenance':request.provenance,'descriptor':descriptor.relative_to(service.store.root).as_posix(),'files':{p.relative_to(service.store.root).as_posix():file_hash(p) for p in directory.rglob('*') if p.is_file()}})


def load(root,snapshot):
    for relative,expected in snapshot['files'].items():
        if file_hash(within(root,relative))!=expected:raise ValueError('scientific asset changed after planning')
    descriptor=within(root,snapshot['descriptor'])
    value=Codec(descriptor.parent).load(json.loads(descriptor.read_text(encoding='utf-8')))
    if fingerprint(value)!=snapshot['content_sha256']:raise ValueError('asset content hash mismatch')
    return value


def freeze_native(steps):
    files={}
    for step in steps:
        if step.implementation_version=='2' and step.op in ('prep_native','automagic_native'):
            from .units.source.eeg_classic_native import native_roots
            for _,root in native_roots(step.op,step.params):
                candidates=[p for p in root.rglob('*') if p.is_file() and '.git' not in p.parts]
                if len(candidates)>50000:raise ValueError('native dependency root exceeds bounded bundle size')
                files.update({str(p.resolve()):file_hash(p) for p in candidates})
            binary=Path(step.params['matlab_path']).resolve()
            if not binary.is_file():raise ValueError('native MATLAB executable missing')
            files[str(binary)]=file_hash(binary)
            continue
        if step.implementation_version!='2' or step.op not in ('cleanline','zapline_plus','mara_assess','adjust_assess'):continue
        from importlib import import_module
        from .units import specification
        module=import_module('app.preprocessing.units.source.'+specification(step.unit_id).implementation['module'])
        root=Path(step.params['source_root']).resolve()
        pins=getattr(module,'SOURCE_HASHES',getattr(module,'_PINS',{}))
        for relative,expected in pins.items():
            if file_hash(within(root,relative))!=expected:raise ValueError('native source or trained asset differs from pinned author version')
        candidates=[p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in ('.m','.mat')]
        if len(candidates)>5000:raise ValueError('native source root must name a bounded algorithm bundle')
        executable=step.params.get('octave_path',step.params.get('octave','octave'))
        binary=Path(shutil.which(executable) or executable).resolve()
        if not binary.is_file():raise ValueError('native executable missing')
        candidates.append(binary)
        prefix=binary.parent.parent
        for base in (prefix/'share/octave/packages',prefix/'lib/octave/packages'):
            if base.exists():
                for directory in base.iterdir():
                    if directory.name.startswith(('signal-','statistics-','optim-','control-','struct-')):
                        candidates.extend(p for p in directory.rglob('*') if p.is_file())
        files.update({str(p.resolve()):file_hash(p) for p in candidates})
    return files


def verify_native(files):
    for path,sha in files.items():
        if file_hash(Path(path))!=sha:raise ValueError('native dependency changed after planning: '+path)
