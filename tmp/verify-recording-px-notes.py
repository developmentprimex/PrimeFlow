import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
from app.config import settings

links = {
    'de789534-dc6e-44b6-b168-ebea83cec11a': ('226fe0f6-9ce1-546d-bc9d-93c41ade1a9a', 'DONE'),
    'a9a8179e-ea34-4292-835b-0df8fc210e11': ('651e91d3-4cb4-5b07-9aec-ac23079c8947', 'TODO'),
    '67f16386-038c-49db-bc5c-2fa55f7efc3f': ('213c1490-1759-5362-b64f-f4866df1d79c', 'IN_PROGRESS'),
}

async def main():
    async with httpx.AsyncClient(base_url='https://api-flow.primexeu.com/api', timeout=30, trust_env=False) as client:
        login = await client.post('/auth/login', json={'email': settings.ADMIN_EMAIL, 'password': settings.ADMIN_PASSWORD})
        login.raise_for_status()
        headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
        response = await client.get('/ga-notes', headers=headers)
        response.raise_for_status()
        notes = {note['id']: note for note in response.json()}
        for task_id, (note_id, expected_status) in links.items():
            assert note_id in notes, 'Note absent from public PX Notes list'
            response = await client.get('/tasks/' + task_id, headers=headers)
            response.raise_for_status()
            task = response.json()
            assert task['ga_note_origin_id'] == note_id
            assert task['title'] == notes[note_id]['content']
            assert task['status'] == expected_status
            assert notes[note_id]['is_converted_to_task']
            print(json.dumps({'verified_task': task_id, 'note_id': note_id, 'status_preserved': expected_status,
                              'visible_in_public_px_notes': True}))

asyncio.run(main())
