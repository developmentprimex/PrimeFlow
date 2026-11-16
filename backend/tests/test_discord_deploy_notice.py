import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from scripts.notify_discord_deploy import deliver, message


class DeployNoticeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_successful_start_recipients_receive_completion_and_replays_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'notice.json'
            state = {'guild_id': '1', 'targets': [
                {'discord_user_id': '11', 'channel_id': '111'},
                {'discord_user_id': '22', 'channel_id': '222'},
            ]}
            sender = AsyncMock(side_effect=[None, RuntimeError('private-secret')])
            self.assertEqual(await deliver(state, path, 'start', sender), (1, 1))
            self.assertNotIn('private-secret', path.read_text())
            self.assertEqual(await deliver(state, path, 'start', sender), (0, 0))
            completed = AsyncMock()
            self.assertEqual(await deliver(state, path, 'success', completed), (1, 0))
            self.assertEqual(completed.call_args.args[0]['channel_id'], '111')
            self.assertEqual(await deliver(state, path, 'success', completed), (0, 0))

    async def test_interrupted_send_is_recorded_and_never_claimed_successful(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'notice.json'
            state = {'targets': [{'discord_user_id': '11', 'channel_id': '111'}]}
            with self.assertRaises(asyncio.CancelledError):
                await deliver(state, path, 'start', AsyncMock(side_effect=asyncio.CancelledError()))
            saved = json.loads(path.read_text())
            self.assertEqual(saved['start']['111'], 'attempted')
            sender = AsyncMock()
            self.assertEqual(await deliver(saved, path, 'start', sender), (0, 0))
            self.assertEqual(await deliver(saved, path, 'failure', sender), (0, 0))
            sender.assert_not_awaited()

    def test_notice_states_seven_minutes_and_failure_never_claims_ready(self):
        self.assertIn('**7 minuta**', message('11', 'start'))
        self.assertIn('<@11>', message('11', 'start'))
        self.assertIn('Mund të vazhdoni', message('11', 'success'))
        self.assertNotIn('Mund të vazhdoni', message('11', 'failure'))
        self.assertIn('nuk përfundoi', message('11', 'failure'))

    def test_workflow_notifies_before_env_replacement_and_service_stop(self):
        import yaml
        workflow = Path(__file__).resolve().parents[2] / '.github/workflows/deploy.yml'
        steps = yaml.safe_load(workflow.read_text(encoding='utf-8'))['jobs']['deploy']['steps']
        names = [step['name'] for step in steps]
        self.assertLess(names.index('Notify Discord before deployment'), names.index('Create Env Files'))
        self.assertLess(names.index('Notify Discord before deployment'), names.index('Apply Database Migrations'))
        self.assertEqual(names[-1], 'Notify Discord of deployment result')
        self.assertIn('job.status', steps[-1]['env']['DEPLOYMENT_STATUS'])


if __name__ == '__main__':
    unittest.main()
