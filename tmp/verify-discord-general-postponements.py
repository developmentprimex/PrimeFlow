"""Read-only live checks for the general postponement entry point."""
import asyncio
import json
from pathlib import Path
import httpx
from dotenv import dotenv_values
config = dotenv_values(Path(r'\\192.168.10.8\C$\actions-runner\_work\PrimeFlow\PrimeFlow\backend\.env'))
actor = {'discord_user_id': '1493249068556750968', 'guild_id': config['DISCORD_GUILD_ID'], 'channel_id': '1564542782197075988'}
async def main():
    async with httpx.AsyncClient(timeout=45) as client:
        for base in ('http://192.168.10.8:8000', 'http://192.168.10.8:8080', 'https://api-flow.primexeu.com'):
            schema = await client.get(base + '/openapi.json')
            schema.raise_for_status()
            route = '/api/discord/bot/m2/postponements/tasks/{task_id}/open'
            assert route in schema.json()['paths'], 'New task route is not active'
            print(json.dumps({'api': base, 'general_postponement_route': True}))
        base = 'https://api-flow.primexeu.com/api/discord'
        headers = {'X-Primeflow-Discord-Secret': config['DISCORD_BRIDGE_SECRET']}
        response = await client.post(base + '/bot/tasks', json=actor, headers=headers)
        response.raise_for_status()
        data = response.json()
        assert data['full_name'] == 'Elza Preniqi'
        tasks = [row for row in data['tasks'] if row.get('status') != 'DONE']
        if tasks:
            response = await client.post(base + '/bot/m2/postponements/tasks/' + tasks[0]['id'] + '/open', json=actor, headers=headers)
            response.raise_for_status()
            result = response.json()
            assert result['source'] == 'task' and result['reasons']
            print(json.dumps({'verified_user': data['full_name'], 'owned_task_form': True, 'dates_and_reasons_available': True}))
        else:
            print(json.dumps({'verified_user': data['full_name'], 'open_tasks_today': 0}))
asyncio.run(main())
