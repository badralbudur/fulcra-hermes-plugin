"""Credential lifecycle regressions; network responses are test fixtures."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fulcra_api.cli import utils
from fulcra_api.credentials import FulcraCredentials

spec = importlib.util.spec_from_file_location(
    "context_tools_credentials", Path(__file__).resolve().parents[1] / "tools.py"
)
assert spec is not None and spec.loader is not None
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


class CredentialTests(unittest.TestCase):
    def test_catalog_uses_saved_credentials(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            with patch.object(utils, "CREDS_FILE", Path(directory) / "creds.json"):
                utils.save_creds(FulcraCredentials(access_token="test-token", access_token_expiration=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)))

                def catalog(client):
                    self.assertIsNotNone(client.fulcra_credentials)
                    self.assertEqual(client.fulcra_credentials.access_token, "test-token")
                    self.assertTrue(callable(client.refresh_callback))
                    return [{"id": "test-fixture"}]

                with patch.object(tools.FulcraAPI, "v1_catalog", catalog):
                    self.assertEqual(json.loads(tools.fulcra_get_data_catalog({})), [{"id": "test-fixture"}])


if __name__ == "__main__":
    unittest.main()
