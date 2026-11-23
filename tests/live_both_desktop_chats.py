"""Actual Studio Send -> desktop MCP replies from both apps -> hidden inbox -> local Qwen."""
import sys,time,json,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
import qwen_studio
scratch=tempfile.TemporaryDirectory();qwen_studio.DATA=Path(scratch.name)/'app';qwen_studio.DATA.mkdir()
app=QApplication([]);s=qwen_studio.Studio(False);s.show()
workspace=Path(scratch.name)/'workspace';workspace.mkdir();s.workspace.addItem('Connection test',str(workspace));s.workspace.setCurrentIndex(s.workspace.count()-1)
s.model.clear();s.model.addItem('qwen3:1.7b');s.leader_choice.setCurrentIndex(s.leader_choice.findData('both'));s.leaders_enabled.setChecked(True)
results=[];original=s.append_message

def record(message):
    if message['role']=='tool' and message.get('tool_name')=='ask_leader':
        value=json.loads(message['content']);results.append(value)
        print(json.dumps({'provider':value.get('provider'),'reply_received':bool(value.get('answer')),'via':value.get('via'),'error':value.get('error')}),flush=True)
    original(message)
s.append_message=record
s.prompt.setPlainText('Connection test only. Ask both leaders for a very short plan with the words LEADER_READY and their own name. After both replies arrive, respond BOTH_LEADERS_CONNECTED and name ChatGPT and Claude. Do not create/read/edit files, execute code or deploy anything. Only test leader communication.')
QTest.mouseClick(s.send_btn,Qt.MouseButton.LeftButton);deadline=time.monotonic()+360
while s.turn_running and time.monotonic()<deadline:
    QTest.qWait(50)
    if getattr(s,'waiting_for_leader',False):break
completed=not s.turn_running
answers={r.get('provider'):r['answer'] for r in results if isinstance(r.get('answer'),str)}
final=(s.current()['messages'][-1].get('content','') if completed else '')
inbox=s.leader_inbox.toPlainText();transcript=s.transcript.toPlainText()
report={'leader_call_count':len(results),'leader_errors':[r['error'] for r in results if 'error' in r],'real_gui_send':True,'desktop_only':True,'received_providers':sorted(answers),'transport':{r.get('provider'):r.get('via') for r in results},'hidden_inbox_has_both':all(a in inbox for a in answers.values()) and len(answers)==2,'full_plans_hidden':all(a not in transcript for a in answers.values()),'local_qwen_finished':completed,'final_answer':final,'status':s.activity.text(),'needs_manual_copy':getattr(s,'waiting_for_leader',False)}
report['passed']=set(answers)=={'chatgpt','claude'} and report['hidden_inbox_has_both'] and report['full_plans_hidden'] and completed and 'BOTH_LEADERS_CONNECTED' in final
output=Path(sys.argv[1]);output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if s.turn_running:s.stop();QTest.qWait(1200)
s.close()
if not report['passed']:raise SystemExit(1)
