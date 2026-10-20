"""Opt-in deployment preflight. Does not log in or record anything."""
import argparse
import json
import shutil
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.config import settings
from discord_voice_client import VoiceCaptureClient, VOICE_DIR


def supported_node(version):
    match=re.fullmatch(r'v(\d+)\.(\d+)\.(\d+)',version.strip())
    return bool(match and tuple(map(int,match.groups()))>=(22,12,0))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--install',action='store_true');args=parser.parse_args()
    if not settings.DISCORD_MEETING_NOTES_ENABLED:
        print('Mira meeting audio: disabled (no voice dependencies required).');return 0
    try:
        version=subprocess.run([settings.DISCORD_VOICE_NODE_BINARY,'--version'],env=VoiceCaptureClient.child_env(),
            capture_output=True,text=True,check=True,timeout=10)
        if not supported_node(version.stdout):raise ValueError('unsupported_node_version')
        if args.install:
            npm=shutil.which('npm')
            if not npm:raise ValueError('npm_unavailable')
            subprocess.run([npm,'ci','--ignore-scripts'],cwd=VOICE_DIR,env=VoiceCaptureClient.child_env(),check=True,timeout=180,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        result=subprocess.run([settings.DISCORD_VOICE_NODE_BINARY,str(VOICE_DIR/'worker.mjs'),'--check'],cwd=VOICE_DIR,
            env=VoiceCaptureClient.child_env(),capture_output=True,text=True,check=True,timeout=20)
        if json.loads(result.stdout).get('voice_ready') is not True:raise ValueError('voice_unavailable')
        subprocess.run([settings.DISCORD_VOICE_NODE_BINARY,'--test',str(VOICE_DIR/'tests'/'audio.test.mjs'),str(VOICE_DIR/'tests'/'worker.test.mjs')],
            cwd=VOICE_DIR,env=VoiceCaptureClient.child_env(),check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=60)
        print('Mira meeting audio: dependencies and tests ready. Live meeting test still required.');return 0
    except (OSError,ValueError,subprocess.SubprocessError):
        print('Mira meeting audio preflight failed. Check Node >=22.12 and backend/discord-voice dependencies.');return 1


if __name__=='__main__':raise SystemExit(main())
