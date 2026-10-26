"""Sequential durable uploads, independent of the audio callback thread."""
import threading
import time

import httpx

from .client import APIError


class Controller:
    def __init__(self, vault, client, notify):
        self.vault,self.client,self.notify = vault,client,notify
        self.cancel = threading.Event();self.thread = None

    def run(self, sid, capture=None):
        if self.thread and self.thread.is_alive():raise ValueError('Një takim po përpunohet.')
        self.cancel.clear()
        self.thread = threading.Thread(target=self._sync,args=(sid,capture),daemon=True,name='Mira upload')
        self.thread.start()

    def _sync(self, sid, capture):
        failures = 0
        try:
            item = self.vault.load(sid)
            if item['owner'] != str(self.client.user['id']) or item['base_url'] != self.client.base_url:
                raise ValueError('Hyr me të njëjtën llogari dhe server që e nisi këtë takim.')
            created = capture is not None
            while not self.cancel.is_set():
                try:
                    if not created:
                        self.client.create(item);created = True
                    if capture and capture.stop_event.is_set() and item['state']=='CAPTURING':
                        capture.stop()
                        item = self.vault.update(sid,state='STOPPED',partial=bool(capture.fault),error=capture.fault or '')
                        self.notify('stopped',item)
                    item = self.vault.load(sid)
                    pending = self.vault.pending(sid)
                    if pending:
                        seq = pending[0]
                        receipt = self.client.upload(item,seq,self.vault.audio(sid,seq))
                        if receipt.get('status')!='DONE' or receipt.get('sequence')!=seq:
                            raise ValueError('PrimeFlow nuk e konfirmoi segmentin. Audioja mbetet e ruajtur lokalisht.')
                        self.vault.ack(sid,seq,receipt.get('transcript',''))
                        self.notify('progress',self.vault.load(sid));failures = 0
                        continue
                    if item['state'] != 'CAPTURING':
                        if not item.get('finish_spec'):
                            item=self.vault.update(sid,finish_spec={'segment_count':item['segment_count'],'partial':item['partial']})
                        self.notify('status','Po përgatis shënimet…')
                        result = self.client.finish(item)
                        if result.get('status') not in ('DONE','SAVED','READY'):
                            raise APIError(409,'Shënimet po përgatiten. Do të provoj përsëri.')
                        self.vault.update(sid,state='DONE',notes=result.get('notes') or '',
                            note_id=result.get('note_id'),error='')
                        self.notify('done',self.vault.load(sid));return
                    self.cancel.wait(.25)
                except (httpx.HTTPError,APIError) as exc:
                    if isinstance(exc,APIError) and exc.status not in (408,409,429,500,502,503,504):raise
                    failures += 1
                    self.notify('status','Lidhja ose përpunimi po vonohet. Audioja pret e enkriptuar në këtë kompjuter.')
                    self.cancel.wait(min(30,2**min(failures,5)))
        except Exception as exc:
            if capture and not capture.stop_event.is_set():capture.stop()
            try:
                item = self.vault.load(sid)
                self.vault.update(sid,state='STOPPED',partial=item['partial'] or bool(capture and capture.fault),error=str(exc))
            except OSError:pass
            self.notify('error',str(exc))

    def stop_sync(self):self.cancel.set()
