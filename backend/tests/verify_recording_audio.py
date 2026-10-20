"""Validate that the browser's actual encoded mix contains both test tones."""
import array
import math
import os
import subprocess
import sys

result = subprocess.run([os.environ.get("MEETING_RECORDINGS_FFMPEG", "ffmpeg"), "-nostdin", "-v", "error", "-ss", "1", "-i", sys.argv[1], "-t", "1", "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "pipe:1"], check=True, stdout=subprocess.PIPE)
samples = array.array("f", result.stdout)
if len(samples) < 4000:
    raise RuntimeError("Insufficient recorded audio")


def amplitude(frequency):
    real = sum(value * math.cos(2 * math.pi * frequency * i / 8000) for i, value in enumerate(samples))
    imaginary = sum(value * math.sin(2 * math.pi * frequency * i / 8000) for i, value in enumerate(samples))
    return 2 * math.hypot(real, imaginary) / len(samples)


for frequency in (440, 880):
    level = amplitude(frequency)
    if level < 0.02 or level < amplitude(600) * 10:
        raise RuntimeError(f"Missing or weak {frequency} Hz source in recorded audio")
    print(f"Verified {frequency} Hz source amplitude {level:.3f}")
