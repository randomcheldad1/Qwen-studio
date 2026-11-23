"""Confined text tools. Paths are traversed using directory FDs and O_NOFOLLOW."""
import os, stat, json, re, hashlib, secrets
from pathlib import Path
from contextlib import contextmanager

LIMIT = 200_000
DENIED = {'.vendor','.local','.git','.ssh','.aws','.config','.codex','.claude','.agents','.gnupg','private','node_modules','__pycache__','.venv','venv','dist','build'}
SENSITIVE = re.compile(r'^(?:\.env(?:\..*)?|\.npmrc|\.pypirc|auth(?:\..*)?|credentials.*|secrets?.*|config\.json|id_(?:rsa|ed25519|ecdsa).*|authorized_keys|known_hosts)$|\.(?:pem|key|p12|pfx|jks|keystore|sqlite\w*|db)$', re.I)
SECRET = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})|(?im:^\s*["\']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)["\']?\s*[:=]\s*["\']?[^\s"\']{8,})')
def guarded_text(text):
    if '\0' in text or SECRET.search(text):
        raise ValueError('Binary or credential-bearing content is restricted.')
    return text

def schema(name, description, properties, required=()):
    return {'type':'function','function':{'name':name,'description':description,'parameters':{'type':'object','properties':{k:(v if isinstance(v,dict) else {'type':'string','description':v}) for k,v in properties.items()},'required':list(required),'additionalProperties':False}}}
TOOLS = [
    schema('list_project_files','List safe entries in the selected workspace.',{'directory':'Relative directory, default .'}),
    schema('read_project_file','Read a UTF-8 file chunk and full-file SHA-256. Use next_offset to continue.',{'file':'Relative file path','offset':{'type':'integer','minimum':0,'description':'Character offset, default 0'}},['file']),
    schema('search_project_files','Search text in safe workspace files.',{'term':'Literal text to find','directory':'Relative directory, default .'},['term']),
    schema('create_project_file','Create a new UTF-8 file; never overwrites.',{'file':'Relative file path','content':'Complete new file content'},['file','content']),
    schema('edit_project_file','Edit after local approval. Use old_text/new_text for a unique targeted replacement, or content for a complete replacement. Read first for full-file SHA-256.',{'file':'Relative file path','content':'Complete replacement content; omit for targeted edits','old_text':'Exact unique text to replace; omit for complete replacement','new_text':'Replacement for old_text','expected_sha256':'Full-file SHA-256 from read_project_file'},['file','expected_sha256']),
    schema('make_project_directory','Create one new directory.',{'directory':'Relative directory'},['directory']),
]

class WorkspaceTools:
    def __init__(self, root, approve=None):
        self.root = Path(root).absolute()
        if any(part.lower() in DENIED or SENSITIVE.search(part) for part in self.root.parts[1:]):
            raise ValueError('Credential or private directories cannot be workspaces.')
        self.approve = approve or (lambda *args: False)
        # Walk from / instead of following a symlink in any root ancestor.
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.root.parts[1:]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = nxt
            self.fd = fd
        except BaseException:
            os.close(fd); raise
    def close(self):
        if self.fd is not None: os.close(self.fd); self.fd = None
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    @staticmethod
    def parts(path, directory=False):
        if directory and path == '.': return []
        if not isinstance(path,str) or not path or len(path)>1024 or '\\' in path or '\0' in path or path.startswith('/'):
            raise ValueError('Use a relative workspace path.')
        parts=path.split('/')
        if any(p in ('','.','..') or p.lower() in DENIED or SENSITIVE.search(p) for p in parts):
            raise ValueError('Restricted path.')
        return parts
    @contextmanager
    def directory(self, parts):
        fd=os.dup(self.fd)
        try:
            for part in parts:
                nxt=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
                os.close(fd);fd=nxt
            self.check_anchor(fd)
            yield fd
        finally: os.close(fd)
    def check_anchor(self,fd):
        root=os.readlink('/proc/self/fd/'+str(self.fd))
        actual=os.readlink('/proc/self/fd/'+str(fd))
        if root!=str(self.root) or not (actual==root or actual.startswith(root+'/')) or actual.endswith(' (deleted)'):
            raise ValueError('Workspace directory moved or was removed; retry the operation.')
    def read_at(self, fd, name):
        self.check_anchor(fd)
        f=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
        try:
            st=os.fstat(f)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>LIMIT: raise ValueError('Not a safe text file (size, type or hard link).')
            with os.fdopen(os.dup(f),'rb') as stream: data=stream.read(LIMIT+1)
            if len(data)>LIMIT: raise ValueError('File exceeds 200 KB.')
            content=guarded_text(data.decode('utf-8'))
            return {'content':content,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
        finally: os.close(f)
    def dispatch(self, name, args):
        try:
            tool=next((t['function'] for t in TOOLS if t['function']['name']==name),None)
            if not tool or not isinstance(args,dict): raise ValueError('Unknown tool or invalid arguments.')
            spec=tool['parameters']
            if set(args)-set(spec['properties']) or any(k not in args for k in spec['required']): raise ValueError('Invalid tool arguments.')
            for key,value in args.items():
                expected=spec['properties'][key]['type']
                if expected=='string' and not isinstance(value,str):raise ValueError('Invalid tool arguments.')
                if expected=='integer' and (type(value) is not int or value<0):raise ValueError('Invalid tool arguments.')
            return self.execute(name,args)
        except (OSError, ValueError, UnicodeError) as e:
            # Avoid OS errors containing absolute paths or private content.
            return {'error': str(e) if isinstance(e,ValueError) and not isinstance(e,UnicodeError) else 'File operation refused or unavailable.'}
    def execute(self,name,args):
        if name in ('list_project_files','search_project_files'):
            directory=args.get('directory','.')
            parts=self.parts(directory,True)
            with self.directory(parts) as fd:
                if name=='list_project_files': return self.list_at(fd,directory)
                term=args['term']
                if not 1<=len(term)<=120: raise ValueError('Search term must be 1–120 characters.')
                hits=[];budget=[1000];truncated=[False]
                def walk(current,prefix,depth):
                    for entry in sorted(os.listdir(current)):
                        budget[0]-=1
                        if budget[0]<0 or len(hits)>=100: truncated[0]=True;return
                        try:
                            self.parts(entry)
                            st=os.stat(entry,dir_fd=current,follow_symlinks=False)
                            rel=prefix+entry
                            if stat.S_ISDIR(st.st_mode):
                                if depth>=6: truncated[0]=True;continue
                                child=os.open(entry,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=current)
                                try: walk(child,rel+'/',depth+1)
                                finally: os.close(child)
                            elif stat.S_ISREG(st.st_mode):
                                for i,line in enumerate(self.read_at(current,entry)['content'].splitlines(),1):
                                    if term in line:
                                        hits.append({'file':rel,'line':i,'preview':line[:250]})
                                        if len(hits)>=100: truncated[0]=True;return
                        except (OSError,ValueError,UnicodeError): continue
                walk(fd,'' if directory=='.' else directory+'/',0)
                return {'hits':hits,'truncated':truncated[0]}
        parts=self.parts(args.get('file',args.get('directory')))
        with self.directory(parts[:-1]) as fd:
            leaf=parts[-1]
            if name=='read_project_file':
                result=self.read_at(fd,leaf);content=result['content'];offset=args.get('offset',0)
                if offset>len(content):raise ValueError('Offset exceeds file length.')
                result['content']=content[offset:offset+6000]
                return {'file':args['file'],**result,'offset':offset,'total_characters':len(content),'truncated':offset+6000<len(content),'next_offset':offset+len(result['content'])}
            if name=='make_project_directory':
                os.mkdir(leaf,mode=0o750,dir_fd=fd);return {'directory':args['directory'],'created':True}
            if name=='edit_project_file' and 'content' not in args:
                before=self.read_at(fd,leaf)
                old=args.get('old_text');new=args.get('new_text')
                if not old or new is None or before['content'].count(old)!=1:raise ValueError('old_text must occur exactly once; provide new_text.')
                args={**args,'content':before['content'].replace(old,new,1)}
            elif name=='edit_project_file' and ('old_text' in args or 'new_text' in args):
                raise ValueError('Choose either complete content or old_text/new_text.')
            data=guarded_text(args['content']).encode('utf-8')
            if len(data)>LIMIT: raise ValueError('Content exceeds 200 KB.')
            if name=='create_project_file':
                out=os.open(leaf,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                with os.fdopen(out,'wb') as stream: stream.write(data);stream.flush();os.fsync(stream.fileno())
            elif name=='edit_project_file':
                before=self.read_at(fd,leaf)
                if before['sha256']!=args['expected_sha256']: raise ValueError('File changed; read it again before editing.')
                if not self.approve(args['file'],before['content'],args['content']): return {'error':'User approval required or declined. File unchanged.'}
                self.check_anchor(fd)
                if self.read_at(fd,leaf)['sha256']!=before['sha256']: raise ValueError('File changed during approval; read it again.')
                mode=stat.S_IMODE(os.stat(leaf,dir_fd=fd,follow_symlinks=False).st_mode)&0o777
                tmp='.qwen-write-'+secrets.token_hex(12)
                out=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode,dir_fd=fd)
                try:
                    with os.fdopen(out,'wb') as stream: stream.write(data);stream.flush();os.fsync(stream.fileno())
                    os.rename(tmp,leaf,src_dir_fd=fd,dst_dir_fd=fd)
                finally:
                    try: os.unlink(tmp,dir_fd=fd)
                    except FileNotFoundError: pass
            return {'file':args['file'],'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'written':True}
    def list_at(self,fd,directory):
        entries=[]
        for name in sorted(os.listdir(fd)):
            try:
                self.parts(name);st=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode): kind='directory'
                elif stat.S_ISREG(st.st_mode) and st.st_nlink==1: kind='file'
                else: continue
                entries.append({'name':name,'type':kind})
            except (OSError,ValueError): continue
        return {'directory':directory,'entries':entries[:100],'truncated':len(entries)>100}

if __name__=='__main__':
    import sys
    # Remote bridge may choose only these two roots, never arbitrary paths.
    base=Path(__file__).resolve().parent
    roots={'qwen-studio':base,'example':base/'workspace'}
    try:
        request=json.load(sys.stdin)
        with WorkspaceTools(roots[request.get('workspace','qwen-studio')]) as fs:
            print(json.dumps(fs.dispatch(request['name'],request['arguments'])))
    except Exception:
        print(json.dumps({'error':'Invalid workspace or request.'}))
