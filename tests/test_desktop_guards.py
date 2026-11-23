import unittest
from desktop_leaders import extract_reply
class DesktopGuards(unittest.TestCase):
    def test_exact_task_reply(self):
        self.assertEqual(extract_reply('QWEN_PLAN_abc\nCreate a file and verify its bytes.\nQWEN_END_abc','abc'),'Create a file and verify its bytes.')
    def test_window_copy_returns_only_current_task(self):
        value='UI label\nBegin your reply with QWEN_PLAN_abc on its own line.\nQWEN_PLAN_abc\nThe current task response is complete.\nQWEN_END_abc\nOther UI label'
        self.assertEqual(extract_reply(value,'abc'),'The current task response is complete.')
        self.assertIsNone(extract_reply(value+'\nQWEN_PLAN_abc','abc'))
    def test_wrong_task_partial_and_prompt_rejected(self):
        for text in ['QWEN_PLAN_other\nCreate a file and verify its bytes.\nQWEN_END_other','QWEN_PLAN_abc\nPartial answer','Begin with QWEN_PLAN_abc on its own line. End with QWEN_END_abc. This is a prompt, not a reply.']:
            self.assertIsNone(extract_reply(text,'abc'))
if __name__=='__main__':unittest.main()
