import tempfile
import tkinter as tk
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock, patch

from mira_windows.app import App


class UIStateTests(unittest.TestCase):
    def test_relogin_blocks_capture_and_recovery_until_authentication_finishes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as directory:
            root=tk.Tk();root.withdraw()
            try:
                app=App(root,Path(directory),smoke=True)
                app.client=Mock();app.set_busy(False)
                with patch('mira_windows.app.threading.Thread'):
                    app.login()
                self.assertTrue(app.busy)
                self.assertEqual(str(app.start_button['state']),'disabled')
                self.assertEqual(str(app.recover_button['state']),'disabled')
            finally:root.destroy()

    def test_closing_after_clean_stop_preserves_finish_flags(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as directory:
            root=tk.Tk();root.withdraw()
            app=App(root,Path(directory),smoke=True)
            item=app.vault.create('https://example.test','owner','Takim')
            app.vault.update(item['id'],state='STOPPED',partial=False,
                finish_spec={'segment_count':0,'partial':False})
            stopped=threading.Event();stopped.set()
            app.sid=item['id'];app.capture=Mock(stop_event=stopped,fault=None)
            app.busy=True
            with patch('mira_windows.app.messagebox.askyesno',return_value=True):app.close()
            saved=app.vault.load(item['id'])
            self.assertFalse(saved['partial'])
            self.assertEqual(saved['finish_spec'],{'segment_count':0,'partial':False})

    def test_successful_relogin_retires_previous_client_outside_the_tk_thread(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as directory:
            root=tk.Tk();root.withdraw()
            try:
                app=App(root,Path(directory),smoke=True)
                previous=Mock();app.client=previous
                replacement=Mock(user={'id':'owner','email':'test@example.test'},base_url='https://example.test')
                app.notify('login',replacement)
                with patch('mira_windows.app.threading.Thread') as thread:app.poll()
                previous.close.assert_not_called()
                self.assertEqual(thread.call_args.kwargs['target'],previous.close)
                self.assertIs(app.client,replacement)
            finally:root.destroy()
