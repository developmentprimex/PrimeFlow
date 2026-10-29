"""Inspect the dedicated worker heartbeat without printing credentials."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def status(path, expected_build, now=None):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        now = now or datetime.now(timezone.utc)
        age = (now - datetime.fromisoformat(data["last_seen_at"])).total_seconds()
        ready = data.get("build") == expected_build and 0 <= age < 90 and bool(data.get("guild_id")) and isinstance(data.get("pid"), int)
    except (OSError, ValueError, KeyError, TypeError):
        return {"ready": False}
    return {"ready": ready, "reminders_enabled": bool(data.get("reminders_enabled")), "build": data.get("build")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-build", required=True)
    parser.add_argument("--state-dir", type=Path, default=Path("C:/PrimeFlowData/Kujtesa"))
    args = parser.parse_args()
    print(json.dumps(status(args.state_dir / ".kujtesa-worker-status.json", args.expected_build)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
