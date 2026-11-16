"""Notify existing personal Discord channels independently of the running bot/API."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path


def message(user_id: str, phase: str) -> str:
    prefix = f"<@{user_id}> "
    if phase == "start":
        return (prefix + "🛠️ **PrimeFlow po përditësohet (PUSH).**\n"
                "Ju lutemi, mos bëni ndryshime për rreth **7 minuta**. "
                "Ndryshimet gjatë përditësimit mund të mos ruhen.\n"
                "Nëse përditësimi zgjat më shumë, prisni njoftimin e përfundimit para se të vazhdoni.")
    if phase == "success":
        return prefix + "✅ **PrimeFlow u përditësua.** Mund të vazhdoni punën normalisht. Rifreskoni faqen."
    return (prefix + "⚠️ **Përditësimi i PrimeFlow nuk përfundoi me sukses.**\n"
            "Ju lutemi, prisni konfirmimin e ekipit teknik para se të bëni ndryshime.")


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(path)


async def targets(database_url: str, guild_id: str) -> list[dict]:
    import asyncpg

    db = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        timeout=10, server_settings={"default_transaction_read_only": "on", "statement_timeout": "15000"},
    )
    try:
        rows = await db.fetch("""
            SELECT DISTINCT l.discord_user_id, l.channel_id
            FROM discord_links l JOIN users u ON u.id = l.user_id
            WHERE l.enabled = true AND u.is_active = true
                AND l.guild_id = $1 AND l.channel_id IS NOT NULL
            ORDER BY l.discord_user_id, l.channel_id
        """, guild_id)
        return [dict(row) for row in rows]
    finally:
        await db.close()


async def deliver(state: dict, path: Path, phase: str, send) -> tuple[int, int]:
    """Persist each attempt before sending; never automatically replay an uncertain send."""
    sent = failed = 0
    for target in state["targets"]:
        key = target["channel_id"]
        if phase != "start" and state.get("start", {}).get(key) != "sent":
            continue
        outcomes = state.setdefault(phase, {})
        if key in outcomes:
            continue
        outcomes[key] = "attempted"
        save_state(path, state)
        try:
            await send(target, message(target["discord_user_id"], phase))
        except Exception as exc:
            outcomes[key] = "failed"
            failed += 1
            # Exception strings can contain HTTP credentials or database URLs.
            print(f"::warning::Discord deployment notice failed ({type(exc).__name__}).")
        else:
            outcomes[key] = "sent"
            sent += 1
        save_state(path, state)
    return sent, failed


async def run(args) -> int:
    from dotenv import dotenv_values

    config = dict(dotenv_values(args.env_file, interpolate=False))
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID"):
        if os.environ.get(key):
            config[key] = os.environ[key]
    token, guild = config.get("DISCORD_BOT_TOKEN"), config.get("DISCORD_GUILD_ID")
    if not token or not guild:
        print("::warning::Discord deployment notice skipped: bot token or guild ID is missing.")
        return 0
    path = args.state_file
    if args.phase == "start":
        if path.exists():
            state = json.loads(path.read_text(encoding="utf-8"))
        else:
            state = {"guild_id": guild, "targets": await targets(config["DATABASE_URL"], guild)}
    else:
        if not path.exists():
            print("No initial Discord notice; no completion message to send.")
            return 0
        state = json.loads(path.read_text(encoding="utf-8"))
    if state["guild_id"] != guild:
        raise ValueError("Discord guild changed during deployment")
    if args.dry_run:
        print(json.dumps({"phase": args.phase, "targets": len(state["targets"]), "discord_messages_sent": 0}))
        return 0

    import discord

    async with discord.Client(intents=discord.Intents.none(), allowed_mentions=discord.AllowedMentions.none()) as client:
        # HTTP login only: no Gateway connection, command sync or bot-ready hooks.
        await client.login(token)

        async def send(target, content):
            channel = await client.fetch_channel(int(target["channel_id"]))
            if str(getattr(getattr(channel, "guild", None), "id", "")) != guild:
                raise ValueError("Personal channel belongs to a different guild")
            await channel.send(content, allowed_mentions=discord.AllowedMentions(
                everyone=False, roles=False, users=[discord.Object(int(target["discord_user_id"]))], replied_user=False))

        sent, failed = await deliver(state, path, args.phase, send)
    print(json.dumps({"phase": args.phase, "sent": sent, "failed": failed, "targets": len(state["targets"])}))
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("start", "success", "failure", "cancelled"), required=True)
    parser.add_argument("--state-file", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(asyncio.wait_for(run(args), timeout=150))
    except Exception as exc:
        print(f"::warning::Discord deployment notification unavailable ({type(exc).__name__}).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
