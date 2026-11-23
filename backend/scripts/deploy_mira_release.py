"""Stage isolated Mira workers, then activate them with a verified fallback."""

import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from zipfile import ZipFile

from dotenv import dotenv_values

from scripts.wait_for_mira_deploy import pm2


BACKEND = Path(__file__).resolve().parents[1]
PROCESSES = {
    "primeflow-discord": ".discord-worker-status.json",
    "primeflow-discord-ai-agent": ".discord-ai-agent-status.json",
}
AGENT_CONFIG = Path(r"C:\PrimeFlowOps\MiraAIAgent\.env")
SHA = re.compile(r"[a-f0-9]{40}")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_json(path, value):
    temporary = path.with_suffix(".new")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def processes():
    return {item["name"]: item for item in json.loads(pm2("jlist")) if item["name"] in PROCESSES}


class Deployment:
    def __init__(self):
        state = Path(os.environ["PM2_HOME"]) / "primeflow-deploy"
        self.root = state / "mira-releases"
        self.root.mkdir(parents=True, exist_ok=True)
        run = f'{os.environ["GITHUB_RUN_ID"]}-{os.environ["GITHUB_RUN_ATTEMPT"]}'
        if not re.fullmatch(r"\d+-\d+", run):
            raise ValueError("Invalid workflow run ID")
        self.plan = self.root / f"{run}.json"
        self.legacy_env = self.root / f"{run}.legacy.env"
        self.active = self.root / "active.json"
        self.backend_marker = state / "backend.sha"
        self.run = run

    def snapshot(self):
        if not self.active.exists() and (BACKEND / ".env").is_file():
            self.legacy_env.write_bytes((BACKEND / ".env").read_bytes())

    def stage(self, build, suffix, config, roles, *, probe):
        if not SHA.fullmatch(build):
            raise ValueError("Invalid Mira release commit")
        runtime = self.root / f"{build[:12]}-{self.run}-{suffix}"
        runtime.mkdir()
        archive = subprocess.check_output(["git", "archive", "--format=zip", build, "backend"], cwd=BACKEND.parent)
        with ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(runtime)
        backend = runtime / "backend"
        (backend / ".env").write_bytes(config)
        if roles:
            subprocess.run([sys.executable, "-m", "venv", str(runtime / "venv")], check=True)
            python = runtime / "venv" / "Scripts" / "python.exe"
            subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements-discord.txt"], cwd=backend, check=True)
            voice_env = os.environ.copy()
            if "primeflow-discord-ai-agent" in roles:
                voice_env["DISCORD_MEETING_NOTES_ENABLED"] = "true"
            subprocess.run([str(python), "scripts/check_discord_voice.py", "--install"], cwd=backend, env=voice_env, check=True)
            subprocess.run([str(python), "-c", "import discord_bot, discord_ai_agent_bot"], cwd=backend, check=True)
            deployment_env = json.dumps({"APP_BUILD_SHA": build, "PRIMEFLOW_API_BASE_URL": "http://127.0.0.1:18080",
                                         "PRIMEFLOW_MIRA_RELEASE_PROBE": "1" if probe else "",
                                         "PRIMEFLOW_MIRA_TRAFFIC_FILE": str(runtime / "traffic.ready") if probe else "",
                                         "PRIMEFLOW_MIRA_HOST_RECOVERY_DIR": str(BACKEND / ".mira-host-recovery")})
            # Preserve Mira Host's durable recovery queue across both new and legacy releases.
            (backend / "mira_release_primary.py").write_text(
                'import os\nimport runpy\nfrom pathlib import Path\nimport mira_host\n'
                'mira_host.RECOVERY_DIR = Path(os.environ["PRIMEFLOW_MIRA_HOST_RECOVERY_DIR"])\n'
                'runpy.run_module("discord_bot", run_name="__main__")\n',
                encoding="utf-8",
            )
            (runtime / "mira.config.cjs").write_text(
                'const backend = require("./backend/ecosystem.config.cjs");\n'
                'const path = require("node:path");\n'
                f"const releaseEnv = {deployment_env};\n"
                f"const roles = {json.dumps(roles)};\n"
                "module.exports = { apps: backend.apps.filter(app => roles.includes(app.name)).map(app => ({\n"
                '  ...app, script: path.join(__dirname, "venv", "Scripts", "python.exe"),\n'
                '  args: app.name === "primeflow-discord" ? "mira_release_primary.py" : app.args,\n'
                "  env: { ...app.env, ...releaseEnv },\n"
                "})) };\n",
                encoding="utf-8",
            )
        return {"build": build, "path": str(runtime), "roles": roles, "probe": probe,
                "voice": dotenv_values(backend / ".env").get("DISCORD_MEETING_NOTES_ENABLED") == "true"}

    def prepare(self):
        previous = read_json(self.active)
        if previous is None:
            running = [name for name, item in processes().items()
                       if item["pm2_env"]["status"] in {"online", "launching"}]
            if running:
                if not self.legacy_env.is_file() or not self.backend_marker.is_file():
                    raise RuntimeError("Cannot stage the currently running Mira release for rollback")
                previous = self.stage(self.backend_marker.read_text(encoding="ascii").strip(), "previous",
                                      self.legacy_env.read_bytes(), running, probe=False)
        self.legacy_env.unlink(missing_ok=True)
        config = BACKEND / ".env"
        enabled = dotenv_values(config).get("DISCORD_ASSISTANT_ENABLED") == "true"
        roles = []
        if enabled:
            roles.append("primeflow-discord")
            if AGENT_CONFIG.is_file():
                roles.append("primeflow-discord-ai-agent")
        candidate = self.stage(os.environ["GITHUB_SHA"], "candidate", config.read_bytes(), roles, probe=True)
        write_json(self.plan, {"previous": previous, "candidate": candidate, "switching": False})

    @staticmethod
    def start(release):
        runtime = Path(release["path"])
        for name in release["roles"]:
            (runtime / "backend" / PROCESSES[name]).unlink(missing_ok=True)
            pm2("start", str(runtime / "mira.config.cjs"), "--only", name, "--update-env")

    @staticmethod
    def verify(release):
        roles = set(release["roles"])
        pending = roles.copy()
        deadline = time.monotonic() + 90
        while pending and time.monotonic() < deadline:
            pending = roles.copy()
            current = processes()
            for name in pending.copy():
                process = current.get(name, {})
                if process.get("pm2_env", {}).get("status") != "online":
                    continue
                file = Path(release["path"]) / "backend" / PROCESSES[name]
                status = read_json(file)
                if not status or status.get("pid") != process.get("pid"):
                    continue
                if name == "primeflow-discord" and status.get("build") != release["build"]:
                    continue
                if name == "primeflow-discord-ai-agent" and status.get("ready") is not True:
                    continue
                if release["probe"] and (release["voice"] or name == "primeflow-discord-ai-agent"):
                    if status.get("panel_ready") is not True or status.get("voice_ready") is not True:
                        continue
                pending.remove(name)
            if pending:
                time.sleep(2)
        if pending:
            raise RuntimeError(f"Mira readiness checks timed out for {', '.join(sorted(pending))}")

    def prune(self, *retained):
        root = self.root.resolve()
        keep = {Path(release["path"]).resolve() for release in retained if release}
        for directory in root.iterdir():
            if not re.fullmatch(r"[a-f0-9]{12}-\d+-\d+-(candidate|previous)", directory.name):
                continue
            if not directory.is_dir() or directory.resolve() != directory or directory in keep:
                continue
            try:
                shutil.rmtree(directory)
            except OSError:
                print(f"Could not remove inactive Mira release {directory.name}.")

    @staticmethod
    def delete_processes():
        for name in processes():
            pm2("delete", name)

    def activate(self):
        plan = read_json(self.plan)
        plan["switching"] = True
        write_json(self.plan, plan)
        candidate = plan["candidate"]
        self.delete_processes()
        self.start(candidate)
        self.verify(candidate)
        write_json(self.active, candidate)
        (Path(candidate["path"]) / "traffic.ready").touch()
        plan["switching"] = False
        write_json(self.plan, plan)
        self.prune(candidate, plan["previous"])
        print("Mira release verified.")

    def recover(self):
        self.legacy_env.unlink(missing_ok=True)
        plan = read_json(self.plan)
        stopped = Path(os.environ["RUNNER_TEMP"]) / f"mira-deploy-{self.run}.json"
        if not plan or not (plan["switching"] or stopped.is_file()):
            return
        if read_json(self.active) == plan["candidate"] and not plan["switching"]:
            return
        previous = plan["previous"]
        self.delete_processes()
        if previous:
            self.start(previous)
            self.verify(previous)
            write_json(self.active, previous)
        else:
            self.active.unlink(missing_ok=True)
        pm2("save")
        self.prune(previous)
        print("Mira rollback verified." if previous else "No previous Mira release was running.")


if __name__ == "__main__":
    release = Deployment()
    command = sys.argv[1]
    if command not in {"snapshot", "prepare", "activate", "recover"}:
        raise SystemExit("Unknown Mira deployment command")
    getattr(release, command)()
