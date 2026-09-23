"""Bounded final output and private artifact regressions."""

from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from test_tools import load_tools


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.tools = load_tools()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        module = types.ModuleType('hermes_constants')
        module.get_hermes_home = lambda: self.home
        stub = patch.dict(sys.modules, {'hermes_constants': module})
        stub.start()
        self.addCleanup(stub.stop)

    def artifact(self, output):
        self.assertIn('[TRUNCATED', output)
        self.assertLess(len(output.encode('utf-8')), 18000)
        path = Path(output.split('Complete UTF-8 text: ', 1)[1].split('\n', 1)[0])
        self.assertTrue(path.is_absolute())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertTrue(path.is_relative_to(self.home))
        return path

    def test_small_and_boundary_results_untouched(self):
        for raw in ('', '  hello\n', 'é' * 8000):
            with patch.object(self.tools, '_run_cli', return_value=raw):
                self.assertEqual(self.tools.fulcra_data_catalog({}), raw)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_utf8_complete_artifact_unique_and_active_profile(self):
        raw = '€' * 10001 + '\n'
        paths = []
        base = self.home
        for profile in ('first', 'second', 'second'):
            self.home = base / profile
            self.home.mkdir(exist_ok=True)
            with patch.object(self.tools, '_run_cli', return_value=raw):
                output = self.tools.fulcra_data_catalog({})
            path = self.artifact(output)
            paths.append(path)
            self.assertEqual(path.read_bytes(), raw.encode('utf-8'))
            preview = output.split('\n[TRUNCATED', 1)[0]
            self.assertLessEqual(len(preview.encode('utf-8')), 16000)
            self.assertNotIn('�', preview)
        self.assertEqual(len(set(paths)), 3)

    def test_combined_listing_and_download_are_bounded_once(self):
        raw = 'x' * 10000
        with patch.object(self.tools, '_run_cli', return_value=raw):
            result = self.tools.fulcra_list_shares({})
        path = self.artifact(result)
        self.assertEqual(path.read_text(), f'incoming:\n{raw}\n\noutgoing:\n{raw}')
        self.assertEqual(result.count('[TRUNCATED'), 1)
        text = 'é' * 16000
        def download(argv):
            Path(argv[3]).write_text(text, encoding='utf-8')
            return 'Downloaded'
        with patch.object(self.tools, '_run_cli', side_effect=download):
            result = self.tools.fulcra_file_download({'path': '/fixture'})
        self.assertEqual(self.artifact(result).read_text(), text)

    def test_only_sanitized_errors_persist(self):
        raw = 'password="hidden password" Bearer hidden-token\x1b[31m denied\n' + 'x' * 20000
        with patch.object(self.tools, '_run_cli', side_effect=PermissionError(raw)):
            output = self.tools.fulcra_data_catalog({})
        full = self.artifact(output).read_text()
        self.assertIn('PermissionError', full)
        self.assertIn('denied', full)
        for value in ('hidden password', 'hidden-token', '\x1b'):
            self.assertNotIn(value, output + full)

    def test_saved_error_redacts_id_token_basic_and_url_userinfo(self):
        raw = ('FulcraCredentials(id_token="private-jwt") '
               'Authorization: Basic dXNlcjpwYXNz '
               'https://alice:p%40ss@example.test/safe/path denied\n' + 'x' * 20000)
        with patch.object(self.tools, '_run_cli', side_effect=RuntimeError(raw)):
            output = self.tools.fulcra_data_catalog({})
        full = self.artifact(output).read_text()
        for secret in ('private-jwt', 'dXNlcjpwYXNz', 'alice:p%40ss'):
            self.assertNotIn(secret, output + full)
        self.assertIn('example.test/safe/path denied', full)

    def test_oversized_real_cli_auth_success_without_persistence(self):
        raw = 'warning\n' * 4000 + '✅ Authorization successful!\n'
        with patch.object(self.tools, '_run_cli', return_value=raw):
            output = self.tools.fulcra_auth_device({'device_code': 'fixture'})
        self.assertFalse(output.startswith('Error:'), output)
        self.assertIn('✅ Authorization successful!', output)
        self.assertLess(len(output.encode()), 18000)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_storage_uses_exclusive_relative_open_without_procfs(self):
        real_open = self.tools.os.open
        creations = []
        def checked_open(path, flags, mode=0o777, *, dir_fd=None):
            self.assertNotIn('/proc/', str(path))
            if flags & self.tools.os.O_CREAT:
                creations.append(path)
                self.assertFalse(Path(path).is_absolute())
                self.assertIsNotNone(dir_fd)
                self.assertTrue(flags & self.tools.os.O_EXCL)
                self.assertTrue(flags & self.tools.os.O_WRONLY)
                self.assertEqual(mode, 0o600)
            return real_open(path, flags, mode, dir_fd=dir_fd)
        with patch.object(self.tools.os, 'open', side_effect=checked_open), \
             patch.object(self.tools, '_run_cli', return_value='x' * 20000):
            output = self.tools.fulcra_data_catalog({})
        self.assertEqual(self.artifact(output).read_text(), 'x' * 20000)
        self.assertEqual(len(creations), 1)

    def test_collision_retries_without_overwriting_or_unlinking_existing_file(self):
        store = self.home / 'fulcra-output'
        store.mkdir(mode=0o700)
        existing = store / ('result-' + 'a' * 32 + '.txt')
        existing.write_text('keep me')
        for tokens, success in ((['a' * 32, 'b' * 32], True), (['a' * 32] * 100, False)):
            with self.subTest(success=success), \
                 patch('secrets.token_hex', side_effect=tokens), \
                 patch.object(self.tools, '_run_cli', return_value='x' * 20000):
                output = self.tools.fulcra_data_catalog({})
                if success:
                    path = self.artifact(output)
                    self.assertEqual(path.name, 'result-' + 'b' * 32 + '.txt')
                    self.assertEqual(path.read_text(), 'x' * 20000)
                else:
                    self.assertTrue(output.startswith('Error:'), output[:100])
                self.assertEqual(existing.read_text(), 'keep me')

    def test_auth_preserves_codes_without_persistence(self):
        codes = 'Web auth URL: https://example.test\n- Web auth code: ABCD\n- Device code: private-device\n'
        for raw in (codes, 'warning\n' * 4000 + codes):
            with patch.object(self.tools, '_run_cli', return_value=raw):
                output = self.tools.fulcra_auth({})
            self.assertIn(codes.strip(), output)
            self.assertLess(len(output.encode()), 18000)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_persistence_failure_is_bounded_and_honest(self):
        real_open = self.tools.os.open
        def fail_create(path, flags, mode=0o777, *, dir_fd=None):
            if flags & self.tools.os.O_CREAT:
                raise OSError('password=secret disk full')
            return real_open(path, flags, mode, dir_fd=dir_fd)
        with patch.object(self.tools, '_run_cli', return_value='x' * 50000), \
             patch.object(self.tools.os, 'open', side_effect=fail_create):
            output = self.tools.fulcra_data_catalog({})
        self.assertTrue(output.startswith('Error:'))
        self.assertIn('artifact', output)
        self.assertIn('verify', output)
        self.assertNotIn('Complete UTF-8 text:', output)
        self.assertNotIn('secret', output)
        self.assertLess(len(output.encode()), 18000)
        self.assertFalse(list(self.home.rglob('*.txt')))

    def test_failed_write_removes_partial_artifact(self):
        with patch.object(self.tools, '_run_cli', return_value='x' * 20000), \
             patch.object(self.tools.os, 'fchmod', side_effect=OSError('disk failure')):
            output = self.tools.fulcra_data_catalog({})
        self.assertTrue(output.startswith('Error:'))
        self.assertFalse(list(self.home.rglob('*.txt')))

    def test_directory_swap_cannot_redirect_artifact(self):
        store = self.home / 'fulcra-output'
        moved = self.home / 'moved'
        outside = self.home / 'outside'
        outside.mkdir()
        real_open = self.tools.os.open
        def swap(path, flags, mode=0o777, *, dir_fd=None):
            if flags & self.tools.os.O_CREAT:
                store.rename(moved)
                store.symlink_to(outside, target_is_directory=True)
            return real_open(path, flags, mode, dir_fd=dir_fd)
        with patch.object(self.tools, '_run_cli', return_value='x' * 20000), \
             patch.object(self.tools.os, 'open', side_effect=swap):
            output = self.tools.fulcra_data_catalog({})
        self.assertTrue(output.startswith('Error:'))
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(list(moved.iterdir()), [])

    def test_large_auth_error_artifact_contains_no_device_code(self):
        with patch.object(self.tools, '_run_cli', side_effect=RuntimeError('opaque-code ' + 'x' * 20000)):
            output = self.tools.fulcra_auth_device({'device_code': 'opaque-code'})
        self.assertNotIn('opaque-code', self.artifact(output).read_text() + output)

    def test_incomplete_oversized_auth_fields_are_not_success(self):
        with patch.object(self.tools, '_run_cli', return_value='x' * 20000 + '\nWeb auth URL: https://example.test'):
            output = self.tools.fulcra_auth({})
        self.assertTrue(output.startswith('Error:'))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_symlink_and_insecure_directory_refused(self):
        outside = self.home / 'outside'
        outside.mkdir()
        store = self.home / 'fulcra-output'
        store.symlink_to(outside, target_is_directory=True)
        for kind in ('symlink', 'permissions'):
            with patch.object(self.tools, '_run_cli', return_value='x' * 20000):
                output = self.tools.fulcra_data_catalog({})
            self.assertTrue(output.startswith('Error:'), output[:100])
            self.assertFalse(list(outside.iterdir()))
            if kind == 'symlink':
                store.unlink()
                store.mkdir(mode=0o755)
        store.rmdir()
        actual = self.home
        self.home = actual / 'linked-home'
        self.home.symlink_to(outside, target_is_directory=True)
        with patch.object(self.tools, '_run_cli', return_value='x' * 20000):
            output = self.tools.fulcra_data_catalog({})
        self.assertTrue(output.startswith('Error:'))
        self.assertFalse(list(outside.iterdir()))
