import json
import os
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'backend/scripts/stop_discord_voice_workers.ps1'


class VoiceDependencyInstallTests(unittest.TestCase):
    def test_deploy_releases_voice_library_before_locked_install_and_restarts_the_bot(self):
        workflow = (ROOT / '.github/workflows/deploy.yml').read_text(encoding='utf-8')
        release = workflow.index('- name: Release Mira Voice Dependencies')
        prepare = workflow.index('- name: Prepare Backend')
        install = workflow.index('check_discord_voice.py --install')
        start = workflow.index('- name: Start Discord Assistant')
        self.assertLess(release, prepare)
        self.assertLess(prepare, install)
        self.assertLess(install, start)
        self.assertIn('stop_discord_voice_workers.ps1', workflow[release:prepare])

    @unittest.skipUnless(os.name == 'nt', 'Deployment runs on Windows')
    def test_worker_selection_excludes_frontend_and_other_workspaces(self):
        voice = r'C:\deployment with spaces\backend\discord-voice'
        cases = [
            (f'node.exe "{voice}\\worker.mjs"', True),
            (f'node.exe "{voice}\\host-worker.mjs" --check', True),
            (f'node.exe "{voice.lower()}\\worker.mjs"', True),
            ('node.exe C:\\other\\backend\\discord-voice\\worker.mjs', False),
            (f'node.exe "{voice}-other\\worker.mjs"', False),
            (f'node.exe "{voice}\\worker.mjs.backup"', False),
            (r'node.exe C:\deployment\frontend\node_modules\next\dist\bin\next start', False),
            ('', False),
        ]
        quote = lambda value: "'" + str(value).replace("'", "''") + "'"
        commands = [f'. {quote(SCRIPT)}', '$results = @()']
        commands.extend(
            f'$results += Test-PrimeFlowVoiceWorker -CommandLine {quote(command)} -VoiceDirectory {quote(voice)}'
            for command, _expected in cases
        )
        commands.append('ConvertTo-Json -InputObject $results -Compress')
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', '; '.join(commands)],
                                capture_output=True, text=True, timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [expected for _command, expected in cases])


if __name__ == '__main__':
    unittest.main()
