import unittest, tempfile, os, hashlib
from pathlib import Path
from workspace_tools import WorkspaceTools

class Files(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.fs=WorkspaceTools(self.root)
    def tearDown(self):self.fs.close();self.tmp.cleanup()
    def call(self,name,**args):return self.fs.dispatch(name,args)
    def test_create_read_search_edit_approval_and_stale_hash(self):
        self.assertTrue(self.call('create_project_file',file='a.txt',content='needle')['written'])
        self.assertIn('error',self.call('create_project_file',file='a.txt',content='overwrite'))
        r=self.call('read_project_file',file='a.txt');self.assertEqual(r['sha256'],hashlib.sha256(b'needle').hexdigest())
        self.assertEqual(self.call('search_project_files',term='needle')['hits'][0]['file'],'a.txt')
        self.assertIn('error',self.call('edit_project_file',file='a.txt',content='changed',expected_sha256=r['sha256']))
        self.assertEqual((self.root/'a.txt').read_text(),'needle')
        self.fs.approve=lambda *a:True
        self.assertIn('error',self.call('edit_project_file',file='a.txt',content='changed',expected_sha256='0'*64))
        self.assertTrue(self.call('edit_project_file',file='a.txt',content='changed',expected_sha256=r['sha256'])['written'])
        self.assertEqual((self.root/'a.txt').read_text(),'changed')
    def test_chunked_read_and_targeted_edit(self):
        original='a'*7000+'TARGET'+'b'*7000
        (self.root/'big').write_text(original)
        first=self.call('read_project_file',file='big');self.assertTrue(first['truncated']);self.assertEqual(len(first['content']),6000)
        second=self.call('read_project_file',file='big',offset=first['next_offset']);self.assertIn('TARGET',second['content'])
        self.assertEqual(first['sha256'],second['sha256']);self.fs.approve=lambda *args:True
        r=self.call('edit_project_file',file='big',old_text='TARGET',new_text='EDITED',expected_sha256=first['sha256'])
        self.assertTrue(r['written']);self.assertEqual((self.root/'big').read_text(),original.replace('TARGET','EDITED'))
        self.assertIn('error',self.call('read_project_file',file='big',offset=-1))
    def test_change_during_approval(self):
        self.call('create_project_file',file='a',content='old');r=self.call('read_project_file',file='a')
        def approve(*a):(self.root/'a').write_text('concurrent');return True
        self.fs.approve=approve
        self.assertIn('error',self.call('edit_project_file',file='a',content='new',expected_sha256=r['sha256']))
        self.assertEqual((self.root/'a').read_text(),'concurrent')
    def test_escape_symlinks_and_hardlinks(self):
        with tempfile.TemporaryDirectory() as outside:
            secret=Path(outside)/'ordinary.txt';secret.write_text('outside')
            (self.root/'link').symlink_to(outside,target_is_directory=True)
            (self.root/'filelink').symlink_to(secret);os.link(secret,self.root/'hardlink')
            for file in ('../ordinary.txt',str(secret),'link/ordinary.txt','filelink','hardlink','a/../ordinary.txt'):
                with self.subTest(file=file):self.assertIn('error',self.call('read_project_file',file=file))
            self.assertIn('error',self.call('create_project_file',file='link/new',content='bad'))
            self.assertEqual(self.call('search_project_files',term='outside')['hits'],[])
            self.assertEqual(self.call('list_project_files')['entries'],[])
            self.assertFalse((Path(outside)/'new').exists())
            with self.assertRaises(OSError):WorkspaceTools(self.root/'link')
    def test_parent_moved_outside_during_approval(self):
        (self.root/'folder').mkdir();(self.root/'folder/a').write_text('original')
        r=self.call('read_project_file',file='folder/a')
        with tempfile.TemporaryDirectory() as outside:
            def approve(*args):
                (self.root/'folder').rename(Path(outside)/'moved');return True
            self.fs.approve=approve
            self.assertIn('error',self.call('edit_project_file',file='folder/a',content='changed',expected_sha256=r['sha256']))
            self.assertEqual((Path(outside)/'moved/a').read_text(),'original')
    def test_credentials_and_special_files(self):
        for file in ('.env','.env.local','private/config.json','.codex/auth.json','credentials.json','secret.pem'):
            self.assertIn('error',self.call('create_project_file',file=file,content='hidden'))
        (self.root/'normal.txt').write_text('api_key = "sk-'+('a'*30)+'"')
        self.assertIn('error',self.call('read_project_file',file='normal.txt'))
        self.assertEqual(self.call('search_project_files',term='sk-')['hits'],[])
        (self.root/'large').write_bytes(b'a'*200001);os.mkfifo(self.root/'pipe')
        for name in ('large','pipe'):
            self.assertIn('error',self.call('read_project_file',file=name))
        self.assertIn('error',self.call('create_project_file',file='bad',content='a\0b'))
    def test_directories_and_invalid_dispatch(self):
        self.assertTrue(self.call('make_project_directory',directory='folder')['created'])
        self.assertTrue(self.call('create_project_file',file='folder/a',content='ok')['written'])
        self.assertEqual(self.call('list_project_files',directory='folder')['entries'][0]['name'],'a')
        self.assertIn('error',self.call('delete_project_file',file='folder/a'))
        self.assertIn('error',self.call('read_project_file',file=42))
        self.assertIn('error',self.call('read_project_file',file='folder/a',approved='true'))

if __name__=='__main__':unittest.main()
