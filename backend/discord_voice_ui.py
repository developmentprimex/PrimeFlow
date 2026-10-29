"""Private text-only meeting controls, safe after bot restarts."""
import io
import hashlib
import json
from datetime import datetime, timedelta
import discord
from discord.http import handle_message_parameters
from app.config import settings


def meeting_view(row):
    view=discord.ui.View(timeout=None);sid=row['id'];state=row['status']
    if state in ('STARTING','LISTENING'):
        view.add_item(discord.ui.Button(label='Përfundo takimin',style=discord.ButtonStyle.danger,custom_id=f'pf:vm:stop:{sid}'))
    elif state=='READY':
        view.add_item(discord.ui.Button(label='Shiko shënimet',custom_id=f'pf:vm:view:{sid}'))
        view.add_item(discord.ui.Button(label='Ruaj në PX Notes',style=discord.ButtonStyle.success,custom_id=f'pf:vm:save:{sid}'))
    elif state=='SAVED' and row.get('note_url'):
        view.add_item(discord.ui.Button(label='Hap PX Notes',url=row['note_url']))
    return view


def result_message(row):
    text=row.get('draft_text') or row.get('error') or 'Shënimet po përgatiten.'
    embed=discord.Embed(title='Shënimet e takimit',description=text if len(text)<=1800 else None)
    parts={'embed':embed,'view':meeting_view(row)}
    if len(text)>1800:parts['file']=discord.File(io.BytesIO(text.encode('utf-8')),filename='shenimet-e-takimit.txt')
    return parts


async def send_durable(bot, channel, row):
    marker=f"Mira takim · {row['id']}"
    marker_url=settings.FRONTEND_URL.rstrip('/')+'/mira?tab=shenimet&meeting='+row['id']
    created=datetime.fromisoformat(row['created_at']) if row.get('created_at') else None
    async for previous in channel.history(limit=None,after=created-timedelta(seconds=5) if created else None):
        if previous.author.id==bot.user.id and any(e.footer.text==marker or e.url==marker_url for e in previous.embeds):return [str(previous.id)]
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
