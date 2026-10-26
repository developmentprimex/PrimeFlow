"""Current-user DPAPI queue. Credentials never enter this store."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import struct
import threading
import uuid


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data, decrypt=False):
    if os.name != 'nt':raise OSError('Mira kërkon Windows për mbrojtjen e të dhënave.')
    source_buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data, target.size)
    finally:kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


def protect(data):return _crypt(data)
def unprotect(data):return _crypt(data, True)


class Vault:
    def __init__(self, root=None, max_bytes=512*1024*1024):
        self.root = Path(root or Path(os.environ['LOCALAPPDATA'])/'PrimeFlow'/'Mira')
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes
        self.lock = threading.RLock()

    def directory(self, sid):return self.root/str(uuid.UUID(sid))

    def _write(self, path, raw):
        encrypted = protect(raw)
        temporary = path.with_suffix('.tmp')
        with temporary.open('wb') as handle:
            handle.write(encrypted);handle.flush();os.fsync(handle.fileno())
        os.replace(temporary, path)

    def save(self, item):
        with self.lock:self._write(self.directory(item['id'])/'session.bin', json.dumps(item, ensure_ascii=False).encode())

    def create(self, base_url, owner, title):
        with self.lock:
            sid = str(uuid.uuid4());self.directory(sid).mkdir()
            item = dict(id=sid, base_url=base_url, owner=str(owner), title=title,
                        segment_count=0, transcript=[], state='CAPTURING', partial=False,
                        segments=[], notes='', note_id=None, error='')
            self.save(item);return item

    def load(self, sid):
        with self.lock:
            item = json.loads(unprotect((self.directory(sid)/'session.bin').read_bytes()))
            # Recover the narrow crash window between durable audio and manifest.
            while (path := self.directory(sid)/f"{item['segment_count']:06d}.bin").exists():
                raw = unprotect(path.read_bytes());start,end = struct.unpack('!QQ', raw[:16])
                item['segments'].append([start,end]);item['segment_count'] += 1
            for path in self.directory(sid).glob('??????.bin'):
                if path.stem.isdigit() and int(path.stem)<len(item['transcript']):
                    try:path.unlink()
                    except OSError:pass  # The receipt is durable; retry cleanup on the next load.
            return item

    def list_sessions(self):
        items = []
        for path in sorted(self.root.glob('*/session.bin'), key=lambda p:p.stat().st_mtime, reverse=True):
            try:items.append(self.load(path.parent.name))
            except (OSError, ValueError, KeyError):continue
        return items

    def append(self, sid, wav, start, end):
        with self.lock:
            total = sum(p.stat().st_size for p in self.root.glob('*/*.bin'))
            if total + len(wav) + 4096 > self.max_bytes:
                raise OSError('Radha lokale është plot. Përfundo dhe provo ruajtjen përsëri.')
            item = self.load(sid);seq = item['segment_count']
            self._write(self.directory(sid)/f'{seq:06d}.bin', struct.pack('!QQ', start,end)+wav)
            item['segments'].append([start,end]);item['segment_count'] += 1
            self.save(item)

    def pending(self, sid):
        with self.lock:
            item = self.load(sid)
            return list(range(len(item['transcript']), item['segment_count']))

    def audio(self, sid, seq):
        with self.lock:return unprotect((self.directory(sid)/f'{seq:06d}.bin').read_bytes())[16:]

    def ack(self, sid, seq, transcript):
        with self.lock:
            item = self.load(sid)
            if seq == len(item['transcript']):item['transcript'].append(transcript)
            elif seq >= len(item['transcript']):raise ValueError('Radha e segmenteve nuk përputhet.')
            self.save(item)
            (self.directory(sid)/f'{seq:06d}.bin').unlink(missing_ok=True)

    def update(self, sid, **fields):
        with self.lock:
            item = self.load(sid);item.update(fields);self.save(item);return item
