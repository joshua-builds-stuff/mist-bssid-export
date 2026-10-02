"""Atomic-replace checks for the .env writer when os.fchmod is unavailable."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bssid_export as be  # noqa: E402

OLD_CONTENT = b'MIST_API_TOKEN=previous-secret\nMIST_ORG_ID=old\n'


def _missing_fchmod(*_args, **_kwargs):
    raise AttributeError("module 'os' has no attribute 'fchmod'")


class _NoFchmod:
    """Remove os.fchmod for the duration, as on Windows Python 3.10-3.12."""

    def __enter__(self):
        self._saved = getattr(os, 'fchmod', None)
        if self._saved is not None:
            del os.fchmod
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            os.fchmod = self._saved
        return False


class TestWriteEnvAtomicReplace(unittest.TestCase):
    def _seed(self, tmp):
        env_path = Path(tmp) / '.env'
        env_path.write_bytes(OLD_CONTENT)
        return env_path

    def test_success_replaces_in_full_without_fchmod(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = self._seed(tmp)
            with _NoFchmod():
                self.assertFalse(hasattr(os, 'fchmod'))
                be.write_env_file(env_path, 'https://api.mist.com', 'new-token', 'new-org')

            self.assertEqual(
                env_path.read_text(encoding='utf-8'),
                "# Mist BSSID Export configuration (written by interactive setup)\n"
                "MIST_API_TOKEN=new-token\n"
                "MIST_ORG_ID=new-org\n"
                "MIST_API_URL=https://api.mist.com\n",
            )
            self.assertEqual(os.listdir(tmp), ['.env'])
            if os.name == 'posix':
                self.assertEqual(env_path.stat().st_mode & 0o777, 0o600)

    def test_fchmod_attribute_error_leaves_previous_env_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = self._seed(tmp)
            with mock.patch.object(os, 'fchmod', _missing_fchmod, create=True):
                with self.assertRaises(AttributeError):
                    be.write_env_file(env_path, 'https://api.mist.com', 'new-token', 'new-org')

            self.assertEqual(env_path.read_bytes(), OLD_CONTENT)
            self.assertEqual(os.listdir(tmp), ['.env'])

    def test_failure_before_replace_leaves_previous_env_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_path = self._seed(tmp)
            with _NoFchmod(), \
                    mock.patch.object(os, 'replace', side_effect=OSError('boom')):
                with self.assertRaises(OSError):
                    be.write_env_file(env_path, 'https://api.mist.com', 'new-token', 'new-org')

            self.assertEqual(env_path.read_bytes(), OLD_CONTENT)
            self.assertEqual(os.listdir(tmp), ['.env'])


if __name__ == '__main__':
    unittest.main()
