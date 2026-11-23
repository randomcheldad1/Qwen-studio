import unittest,tempfile,time
from pathlib import Path
from test_chat import APP
from PyQt6.QtWidgets import QWidget,QComboBox,QLineEdit,QMessageBox
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtTest import QTest
from sftp_tab import SftpTab
from test_sftp_integration import LocalServer
class StudioFixture(QWidget):
    def __init__(self,path):super().__init__();self.workspace=QComboBox();self.project=QLineEdit(str(path))
class Panel(unittest.TestCase):
    def test_connect_upload_and_download_real_buttons(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);local=base/'local';local.mkdir();remote=base/'remote';remote.mkdir();(remote/'site').mkdir()
            (local/'upload.txt').write_text('Uploaded from the actual SFTP panel.');(remote/'site/download.txt').write_text('Downloaded through the SFTP panel.')
            server=LocalServer(remote);studio=StudioFixture(local);panel=SftpTab(studio,base/'appdata');panel.show()
            def wait():
                deadline=time.monotonic()+15
                while panel.job and time.monotonic()<deadline:QTest.qWait(20)
                self.assertIsNone(panel.job,panel.status.text())
            try:
                panel.host.setText('127.0.0.1');panel.port.setValue(server.port);panel.user.setText('tester');panel.password.setText('synthetic-password');panel.remote_root.setText('/site')
                def trust():
                    modal=APP.activeModalWidget()
                    if isinstance(modal,QMessageBox):modal.button(QMessageBox.StandardButton.Yes).click()
                timer=QTimer();timer.timeout.connect(trust);timer.start(20)
                QTest.mouseClick(panel.connect_button,Qt.MouseButton.LeftButton);wait();timer.stop()
                self.assertTrue(panel.connected,panel.status.text());self.assertEqual(panel.password.text(),'')
                self.assertTrue(panel.known_hosts.exists())
                for i in range(panel.local_list.count()):
                    if panel.local_list.item(i).text()=='upload.txt':panel.local_list.setCurrentRow(i)
                QTest.mouseClick(panel.upload_button,Qt.MouseButton.LeftButton);wait()
                # Upload completion triggers one listing refresh.
                if panel.job:wait()
                self.assertEqual((remote/'site/upload.txt').read_text(),'Uploaded from the actual SFTP panel.')
                for i in range(panel.remote_list.count()):
                    if panel.remote_list.item(i).text()=='download.txt':panel.remote_list.setCurrentRow(i)
                QTest.mouseClick(panel.download_button,Qt.MouseButton.LeftButton);wait()
                self.assertEqual((local/'download.txt').read_text(),'Downloaded through the SFTP panel.')
                QTest.mouseClick(panel.disconnect_button,Qt.MouseButton.LeftButton);self.assertFalse(panel.connected)
            finally:
                panel.disconnect()
                if panel.job:panel.job.wait(3000);QTest.qWait(30)
                panel.close();studio.close();server.close()
if __name__=='__main__':unittest.main()
