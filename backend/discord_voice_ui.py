"""Private text-only meeting controls, safe after bot restarts."""
import io
import hashlib
import json
from datetime import datetime, timedelta
import discord
from discord.http import handle_message_parameters
from app.config import settings
from app.services.discord_voice_note_format import QUICK_SECTIONS, albanian_date, meeting_url


def meeting_view(row):
    view=discord.ui.View(timeout=None);sid=row['id'];state=row['status']
    if state in ('STARTING','LISTENING'):
        view.add_item(discord.ui.Button(label='Përfundo takimin',style=discord.ButtonStyle.danger,custom_id=f'pf:vm:stop:{sid}'))
    elif state=='READY':
        view.add_item(discord.ui.Button(label='Shiko shënimet',custom_id=f'pf:vm:view:{sid}'))
        view.add_item(discord.ui.Button(label='Ruaj në PX Notes',style=discord.ButtonStyle.success,custom_id=f'pf:vm:save:{sid}'))
    elif state=='SAVED' and row.get('note_url'):
        view.add_item(discord.ui.Button(label='Hap takimin',url=row['note_url']))
    return view


def result_message(row):
    quick = row.get('quick_summary')
    if quick:
        date = albanian_date(datetime.fromisoformat(row['started_at'])) if row.get('started_at') else ''
        lines = [' | '.join(filter(None, (date, discord.utils.escape_markdown(row['title']))))]
        if row.get('partial'):
            lines.append('⚠️ Regjistrimi ose transkripti është i pjesshëm.')
        header = '\n\n'.join(lines)
        for key, label in QUICK_SECTIONS.items():
            items = ['• ' + discord.utils.escape_markdown(item, ignore_links=False) for item in quick[key]]
            lines.append('\n'.join([f'**{label}**', *(items or ['—'])]))
        links = (f"[Shënimet e plota]({meeting_url(row['id'], 'full')}) | "
                 f"[Transkripti]({meeting_url(row['id'], 'transcript')})")
        description = '\n\n'.join([*lines, links])
        if len(description.encode('utf-16-le')) // 2 <= 4096:
            return {'embed': discord.Embed(title='MIRA | Meeting Notes', description=description), 'view': meeting_view(row)}
        # Discord counts the escaped rendering. Keep all points when markup makes it too long.
        plain = '\n\n'.join('\n'.join([label, *(quick[key] or ['—'])]) for key, label in QUICK_SECTIONS.items())
        return {'embed': discord.Embed(title='MIRA | Meeting Notes', description='\n\n'.join([header, links])),
            'view': meeting_view(row), 'file': discord.File(io.BytesIO(plain.encode('utf-8')), filename='permbledhja.txt')}
    text=row.get('draft_text') or row.get('error') or 'Shënimet po përgatiten.'
    embed=discord.Embed(title='Shënimet e takimit',description=text if len(text)<=1800 else None)
    parts={'embed':embed,'view':meeting_view(row)}
    if len(text)>1800:parts['file']=discord.File(io.BytesIO(text.encode('utf-8')),filename='shenimet-e-takimit.txt')
    return parts


async def send_durable(bot, channel, row):
    marker=f"Mira takim · {row['id']}"
    marker_url = meeting_url(row['id'], 'quick' if row.get('quick_summary') else 'full')
    legacy_urls = {f"{settings.FRONTEND_URL.rstrip('/')}/mira?tab={tab}&meeting={row['id']}"
                   for tab in ('notetaker', 'shenimet')}
    created=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None
    async for previous in channel.history(limit=None,after=created-timedelta(seconds=5) if created else None):
        if previous.author.id==bot.user.id and any(e.footer.text==marker or e.url==marker_url or e.url in legacy_urls for e in previous.embeds):return [str(previous.id)]
    parts=result_message(row);parts['embed'].url=marker_url
    nonce=hashlib.sha256(marker.encode()).hexdigest()[:24]
    try:
        with handle_message_parameters(**parts,nonce=nonce,allowed_mentions=discord.AllowedMentions.none()) as params:
            if params.payload is not None:params.payload['enforce_nonce']=True
            else:
                for field in params.multipart:
                    if field.get('name')=='payload_json':
                        body=json.loads(field['value']);body['enforce_nonce']=True;field['value']=json.dumps(body)
            sent=await bot.http.send_message(channel.id,params=params)
            return [str(sent['id'])]
    finally:
        if 'file' in parts:parts['file'].close()
