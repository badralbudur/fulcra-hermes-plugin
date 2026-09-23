"""Agent-facing handler safety regressions; no account requests."""
import ast
import json
import os
import subprocess
import unittest
from unittest.mock import patch
from test_tools import ROOT, load_tools


class DocumentationTests(unittest.TestCase):
    def test_all_functions_have_docstrings_including_wrappers(self):
        tree = ast.parse((ROOT / "tools.py").read_text())
        missing = [node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not ast.get_docstring(node)]
        self.assertEqual(missing, [])


class ErrorTests(unittest.TestCase):
    def test_exception_types_diagnostics_and_secrets(self):
        tools = load_tools()
        diagnostic = ('\x1b[31mdenied /safe/path\x1b[0m password="two words" '
                      'access_token=access refresh_token: refresh client_secret=client '
                      'API key: apikey Authorization: Bearer bearer device_code=device '
                      'ambient-secret\x00')
        with patch.dict(os.environ, {"TEST_API_KEY": "ambient-secret"}), \
             patch.object(tools, "_run_cli", side_effect=PermissionError(diagnostic)):
            result = tools.fulcra_data_catalog({})
        self.assertIn("PermissionError", result)
        self.assertIn("denied /safe/path", result)
        for secret in ('two words', '=access', ': refresh', '=client', ': apikey',
                       'Bearer bearer', '=device', 'ambient-secret', '\x1b', '\x00'):
            self.assertNotIn(secret, result)

    def test_credential_id_token_basic_and_url_userinfo(self):
        tools = load_tools()
        cases = (
            ('FulcraCredentials(id_token=\'private-jwt\', expires_at=123)', 'private-jwt'),
            ('{"id_token": "private-json-jwt"}', 'private-json-jwt'),
            ('Authorization: Basic dXNlcjpwYXNz', 'dXNlcjpwYXNz'),
            ('{"Authorization": "Basic Zm9vOmJhcg=="}', 'Zm9vOmJhcg=='),
            ('GET https://alice:p%40ss@example.test/safe/path?limit=2', 'alice:p%40ss'),
            ('GET https://private-user@example.test/safe/path?limit=2', 'private-user'),
        )
        for diagnostic, secret in cases:
            with self.subTest(diagnostic=diagnostic), patch.object(
                    tools, '_run_cli', side_effect=RuntimeError(diagnostic + ' denied')):
                result = tools.fulcra_data_catalog({})
                self.assertNotIn(secret, result)
                self.assertIn('RuntimeError', result)
                self.assertIn('denied', result)
                if 'https://' in diagnostic:
                    self.assertIn('example.test/safe/path?limit=2', result)
        with patch.object(tools, '_run_cli', side_effect=RuntimeError(
                'Basic troubleshooting: identity_token=public https://example.test/safe/path')):
            result = tools.fulcra_data_catalog({})
        self.assertIn('Basic troubleshooting: identity_token=public https://example.test/safe/path', result)

    def test_device_code_redacted_from_unexpected_errors(self):
        tools = load_tools()
        with patch.object(tools, "_run_cli", side_effect=KeyError("opaque-device")):
            result = tools.fulcra_auth_device({"device_code": "opaque-device"})
        self.assertIn("KeyError", result)
        self.assertNotIn("opaque-device", result)

    def test_timeout_at_handler_boundary_never_formats_exception(self):
        tools = load_tools()
        error = subprocess.TimeoutExpired(['secret-argv'], 1, output='secret-output', stderr='secret-stderr')
        with patch.object(tools, "_run_cli", side_effect=error):
            result = tools.fulcra_data_catalog({})
        self.assertIn("TimeoutExpired", result)
        self.assertIn("uncertain", result)
        self.assertIn("verify", result)
        self.assertNotIn("secret", result)


class ShareGuardTests(unittest.TestCase):
    ID = '01234567-89ab-cdef-0123-456789abcdef'
    TIME = '2026-01-01T00:00:00Z'

    def test_paths_are_guarded_in_every_selector(self):
        tools = load_tools()
        for field in ('path', 'files', 'add_files', 'remove_files', 'set_files'):
            for path in ('relative', '/a/../b', '/./a', '/a\\b', '//a', '/a//b', '/a\x00'):
                name = 'fulcra_file_stat' if field == 'path' else ('fulcra_create_share' if field == 'files' else 'fulcra_update_share')
                args = ({'path': path} if field == 'path' else
                        {'files': [path], 'user_ids': [self.ID]} if field == 'files' else
                        {'share_id': self.ID, field: [path]})
                with self.subTest(field=field, path=path), patch.object(tools, '_run_cli') as run:
                    self.assertTrue(getattr(tools, name)(args).startswith('Error'))
                    run.assert_not_called()
        with patch.object(tools, '_run_cli', return_value='ok'):
            self.assertEqual(tools.fulcra_create_share({'files': ['/'], 'user_ids': [self.ID]}), 'ok')

    def test_explicit_file_or_all_scope_with_bounds_is_rejected(self):
        tools = load_tools()
        for name, args in (
            ('fulcra_create_share', {'user_ids': [self.ID], 'files': ['/']}),
            ('fulcra_create_share', {'user_ids': [self.ID], 'share_all': True}),
            ('fulcra_update_share', {'share_id': self.ID, 'add_files': ['/']}),
            ('fulcra_update_share', {'share_id': self.ID, 'set_files': ['/']}),
            ('fulcra_update_share', {'share_id': self.ID, 'share_all': True}),
        ):
            with self.subTest(args=args), patch.object(tools, '_run_cli') as run:
                self.assertIn('time bounds', getattr(tools, name)({**args, 'start_time': self.TIME}))
                run.assert_not_called()

    def test_bounds_inspect_jsonl_and_fail_closed(self):
        tools = load_tools()
        safe = {'id': self.ID, 'fulcra_data_types': ['HeartRate'], 'share_all_data': False}
        for row in (safe, {**safe, 'fulcra_data_types': ['file:/']},
                    {**safe, 'fulcra_data_types': ['filehistory:/']},
                    {**safe, 'share_all_data': True}, {'id': self.ID},
                    {**safe, 'share_all_data': 'false'}, {**safe, 'fulcra_data_types': None}):
            with self.subTest(row=row), patch.object(tools, '_run_cli', side_effect=[json.dumps(row)+'\n', 'updated']) as run:
                result = tools.fulcra_update_share({'share_id': self.ID, 'start_time': self.TIME})
                self.assertEqual(result == 'updated', row == safe)
                self.assertEqual(run.call_args_list[0].args[0], ['share', 'list-outgoing'])
                self.assertEqual(run.call_count, 2 if row == safe else 1)
        for raw in ('', '[]', 'not json', json.dumps(safe)+'\n'+json.dumps(safe)):
            with patch.object(tools, '_run_cli', return_value=raw) as run:
                self.assertTrue(tools.fulcra_update_share({'share_id': self.ID, 'end_time': self.TIME}).startswith('Error'))
                self.assertEqual(run.call_count, 1)

    def test_safe_removal_and_clear_transitions(self):
        tools = load_tools()
        row = {'id': self.ID, 'fulcra_data_types': ['file:/', 'HeartRate'], 'share_all_data': True}
        for changes in ({'clear': True, 'add_data_types': ['HeartRate']},
                        {'remove_files': ['/'], 'share_all': False},
                        {'set_data_types': ['HeartRate'], 'share_all': False}):
            with patch.object(tools, '_run_cli', side_effect=[json.dumps(row), 'updated']):
                self.assertEqual(tools.fulcra_update_share({'share_id': self.ID, 'start_time': self.TIME, **changes}), 'updated')
        row.update(time_start=self.TIME, time_end=None)
        with patch.object(tools, '_run_cli', return_value=json.dumps(row)) as run:
            self.assertIn('time bounds', tools.fulcra_update_share({'share_id': self.ID, 'add_files': ['/new']}))
            self.assertEqual(run.call_count, 1)
