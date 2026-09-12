"""Download pinned author files into an isolated directory; enforce source hashes."""
from pathlib import Path
from urllib.request import urlopen, Request
import argparse
import hashlib
import json
import time
import zipfile
from app.preprocessing.units.source import eeg_mara, eeg_adjust, eeg_sine_regression, eeg_zapline


def download(url,path,expected=None):
    if path.exists() and (expected is None or hashlib.sha256(path.read_bytes()).hexdigest()==expected):return
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.download')
    digest=hashlib.sha256()
    with urlopen(Request(url,headers={'User-Agent':'BrainAgent-reproducible-assets/2'}),timeout=90) as response,temporary.open('wb') as out:
        while chunk:=response.read(1024*1024):out.write(chunk);digest.update(chunk)
    if expected and digest.hexdigest()!=expected:raise ValueError('upstream content differs from source pin: '+url)
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--octave',action='store_true');args=parser.parse_args()
    args.root.mkdir(parents=True,exist_ok=True);receipts=[]
    jobs=[]
    for name,module,repo in [('cleanline',eeg_sine_regression,'sccn/cleanline'),('zapline',eeg_zapline,'MariusKlug/zapline-plus')]:
        for path,sha in module.SOURCE_HASHES.items():jobs.append((args.root/name/path,sha,[f'https://raw.githubusercontent.com/{repo}/{module.SOURCE_COMMIT}/{path}']))
    pins={**eeg_mara._PINS,**eeg_adjust._PINS}
    for path,sha in pins.items():
        group,relative=path.split('/',1)
        if group=='MARA':urls=[f'https://raw.githubusercontent.com/irenne/MARA/24e36719362bf24c7bb09f063bbca7523fb5f404/{relative}']
        elif group=='SASICA':urls=[f'https://raw.githubusercontent.com/dnacombo/SASICA/9ab76d7552e28b3ee6537256d1b66fa8ed4744e1/{relative}']
        else:urls=[f'https://raw.githubusercontent.com/sccn/eeglab/{tag}/{relative}' for tag in ['2025.1.0','2025.0.0','2024.2.1','develop']]
        jobs.append((args.root/'classification'/path,sha,urls))
    # EEG_CHECKSET invokes these author helpers transitively. The original
    # four-file manifest omitted them; pin the containing EEGLAB Git commit.
    for relative in ['functions/adminfunc/eeg_options.m','functions/adminfunc/eeg_optionsbackup.m','functions/adminfunc/eeglab_options.m','functions/adminfunc/eeglab_error.m','functions/adminfunc/eeglab_warning.m','functions/sigprocfunc/icadefs.m','functions/adminfunc/eeg_checkchanlocs.m','functions/adminfunc/ismatlab.m','functions/adminfunc/vararg2str.m','functions/adminfunc/eeg_getversion.m']:
        jobs.append((args.root/'classification/eeglab'/relative,None,[f'https://raw.githubusercontent.com/sccn/eeglab/6d3c2730376e14ea95d0396c3f6caecc39cce308/{relative}']))
    if args.octave:
        jobs.append((args.root/'octave-11.3.0-w64.7z','fd3cf0e885467a15211b8ceded42800432a5462481324d49a896ef257e05d1a0',['https://ftp.gnu.org/gnu/octave/windows/octave-11.3.0-w64.7z','https://mirrors.ibiblio.org/gnu/octave/windows/octave-11.3.0-w64.7z']))
    for path,sha,urls in jobs:
        attempts=[];ok=False
        for url in urls:
            try:download(url,path,sha);ok=True;attempts.append({'url':url,'status':'verified' if sha else 'downloaded'});break
            except Exception as exc:attempts.append({'url':url,'error':str(exc)})
        receipts.append(dict(path=str(path.resolve()),expected_sha256=sha,actual_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if ok else None,attempts=attempts,success=ok))
        (args.root/'fetch-receipts.json').write_text(json.dumps(receipts,ensure_ascii=False,indent=2),encoding='utf-8')
        print(path.name,ok,flush=True)
    # Install the complete author helper directories. Native EEGLAB checks
    # traverse metadata helpers that are absent from the original short pins.
    archive=args.root/'eeglab-6d3c2730.zip'
    download('https://codeload.github.com/sccn/eeglab/zip/6d3c2730376e14ea95d0396c3f6caecc39cce308',archive,'d6a405e8e8d6aa05dad492da16409c56e4ed386992a542ddc59e16f11bcb866c')
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            parts=Path(entry.filename).parts[1:]
            if len(parts)<3 or parts[0]!='functions' or parts[1] not in ('adminfunc','sigprocfunc','popfunc') or entry.is_dir():continue
            destination=(args.root/'classification/eeglab'/Path(*parts)).resolve()
            if not destination.is_relative_to((args.root/'classification/eeglab').resolve()):raise ValueError('unsafe EEGLAB archive entry')
            if destination.exists():
                if destination.read_bytes()!=z.read(entry):raise ValueError('existing EEGLAB helper differs from pinned archive: '+str(destination))
                continue
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(z.read(entry))
    print('EEGLAB transitive helper directories installed from pinned commit',flush=True)
    if args.octave and (archive:=args.root/'octave-11.3.0-w64.7z').exists():
        import py7zr
        destination=(args.root/'octave').resolve();destination.mkdir(exist_ok=True)
        with py7zr.SevenZipFile(archive) as z:
            if any(not (destination/name).resolve().is_relative_to(destination) for name in z.getnames()):raise ValueError('unsafe archive member')
            z.extractall(destination)
        print('portable Octave extracted',flush=True)


if __name__=='__main__':main()
