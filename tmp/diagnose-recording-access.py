import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
from app.config import settings


async def check(base):
    async with httpx.AsyncClient(base_url=base, timeout=25, trust_env=False) as client:
        login = await client.post('/auth/login', json={'email': settings.ADMIN_EMAIL, 'password': settings.ADMIN_PASSWORD})
        if login.status_code != 200:
            return {'api': base, 'login_status': login.status_code}
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        me = await client.get('/auth/me', headers=headers)
        listing = await client.get('/meeting-recordings?limit=100', headers=headers)
        rid = '78e048ae-6965-407d-96d4-99f21fe315fa'
        detail = await client.get('/meeting-recordings/' + rid, headers=headers)
        media = await client.head('/meeting-recordings/' + rid + '/stream', headers=headers)
        preview = await client.get('/meeting-recordings/' + rid + '/stream',
                                   headers={**headers, 'Range': 'bytes=0-1023'})
        rows = listing.json() if listing.status_code == 200 else []
        result = {'api': base, 'role': me.json().get('role') if me.status_code == 200 else me.status_code,
                'list_status': listing.status_code, 'count': len(rows),
                'nolte_in_list': any(r.get('id') == rid for r in rows),
                'nolte_detail': detail.status_code, 'media_status': media.status_code,
                'range_status': preview.status_code, 'range_bytes': len(preview.content),
                'container_valid': preview.content.startswith(b'\x1a\x45\xdf\xa3'),
                'media_available': detail.json().get('media_available') if detail.status_code == 200 else None}
        if base.startswith('https://'):
            grant = await client.post('/meeting-recordings/' + rid + '/playback', headers=headers)
            grant.raise_for_status()
            cookie = await client.post(f'https://primeflow.primexeu.com/api/meeting-recordings/{rid}/playback',
                                       headers={'Origin': 'https://primeflow.primexeu.com'}, json=grant.json())
            result['website_grant'] = cookie.status_code
            for action in ('stream', 'download'):
                response = await client.get(f'https://primeflow.primexeu.com/api/meeting-recordings/{rid}/{action}',
                                            headers={'Range': 'bytes=0-1023'})
                result['website_' + action] = response.status_code
                result['website_' + action + '_valid'] = (len(response.content) == 1024 and response.content.startswith(b'\x1a\x45\xdf\xa3'))
        return result


async def main():
    for base in ['http://localhost:8000/api', 'https://api-flow.primexeu.com/api']:
        try:
            print(json.dumps(await check(base)))
        except httpx.HTTPError as exc:
            print(json.dumps({'api': base, 'error': type(exc).__name__}))

asyncio.run(main())
