"""Manual, non-model SFTP panel. Network work runs off the Qt GUI thread."""
from pathlib import Path
import posixpath
from PyQt6.QtCore import QThread,pyqtSignal,Qt
from PyQt6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLineEdit,QSpinBox,QPushButton,QLabel,QSplitter,QListWidget,QListWidgetItem,QFileDialog,QMessageBox,QProgressBar)
from sftp_backend import SftpSession,UnknownHost,fingerprint,remember_host,paramiko

class TransferJob(QThread):
    progress=pyqtSignal(int,int)
    def __init__(self,fn,parent):super().__init__(parent);self.fn=fn;self.value=None;self.error=None
    def run(self):
        try:self.value=self.fn(lambda done,total:self.progress.emit(done,total))
        except Exception as error:self.error=error
        finally:self.fn=None

class SftpTab(QWidget):
    def __init__(self,studio,data):
        super().__init__();self.studio=studio;self.session=SftpSession();self.job=None;self.remote_directory='';self.local_directory='';self.params=None
        self.known_hosts=Path(data)/'private/sftp_known_hosts';self.local_root=None;self.connected=False;self.generation=0
        layout=QVBoxLayout(self);title=QLabel('Remote files');title.setObjectName('title');layout.addWidget(title)
        note=QLabel('Manually transfer files over SFTP. Your server must support SSH/SFTP. Passwords and keys are never sent to chat or saved by this panel.');note.setWordWrap(True);layout.addWidget(note)
        form=QFormLayout();row=QHBoxLayout();self.host=QLineEdit();self.host.setPlaceholderText('sftp.example.com');row.addWidget(self.host,1);self.port=QSpinBox();self.port.setRange(1,65535);self.port.setValue(22);row.addWidget(QLabel('Port'));row.addWidget(self.port);form.addRow('Server',row)
        self.user=QLineEdit();form.addRow('Username',self.user)
        self.password=QLineEdit();self.password.setEchoMode(QLineEdit.EchoMode.Password);self.password.setPlaceholderText('Password / key passphrase (memory only)');form.addRow('Password',self.password)
        row=QHBoxLayout();self.key=QLineEdit();self.key.setPlaceholderText('Optional private key; otherwise password or SSH agent');row.addWidget(self.key,1);self.key_browse=QPushButton('Choose key…');self.key_browse.clicked.connect(self.choose_key);row.addWidget(self.key_browse);form.addRow('SSH key',row)
        self.remote_root=QLineEdit('/');form.addRow('Remote root',self.remote_root);layout.addLayout(form)
        row=QHBoxLayout();self.connect_button=QPushButton('Connect');self.connect_button.clicked.connect(self.connect_server);row.addWidget(self.connect_button);self.disconnect_button=QPushButton('Disconnect / Cancel');self.disconnect_button.clicked.connect(self.disconnect);row.addWidget(self.disconnect_button);self.refresh_button=QPushButton('Refresh');self.refresh_button.clicked.connect(self.refresh);row.addWidget(self.refresh_button);layout.addLayout(row)
        split=QSplitter();left=QWidget();ll=QVBoxLayout(left);self.local_label=QLabel('Local workspace');self.local_label.setWordWrap(True);ll.addWidget(self.local_label);self.local_list=QListWidget();self.local_list.itemDoubleClicked.connect(self.local_enter);ll.addWidget(self.local_list);split.addWidget(left)
        right=QWidget();rl=QVBoxLayout(right);self.remote_label=QLabel('Remote · not connected');self.remote_label.setWordWrap(True);rl.addWidget(self.remote_label);self.remote_list=QListWidget();self.remote_list.itemDoubleClicked.connect(self.remote_enter);rl.addWidget(self.remote_list);split.addWidget(right);layout.addWidget(split,1)
        row=QHBoxLayout();self.upload_button=QPushButton('Upload selected →');self.upload_button.clicked.connect(self.upload);row.addWidget(self.upload_button);self.download_button=QPushButton('← Download selected');self.download_button.clicked.connect(self.download);row.addWidget(self.download_button);layout.addLayout(row)
        self.progress=QProgressBar();self.progress.setRange(0,100);self.progress.setValue(0);layout.addWidget(self.progress);self.status=QLabel('Choose a server and remote root. Transfers are limited to 64 MB per file.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.studio.workspace.currentIndexChanged.connect(self.workspace_changed);self.workspace_changed();self.controls(False)
    def controls(self,busy):
        for widget in (self.host,self.port,self.user,self.password,self.key,self.key_browse,self.remote_root):widget.setEnabled(not busy and not self.connected)
        self.connect_button.setEnabled(not busy and not self.connected);self.refresh_button.setEnabled(not busy and self.connected)
        for widget in (self.upload_button,self.download_button,self.local_list,self.remote_list):widget.setEnabled(not busy and self.connected)
        self.disconnect_button.setEnabled(busy or self.connected)
    def choose_key(self):
        path,_=QFileDialog.getOpenFileName(self,'Choose SSH private key')
        if path:self.key.setText(path)
    def workspace_changed(self):
        self.local_root=Path(self.studio.project.text());self.local_directory=''
        if self.job:
            self.disconnect();self.status.setText('Workspace changed; transfer cancelled. Reconnect before transferring more files.');return
        self.local_root=Path(self.studio.project.text());self.local_directory='';self.list_local()
    def list_local(self):
        from workspace_tools import WorkspaceTools
        self.local_list.clear();self.local_label.setText(str(self.local_root/ self.local_directory))
        try:
            with WorkspaceTools(self.local_root) as fs:value=fs.dispatch('list_project_files',{'directory':self.local_directory or '.'})
            if 'error' in value:raise ValueError(value['error'])
            if self.local_directory:self.add_item(self.local_list,{'name':'..','type':'directory'})
            for item in value['entries']:self.add_item(self.local_list,item)
        except (OSError,ValueError):self.status.setText('Local workspace is unavailable or restricted.')
    def add_item(self,widget,value):
        kind=value.get('kind',value.get('type'));item=QListWidgetItem(('▸ ' if kind=='directory' else '')+value['name']);item.setData(Qt.ItemDataRole.UserRole,{**value,'kind':kind});widget.addItem(item)
    def local_enter(self,item):
        value=item.data(Qt.ItemDataRole.UserRole)
        if value['kind']!='directory':return
        self.local_directory=posixpath.dirname(self.local_directory) if value['name']=='..' else posixpath.join(self.local_directory,value['name']);self.list_local()
    def remote_enter(self,item):
        value=item.data(Qt.ItemDataRole.UserRole)
        if value['kind']!='directory':return
        directory=posixpath.dirname(self.remote_directory) if value['name']=='..' else posixpath.join(self.remote_directory,value['name'])
        self.launch(lambda progress:self.session.list_directory(directory),self.show_remote)
    def show_remote(self,value):
        self.connected=True;self.remote_directory=value['directory'];self.remote_label.setText(value['root']+'/'+self.remote_directory);self.remote_list.clear()
        if self.remote_directory:self.add_item(self.remote_list,{'name':'..','kind':'directory'})
        for entry in value['entries']:self.add_item(self.remote_list,entry)
        self.controls(False)
    def launch(self,fn,callback):
        if self.job:return
        self.controls(True);self.progress.setValue(0);job=TransferJob(fn,self);self.job=job;generation=self.generation
        job.progress.connect(lambda done,total:self.progress.setValue(round(done*100/max(1,total))))
        def finished():
            self.job=None;error=job.error;value=job.value;job.error=None;job.value=None;job.deleteLater();self.controls(False)
            if generation!=self.generation or self.session.cancelled:
                self.session.close()
                self.connected=False;self.params=None;self.controls(False);self.status.setText('Disconnected. Any interrupted transfer may need checking.');return
            if isinstance(error,UnknownHost):
                message=QMessageBox(self);message.setWindowTitle('Verify SSH server identity');message.setText('Trust the SSH key for '+error.host+'?');message.setInformativeText('Verify this fingerprint with your server provider before accepting:\n'+fingerprint(error.key));message.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No);message.setDefaultButton(QMessageBox.StandardButton.No)
                if message.exec()==QMessageBox.StandardButton.Yes:
                    remember_host(self.known_hosts,error.host,error.key);self.start_connect();return
                self.params=None;self.status.setText('SSH host key was not accepted.');return
            if error:
                self.params=None
                if isinstance(error,paramiko.BadHostKeyException):text='Server host key changed. Connection refused; verify it with your provider.'
                elif isinstance(error,paramiko.AuthenticationException):text='Authentication failed. Check the username, password, SSH key or agent.'
                elif isinstance(error,ValueError):text=str(error)
                else:text='SFTP operation failed. Check the server, connection, permissions and remote root.'
                self.status.setText(text);return
            callback(value)
        job.finished.connect(finished);job.start()
    def connect_server(self):
        self.params={'host':self.host.text().strip(),'port':self.port.value(),'user':self.user.text().strip(),'password':self.password.text(),'key_file':self.key.text().strip(),'remote_root':self.remote_root.text().strip(),'known_hosts':str(self.known_hosts)};self.password.clear();self.start_connect()
    def start_connect(self):
        params=dict(self.params or {});self.status.setText('Connecting securely…');self.session.cancelled=False
        def connected(value):self.params=None;self.status.setText('Connected. Select a file to transfer.');self.show_remote(value)
        self.launch(lambda progress:self.session.connect(**params),connected)
    def refresh(self):
        self.list_local();self.launch(lambda progress:self.session.list_directory(self.remote_directory),self.show_remote)
    def upload(self,approved_hash=None):
        item=self.local_list.currentItem()
        if not item:return
        value=item.data(Qt.ItemDataRole.UserRole)
        if value['kind']!='file':self.status.setText('Select one local file to upload.');return
        relative=posixpath.join(self.local_directory,value['name']);workspace=str(self.local_root);directory=self.remote_directory
        self.status.setText('Uploading and verifying '+value['name']+'…')
        def completed(result):
            if result.get('approval_required'):
                decision=QMessageBox.question(self,'Approve remote overwrite','Replace '+result['remote']+' on '+self.host.text()+'?\nThe current remote contents will be replaced by your selected local file.',QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
                if decision==QMessageBox.StandardButton.Yes:self.upload(result['sha256'])
                else:self.status.setText('Overwrite declined. Remote file unchanged.')
                return
            self.progress.setValue(100);self.status.setText('Uploaded and SHA-256 verified: '+result['uploaded']);self.refresh()
        # clicked supplies a boolean; only an explicit digest is an approval.
        approved_hash=approved_hash if isinstance(approved_hash,str) else None
        self.launch(lambda progress:self.session.upload(workspace,relative,directory,approved_hash,progress),completed)
    def download(self):
        item=self.remote_list.currentItem()
        if not item:return
        value=item.data(Qt.ItemDataRole.UserRole)
        if value['kind']!='file':self.status.setText('Select one remote file to download.');return
        remote=posixpath.join(self.remote_directory,value['name']);target=posixpath.join(self.local_directory,value['name'])
        if (self.local_root/target).exists():self.status.setText('A local file with this name already exists. Choose another local folder; downloads never overwrite files.');return
        workspace=str(self.local_root);self.status.setText('Downloading and verifying '+value['name']+'…')
        def completed(result):self.progress.setValue(100);self.status.setText('Downloaded and SHA-256 verified: '+result['downloaded']);self.list_local()
        self.launch(lambda progress:self.session.download(remote,workspace,target,progress),completed)
    def disconnect(self):
        self.generation+=1
        self.session.close();self.connected=False;self.params=None;self.password.clear();self.remote_list.clear();self.remote_label.setText('Remote · disconnected');self.controls(bool(self.job));self.status.setText('Disconnected.' if not self.job else 'Cancelling transfer…')
    def shutdown(self):
        self.disconnect()
        if self.job and self.job.isRunning():return False
        return True
