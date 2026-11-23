"""Manual SFTP operations. No model dispatch, credential storage, or shell access."""
import sys,os,stat,posixpath,hashlib,base64,secrets,errno
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'.vendor'))
import paramiko
from workspace_tools import WorkspaceTools,SECRET
MAX_BYTES=64*1024*1024
class UnknownHost(Exception):
    def __init__(self,host,key):self.host=host;self.key=key;super().__init__('Unknown SSH host key')
class AskHost(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self,client,hostname,key):raise UnknownHost(hostname,key)
def fingerprint(key):return 'SHA256:'+base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
def remember_host(path,host,key):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    keys=paramiko.HostKeys()
    if path.exists():keys.load(str(path))
    keys.add(host,key.get_name(),key)
    temp=path.with_name(path.name+'.'+secrets.token_hex(8));keys.save(str(temp));temp.chmod(0o600);temp.replace(path)
class SftpSession:
    def __init__(self):self.client=None;self.sftp=None;self.root=None;self.cancelled=False
    def connect(self,host,port,user,password,key_file,remote_root,known_hosts):
        self.close();self.cancelled=False
        if not host or not user or not 1<=port<=65535:raise ValueError('Enter a host, username, and valid port.')
        self.client=paramiko.SSHClient();self.client.load_system_host_keys()
        if Path(known_hosts).is_file():self.client.load_host_keys(str(known_hosts))
        self.client.set_missing_host_key_policy(AskHost())
        try:
            self.client.connect(hostname=host,port=port,username=user,password=password or None,key_filename=key_file or None,look_for_keys=False,allow_agent=not bool(password or key_file),timeout=10,banner_timeout=10,auth_timeout=15,channel_timeout=15)
            self.sftp=self.client.open_sftp();self.sftp.get_channel().settimeout(20)
            if not remote_root.startswith('/'):raise ValueError('Remote root must be an absolute directory.')
            self.root='/'
            self.root=self.checked(remote_root.lstrip('/'),directory=True)
            return self.list_directory('')
        except BaseException:
            self.close();self.cancelled=False;raise
    def close(self):
        self.cancelled=True
        if self.client:self.client.close()
        self.sftp=None;self.client=None;self.root=None
    def parts(self,relative):
        if relative=='':return []
        if not isinstance(relative,str) or relative.startswith('/') or '\\' in relative or '\0' in relative:raise ValueError('Invalid relative remote path.')
        parts=relative.split('/')
        if any(p in ('','.','..') for p in parts):raise ValueError('Remote path escapes the selected root.')
        return parts
    def checked(self,relative,directory=False,missing=False):
        parts=self.parts(relative);path=self.root
        if not self.sftp or not path:raise ValueError('Connect first.')
        for i,part in enumerate(parts):
            path=posixpath.join(path,part)
            try:mode=self.sftp.lstat(path).st_mode
            except OSError as e:
                if missing and i==len(parts)-1 and e.errno==errno.ENOENT:return path
                raise
            if stat.S_ISLNK(mode):raise ValueError('Remote symbolic links are not followed.')
            if (i<len(parts)-1 or directory) and not stat.S_ISDIR(mode):raise ValueError('Not a remote directory.')
            if i==len(parts)-1 and not directory and not stat.S_ISREG(mode):raise ValueError('Not a regular remote file.')
        return path
    def list_directory(self,relative):
        path=self.checked(relative,directory=True);entries=[]
        for item in self.sftp.listdir_attr(path):
            if len(entries)>=2000:break
            try:self.parts(item.filename)
            except ValueError:continue
            if '/' in item.filename or stat.S_ISLNK(item.st_mode):continue
            kind='directory' if stat.S_ISDIR(item.st_mode) else 'file' if stat.S_ISREG(item.st_mode) else None
            if kind:entries.append({'name':item.filename,'kind':kind,'size':item.st_size})
        return {'root':self.root,'directory':relative,'entries':sorted(entries,key=lambda e:(e['kind']!='directory',e['name'].lower()))}
    def digest_remote(self,path):
        digest=hashlib.sha256();size=0
        with self.sftp.open(path,'rb') as stream:
            while True:
                if self.cancelled:raise ValueError('Transfer cancelled.')
                data=stream.read(65536)
                if not data:break
                size+=len(data)
                if size>MAX_BYTES:raise ValueError('File exceeds 64 MB transfer limit.')
                digest.update(data)
        return digest.hexdigest()
    def upload(self,workspace,relative,directory,approved_hash=None,progress=lambda done,total:None):
        with WorkspaceTools(workspace) as fs:
            parts=fs.parts(relative)
            with fs.directory(parts[:-1]) as fd:
                source=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=fd)
                with os.fdopen(source,'rb') as stream:
                    info=os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>MAX_BYTES:raise ValueError('Choose a regular file below 64 MB without symbolic or hard links.')
                    digest=hashlib.sha256();carry=''
                    while True:
                        chunk=stream.read(65536)
                        if not chunk:break
                        text=carry+chunk.decode('utf-8',errors='ignore')
                        if SECRET.search(text):raise ValueError('Credential-bearing files cannot be uploaded.')
                        carry=text[-512:];digest.update(chunk)
                    stream.seek(0)
                    parent=self.checked(directory,directory=True);target=posixpath.join(parent,parts[-1]);remote_relative='/'.join([x for x in (directory,parts[-1]) if x])
                    try:
                        self.checked(remote_relative);old=self.digest_remote(target)
                    except OSError as e:
                        if e.errno!=errno.ENOENT:raise
                        old=None
                    if old is not None and approved_hash!=old:return {'approval_required':True,'remote':remote_relative,'sha256':old,'bytes':info.st_size}
                    if old is None and approved_hash is not None:raise ValueError('Remote file changed after approval. Review again.')
                    temp=posixpath.join(parent,'.qwen-upload-'+secrets.token_hex(12));created=False
                    try:
                        with self.sftp.open(temp,'wx') as out:
                            created=True;done=0
                            while True:
                                if self.cancelled:raise ValueError('Transfer cancelled.')
                                chunk=stream.read(65536)
                                if not chunk:break
                                out.write(chunk);done+=len(chunk);progress(done,info.st_size)
                        if self.digest_remote(temp)!=digest.hexdigest():raise ValueError('Uploaded content did not verify.')
                        self.checked(directory,directory=True)
                        if old is not None:
                            self.checked(remote_relative)
                            if self.digest_remote(target)!=old:raise ValueError('Remote file changed; nothing replaced.')
                            self.sftp.posix_rename(temp,target)
                        else:self.sftp.rename(temp,target)
                        created=False
                        return {'uploaded':remote_relative,'bytes':info.st_size,'sha256':digest.hexdigest()}
                    finally:
                        if created:
                            try:self.sftp.remove(temp)
                            except Exception:pass
    def download(self,relative,workspace,destination,progress=lambda done,total:None):
        remote=self.checked(relative);size=self.sftp.stat(remote).st_size
        if size>MAX_BYTES:raise ValueError('File exceeds 64 MB transfer limit.')
        with WorkspaceTools(workspace) as fs:
            parts=fs.parts(destination)
            with fs.directory(parts[:-1]) as fd:
                # Local files are never overwritten; choose another filename.
                target=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                try:
                    with os.fdopen(target,'wb') as out,self.sftp.open(remote,'rb') as src:
                        done=0;digest=hashlib.sha256();carry=''
                        while True:
                            if self.cancelled:raise ValueError('Transfer cancelled.')
                            chunk=src.read(65536)
                            if not chunk:break
                            done+=len(chunk)
                            if done>MAX_BYTES:raise ValueError('File exceeds 64 MB transfer limit.')
                            text=carry+chunk.decode('utf-8',errors='ignore')
                            if SECRET.search(text):raise ValueError('Credential-bearing remote files cannot be downloaded into the workspace.')
                            carry=text[-512:];out.write(chunk);digest.update(chunk);progress(done,size)
                    if self.digest_remote(self.checked(relative))!=digest.hexdigest():raise ValueError('Remote file changed during download; try again.')
                except BaseException:os.unlink(parts[-1],dir_fd=fd);raise
        return {'downloaded':destination,'bytes':done,'sha256':digest.hexdigest()}
