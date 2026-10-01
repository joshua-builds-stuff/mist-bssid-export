"""Permission and content checks for interactive setup's .env writer."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bssid_export as be  # noqa: E402


class TestWriteEnvRestrictiveMode(unittest.TestCase):
    def test_creates_restrictive_file_with_expected_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / '.env'
            be.write_env_file(env_path, 'https://api.mist.com', 'dummy-token', 'dummy-org')

            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)
            self.assertIn('MIST_API_TOKEN=dummy-token\n', env_path.read_text())
            self.assertIn('MIST_ORG_ID=dummy-org\n', env_path.read_text())
            self.assertIn('MIST_API_URL=https://api.mist.com\n', env_path.read_text())

    def test_creates_missing_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / 'nested' / 'config' / '.env'
            be.write_env_file(env_path, 'https://api.mist.com', 'dummy-token', 'dummy-org')

            self.assertTrue(env_path.is_file())
            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_restricts_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = Path(tmp) / '.env'
            env_path.write_text('old token\n')
            env_path.chmod(0o644)

            be.write_env_file(env_path, 'https://api.mist.com', 'dummy-token', 'dummy-org')

            self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('old token', env_path.read_text())
