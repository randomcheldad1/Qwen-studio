"""One Qt auto-follow controller; model tokens are never painted until completion."""
from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QTextBrowser

class ChatView(QTextBrowser):
    def __init__(self):
        super().__init__()
        self.follow=True
        self.generation=0
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.setInterval(0)
        self.timer.timeout.connect(self.apply_follow)
        self.viewport().installEventFilter(self)
        self.installEventFilter(self)
        bar=self.verticalScrollBar()
        bar.sliderPressed.connect(self.pause)
        bar.sliderReleased.connect(self.user_scrolled)
        bar.actionTriggered.connect(self.scroll_action)
        bar.rangeChanged.connect(self.schedule)
        self.on_follow_changed=lambda value:None
    def pause(self):
        self.follow=False;self.timer.stop();self.on_follow_changed(False)
    def user_scrolled(self):
        bar=self.verticalScrollBar()
        self.follow=bar.maximum()-bar.value()<=40
        self.on_follow_changed(self.follow)
        if self.follow:self.schedule()
    def scroll_action(self,action):
        # A queued check runs after the scrollbar's user action has taken effect.
        self.pause()
        if action not in (2,4,5):self.queue_user_check()
    def eventFilter(self,obj,event):
        if event.type()==QEvent.Type.Wheel:
            if event.angleDelta().y()>0:self.pause()
            elif event.angleDelta().y()<0:self.queue_user_check()
        elif event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Up,Qt.Key.Key_PageUp,Qt.Key.Key_Home):self.pause()
        elif event.type()==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_End and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.latest();return True
        elif event.type()==QEvent.Type.KeyPress and event.key() in (Qt.Key.Key_Down,Qt.Key.Key_PageDown,Qt.Key.Key_End):self.queue_user_check()
        return super().eventFilter(obj,event)
    def queue_user_check(self):
        generation=self.generation
        QTimer.singleShot(0,lambda:self.user_scrolled() if generation==self.generation else None)
    def schedule(self,*args):
        if self.follow and self.isVisible() and not self.timer.isActive():self.timer.start()
    def apply_follow(self):
        if self.follow and self.isVisible():
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
    def latest(self):
        self.follow=True;self.on_follow_changed(True);self.schedule()
    def append_message(self,label,text):
        # Insert with a detached cursor: never move the view's cursor or rebuild its document.
        position=self.verticalScrollBar().value()
        cursor=QTextCursor(self.document());cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(('\n\n' if not self.document().isEmpty() else '')+label+'\n'+text)
        if self.follow:self.schedule()
        else:self.verticalScrollBar().setValue(position)
    def replace_messages(self,messages):
        self.generation+=1;self.timer.stop();self.clear()
        for label,text in messages:self.append_message(label,text)
        self.latest()
    def hideEvent(self,event):
        self.generation+=1;self.timer.stop();super().hideEvent(event)
    def showEvent(self,event):
        super().showEvent(event);self.schedule()
