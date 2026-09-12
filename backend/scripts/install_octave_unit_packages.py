"""Install source-pinned Octave packages only into the portable task runtime."""
from pathlib import Path
import argparse
import os
import subprocess
from .fetch_unit_assets import download


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args();root=args.root.resolve()
    portable=root/'octave/octave-11.3.0-w64';binary=portable/'mingw64/bin/octave-cli.exe'
    packages=[('signal-1.4.8.tar.gz','https://github.com/gnu-octave/octave-signal/releases/download/1.4.8/signal-1.4.8.tar.gz','f5989b4f148e6f5b696a7b7ceee8c610140acf6084eb3e7eafbf0eb38df79a33'),('statistics-1.7.7.tar.gz','https://github.com/gnu-octave/statistics/releases/download/release-1.7.7/statistics-1.7.7.tar.gz','cef3c090aee13eaad50b4b9beb2f003e8756cbf018d2be7233326de9696cdf7e')]
    for name,url,sha in packages:download(url,root/name,sha)
    env=os.environ.copy();env['PATH']=str(portable/'mingw64/bin')+os.pathsep+str(portable/'usr/bin')+os.pathsep+env['PATH']
    # -global here means this portable installation, not the machine's Octave.
    script='\n'.join("pkg('install','-global','"+(root/name).as_posix().replace("'","''")+"');" for name,_,_ in packages)+"\npkg load signal; pkg load statistics; pkg load optim; disp(ver('signal')); disp(ver('statistics')); disp(ver('optim'));\n"
    driver=root/'install-packages.m';driver.write_text(script,encoding='utf-8')
    with (root/'package-install.log').open('w',encoding='utf-8') as log:
        run=subprocess.run([str(binary),'--no-gui','--quiet',str(driver)],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    print('package installation exit:',run.returncode,flush=True)
    if run.returncode:raise RuntimeError('see '+str(root/'package-install.log'))


if __name__=='__main__':main()
