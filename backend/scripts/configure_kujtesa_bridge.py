"""Install the inspected Kujtesa adapter and configure only its private bridge.

Preview is the default. Apply requires the exact expected database host/name.
Never connects to Discord, sends messages, or enables reminders.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func
from sqlalchemy.engine import make_url

from app.config import settings
from app.db import SessionLocal
from app.models.ga_personal import GaPersonalSpace as Space, GaPersonalMember as Member, GaPersonalOccurrence as Occurrence, GaPersonalDiscordDelivery as Outbox, GaPersonalEvent as Event
from app.models.user import User
from app.schemas.ga_personal_discord import DiscordSettings
from app.services import ga_personal as service

ROOT = Path(__file__).resolve().parents[1]


def env_values(path):
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def update_env(path, values):
    lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
    result = []
    remaining = dict(values)
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in values:
            if key in remaining:
                result.append(key + "=" + remaining.pop(key))
        else:
            result.append(line)
    result.extend(key + "=" + value for key, value in remaining.items())
    temporary = path.with_name(path.name + ".primeflow-tmp")
    temporary.write_text("\n".join(result) + "\n", encoding="utf-8")
    temporary.replace(path)


async def configure(args):
    target = make_url(settings.DATABASE_URL)
    if args.apply and (target.host != args.expected_host or target.database != args.expected_database):
        raise SystemExit("Database target differs from the expected host/database.")
    bot_dir = Path(args.bot_directory).resolve()
    original = bot_dir / "kujtesa.py"
    if not original.is_file() or not (bot_dir / "household.py").is_file():
        raise SystemExit("Expected the inspected Kujtesa bot directory.")
    source = original.read_text(encoding="utf-8")
    anchor = "def main():\n    load_env()\n"
    if "from primeflow_bot import main as primeflow_main" not in source and source.count(anchor) != 1:
        raise SystemExit("The bot entry point changed; inspect it before installation.")
    bot_env = env_values(bot_dir / ".env")
    cfg = DiscordSettings(enabled=False, guild_id=bot_env.get("DISCORD_GUILD_ID", ""),
        channel_id=bot_env.get("DISCORD_CHANNEL_ID", ""), expected_version=0,
        user_ids={person: bot_env.get(name, "") for person, name in (
            ("rrita", "RITA_DISCORD_USER_ID"), ("mrika", "MRIKA_DISCORD_USER_ID"), ("gane", "GANE_DISCORD_USER_ID"))})
    if not cfg.guild_id or not cfg.channel_id:
        raise SystemExit("Configure the guild and private channel IDs in the bot environment first.")
    server_env = env_values(ROOT / ".env")
    existing_key = server_env.get("GA_PERSONAL_DISCORD_BRIDGE_SECRET") or settings.GA_PERSONAL_DISCORD_BRIDGE_SECRET
    if existing_key and len(existing_key) < 32:
        raise SystemExit("Existing bridge key is too short; inspect configuration.")
    key = existing_key or secrets.token_urlsafe(48)
    async with SessionLocal() as db:
        space = (await db.execute(select(Space).where(Space.key == "ga_personal"))).scalar_one()
        admin = (await db.execute(select(Member).join(User, User.id == Member.user_id).where(
            Member.space_id == space.id, Member.person_key == args.admin_person, Member.is_admin.is_(True),
            Member.active.is_(True), User.is_active.is_(True),
        ))).scalar_one_or_none()
        if admin is None or not space.password_hash:
            raise SystemExit("Expected an existing active module administrator and configured password.")
        count_before = (await db.execute(select(func.count(Occurrence.id)).where(Occurrence.space_id == space.id))).scalar_one()
        if not args.apply:
            print(json.dumps({"preview": True, "host": target.host, "database": target.database,
                              "bot_directory": str(bot_dir), "outgoing_messages": False, "existing_tasks": count_before}))
            return
        connection = await db.connection()
        # Only this private new table is provisioned. Do not run all migrations
        # or modify the production Alembic stamp from this local setup script.
        await connection.run_sync(lambda sync: Outbox.__table__.create(sync, checkfirst=True))
        space = await service.lock_space(db, space.id)
        previous = space.config.get("discord", {})
        if not previous:
            space.config = {**space.config, "discord": {**cfg.model_dump(exclude={"expected_version"}), "version": 1}}
            db.add(Event(space_id=space.id, actor_id=admin.user_id, request_id=str(service.uuid.uuid4()),
                kind="discord_configured", payload={"enabled": False, "version": 1}))
        elif previous.get("enabled"):
            raise SystemExit("Existing active Discord delegation found; stop before changing runtime configuration.")
        await db.commit()
        count_after = (await db.execute(select(func.count(Occurrence.id)).where(Occurrence.space_id == space.id))).scalar_one()
        if count_after != count_before:
            raise SystemExit("Task count changed concurrently; review before proceeding.")
    # Never copy the Discord token into PrimeFlow.
    update_env(ROOT / ".env", {"GA_PERSONAL_DISCORD_BRIDGE_SECRET": key})
    adapter = ROOT / "integrations" / "kujtesa" / "primeflow_bot.py"
    (bot_dir / "primeflow_bot.py").write_bytes(adapter.read_bytes())
    readme = ROOT / "integrations" / "kujtesa" / "README.md"
    if readme.exists():
        (bot_dir / "README-primeflow.md").write_bytes(readme.read_bytes())
    requirements = ROOT / "integrations" / "kujtesa" / "requirements-primeflow.txt"
    (bot_dir / requirements.name).write_bytes(requirements.read_bytes())
    if "from primeflow_bot import main as primeflow_main" not in source:
        backup = bot_dir / "kujtesa.before-primeflow.py"
        if not backup.exists():
            backup.write_bytes(original.read_bytes())
        source = source.replace(anchor, anchor + '    if setting("PRIMEFLOW_API_URL"):\n        from primeflow_bot import main as primeflow_main\n        return primeflow_main()\n')
    source = source.replace('        if not setting("RITA_DISCORD_USER_ID"):',
                            '        if setting("SEND_PRACTICE_ON_STARTUP") != "1" or not setting("RITA_DISCORD_USER_ID"):')
    original.write_text(source, encoding="utf-8")
    update_env(bot_dir / ".env", {"PRIMEFLOW_API_URL": args.api_url, "PRIMEFLOW_GA_BRIDGE_KEY": key,
                                  "REMINDERS_ENABLED": "0", "SEND_PRACTICE_ON_STARTUP": "0"})
    ignore = bot_dir / ".gitignore"
    existing_ignore = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    entries = [".env*", ".primeflow-*", "*.sqlite*", "__pycache__/", "kujtesa.before-primeflow.py"]
    ignore.write_text(existing_ignore.rstrip() + "\n" + "\n".join(e for e in entries if e not in existing_ignore.splitlines()) + "\n", encoding="utf-8")
    print(json.dumps({"installed": True, "bot_directory": str(bot_dir), "bridge_secret_configured": True,
                      "reminders_enabled": False, "tasks_preserved": count_after, "alembic_stamp_changed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bot-directory", required=True)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/api")
    parser.add_argument("--admin-person", choices=["rrita", "mrika", "gane"], required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    args = parser.parse_args()
    if args.apply and (not args.expected_host or not args.expected_database):
        parser.error("--apply requires --expected-host and --expected-database")
    asyncio.run(configure(args))
