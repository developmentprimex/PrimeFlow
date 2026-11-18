"""Wait for both recorders and stop their supervisors while holding database write barriers."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import asyncpg
from dotenv import dotenv_values


def pm2(*args):
    return subprocess.check_output(
        ["cmd.exe", "/d", "/c", "pm2.cmd", *args], encoding="utf-8", errors="replace", timeout=90
    )


async def wait_and_stop():
    backend = Path(__file__).resolve().parents[1]
    config = dotenv_values(backend / ".env")
    supervisors = {"primeflow-discord", "primeflow-discord-ai-agent"}
    running = [p["name"] for p in json.loads(pm2("jlist"))
               if p["name"] in supervisors and p["pm2_env"]["status"] in ("online", "launching")]
    conn = await asyncpg.connect(config["DATABASE_URL"].replace("+asyncpg", ""), timeout=10)
    try:
        while True:
            async with conn.transaction():
                # SHARE waits for in-flight starts to commit and excludes a
                # concurrent INSERT/UPDATE only during this check and stop.
                # Release the transaction before sleeping so heartbeats continue.
                tables = await conn.fetchval("""
                    SELECT to_regclass('discord_voice_meetings') IS NOT NULL
                       AND to_regclass('mira_1h_meetings') IS NOT NULL
                """)
                if not tables:
                    if running:
                        raise RuntimeError("Cannot verify active meetings before stopping Mira.")
                    return
                await conn.execute("LOCK TABLE discord_voice_meetings, mira_1h_meetings IN SHARE MODE")
                active = await conn.fetchval("""
                    SELECT (SELECT count(*) FROM discord_voice_meetings
                            WHERE status IN ('STARTING','LISTENING','FINALIZING')
                               OR (status = 'INTERRUPTED' AND heartbeat_at > now() - interval '60 seconds'))
                         + (SELECT count(*) FROM mira_1h_meetings
                            WHERE status IN ('PREP','GA_PHASE','STAFF_PHASE'))
                """)
                if not active:
                    state = Path(os.environ["RUNNER_TEMP"]) / (
                        f"mira-deploy-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}.json")
                    state.write_text(json.dumps(running), encoding="utf-8")
                    for name in running:
                        pm2("stop", name)
                    return
            print(f"Waiting for {active} active or finalizing Mira session(s).", flush=True)
            await asyncio.sleep(15)
    finally:
        await conn.close()


if __name__ == "__main__":
    if "--recover" in sys.argv:
        state = Path(os.environ["RUNNER_TEMP"]) / (
            f"mira-deploy-{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}.json")
        if state.exists():
            statuses = {p["name"]: p["pm2_env"]["status"] for p in json.loads(pm2("jlist"))}
            for name in json.loads(state.read_text()):
                if statuses.get(name) != "online":
                    pm2("start", "ecosystem.config.cjs", "--only", name, "--update-env")
    else:
        asyncio.run(wait_and_stop())
