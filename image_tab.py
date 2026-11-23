"""Local Stable Diffusion via the user's existing local ComfyUI installation."""
import json, uuid, secrets, time, os, sys
from pathlib import Path
from PyQt6.QtCore import Qt,QUrl,QUrlQuery,QTimer,QProcess
from PyQt6.QtGui import QPixmap,QDesktopServices
from PyQt6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QLineEdit,QPlainTextEdit,QComboBox,QSpinBox,QCheckBox,QMessageBox,QFileDialog,QSplitter
BASE=Path(__file__).resolve().parent
COMFY=Path(os.environ.get('COMFYUI_ROOT',str(Path.home()/'ComfyUI')))
PYTHON=Path(os.environ.get('COMFYUI_PYTHON',sys.executable))
OUTPUT=BASE/'generated'

def workflow(checkpoint,prompt,negative,width,height,steps,seed):
    return {
      '1':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':checkpoint}},
      '2':{'class_type':'CLIPTextEncode','inputs':{'clip':['1',1],'text':prompt}},
      '3':{'class_type':'CLIPTextEncode','inputs':{'clip':['1',1],'text':negative}},
      '4':{'class_type':'EmptyLatentImage','inputs':{'width':width,'height':height,'batch_size':1}},
      '5':{'class_type':'KSampler','inputs':{'model':['1',0],'positive':['2',0],'negative':['3',0],'latent_image':['4',0],'seed':seed,'steps':steps,'cfg':7.0,'sampler_name':'euler','scheduler':'normal','denoise':1.0}},
      '6':{'class_type':'VAEDecode','inputs':{'samples':['5',0],'vae':['1',2]}},
      '7':{'class_type':'SaveImage','inputs':{'images':['6',0],'filename_prefix':'QwenStudio'}}}

class ImagesTab(QWidget):
    def __init__(self,studio):
        super().__init__();self.studio=studio;self.net=QNetworkAccessManager(self);self.server=None;self.job_id=None;self.job_url=None;self.pending=False;self.polling=False;self.image_path=None;self.pixmap=None;self.metadata={};self.poll_errors=0;self.start_attempts=0;self.refine_reply=None
        OUTPUT.mkdir(exist_ok=True);layout=QVBoxLayout(self);layout.setSpacing(12)
        row=QHBoxLayout();row.addWidget(QLabel('Image maker'));self.url=QLineEdit('http://127.0.0.1:8188');row.addWidget(self.url,1);self.url.hide();advanced=QCheckBox('Connection settings');advanced.toggled.connect(self.url.setVisible);row.addWidget(advanced);row.addWidget(self.button('Connect',self.connect_backend));self.start_button=self.button('Start image maker',self.start_backend);row.addWidget(self.start_button);row.addWidget(self.button('More image tools',lambda:QDesktopServices.openUrl(QUrl(self.url.text()))));layout.addLayout(row)
        self.status=QLabel('Use your installed Stable Diffusion model. Start the generator, then connect.');self.status.setWordWrap(True);layout.addWidget(self.status)
        split=QSplitter();settings=QWidget();sl=QVBoxLayout(settings);sl.setContentsMargins(0,0,10,0)
        sl.addWidget(QLabel('PICTURE STYLE'));self.models=QComboBox();self.models.addItem('Stable Diffusion 1.5','sd15-v1-5-pruned-emaonly.safetensors');sl.addWidget(self.models)
        sl.addWidget(QLabel('DESCRIBE YOUR PICTURE'));self.prompt=QPlainTextEdit();self.prompt.setPlaceholderText('Describe the image you want to create…');self.prompt.setMaximumHeight(130);sl.addWidget(self.prompt)
        self.refine_button=self.button('Improve description',self.refine_prompt);sl.addWidget(self.refine_button)
        sl.addWidget(QLabel('LEAVE OUT'));self.negative=QLineEdit('blurry, low quality, watermark, text');sl.addWidget(self.negative)
        row=QHBoxLayout();self.size=QComboBox();self.size.addItems(['512 × 512','512 × 768','768 × 512']);row.addWidget(QLabel('Size'));row.addWidget(self.size);self.steps=QSpinBox();self.steps.setRange(1,50);self.steps.setValue(20);row.addWidget(QLabel('Steps'));row.addWidget(self.steps);sl.addLayout(row)
        row=QHBoxLayout();row.addWidget(QLabel('Variation number'));self.seed=QSpinBox();self.seed.setRange(-1,2147483647);self.seed.setValue(-1);self.seed.setSpecialValueText('Random');row.addWidget(self.seed,1);sl.addLayout(row)
        self.release=QCheckBox('Make room for image creation');self.release.setChecked(True);sl.addWidget(self.release)
        note=QLabel('Start with the small picture size for faster results. Pictures stay on this computer.');note.setWordWrap(True);note.setObjectName('muted');sl.addWidget(note)
        row=QHBoxLayout();self.generate=self.button('Make image',self.submit);self.generate.setObjectName('primary');row.addWidget(self.generate);self.cancel=self.button('Cancel image',self.cancel_job);self.cancel.setEnabled(False);row.addWidget(self.cancel);sl.addLayout(row)
        sl.addWidget(self.button('My pictures',lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT)))));self.save_button=self.button('Save a copy…',self.save_as);self.save_button.setEnabled(False);sl.addWidget(self.save_button);sl.addStretch()
        self.log=QPlainTextEdit();self.log.setReadOnly(True);self.log.setMaximumBlockCount(1000);self.log.setMaximumHeight(140);sl.addWidget(self.log);split.addWidget(settings)
        self.preview=QLabel('Your generated image will appear here');self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setMinimumSize(300,300);self.preview.setStyleSheet('background:#10131c;border:1px solid #343b51;border-radius:8px;color:#929bb0');split.addWidget(self.preview);split.setSizes([400,500]);layout.addWidget(split,1)
        self.timer=QTimer(self);self.timer.setInterval(1500);self.timer.timeout.connect(self.poll)
        self.start_timer=QTimer(self);self.start_timer.setInterval(2000);self.start_timer.timeout.connect(self.start_probe)
        self.discover_timer=QTimer(self);self.discover_timer.setSingleShot(True);self.discover_timer.timeout.connect(lambda:self.connect_backend(quiet=True));self.discover_timer.start(300)
    def button(self,label,fn):
        b=QPushButton(label);b.clicked.connect(fn);return b
    def request(self,path,callback,payload=None,base=None,binary=False):
        origin=(base or self.url.text()).rstrip('/');parsed=QUrl(origin)
        if parsed.scheme()!='http' or parsed.host() not in ('localhost','127.0.0.1','::1'):
            callback(None,'Use a local ComfyUI address (localhost or 127.0.0.1).');return
        req=QNetworkRequest(QUrl(origin+path));req.setTransferTimeout(15000)
        if payload is None:r=self.net.get(req)
        else:req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json');r=self.net.post(req,json.dumps(payload).encode())
        def finished():
            data=bytes(r.readAll());error=None;value=None
            if r.error()!=QNetworkReply.NetworkError.NoError:error=r.errorString()+(' · '+data.decode(errors='replace')[:350] if data else '')
            else:
                try:value=data if binary else json.loads(data or b'{}')
                except ValueError:error='Invalid response from ComfyUI.'
            r.deleteLater();callback(value,error)
        r.finished.connect(finished)
    def connect_backend(self,_=False,quiet=False):
        if self.pending:
            self.timer.start();self.poll();return
        def got(data,error):
            if error:
                if not quiet:self.status.setText('Generator is not connected. Click Start image maker.');self.log.appendPlainText(error)
                return
            try:names=data['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
            except (KeyError,TypeError):self.status.setText('No image checkpoints found.');return
            self.models.clear()
            for name in names:self.models.addItem('Stable Diffusion 1.5' if name=='sd15-v1-5-pruned-emaonly.safetensors' else name,name)
            self.status.setText('● Connected to local ComfyUI · '+str(len(names))+' installed image model(s)');self.start_timer.stop();self.start_button.setEnabled(True)
        self.request('/object_info/CheckpointLoaderSimple',got)
    def start_backend(self):
        if self.server:
            self.connect_backend();return
        if not PYTHON.exists() or not (COMFY/'main.py').exists():self.status.setText('The existing local generator installation was not found.');return
        def checked(data,error):
            if not error:self.connect_backend();return
            if QUrl(self.url.text()).port(8188)!=8188:self.status.setText('Set the address to http://127.0.0.1:8188 to start the installed generator.');return
            for p in [BASE/'comfy-user',BASE/'comfy-temp',OUTPUT/'backend']:p.mkdir(parents=True,exist_ok=True)
            proc=QProcess(self);self.server=proc;proc.setWorkingDirectory(str(COMFY));proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            proc.readyReadStandardOutput.connect(lambda:self.log.insertPlainText(bytes(proc.readAllStandardOutput()).decode(errors='replace')))
            proc.finished.connect(lambda *_:self.server_finished(proc));proc.errorOccurred.connect(lambda _:self.status.setText('Generator start failed: '+proc.errorString()))
            args=[str(COMFY/'main.py'),'--listen','127.0.0.1','--port','8188','--lowvram','--force-fp32','--fp32-text-enc','--use-split-cross-attention','--disable-async-offload','--disable-cuda-malloc','--preview-method','none','--disable-auto-launch','--disable-all-custom-nodes','--user-directory',str(BASE/'comfy-user'),'--temp-directory',str(BASE/'comfy-temp'),'--output-directory',str(OUTPUT/'backend')]
            self.start_button.setEnabled(False);proc.start(str(PYTHON),args);self.status.setText('Starting the existing Stable Diffusion generator…');self.start_attempts=0;self.start_timer.start()
        self.request('/system_stats',checked)
    def server_finished(self,proc):
        if self.server is proc:self.server=None;self.start_timer.stop();self.start_button.setEnabled(True);self.status.setText('Generator stopped. See the log for details.')
        proc.deleteLater()
    def start_probe(self):
        self.start_attempts+=1
        if self.start_attempts>45:self.start_timer.stop();self.status.setText('Startup is taking longer than expected. Check the log and click Connect.');self.start_button.setEnabled(True);return
        self.connect_backend(quiet=True)
    def busy(self,yes):
        self.pending=yes
        for w in [self.generate,self.models,self.url,self.size,self.steps,self.seed,self.start_button,self.refine_button]:w.setEnabled(not yes)
        self.cancel.setEnabled(yes and self.job_id is not None)
    def refine_prompt(self):
        if self.pending:return
        if self.refine_reply:
            self.refine_reply.abort();return
        if self.studio.reply:
            self.status.setText('Finish the current Qwen chat response first.');return
        original=self.prompt.toPlainText().strip()
        if not original:self.status.setText('Describe an image first, then ask Qwen to refine it.');return
        model=self.studio.model.currentText()
        # Prefer the installed lightweight Qwen for this short, specialized task.
        if self.studio.model.findText('qwen3:1.7b')>=0:model='qwen3:1.7b'
        if not model or not model.rsplit('/',1)[-1].lower().startswith('qwen'):
            self.status.setText('Select an installed Qwen model in the top bar first.');return
        request=QNetworkRequest(QUrl(self.studio.endpoint.text().rstrip('/')+'/api/chat'))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json');request.setTransferTimeout(600000)
        payload={'model':model,'stream':False,'messages':[
            {'role':'system','content':'You refine image prompts for local Stable Diffusion 1.5. Preserve the user’s subject and intent. Make one concise visual prompt, at most 80 words, with concrete composition, lighting, materials, and style only where useful. Do not add unrelated subjects, text, branding, or explanations. Return ONLY the refined prompt. /no_think'},
            {'role':'user','content':original}], 'options':{'num_ctx':4096,'num_predict':2048},'keep_alive':'2m'}
        if 'qwen3' in model:payload['think']=False
        r=self.net.post(request,json.dumps(payload).encode());self.refine_reply=r
        self.generate.setEnabled(False);self.refine_button.setText('Stop prompt refinement');self.status.setText('Refining locally with '+model+'…')
        def finished():
            raw=bytes(r.readAll());self.refine_reply=None;self.generate.setEnabled(True);self.refine_button.setText('Improve description')
            try:
                if r.error()!=QNetworkReply.NetworkError.NoError:raise RuntimeError(r.errorString())
                data=json.loads(raw)
                if data.get('error'):raise RuntimeError(data['error'])
                text=data.get('message',{}).get('content','').split('</think>')[-1].strip()
                if not text or text.startswith('<think>') or data.get('done_reason')=='length' or len(text.split())>120:raise RuntimeError('Qwen returned no finished prompt. Try a shorter description.')
                if self.prompt.toPlainText().strip()!=original:
                    self.log.appendPlainText('Qwen suggestion (your newer prompt was preserved): '+text)
                    self.status.setText('Suggestion is in the log; you edited the prompt while Qwen was working.')
                else:
                    self.prompt.setPlainText(text);self.log.appendPlainText('Original prompt: '+original);self.status.setText('Prompt refined locally. Review it, then Make image.')
            except (ValueError,RuntimeError) as e:self.status.setText('Prompt kept unchanged: '+str(e))
            r.deleteLater()
        r.finished.connect(finished)
    def submit(self):
        if self.pending:return
        if self.studio.reply:self.status.setText('Finish or stop the Qwen chat response before generating an image.');return
        prompt=self.prompt.toPlainText().strip();checkpoint=self.models.currentData()
        if not prompt or not checkpoint:self.status.setText('Enter a prompt and connect to an installed image model.');return
        width,height=[int(x.strip()) for x in self.size.currentText().split('×')];seed=secrets.randbelow(2147483647) if self.seed.value()<0 else self.seed.value();self.metadata={'prompt':prompt,'negative':self.negative.text(),'checkpoint':checkpoint,'width':width,'height':height,'steps':self.steps.value(),'seed':seed};graph=workflow(checkpoint,prompt,self.negative.text(),width,height,self.steps.value(),seed);self.job_url=self.url.text().rstrip('/');self.busy(True);self.status.setText('Preparing image generation…')
        def enqueue():
            self.request('/prompt',queued,{'prompt':graph,'client_id':'qwen-studio-'+uuid.uuid4().hex},base=self.job_url)
        def queued(data,error):
            if error:self.fail('Could not queue image: '+error);return
            if not data.get('prompt_id'):self.fail('ComfyUI rejected the image workflow: '+str(data)[:400]);return
            self.job_id=data['prompt_id'];self.metadata['prompt_id']=self.job_id;self.poll_errors=0;self.cancel.setEnabled(True);self.status.setText('Queued / rendering locally · seed '+str(seed));self.timer.start()
        if self.release.isChecked() and self.studio.model.currentText():
            req=QNetworkRequest(QUrl(self.studio.endpoint.text().rstrip('/')+'/api/generate'));req.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader,'application/json');req.setTransferTimeout(10000)
            r=self.net.post(req,json.dumps({'model':self.studio.model.currentText(),'keep_alive':0}).encode())
            def released():r.deleteLater();enqueue()
            r.finished.connect(released)
        else:enqueue()
    def poll(self):
        if not self.job_id or self.polling:return
        job=self.job_id;self.polling=True
        def got(data,error):
            self.polling=False
            if self.job_id!=job:return
            if error:
                self.poll_errors+=1
                if self.poll_errors>=5:self.timer.stop();self.status.setText('Connection lost. Job ID '+job+' may still be running. Cancel or reconnect before another job.');self.log.appendPlainText(error)
                return
            self.poll_errors=0;row=data.get(job)
            if not row:return
            status=row.get('status',{})
            if status.get('status_str')=='error':self.fail('Generation failed: '+str(status.get('messages','See ComfyUI log'))[:700]);return
            images=[i for output in row.get('outputs',{}).values() for i in output.get('images',[])]
            if images:self.timer.stop();self.fetch_image(images[0],job)
            elif status.get('completed'):self.fail('The generator finished without an image.')
        self.request('/history/'+job,got,base=self.job_url)
    def fetch_image(self,item,job):
        query=QUrlQuery()
        for key in ['filename','subfolder','type']:query.addQueryItem(key,item.get(key,'output' if key=='type' else ''))
        def got(data,error):
            if self.job_id!=job:return
            if error:self.fail('Unable to retrieve generated image: '+error);return
            pix=QPixmap()
            if not pix.loadFromData(data):self.fail('Generator returned an unreadable image.');return
            name='image-'+time.strftime('%Y%m%d-%H%M%S')+'-'+job[:8];path=OUTPUT/(name+'.png')
            try:
                path.write_bytes(data);path.with_suffix('.json').write_text(json.dumps(self.metadata,indent=2))
            except OSError as e:self.fail('Could not save image: '+str(e));return
            self.image_path=path;self.pixmap=pix;self.show_image();self.job_id=None;self.busy(False);self.save_button.setEnabled(True);self.status.setText('Saved '+path.name+' · seed '+str(self.metadata['seed']))
        self.request('/view?'+query.toString(),got,base=self.job_url,binary=True)
    def show_image(self):
        if self.pixmap:self.preview.setPixmap(self.pixmap.scaled(self.preview.size(),Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
    def resizeEvent(self,event):super().resizeEvent(event);self.show_image()
    def fail(self,message):self.timer.stop();self.job_id=None;self.busy(False);self.status.setText(message);self.log.appendPlainText(message)
    def cancel_job(self):
        if not self.job_id:return
        job=self.job_id
        def done(data,error):
            if error:self.status.setText('Could not cancel this image: '+error);return
            if self.job_id!=job:return
            self.timer.stop();self.job_id=None;self.busy(False);self.status.setText('Image job cancelled.')
        self.request('/api/jobs/'+job+'/cancel',done,{},base=self.job_url)
    def save_as(self):
        if not self.image_path:return
        name,_=QFileDialog.getSaveFileName(self,'Save image',str(self.image_path),'PNG image (*.png)')
        if name:
            try:Path(name).write_bytes(self.image_path.read_bytes())
            except OSError as e:QMessageBox.warning(self,'Save failed',str(e))
    def shutdown(self):
        if self.refine_reply:self.refine_reply.abort()
        self.timer.stop();self.start_timer.stop()
        if self.server:self.server.kill();self.server.waitForFinished(3000)
