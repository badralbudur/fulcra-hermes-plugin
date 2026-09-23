"""Opt-in integration test of credential ownership in the published CLI.

FULCRA_CLI_SMOKE=1 python3 -m unittest discover -s tests -v
Downloads the pinned CLI into uv's cache. Uses only temporary fixture credentials;
no authentication or Fulcra network requests are made.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_tools import load_tools


@unittest.skipUnless(os.environ.get("FULCRA_CLI_SMOKE") == "1", "set FULCRA_CLI_SMOKE=1 for uv integration")
class CredentialTests(unittest.TestCase):
    def test_pinned_cli_expansion_against_fixture_api(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            result = subprocess.run(
                [shutil.which("uv"), "tool", "run", "--isolated", "--no-config", "--from", load_tools().FULCRA_PACKAGE,
                 "python", str(root / "tests" / "cli_fixture.py"), str(root), directory],
                capture_output=True, text=True, timeout=180,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PASS", result.stdout)

    def test_published_cli_loads_and_saves_credentials(self):
        uv = shutil.which("uv")
        self.assertIsNotNone(uv, "uv must be installed for this integration test")
        # Run SDK assertions inside uv's interpreter, never inside Hermes's.
        script = '''
import datetime, json, sys
from pathlib import Path
from click.testing import CliRunner
from fulcra_api.cli import cli, utils
from fulcra_api.core import FulcraAPI
from fulcra_api.credentials import FulcraCredentials
utils.CONFIG_PATH = Path(sys.argv[1])
utils.CREDS_FILE = utils.CONFIG_PATH / "credentials.json"
creds = FulcraCredentials(access_token="fixture-token", access_token_expiration=datetime.datetime.now() + datetime.timedelta(hours=1))
utils.save_creds(creds)
def catalog(client, **kwargs):
    assert client.fulcra_credentials.access_token == "fixture-token"
    assert callable(client.refresh_callback)
    client.fulcra_credentials.access_token = "fixture-refreshed"
    client.refresh_callback(client.fulcra_credentials)
    return [{"id": "fixture-catalog"}]
FulcraAPI.v1_catalog = catalog
result = CliRunner().invoke(cli, ["catalog"])
assert result.exit_code == 0, (result.output, repr(result.exception))
assert [json.loads(line) for line in result.output.splitlines()] == [{"id": "fixture-catalog", "related_cli_commands": []}], result.output
assert utils.load_creds().access_token == "fixture-refreshed"
print("CLI credential load/refresh persistence: PASS (fixtures only)")
'''
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
            probe = Path(directory) / "probe.py"
            probe.write_text(script)
            result = subprocess.run(
                [uv, "tool", "run", "--isolated", "--no-config", "--from", load_tools().FULCRA_PACKAGE,
                 "python", str(probe), directory],
                capture_output=True, text=True, timeout=180,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
