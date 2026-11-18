import json
from unittest.mock import Mock

from scripts import primeflow_api_monitor as monitor


def snapshot(owner_8000=10, owner_8080=21):
    ok = {"status": "200", "ok": True}
    return {
        "8000": ok, "8080": ok, "public": ok,
        "pm2": [{"name": "primex-backend", "pid": 10, "status": "online"},
                {"name": "backend-api-flow", "pid": 20, "status": "online"}],
        "ports": {"listeners": [{"LocalPort": port, "OwningProcess": pid}
                               for port, pid in ((8000, owner_8000), (8080, owner_8080)) if pid],
                  "parents": {"21": 20}},
    }


def test_healthy_worker_child_is_accepted():
    assert all(issue is None for issue in monitor.findings(snapshot()).values())


def test_http_works_but_port_owner_differs_from_pm2():
    issues = monitor.findings(snapshot(owner_8000=99))
    assert issues["HTTP 8000"] is None
    assert issues["Port 8000"][0] == "PID mismatch"
    assert "PID 10" in issues["Port 8000"][1]
    assert "[99]" in issues["Port 8000"][1]


def test_pm2_online_without_listener_and_public_502():
    current = snapshot(owner_8000=None)
    current.update({"8000": {"error": "exit 7"}, "public": {"status": "502"}})
    issues = monitor.findings(current)
    assert issues["Port 8000"][0] == "PM2 online without listener"
    assert issues["HTTP 8000"][0] == "unavailable"
    assert "HTTP 502" in issues["HTTP public"][1]
    assert issues["HTTP 8080"] is None


def test_duplicate_service_is_detected():
    current = snapshot()
    current["pm2"].append({"name": "primex-public-api", "pid": 22, "status": "online"})
    assert monitor.findings(current)["Port 8080"][0] == "process conflict"


def test_broken_http_probe_is_distinguished_from_an_api_outage():
    current = snapshot()
    current["public"] = {"error": "FileNotFoundError", "collector_error": True}
    assert monitor.findings(current)["HTTP public"][0] == "monitor probe failed"


def test_listener_and_http_failure_open_one_local_incident():
    current = snapshot(owner_8000=None)
    current["8000"] = {"error": "ConnectFailure"}
    issues = monitor.group_port_issues(monitor.findings(current))
    assert "HTTP 8000" not in issues
    assert issues["Port 8000"][0] == "PM2 online without listener"
    assert "ConnectFailure" in issues["Port 8000"][1]


def test_error_changes_during_an_incident_do_not_repeat_the_alarm(tmp_path):
    path = tmp_path / "state.json"
    state = {}
    discord = Mock(return_value="accepted")
    sinks = {"discord:new": discord}
    incident = {"Port 8000": ("PID mismatch", "first observation")}
    for _ in range(2):
        monitor.evaluate(state, incident)
    state["Port 8000"]["sent"]["discord"] = "PID mismatch"
    monitor.notify(path, state, sinks, snapshot())
    message = discord.call_args.args[0]
    assert "primex-backend | Porta 8000" in message
    assert "Koha:" in message
    assert "PID 10 (online)" in message
    for _ in range(2):
        monitor.evaluate(state, {"Port 8000": ("PM2 online without listener", "second error")})
        monitor.notify(path, state, sinks, snapshot())
    assert discord.call_count == 1


def test_collection_failure_does_not_clear_active_mismatch():
    current = snapshot(owner_8000=99)
    state = {}
    for _ in range(2):
        monitor.evaluate(state, monitor.findings(current))
    current["pm2"] = {"error": "timeout"}
    for _ in range(2):
        monitor.evaluate(state, monitor.findings(current))
    assert state["Port 8000"]["active"] == "PID mismatch"
    assert state["PM2"]["active"] == "unavailable"


def test_alert_retries_each_sink_separately_and_sends_one_recovery(tmp_path):
    path = tmp_path / "state.json"
    state = {}
    windows = Mock()
    discord = Mock(side_effect=[OSError(), None, None])
    sinks = {"windows": windows, "discord": discord}
    failed = monitor.findings(snapshot(owner_8000=99))
    monitor.evaluate(state, failed)
    monitor.notify(path, state, sinks)
    windows.assert_not_called()
    monitor.evaluate(state, failed)
    for _ in range(3):
        monitor.notify(path, state, sinks)
    assert windows.call_count == 1
    assert discord.call_count == 2
    assert "PID mismatch" in windows.call_args.args[0]
    assert json.loads(path.read_text())["Port 8000"]["sent"]["discord"] == "PID mismatch"

    for _ in range(2):
        monitor.evaluate(state, monitor.findings(snapshot()))
        monitor.notify(path, state, sinks)
    assert windows.call_count == 2
    assert discord.call_count == 3
    assert windows.call_args.args[1] is True
