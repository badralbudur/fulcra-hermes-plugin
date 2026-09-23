"""Agent-facing handler safety regressions; no account requests."""
import ast
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
