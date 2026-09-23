"""Install/remove a per-user background service. No administrator rights required."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
LABEL='com.mentalist.market'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','remove'])
    action=parser.parse_args().action
    if sys.platform=='darwin':
        path=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
        target=f'gui/{os.getuid()}'
        if action=='remove':
            subprocess.run(['launchctl','bootout',target,str(path)],check=False)
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True,exist_ok=True)
            logs=ROOT/'.scanner';logs.mkdir(exist_ok=True)
            payload={'Label':LABEL,'ProgramArguments':[sys.executable,str(ROOT/'server.py')],'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':30,'StandardOutPath':str(logs/'service.log'),'StandardErrorPath':str(logs/'service-error.log')}
            path.write_bytes(plistlib.dumps(payload))
            subprocess.run(['launchctl','bootout',target,str(path)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            subprocess.run(['launchctl','bootstrap',target,str(path)],check=True)
    elif sys.platform=='win32':
        startup=Path(os.environ['APPDATA'])/'Microsoft/Windows/Start Menu/Programs/Startup/Mentalist.cmd'
        if action=='remove':startup.unlink(missing_ok=True)
        else:
            python=Path(sys.executable).with_name('pythonw.exe')
            if not python.exists():python=Path(sys.executable)
            startup.write_text(f'@echo off\nstart "Mentalist" "{python}" "{ROOT / "server.py"}"\n')
            subprocess.Popen([str(python),str(ROOT/'server.py')],cwd=ROOT)
    else:
        raise SystemExit('Linux: follow the systemd instructions in RUNNING.md.')
    print('Background startup '+('installed. Open http://127.0.0.1:8765. Keep the computer awake.' if action=='install' else 'removed. On Windows, stop any running server separately.'))

if __name__=='__main__':main()
