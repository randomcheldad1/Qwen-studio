"""Execute Python/JavaScript in an empty, networkless, read-only-system sandbox.
No workspace, home directory, credentials or host temporary files are mounted.
"""
import json,os,resource,signal,subprocess,tempfile,time,selectors
from pathlib import Path
from workspace_tools import guarded_text
_ACTIVE=None
def cancel(*args):
    if _ACTIVE is not None:
        try:os.killpg(_ACTIVE.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    raise SystemExit(130)

def limits():
    os.setsid()
    resource.setrlimit(resource.RLIMIT_CPU,(15,15))
    resource.setrlimit(resource.RLIMIT_FSIZE,(10_000_000,10_000_000))
    resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))

def run_code(language,code):
    global _ACTIVE
    if language not in ('python','javascript') or not isinstance(code,str) or not 1<=len(code)<=20000:raise ValueError('Use python or javascript and at most 20000 code characters.')
    guarded_text(code)
    if not Path('/usr/bin/bwrap').is_file():return {'error':'Safe code isolation is unavailable. No code was run.'}
    runtime='/usr/bin/python3'
    if language=='javascript':
        candidates=[Path('/usr/bin/node')]+sorted((Path.home()/'.nvm/versions/node').glob('*/bin/node'),reverse=True)
        runtime=str(next((p for p in candidates if p.is_file()),''))
        if not runtime:return {'error':'JavaScript runtime is unavailable.'}
    with tempfile.TemporaryDirectory(prefix='qwen-code-') as folder:
        script=Path(folder)/('main.py' if language=='python' else 'main.js');script.write_text(code)
        args=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--clearenv','--ro-bind','/usr','/usr']
        for directory in ('/lib','/lib64','/bin'):
            if Path(directory).exists():args+=['--ro-bind',directory,directory]
        args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--ro-bind',folder,'/work','--chdir','/work','--setenv','HOME','/tmp','--setenv','PATH','/usr/bin:/bin','--setenv','LANG','C.UTF-8']
        if language=='javascript':args+=['--ro-bind',runtime,'/runtime','--','/runtime','--max-old-space-size=128','/work/main.js']
        else:args+=['--','/usr/bin/python3','-I','-B','/work/main.py']
        args=['/usr/bin/systemd-run','--user','--scope','--quiet','--property=MemoryMax=512M','--property=TasksMax=32','--property=CPUQuota=100%','--property=RuntimeMaxSec=30s']+args
        p=subprocess.Popen(args,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,preexec_fn=limits)
        _ACTIVE=p
        output=bytearray();deadline=time.monotonic()+25;selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ)
        timed_out=False;truncated=False
        try:
            while True:
                if time.monotonic()>deadline:timed_out=True;break
                events=selector.select(.1)
                if events:
                    chunk=os.read(p.stdout.fileno(),4096)
                    if not chunk:break
                    output.extend(chunk)
                    if len(output)>64000:truncated=True;break
                elif p.poll() is not None:break
        finally:
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            p.wait();selector.close();p.stdout.close()
        _ACTIVE=None
        text=output[:64000].decode(errors='replace')
        if text.startswith(('bwrap:','Failed to connect to bus','Failed to start transient scope','Failed to start transient unit')):return {'error':'The operating system refused safe isolation. No unrestricted fallback was attempted.'}
        guarded_text(text)
        return {'language':language,'exit_code':p.returncode,'output':text,'timed_out':timed_out,'truncated':truncated,'scope':'isolated scratch runtime; no workspace, network, home or credentials'}

if __name__=='__main__':
    signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
    try:
        data=json.load(__import__('sys').stdin);result=run_code(data['language'],data['code'])
    except ValueError as e:result={'error':str(e)}
    except Exception:result={'error':'Code execution failed safely.'}
    print(json.dumps(result))
