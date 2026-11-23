"""Actual SSH/SFTP loopback transfers, using disposable credentials and host keys."""
import os,socket,threading,tempfile,unittest,stat,errno
from pathlib import Path
from sftp_backend import SftpSession,UnknownHost,remember_host,fingerprint,paramiko
class Auth(paramiko.ServerInterface):
    def check_auth_password(self,user,password):return paramiko.AUTH_SUCCESSFUL if (user,password)==('tester','synthetic-password') else paramiko.AUTH_FAILED
    def check_channel_request(self,kind,channel_id):return paramiko.OPEN_SUCCEEDED if kind=='session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    def get_allowed_auths(self,user):return 'password'
class Files(paramiko.SFTPServerInterface):
    def __init__(self,server,*args,root,**kwargs):super().__init__(server,*args,**kwargs);self.root=Path(root)
    def path(self,p):
        out=self.root/p.lstrip('/')
        if os.path.commonpath([str(self.root),str(out.absolute())])!=str(self.root) or '..' in Path(p).parts:raise PermissionError(errno.EACCES,'Outside test root')
        return out
    def canonicalize(self,p):return '/'+str(Path(p)).lstrip('/')
    def list_folder(self,p):
        try:
            result=[]
            for item in self.path(p).iterdir():
                a=paramiko.SFTPAttributes.from_stat(item.lstat());a.filename=item.name;result.append(a)
            return result
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def lstat(self,p):
        try:return paramiko.SFTPAttributes.from_stat(self.path(p).lstat())
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def stat(self,p):
        try:return paramiko.SFTPAttributes.from_stat(self.path(p).stat())
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def open(self,p,flags,attr):
        try:
            fd=os.open(self.path(p),flags,0o600)
            mode='r+b' if flags&os.O_RDWR else 'wb' if flags&os.O_WRONLY else 'rb'
            stream=os.fdopen(fd,mode);handle=paramiko.SFTPHandle(flags)
            if flags&os.O_WRONLY or flags&os.O_RDWR:handle.writefile=stream
            if not flags&os.O_WRONLY:handle.readfile=stream
            return handle
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def remove(self,p):
        try:self.path(p).unlink();return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def rename(self,a,b):
        try:
            if self.path(b).exists():return paramiko.SFTP_FAILURE
            self.path(a).rename(self.path(b));return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
    def posix_rename(self,a,b):
        try:os.replace(self.path(a),self.path(b));return paramiko.SFTP_OK
        except OSError as e:return paramiko.SFTPServer.convert_errno(e.errno)
class LocalServer:
    def __init__(self,root):
        self.root=root;self.key=paramiko.RSAKey.generate(2048);self.socket=socket.socket();self.socket.bind(('127.0.0.1',0));self.socket.listen();self.socket.settimeout(.2);self.port=self.socket.getsockname()[1];self.closed=False;self.transports=[]
        self.thread=threading.Thread(target=self.accept,daemon=True);self.thread.start()
    def accept(self):
        while not self.closed:
            try:sock,_=self.socket.accept()
            except (socket.timeout,OSError):continue
            transport=paramiko.Transport(sock);self.transports.append(transport);transport.add_server_key(self.key);transport.set_subsystem_handler('sftp',paramiko.SFTPServer,Files,root=self.root)
            try:transport.start_server(server=Auth())
            except Exception:transport.close()
    def close(self):
        self.closed=True;self.socket.close()
        for t in self.transports:t.close()
        self.thread.join(timeout=2)
class SftpIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name);self.remote=base/'remote';self.remote.mkdir();(self.remote/'site').mkdir();self.local=base/'local';self.local.mkdir();self.hosts=base/'private/known_hosts';self.server=LocalServer(self.remote);self.session=SftpSession()
        remember_host(self.hosts,'[127.0.0.1]:'+str(self.server.port),self.server.key)
    def tearDown(self):self.session.close();self.server.close();self.temp.cleanup()
    def connect(self,hosts=None,password='synthetic-password'):
        return self.session.connect('127.0.0.1',self.server.port,'tester',password,'','/site',hosts or self.hosts)
    def test_real_upload_download_and_verified_overwrite(self):
        self.connect();(self.local/'hello.txt').write_text('first version');progress=[]
        result=self.session.upload(self.local,'hello.txt','',progress=lambda a,b:progress.append((a,b)))
        self.assertEqual((self.remote/'site/hello.txt').read_text(),'first version');self.assertEqual(result['bytes'],13);self.assertTrue(progress)
        (self.local/'hello.txt').write_text('second version');review=self.session.upload(self.local,'hello.txt','');self.assertTrue(review['approval_required'])
        self.assertEqual((self.remote/'site/hello.txt').read_text(),'first version')
        self.session.upload(self.local,'hello.txt','',review['sha256']);self.assertEqual((self.remote/'site/hello.txt').read_text(),'second version')
        download=self.session.download('hello.txt',self.local,'download.txt');self.assertEqual((self.local/'download.txt').read_text(),'second version');self.assertEqual(download['bytes'],14)
        with self.assertRaises(FileExistsError):self.session.download('hello.txt',self.local,'download.txt')
        self.assertFalse(any(p.name.startswith('.qwen-upload') for p in (self.remote/'site').iterdir()))
    def test_unknown_changed_host_key_and_wrong_password(self):
        with self.assertRaises(UnknownHost) as ctx:self.connect(hosts=self.hosts.with_name('missing'))
        self.assertTrue(fingerprint(ctx.exception.key).startswith('SHA256:'))
        wrong=self.hosts.with_name('wrong');remember_host(wrong,'[127.0.0.1]:'+str(self.server.port),paramiko.RSAKey.generate(2048))
        with self.assertRaises(paramiko.BadHostKeyException):self.connect(hosts=wrong)
        with self.assertRaises(paramiko.AuthenticationException):self.connect(password='wrong')
    def test_confinement_links_credentials_and_stale_approval(self):
        self.connect();(self.local/'a.txt').write_text('safe');(self.remote/'site/a.txt').write_text('old')
        review=self.session.upload(self.local,'a.txt','');(self.remote/'site/a.txt').write_text('concurrent')
        again=self.session.upload(self.local,'a.txt','',review['sha256']);self.assertTrue(again['approval_required']);self.assertEqual((self.remote/'site/a.txt').read_text(),'concurrent')
        (self.remote/'site/link').symlink_to(self.remote/'site/a.txt')
        with self.assertRaises(ValueError):self.session.download('link',self.local,'b.txt')
        with self.assertRaises(ValueError):self.session.checked('../outside')
        (self.local/'alias').symlink_to(self.local/'a.txt')
        with self.assertRaises(OSError):self.session.upload(self.local,'alias','')
        (self.local/'.env').write_text('restricted')
        with self.assertRaises(ValueError):self.session.upload(self.local,'.env','')
        (self.local/'secret.txt').write_text('-----BEGIN PRIVATE KEY-----')
        with self.assertRaises(ValueError):self.session.upload(self.local,'secret.txt','')
        self.assertFalse((self.remote/'site/secret.txt').exists())
if __name__=='__main__':unittest.main()
