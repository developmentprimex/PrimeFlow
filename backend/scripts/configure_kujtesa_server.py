"""Write only Kujtesa's private server environment, without echoing secrets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re


DEFAULT_STATE_DIR = Path("C:/PrimeFlowData/Kujtesa")


def boolean(value, name, default=False):
    if not value:
        return default
    if value.lower() not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false.")
    return value.lower() in {"true", "1"}


def build_config(env):
    token = env.get("KUJTESA_DISCORD_TOKEN", "").strip()
    key = env.get("GA_PERSONAL_DISCORD_BRIDGE_SECRET", "").strip()
    enabled = boolean(env.get("KUJTESA_ENABLED", "").strip(), "KUJTESA_ENABLED", default=bool(token))
    reminders = boolean(env.get("KUJTESA_REMINDERS_ENABLED", "").strip(), "KUJTESA_REMINDERS_ENABLED")
    for value in (token, key):
        if any(char in value for char in ("\n", "\r", "\x00", "${")):
            raise ValueError("Kujtesa secrets must be single-line, literal values.")
    if enabled:
        missing = [name for name, value in (("KUJTESA_DISCORD_TOKEN", token), ("GA_PERSONAL_DISCORD_BRIDGE_SECRET", key)) if not value]
        if missing:
            raise ValueError("Missing GitHub Actions secrets: " + ", ".join(missing))
        if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", key):
            raise ValueError("GA_PERSONAL_DISCORD_BRIDGE_SECRET must be the generated URL-safe key.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{20,256}", token):
            raise ValueError("KUJTESA_DISCORD_TOKEN must be a valid dedicated bot token.")
    return {"KUJTESA_ENABLED": str(enabled).lower(), "DISCORD_TOKEN": token if enabled else "",
            "PRIMEFLOW_API_URL": "http://127.0.0.1:8000/api", "PRIMEFLOW_GA_BRIDGE_KEY": key if enabled else "",
            "REMINDERS_ENABLED": "1" if enabled and reminders else "0", "SEND_PRACTICE_ON_STARTUP": "0"}


def write_config(path, values):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text("\n".join(f"{name}={json.dumps(value)}" for name, value in values.items()) + "\n", encoding="utf-8")
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    path = args.state_dir / ".env"
    if args.status:
        from dotenv import dotenv_values
        values = dotenv_values(path, interpolate=False) if path.exists() else {}
        print(json.dumps({"enabled": values.get("KUJTESA_ENABLED") == "true", "reminders_enabled": values.get("REMINDERS_ENABLED") == "1"}))
        return 0
    try:
        values = build_config(os.environ)
        write_config(path, values)
    except ValueError as error:
        print("Kujtesa configuration error: " + str(error))
        return 1
    print("Kujtesa server configuration: " + ("enabled" if values["KUJTESA_ENABLED"] == "true" else "disabled"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
