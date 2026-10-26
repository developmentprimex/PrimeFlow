import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import threading

import httpx
import numpy as np

from mira_windows.audio import Capture, TimelineMixer, wav_bytes
from mira_windows.storage import Vault, protect, unprotect
from mira_windows.client import PrimeFlowClient, safe_base_url
from mira_windows.controller import Controller


class AudioTests(unittest.TestCase):
    def test_mix_resamples_both_sources_without_clipping_and_keeps_short_tail(self):
        mixer = TimelineMixer()
        mixer.push('system', np.full((44100, 2), .8), 44100, 0)
        mixer.push('mic', np.full((48000, 1), .8), 48000, 0)
        chunks = list(mixer.flush(1, final=True))
        self.assertEqual(len(chunks), 1)
        start, end, pcm = chunks[0]
        self.assertEqual((start, end, pcm.shape), (0, 1000, (48000, 2)))
        self.assertLessEqual(np.max(np.abs(pcm)), 32767)
        self.assertGreater(np.mean(pcm), 24000)
        with wave.open(io.BytesIO(wav_bytes(pcm)), 'rb') as stream:
            self.assertEqual((stream.getnchannels(), stream.getframerate(), stream.getnframes()), (2, 48000, 48000))

    def test_silence_advances_timeline_and_long_capture_releases_chunks(self):
        mixer = TimelineMixer()
        self.assertEqual(list(mixer.flush(9)), [])
        chunks = list(mixer.flush(20))
        self.assertEqual([(s, e) for s, e, _ in chunks], [(0, 10000), (10000, 20000)])
        self.assertFalse(np.any(chunks[0][2]))
        self.assertEqual(mixer.buffered_frames, 0)

    def test_late_audio_is_reported_instead_of_silently_lost(self):
        mixer = TimelineMixer(); list(mixer.flush(10))
        with self.assertRaises(ValueError):
            mixer.push('mic', np.ones((480, 1)), 48000, 1)

    def test_final_flush_emits_incrementally_without_allocating_hours_of_audio(self):
        mixer=TimelineMixer();chunks=mixer.flush(14400,final=True)
        self.assertIs(iter(chunks),chunks)
        self.assertEqual(next(chunks)[1],10000)
        self.assertEqual(mixer.cursor,480000)
        self.assertEqual(mixer.buffered_frames,0)

    def test_suspend_gap_stops_without_synthesizing_missing_hours(self):
        import queue
        capture=object.__new__(Capture)
        capture.started=0;capture.last_checked=1;capture.fault=None
        capture.stop_event=threading.Event();capture.events=queue.Queue()
        capture.mixer=TimelineMixer();capture.streams=[Mock()]
        capture.on_chunk=Mock()
        with patch('mira_windows.audio.time.monotonic',return_value=3600):capture._run()
        self.assertTrue(capture.stop_event.is_set())
        self.assertIn('ndërpre',capture.fault)
        self.assertLessEqual(capture.mixer.cursor,48000)

    def test_suspend_during_queue_wait_is_checked_before_advancing_clock(self):
        import queue
        capture=object.__new__(Capture)
        capture.started=0;capture.last_checked=1;capture.fault=None
        capture.stop_event=threading.Event();capture.events=queue.Queue()
        capture.mixer=TimelineMixer();capture.streams=[Mock()];capture.on_chunk=Mock()
        with patch('mira_windows.audio.time.monotonic',side_effect=[1.1,3600,3600]):capture._run()
        self.assertIn('ndërpre',capture.fault)
        self.assertLessEqual(capture.mixer.cursor,48000)


class StorageTests(unittest.TestCase):
    def test_windows_dpapi_roundtrip_hides_plaintext(self):
        raw = b'private call transcript'
        sealed = protect(raw)
        self.assertNotIn(raw, sealed)
        self.assertEqual(unprotect(sealed), raw)
        with self.assertRaises(OSError):unprotect(sealed[:-5]+b'bad!!')

    def test_spool_survives_restart_and_deletes_audio_only_after_receipt(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault = Vault(Path(temp)); item = vault.create('https://primeflow.example', 'owner', 'Takim')
            vault.append(item['id'], wav_bytes(np.zeros((480, 2), dtype=np.int16)), 0, 10)
            restored = Vault(Path(temp)).load(item['id'])
            self.assertEqual(restored['segment_count'], 1)
            self.assertEqual(len(vault.pending(item['id'])), 1)
            vault.ack(item['id'], 0, 'Biseda.')
            self.assertEqual(vault.pending(item['id']), [])
            self.assertEqual(vault.load(item['id'])['transcript'], ['Biseda.'])
            self.assertNotIn(b'Biseda.', (Path(temp)/item['id']/'session.bin').read_bytes())

    def test_queue_limit_does_not_claim_a_segment_was_persisted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault = Vault(Path(temp), max_bytes=10); item = vault.create('https://example.test', 'owner', 'Test')
            with self.assertRaises(OSError):vault.append(item['id'], b'x'*11, 0, 10)
            self.assertEqual(vault.load(item['id'])['segment_count'], 0)

    def test_orphaned_chunk_is_recovered_after_manifest_write_failure(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault=Vault(Path(temp));item=vault.create('https://example.test','owner','Test')
            save=vault.save;vault.save=Mock(side_effect=OSError('disk failure'))
            with self.assertRaises(OSError):vault.append(item['id'],b'wav',0,10)
            vault.save=save
            self.assertEqual(vault.load(item['id'])['segments'],[[0,10]])
            self.assertEqual(vault.audio(item['id'],0),b'wav')

    def test_recovery_removes_audio_already_acknowledged_in_the_manifest(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault=Vault(Path(temp));item=vault.create('https://example.test','owner','Test')
            vault.append(item['id'],b'wav',0,10)
            # Crash after saving receipt, before unlinking its encrypted audio.
            vault.update(item['id'],transcript=['Po'])
            path=vault.directory(item['id'])/'000000.bin'
            self.assertTrue(path.exists())
            self.assertEqual(vault.load(item['id'])['transcript'],['Po'])
            self.assertFalse(path.exists())


class ControllerTests(unittest.TestCase):
    def test_receipt_must_confirm_done_before_local_audio_is_deleted(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault=Vault(Path(temp));item=vault.create('https://example.test','owner','Test')
            vault.append(item['id'],b'wav',0,10);vault.update(item['id'],state='STOPPED')
            client=SimpleNamespace(user={'id':'owner'},base_url='https://example.test',create=Mock(),
                upload=Mock(return_value={'status':'PROCESSING','sequence':0,'transcript':''}),finish=Mock())
            events=[];controller=Controller(vault,client,lambda k,v:events.append((k,v)))
            controller._sync(item['id'],None)
            self.assertEqual(vault.pending(item['id']),[0])
            client.finish.assert_not_called()

    def test_offline_recovery_uploads_in_order_and_finishes_once(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault=Vault(Path(temp));item=vault.create('https://example.test','owner','Test')
            for i in range(2):vault.append(item['id'],b'wav',i*10,(i+1)*10)
            vault.update(item['id'],state='STOPPED',partial=True)
            client=SimpleNamespace(user={'id':'owner'},base_url='https://example.test',create=Mock(),
                upload=Mock(side_effect=lambda _,seq,wav:{'status':'DONE','sequence':seq,'transcript':str(seq)}),
                finish=Mock(return_value={'status':'DONE','notes':'Notes','note_id':'note-id'}))
            controller=Controller(vault,client,lambda *args:None);controller._sync(item['id'],None)
            self.assertEqual([c.args[1] for c in client.upload.call_args_list],[0,1])
            self.assertEqual(vault.load(item['id'])['state'],'DONE')
            self.assertEqual(vault.load(item['id'])['note_id'],'note-id')
            self.assertTrue(client.finish.call_args.args[0]['partial'])
            client.finish.assert_called_once()

    def test_different_account_cannot_upload_recovered_audio(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'tmp') as temp:
            vault=Vault(Path(temp));item=vault.create('https://example.test','owner','Test')
            client=SimpleNamespace(user={'id':'someone-else'},base_url='https://example.test',create=Mock())
            controller=Controller(vault,client,lambda *args:None);controller._sync(item['id'],None)
            client.create.assert_not_called()


class ClientTests(unittest.TestCase):
    def test_login_uses_api_host_and_keeps_frontend_host_for_px_notes(self):
        def handle(request):
            if request.url.path=='/api/auth/login':return httpx.Response(200,json={'access_token':'test'})
            if request.url.path=='/api/auth/me':return httpx.Response(200,json={'id':'owner'})
            return httpx.Response(200,json={'enabled':True,'frontend_url':'https://primeflow.example'})
        client=PrimeFlowClient('https://api.example',transport=httpx.MockTransport(handle))
        client.login('user@example.test','not-saved')
        self.assertEqual(client.base_url,'https://api.example')
        self.assertEqual(client.frontend_url,'https://primeflow.example')

    def test_finish_retries_use_the_immutable_saved_arguments(self):
        bodies=[]
        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200,json={'status':'DONE'})
        client=PrimeFlowClient('https://example.test',transport=httpx.MockTransport(handle))
        client.finish({'id':'session','segment_count':3,'partial':True,
            'finish_spec':{'segment_count':3,'partial':False}})
        self.assertEqual(bodies,[{'segment_count':3,'partial':False}])

    def test_rejects_insecure_remote_and_embedded_credentials(self):
        for url in ['http://example.test', 'https://user:password@example.test', 'https://example.test/?secret=x', 'file:///x']:
            with self.assertRaises(ValueError):safe_base_url(url)
        self.assertEqual(safe_base_url('https://example.test/'), 'https://example.test')
        self.assertEqual(safe_base_url('http://127.0.0.1:8000'), 'http://127.0.0.1:8000')

    def test_expired_token_refreshes_once_without_sending_password_again(self):
        calls = []
        def handle(request):
            calls.append(request)
            if request.url.path == '/api/auth/refresh':return httpx.Response(200, json={'access_token':'fresh'})
            if request.headers.get('Authorization') == 'Bearer fresh':return httpx.Response(200, json={'enabled':True})
            return httpx.Response(401)
        client = PrimeFlowClient('https://example.test', transport=httpx.MockTransport(handle)); client.token = 'expired'
        self.assertTrue(client.call('GET', '/mira-desktop/capabilities')['enabled'])
        self.assertEqual(len(calls), 3)
        self.assertFalse(any(b'password' in r.content for r in calls))

    def test_redirect_does_not_forward_session_to_another_host(self):
        calls = []
        def handle(request):
            calls.append(request)
            return httpx.Response(307, headers={'Location':'https://other.test/steal'})
        client = PrimeFlowClient('https://example.test', transport=httpx.MockTransport(handle)); client.token = 'token'
        with self.assertRaises(Exception):client.call('GET', '/mira-desktop/capabilities')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':unittest.main()
