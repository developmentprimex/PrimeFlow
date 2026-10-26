"""Run reply regressions in disposable schemas without exposing DB credentials."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.config import settings
os.environ['M2_TEST_DATABASE_URL'] = settings.DATABASE_URL
import pytest
raise SystemExit(pytest.main(['tests/test_discord_m2.py', 'tests/test_discord_m2_database.py', '-q', '--tb=short', *sys.argv[1:]]))
