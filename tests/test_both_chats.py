import unittest,json
from test_chat import APP
from qwen_studio import Studio
class BothChats(unittest.TestCase):
    def setUp(self):self.s=Studio(False);self.s.new_chat();self.s.show()
    def tearDown(self):self.s.close()
    def test_two_distinct_plans_feed_qwen_and_remain_hidden(self):
        s=self.s;s.turn_running=True;s.cancelled=False;s.turn_messages=[];s.awaiting_plan=True
        s.plan_question='Plan a task';s.plan_providers=['chatgpt','claude'];s.leader_results={}
        requested=[];rounds=[];s.call_leader=lambda name,args:requested.append(args['provider']);s.request_round=lambda:rounds.append(True)
        s.append_message({'role':'user','content':'Task for both chats'})
        s.start_next_plan();self.assertEqual(requested,['chatgpt'])
        s.tool_result('ask_leader',{'provider':'chatgpt','answer':'First complete plan from ChatGPT.'})
        self.assertEqual(requested,['chatgpt','claude']);self.assertEqual(rounds,[])
        s.tool_result('ask_leader',{'provider':'claude','answer':'Second complete plan from Claude.'})
        self.assertEqual(rounds,[True]);self.assertFalse(s.awaiting_plan)
        self.assertEqual(set(s.leader_results),{'chatgpt','claude'})
        self.assertIn('First complete plan',s.leader_inbox.toPlainText());self.assertIn('Second complete plan',s.leader_inbox.toPlainText())
        self.assertNotIn('complete plan',s.transcript.toPlainText())
        self.assertEqual(len([m for m in s.turn_messages if m['role']=='tool']),2)
        s.render();self.assertIn('Second complete plan',s.leader_inbox.toPlainText());self.assertNotIn('complete plan',s.transcript.toPlainText())
        s.turn_running=False
    def test_manual_copy_recovery_uses_selected_provider(self):
        s=self.s;s.turn_running=True;s.cancelled=False;s.waiting_for_leader=True;s.plan_provider='claude'
        received=[];s.tool_result=lambda name,result:received.append(result)
        APP.clipboard().setText('A complete copied plan for the selected task.')
        s.use_copied_leader_reply()
        self.assertEqual(received[0]['provider'],'claude');self.assertEqual(received[0]['via'],'user clipboard');self.assertFalse(s.waiting_for_leader)
        s.turn_running=False
if __name__=='__main__':unittest.main()
