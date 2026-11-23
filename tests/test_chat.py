import os, tempfile, unittest, json
os.environ['QT_QPA_PLATFORM']='offscreen'
DATA=tempfile.TemporaryDirectory();os.environ['XDG_DATA_HOME']=DATA.name
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from PyQt6.QtCore import Qt
from qwen_studio import Studio
APP=QApplication.instance() or QApplication([])
class Chat(unittest.TestCase):
    def setUp(self):self.s=Studio(False);self.s.new_chat();self.s.show();QTest.qWait(30)
    def tearDown(self):self.s.close();QTest.qWait(20)
    def test_long_complete_answer_and_pause(self):
        v=self.s.transcript;b=v.verticalScrollBar();positions=[];b.valueChanged.connect(positions.append)
        v.append_message('QWEN','Long answer with wrapped content '*20+'\n'+'A complete paragraph.\n'*2000)
        QTest.qWait(100)
        self.assertEqual(b.value(),b.maximum());self.assertTrue(all(a<=z for a,z in zip(positions,positions[1:])),positions)
        v.pause();b.setValue(b.maximum()//2);position=b.value()
        v.append_message('TOOL','Result\n'*300);QTest.qWait(40);self.assertEqual(b.value(),position)
        self.s.tabs.setCurrentIndex(1);QTest.qWait(20);self.s.tabs.setCurrentIndex(0);QTest.qWait(40);self.assertEqual(b.value(),position)
        v.latest();QTest.qWait(80);self.assertEqual(b.value(),b.maximum())
        QTest.keyClick(v,Qt.Key.Key_PageUp);QTest.qWait(30);self.assertFalse(v.follow)
        QTest.keyClick(v,Qt.Key.Key_End,Qt.KeyboardModifier.ControlModifier);QTest.qWait(50);self.assertTrue(v.follow)
    def test_stream_tokens_and_reasoning_not_displayed(self):
        before=self.s.transcript.toPlainText();bar=self.s.transcript.verticalScrollBar();positions=[];bar.valueChanged.connect(positions.append)
        self.s.answer='';self.s.reasoning='';self.s.calls=[];self.s.saw_done=False
        for i in range(2000):
            self.s.consume(json.dumps({'message':{'content':'token\n','thinking':'reasoning\n'}}).encode())
        QTest.qWait(20)
        self.assertEqual(self.s.transcript.toPlainText(),before);self.assertEqual(positions,[])
        self.assertEqual(self.s.answer.count('token'),2000);self.assertEqual(self.s.reasoning.count('reasoning'),2000)
    def test_leader_clipboard_result_uses_hidden_inbox(self):
        s=self.s;s.turn_running=True;s.cancelled=False;s.turn_messages=[];s.awaiting_plan=False
        s.execute_next_tool=lambda:None
        answer='A private leader plan with complete copied text.'
        s.tool_result('ask_leader',{'provider':'claude','answer':answer,'via':'desktop'})
        self.assertEqual(s.leader_inbox.toPlainText(),answer)
        self.assertTrue(s.leader_inbox.isHidden())
        self.assertNotIn(answer,s.transcript.toPlainText())
        self.assertEqual(json.loads(s.turn_messages[-1]['content'])['answer'],answer)
        self.assertNotIn('hidden',s.turn_messages[-1])
        s.render();self.assertNotIn(answer,s.transcript.toPlainText())
        self.assertEqual(s.leader_inbox.toPlainText(),answer)
        s.turn_running=False;s.new_chat();self.assertEqual(s.leader_inbox.toPlainText(),'')
    def test_workspace_history(self):
        default=self.s.workspace.itemData(0);self.s.workspace.setCurrentIndex(1)
        self.assertEqual(self.s.current()['workspace'],self.s.workspace.itemData(1))
        self.s.workspace.setCurrentIndex(0);self.assertEqual(self.s.current()['workspace'],default)
        self.s.select_chat(1);self.assertEqual(self.s.project.text(),self.s.workspace.itemData(1))
if __name__=='__main__':unittest.main()
