"""Transfer Actions environment to dotenv without shell-expanding secrets."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re

KEYS = (
    "DISCORD_ASSISTANT_ENABLED", "DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID",
    "DISCORD_BRIDGE_SECRET", "DISCORD_CATEGORY_ID", "DISCORD_MESSAGE_CONTENT_ENABLED",
    "DISCORD_AI_MODEL", "DISCORD_AI_TIMEOUT_SECONDS", "DISCORD_AGENT_MODEL",
    "DISCORD_MEETING_VOICE_CHANNEL_ID", "DISCORD_MEETING_NOTES_ENABLED", "DISCORD_VOICE_NODE_BINARY",
    "MIRA_MEMORY_ENABLED",
)
REQUIRED = ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_BRIDGE_SECRET")


def boolean(value: str, name: str) -> bool:
    if value.lower() not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false.")
    return value.lower() == "true"


def build_config(env: dict | os._Environ) -> dict[str, str]:
    values = {key: env.get(key, "").strip() for key in KEYS}
    if any("\n" in value or "\r" in value or "\x00" in value for value in values.values()):
        raise ValueError("Discord settings must be single-line values.")
    if any("${" in value for value in values.values()):
        raise ValueError("Discord settings cannot contain dotenv interpolation expressions.")
    requested = values["DISCORD_ASSISTANT_ENABLED"]
    enabled = boolean(requested, "DISCORD_ASSISTANT_ENABLED") if requested else any(values[key] for key in REQUIRED)
    if enabled:
        missing = [key for key in REQUIRED if not values[key]]
        if missing:
            raise ValueError("Missing GitHub Actions secrets: " + ", ".join(missing))
        if not env.get("OPENAI_API_KEY", "").strip():
            raise ValueError("OPENAI_API_KEY is required for the Discord assistant.")
        if not re.fullmatch(r"\d{17,20}", values["DISCORD_GUILD_ID"]):
            raise ValueError("DISCORD_GUILD_ID must be the numeric Discord Server ID.")
        if len(values["DISCORD_BRIDGE_SECRET"]) < 32:
            raise ValueError("DISCORD_BRIDGE_SECRET must contain at least 32 characters.")
    if values["DISCORD_CATEGORY_ID"] and not re.fullmatch(r"\d{17,20}", values["DISCORD_CATEGORY_ID"]):
        raise ValueError("DISCORD_CATEGORY_ID must be a numeric Discord category ID.")
    if values["DISCORD_MEETING_VOICE_CHANNEL_ID"] and not re.fullmatch(r"\d{17,20}", values["DISCORD_MEETING_VOICE_CHANNEL_ID"]):
        raise ValueError("DISCORD_MEETING_VOICE_CHANNEL_ID must be a numeric Discord voice channel ID.")
    voice_enabled = boolean(values["DISCORD_MEETING_NOTES_ENABLED"] or "false", "DISCORD_MEETING_NOTES_ENABLED")
    if voice_enabled and not enabled:
        raise ValueError("Meeting notes require the Discord assistant to be enabled.")
    values["DISCORD_MEETING_NOTES_ENABLED"] = str(voice_enabled).lower()
    values["DISCORD_VOICE_NODE_BINARY"] = values["DISCORD_VOICE_NODE_BINARY"] or "node"
    values["MIRA_MEMORY_ENABLED"] = str(boolean(values["MIRA_MEMORY_ENABLED"] or "false", "MIRA_MEMORY_ENABLED")).lower()
    values["DISCORD_ASSISTANT_ENABLED"] = str(enabled).lower()
    values["DISCORD_MESSAGE_CONTENT_ENABLED"] = str(boolean(values["DISCORD_MESSAGE_CONTENT_ENABLED"] or "true", "DISCORD_MESSAGE_CONTENT_ENABLED")).lower()
    values["DISCORD_AI_MODEL"] = values["DISCORD_AI_MODEL"] or "gpt-5.4-mini"
    values["DISCORD_AGENT_MODEL"] = values["DISCORD_AGENT_MODEL"] or "gpt-6-luna"
    timeout = values["DISCORD_AI_TIMEOUT_SECONDS"] or "45"
    if not timeout.isdigit() or not 1 <= int(timeout) <= 90:
        raise ValueError("DISCORD_AI_TIMEOUT_SECONDS must be between 1 and 90.")
    values["DISCORD_AI_TIMEOUT_SECONDS"] = timeout
    return values


def write_config(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    # Replace our keys only. Quoted dotenv values preserve shell metacharacters,
    # dollar signs and backslashes; secrets are never interpolated into commands.
    lines = [line for line in lines if line.partition("=")[0].strip() not in KEYS]
    lines.extend(f"{key}={json.dumps(value, ensure_ascii=True)}" for key, value in values.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    args = parser.parse_args()
    if args.status:
        from dotenv import dotenv_values
        values = dotenv_values(args.env_file, interpolate=False)
        print(json.dumps({"enabled": values.get("DISCORD_ASSISTANT_ENABLED") == "true",
                          "guild_id": values.get("DISCORD_GUILD_ID")}))
        return 0
    try:
        values = build_config(os.environ)
        write_config(args.env_file, values)
    except ValueError as exc:
        print(f"Discord configuration error: {exc}")
        return 1
    print("Discord configuration: " + ("enabled" if values["DISCORD_ASSISTANT_ENABLED"] == "true" else "disabled"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
