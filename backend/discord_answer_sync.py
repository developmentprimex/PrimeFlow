"""Edit existing messages when their answer changed in PrimeFlow; never send one."""
import asyncio
import logging
import discord
import discord_m2_client as m2
import discord_ui as ui

log = logging.getLogger(__name__)


async def update_one(bot, claimed):
    actor = {key: claimed[key] for key in ('discord_user_id', 'guild_id', 'channel_id')}
    path = f"/bot/answer-sync/{claimed['source']}/{claimed['id']}"
    job = claimed
    try:
        # Recheck ownership, active link, current channel and latest platform
        # answer immediately before the Discord edit.
        job = (await bot.bridge(path + '/open', actor))['job']
        if not job:
            return
        channel = await bot.private_channel(job['guild_id'], job['channel_id'], job['discord_user_id'])
        message = await channel.fetch_message(int(job['message_id']))
        payload = job['payload']
        if job['source'] == 'm2':
            content, view = m2.prompt(payload), m2.controls(payload)
            embed = None
        elif payload['status']:
            content = ui.meeting_held_text(payload['meeting']['title'], payload['status'], payload['by']) + '\n*Përditësuar nga PrimeFlow.*'
            embed, view = None, None
        else:
            content, embed, view = ui.meeting_alert(payload)
        await message.edit(content=content, embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        await bot.bridge(path + '/ack', {**actor, 'fingerprint': job['fingerprint']})
    except discord.NotFound:
        # Deleted Discord messages stay deleted, rather than being recreated.
        await bot.bridge(path + '/ack', {**actor, 'fingerprint': job['fingerprint']})
    except Exception as exc:
        log.warning('Answer sync %s failed: %s', claimed['id'], type(exc).__name__)


async def deliver(bot):
    jobs = (await bot.bridge('/bot/answer-sync/claim', {}))['jobs']
    semaphore = asyncio.Semaphore(3)
    async def update(job):
        async with semaphore:
            await update_one(bot, job)
    await asyncio.gather(*(update(job) for job in jobs))
