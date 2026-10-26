"""Pure staging tests: no server access or task execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch


class ActivationTests(unittest.TestCase):
    def test_process_output_accepts_pm2_utf8_symbols_without_failing_activation(self):
        root=Path(__file__).resolve().parents[2]
        spec=importlib.util.spec_from_file_location('mira_activation',root/'desktop/activate_server.py')
        activate=importlib.util.module_from_spec(spec);spec.loader.exec_module(activate)
        with tempfile.TemporaryDirectory(dir=root/'tmp') as directory:
            base=Path(directory)
            with patch.multiple(activate,ROOT=base,OPS=base):
                activate.command([sys.executable,'-c',"import os; os.write(1,bytes([240,159,154,128]))"])
            self.assertIn('\U0001f680',(base/'commands.log').read_text(encoding='utf-8'))

    def test_scoped_staging_preserves_existing_registrations_and_has_no_auto_trigger(self):
        root=Path(__file__).resolve().parents[2]
        spec=importlib.util.spec_from_file_location('mira_staging',root/'desktop/stage_server.py')
        stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
        with tempfile.TemporaryDirectory(dir=root/'tmp') as directory:
            base=Path(directory);remote=base/'server';ops=base/'ops'
            router=remote/'app/api/routers/__init__.py';router.parent.mkdir(parents=True)
            router.write_text('from existing_m2 import router\napi_router = APIRouter()\n# preserve M2\n')
            models=remote/'app/models/__init__.py';models.parent.mkdir(parents=True)
            models.write_text('from existing_m2 import Model\n')
            with patch.multiple(stage,REMOTE=remote,OPS=ops,STATE_DIR=base/'state'),patch.object(stage.subprocess,'run') as run:
                stage.main()
            manifest=json.loads((ops/'manifest.json').read_text())
            self.assertEqual(len(manifest),8)
            self.assertTrue(all('discord_voice' not in row['path'] and 'discord_bot' not in row['path'] for row in manifest))
            self.assertIn('preserve M2',(ops/'staged/app/api/routers/__init__.py').read_text())
            self.assertIn('existing_m2',(ops/'staged/app/models/__init__.py').read_text())
            xml=(base/'state/mira-activate-server.xml').read_text(encoding='utf-16')
            self.assertNotIn('<Triggers>',xml)
            self.assertIn('S-1-5-18',xml)
            self.assertEqual(run.call_count,2)
