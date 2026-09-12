"""Create a new independent Python environment; never update an existing one."""
from pathlib import Path
import argparse,subprocess,sys,json,hashlib


def main():
    p=argparse.ArgumentParser();p.add_argument('--environment',type=Path,required=True);p.add_argument('--assets',type=Path);args=p.parse_args()
    target=args.environment.resolve()
    if target.exists():raise ValueError('choose a new environment directory; existing environments are preserved')
    if sys.version_info[:2]!=(3,12):raise ValueError('run with Python 3.12; audited patch version is 3.12.14')
    backend=Path(__file__).resolve().parents[1];lock=backend/'requirements-units-v2.lock.txt'
    subprocess.run([sys.executable,'-m','venv',str(target)],check=True)
    python=target/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    commands=[[str(python),'-m','pip','install','-r',str(lock)],[str(python),'-m','pip','check']]
    if args.assets:
        commands.extend([[str(python),'-X','utf8','-m','scripts.fetch_unit_assets','--root',str(args.assets.resolve()),'--octave'],[str(python),'-X','utf8','-m','scripts.install_octave_unit_packages','--root',str(args.assets.resolve())]])
    history=[]
    for command in commands:
        result=subprocess.run(command,cwd=backend);history.append({'command':command,'exit_code':result.returncode})
        (target/'bootstrap-receipt.json').write_text(json.dumps({'python':sys.version,'lock_sha256':hashlib.sha256(lock.read_bytes()).hexdigest(),'commands':history},indent=2),encoding='utf-8')
        if result.returncode:raise SystemExit(result.returncode)


if __name__=='__main__':main()
