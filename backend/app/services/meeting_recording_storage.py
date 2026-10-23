"""Private storage boundary. Keys are relative, portable and server generated.

A future provider implements receive/path/finalize with the same durability and
integrity guarantees. Network storage is deliberately not implemented here.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import shutil
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


class StorageError(Exception):
    pass


class StorageBusy(StorageError):
    pass


@contextmanager
def finalization_lock(folder: Path):
    # The OS lock outlives a cancelled asyncio request while its remux thread
    # finishes. A second API process cannot race the first atomic publication.
    with (folder / ".finalize.lock").open("a+b") as handle:
        handle.write(b"\0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise StorageBusy("Recording is already being finalized; retry shortly") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def durable_replace(source: Path, target: Path):
    os.replace(source, target)
    # Persist directory entries as well as file data on POSIX. Windows replace
    # is atomic and file handles have already been flushed before this call.
    if os.name != "nt":
        fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


class LocalMeetingStorage:
    def __init__(self, root: str = ""):
        backend = Path(__file__).resolve().parents[2]
        configured = Path(root or "uploads/meeting-recordings")
        self.root = (configured if configured.is_absolute() else backend / configured).resolve()

    def path(self, key: str) -> Path:
        if "\\" in key or ":" in key or PurePosixPath(key).is_absolute() or ".." in PurePosixPath(key).parts:
            raise StorageError("Invalid storage key")
        result = (self.root / key).resolve()
        if result == self.root or self.root not in result.parents:
            raise StorageError("Invalid storage key")
        return result

    def available_media(self, key: str, mime: str, size_bytes: int) -> Path | None:
        extension = "webm" if mime == "video/webm" else "mp4"
        file = self.path(f"{key}/recording.{extension}")
        try:
            if file.is_file() and file.stat().st_size == size_bytes:
                return file
        except OSError:
            pass
        return None

    async def receive(self, key: str, body, limit: int) -> tuple[Path, int, str]:
        folder = self.path(key)
        await asyncio.to_thread(folder.mkdir, parents=True, exist_ok=True)
        temp = folder / f"{uuid.uuid4()}.part"
        digest, size = hashlib.sha256(), 0
        try:
            with temp.open("xb") as output:
                async for block in body:
                    size += len(block)
                    if size > limit:
                        raise StorageError("Chunk exceeds upload limit")
                    digest.update(block)
                    await asyncio.to_thread(output.write, block)
                if not size:
                    raise StorageError("Empty chunk")
                await asyncio.to_thread(output.flush)
                await asyncio.to_thread(os.fsync, output.fileno())
            return temp, size, digest.hexdigest()
        except BaseException:
            temp.unlink(missing_ok=True)
            raise

    def finalize(self, key: str, chunks, mime: str, ffmpeg: str, ffprobe: str, max_duration: int) -> dict:
        with finalization_lock(self.path(key)):
            return self._finalize(key, chunks, mime, ffmpeg, ffprobe, max_duration)

    def _finalize(self, key: str, chunks, mime: str, ffmpeg: str, ffprobe: str, max_duration: int) -> dict:
        """Reassemble fragments from ONE MediaRecorder, then remux and probe.

        Individual timeslices are not independently playable files. Never use
        FFmpeg's concat demuxer on them or concatenate independent recordings.
        """
        folder = self.path(key)
        extension = "webm" if mime == "video/webm" else "mp4"
        joined = folder / "assembled.part"
        output = folder / f"remux.{extension}"
        try:
            with joined.open("wb") as dest:
                for chunk in chunks:
                    source = folder / "chunks" / f"{chunk.index:08d}.chunk"
                    digest, size = hashlib.sha256(), 0
                    with source.open("rb") as incoming:
                        while block := incoming.read(1024 * 1024):
                            digest.update(block)
                            size += len(block)
                            dest.write(block)
                    if size != chunk.size_bytes or digest.hexdigest() != chunk.sha256:
                        raise StorageError("Stored chunk integrity check failed")
                dest.flush()
                os.fsync(dest.fileno())
            with joined.open("rb") as header:
                magic = header.read(32)
            if (extension == "webm" and not magic.startswith(b"\x1a\x45\xdf\xa3")) or (extension == "mp4" and magic[4:8] != b"ftyp"):
                raise StorageError("Invalid recording container")
            flags = ["-movflags", "+faststart"] if extension == "mp4" else []
            # No shell, external resources, subtitles, attachments or data tracks.
            subprocess.run([ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-xerror", "-y",
                            "-protocol_whitelist", "file", "-f", "matroska" if extension == "webm" else "mov",
                            "-i", str(joined), "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", *flags, str(output)],
                           check=True, timeout=600, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            result = subprocess.run([ffprobe, "-v", "error", "-protocol_whitelist", "file", "-show_streams", "-show_format", "-of", "json", str(output)],
                                    check=True, timeout=60, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            probe = json.loads(result.stdout)
            video = next((s for s in probe["streams"] if s["codec_type"] == "video"), None)
            duration = float(probe["format"].get("duration", 0))
            if not video or video.get("width", 0) <= 0 or not math.isfinite(duration) or not 0 < duration <= max_duration:
                raise StorageError("Recording has no valid video or duration")
            allowed_video = {"vp8", "vp9", "av1"} if extension == "webm" else {"h264", "hevc", "av1"}
            if video.get("codec_name") not in allowed_video:
                raise StorageError("Unsupported video codec")
            metadata = {"mime_type": mime, "duration_seconds": duration, "size_bytes": output.stat().st_size,
                        "video_width": video["width"], "video_height": video["height"],
                        "has_audio": any(s["codec_type"] == "audio" for s in probe["streams"])}
            with output.open("r+b") as media:
                os.fsync(media.fileno())
            durable_replace(output, folder / f"recording.{extension}")
            temp_metadata = folder / "metadata.part"
            with temp_metadata.open("w", encoding="utf-8") as meta:
                json.dump(metadata, meta)
                meta.flush()
                os.fsync(meta.fileno())
            durable_replace(temp_metadata, folder / "metadata.json")
            return metadata
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            raise StorageError("Media could not be validated; retained chunks can be retried") from exc
        finally:
            joined.unlink(missing_ok=True)
            output.unlink(missing_ok=True)

    @staticmethod
    def check_tools(ffmpeg: str, ffprobe: str):
        if not shutil.which(ffmpeg) or not shutil.which(ffprobe):
            raise StorageError("FFmpeg and ffprobe must be configured before recording")
