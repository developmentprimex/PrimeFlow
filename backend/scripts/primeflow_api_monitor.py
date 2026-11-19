"""One read-only monitoring cycle for the two PrimeFlow APIs and public route."""
import argparse
import ctypes
import hashlib
import http.client
import json
import logging
import os
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


HERE = Path(__file__).resolve().parent
SERVER = Path(r"C:\Windows\System32")
POWERSHELL = SERVER / "WindowsPowerShell/v1.0/powershell.exe"
NODE = Path(r"C:\Program Files\nodejs\node.exe")
PM2 = Path(r"C:\npm-global\node_modules\pm2")
SERVICES = {8000: "primex-backend", 8080: "backend-api-flow"}
URLS = {str(port): f"http://127.0.0.1:{port}/health" for port in SERVICES}
URLS["public"] = "https://api-flow.primexeu.com/health"
ALERT_THRESHOLD = 2
log = logging.getLogger("primeflow.api_monitor")


def command(args, timeout):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=True).stdout


def http_probe(url):
    target = urlsplit(url)
    transport = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
    connection = transport(target.hostname, target.port, timeout=5)
    try:
        connection.request("GET", target.path, headers={"User-Agent": "PrimeFlow-ApiMonitor/1"})
        response = connection.getresponse()
        result = {"status": str(response.status)}
        if response.status == 200:
            try:
                data = json.loads(response.read(8193))
            except (ValueError, UnicodeError):
                return result
            if isinstance(data, dict) and data.get("status") == "ok":
                result.update(ok=True, build=data.get("build", ""))
        return result
    except (OSError, http.client.HTTPException) as exc:
        return {"error": type(exc).__name__}
    finally:
        connection.close()


def process_snapshot():
    return json.loads(command([str(NODE), str(HERE / "primeflow_monitor_pm2.cjs"), str(PM2)], 8))


def port_snapshot():
    return json.loads(command(
        [str(POWERSHELL), "-NoProfile",
         "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
         str(HERE / "primeflow_monitor_ports.ps1")], 20
    ))


def cpu_times():
    values = [ctypes.c_ulonglong() for _ in range(3)]
    if ctypes.windll.kernel32.GetSystemTimes(*(ctypes.byref(v) for v in values)):
        idle, kernel, user = (v.value for v in values)
        return idle, kernel + user


def timed_probe(fn, args):
    start = time.monotonic()
    try:
        value = fn(*args)
    except subprocess.CalledProcessError as exc:
        value = {"error": f"exit {exc.returncode}", "collector_error": True}
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        value = {"error": type(exc).__name__, "collector_error": True}
    return value, round((time.monotonic() - start) * 1000)


def collect():
    work = {name: (http_probe, (url,)) for name, url in URLS.items()}
    work.update(pm2=(process_snapshot, ()), ports=(port_snapshot, ()))
    before = cpu_times()
    result = {"elapsed_ms": {}}
    with ThreadPoolExecutor(max_workers=len(work)) as executor:
        pending = {name: executor.submit(timed_probe, fn, args) for name, (fn, args) in work.items()}
        for name, future in pending.items():
            result[name], result["elapsed_ms"][name] = future.result()
    after = cpu_times()
    if before and after and after[1] > before[1]:
        result["cpu_percent"] = round(100 * (1 - (after[0]-before[0]) / (after[1]-before[1])), 1)
    # MEMORYSTATUSEX begins with two DWORDs followed by seven DWORDLONGs.
    class MemoryStatus(ctypes.Structure):
        _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
                    ("total", ctypes.c_uint64), ("available", ctypes.c_uint64),
                    ("remaining", ctypes.c_uint64 * 5)]
    memory = MemoryStatus()
    memory.length = ctypes.sizeof(memory)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        result["available_memory_mb"] = memory.available // (1024 * 1024)
    return result


def external_findings(path):
    try:
        sample = json.loads(path.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample["at"])).total_seconds()
        if not 0 <= age <= 100:
            raise ValueError("stale sample")
        issues = {"Monitori i jashtëm": None}
        for name in ("api", "login"):
            item = sample["checks"][name]
            issues[f"Jashtë serverit | {name}"] = None if item["ok"] else (
                "Kontrolli i jashtëm dështoi", f"{item['url']} — HTTP {item.get('status', '—')}, "
                f"{item.get('error', 'përgjigje e papritur')}, {item['elapsed_ms']} ms. {sample['at']}")
        return issues
    except (OSError, ValueError, TypeError, KeyError):
        return {"Monitori i jashtëm": ("Matja mungon", "Matja e jashtme mungon ose është vonuar.")}


def belongs_to(owner, root, parents):
    seen = set()
    while owner and owner not in seen:
        if owner == root:
            return True
        seen.add(owner)
        owner = parents.get(str(owner), 0)
    return False


def findings(snapshot):
    """An absent key means the check could not run. None means it passed."""
    issues = {}
    for name in URLS:
        http = snapshot[name]
        if not http.get("ok"):
            detail = f"HTTP {http['status']}" if "status" in http else http["error"]
            code = "monitor probe failed" if http.get("collector_error") else "unavailable"
            issues[f"HTTP {name}"] = (code, f"{URLS[name]} — {detail}")
        else:
            issues[f"HTTP {name}"] = None

    rows = snapshot["pm2"]
    ports = snapshot["ports"]
    for name, value in (("PM2", rows), ("Windows listeners", ports)):
        error = value.get("error") if isinstance(value, dict) else None
        issues[name] = ("unavailable", f"Status collection failed: {error}") if error else None

    if isinstance(rows, list) and "listeners" in ports:
        for port, service in SERVICES.items():
            owners = sorted({row["OwningProcess"] for row in ports["listeners"]
                             if row["LocalPort"] == port})
            expected = [row for row in rows if row["name"] == service]
            competing = [row for row in rows if port == 8080 and row["name"] == "primex-public-api"
                         and row["status"] in ("online", "launching")]
            tracked = ", ".join(f"{row['name']} PID {row['pid']} ({row['status']})"
                                for row in expected + competing) or "missing"
            detail = f"PM2: {tracked}. Listener PID(s): {owners or 'none'}."
            active = [row for row in expected if row["status"] == "online" and (row["pid"] or 0) > 0]
            code = None
            if len(expected) > 1 or competing or len(owners) > 1:
                code = "process conflict"
            elif not active:
                code = "PM2 process missing or offline"
            elif not owners:
                code = "PM2 online without listener"
            elif not (owners[0] == active[0]["pid"] or
                      (port == 8080 and belongs_to(owners[0], active[0]["pid"], ports["parents"]))):
                code = "PID mismatch"
            issues[f"Port {port}"] = (code, detail) if code else None
    return issues


def evaluate(state, issues):
    observed_at = datetime.now(timezone.utc).isoformat()
    for check in state.values():
        check.setdefault("event_at", observed_at)
    for name in state.keys() - issues.keys():
        state[name]["count"] = 0
    for name, observation in issues.items():
        check = state.setdefault(name, {"pending": None, "count": 0, "active": None, "sent": {}})
        code = observation[0] if observation else None
        same_status = (check["pending"] is None) == (code is None)
        check["count"] = min(check["count"] + 1, ALERT_THRESHOLD) if same_status else 1
        check["pending"] = code
        if check["count"] >= ALERT_THRESHOLD:
            if (check["active"] is None) != (code is None):
                check["active"] = code
                check["event_at"] = observed_at
            check.setdefault("event_at", observed_at)
            check["current_code"] = code
            check["detail"] = observation[1] if observation else "Kontrolli po kalon përsëri."


def group_port_issues(issues):
    for port in SERVICES:
        http = issues.pop(f"HTTP {port}")
        name = f"Port {port}"
        owner = issues.get(name)
        if owner and http:
            issues[name] = (owner[0], f"{owner[1]} {http[1]}")
        elif http:
            issues[name] = http
    return issues


def alert_target(name, snapshot):
    if name.startswith(("Jashtë serverit", "Monitori i jashtëm")):
        return name, "Kontroll nga kompjuteri i jashtëm."
    port = name.removeprefix("Port ")
    if port.isdecimal() and int(port) in SERVICES:
        service = SERVICES[int(port)]
        needed = {service, "primex-public-api"} if port == "8080" else {service}
        label = f"{service} | Porta {port}"
    else:
        needed = {*SERVICES.values(), "primex-public-api"}
        label = "API publike e PrimeFlow | Porta HTTPS 443" if name == "HTTP public" else f"{name} | Portat 8000, 8080"
    rows = snapshot.get("pm2")
    if not isinstance(rows, list):
        return label, "Gjendja e PM2 është e padisponueshme."
    summary = ", ".join(f"{row['name']} PID {row['pid']} ({row['status']})"
                        for row in rows if row["name"] in needed)
    return label, f"PM2: {summary or 'procesi nuk figuron'}."


def windows_event(message, resolved):
    command([str(SERVER / "eventcreate.exe"), "/L", "APPLICATION", "/SO", "PrimeFlowApiMonitor",
             "/T", "INFORMATION" if resolved else "WARNING", "/ID", "902" if resolved else "901",
             "/D", message], 5)


def discord_event(env_file, channel_id, message):
    from dotenv import dotenv_values

    env = dotenv_values(env_file, interpolate=False)
    token = env["DISCORD_BOT_TOKEN"]
    guild_id = env["DISCORD_GUILD_ID"]
    if not channel_id or not channel_id.isdecimal() or not guild_id or not guild_id.isdecimal():
        raise ValueError("Discord channel is not configured")
    url = f"https://discord.com/api/v10/channels/{channel_id}"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json",
               "User-Agent": "DiscordBot (https://primeflow.primexeu.com, 1.0)"}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as response:
        channel = json.load(response)
    if (channel.get("name") != "primeflow-monitorim" or channel.get("guild_id") != guild_id
            or channel.get("type") != 0):
        raise ValueError("Discord destination does not match")
    identity = "\n".join(message.splitlines()[:3])
    nonce = hashlib.sha256(identity.encode()).hexdigest()[:24]
    data = json.dumps({"content": message, "allowed_mentions": {"parse": []},
                       "nonce": nonce, "enforce_nonce": True}).encode()
    request = urllib.request.Request(url + "/messages", data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)["id"]


def write_state(path, state):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def notify(path, state, sinks, snapshot=None, *, prefix=""):
    for name, check in state.items():
        active = check["active"]
        for sink, send in sinks.items():
            previous = check["sent"].get(sink)
            if active == previous:
                continue
            title = "ALARM PrimeFlow" if active else "PrimeFlow u rikthye"
            target, processes = alert_target(name, snapshot or {})
            event_at = check["event_at"]
            error = (check.get("current_code") or active) if active else previous
            if active and (error == "monitor probe failed" or
                           (name in ("PM2", "Windows listeners") and error == "unavailable")):
                title = "Monitori lokal nuk përfundoi kontrollin"
            elif not active:
                title = "Kontrolli po kalon përsëri"
            error_label = "Gabimi" if active else "Gabimi i mëparshëm"
            message = (f"{prefix}{title}\n{target}\nKoha: {event_at}\n"
                       f"{error_label}: {error}\n{processes}\n{check['detail']}")
            try:
                receipt = send(message, active is None)
            except Exception as exc:
                # Network and process exceptions can contain Discord credentials or payloads.
                log.warning("notification_failed sink=%s check=%s error=%s http=%s",
                            sink, name, type(exc).__name__, getattr(exc, "code", None))
                continue
            check["sent"][sink] = active
            write_state(path, state)
            log.info("notification_sent sink=%s check=%s status=%s receipt=%s",
                     sink, name, active or "resolved", receipt or "-")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--discord-env", type=Path)
    args = parser.parse_args()
    args.state_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(args.state_dir / "monitor.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(message)s")
    state_path = args.state_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    for port in SERVICES:
        previous = state.pop(f"HTTP {port}", None)
        name = f"Port {port}"
        if previous and previous["active"] and not state.get(name, {}).get("active"):
            state[name] = previous
    snapshot = collect()
    issues = group_port_issues(findings(snapshot))
    external = args.state_dir / "external.json"
    if external.exists() or "Monitori i jashtëm" in state:
        issues.update(external_findings(external))
    log.info("%s snapshot=%s", datetime.now(timezone.utc).isoformat(),
             json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
    evaluate(state, issues)
    write_state(state_path, state)
    sinks = {"windows": windows_event}
    if args.discord_env:
        try:
            channel_id = (args.state_dir.parent / "discord-channel.txt").read_text(encoding="ascii").strip()
            if not channel_id.isdecimal():
                raise ValueError("Invalid Discord channel ID")
        except (OSError, ValueError) as exc:
            log.error("discord_configuration_unavailable error=%s", type(exc).__name__)
        else:
            sinks[f"discord:{channel_id}"] = lambda message, _: discord_event(args.discord_env, channel_id, message)
    notify(state_path, state, sinks, snapshot)


if __name__ == "__main__":
    main()
