"""Contract tests against the installed Fulcra SDK (no network calls)."""
import importlib.util
from pathlib import Path
import unittest


class SDKContractTests(unittest.TestCase):
    def test_plugin_imports_and_sdk_supports_handlers(self):
        spec = importlib.util.spec_from_file_location(
            "context_plugin_tools", Path(__file__).resolve().parents[1] / "tools.py"
        )
        assert spec is not None and spec.loader is not None
        tools = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(tools)
        except ImportError as exc:
            self.fail(f"Plugin imports fail: {exc}")
        api = tools.FulcraAPI()
        self.assertTrue(callable(getattr(api, "v1_catalog", None)))
        oidc = getattr(api, "oidc", None)
        self.assertTrue(callable(getattr(oidc, "get_device_code", None)))
        self.assertTrue(callable(getattr(oidc, "poll_for_token", None)))
        self.assertTrue(callable(tools.save_creds))
        self.assertEqual(tools.save_creds.__module__, "fulcra_api.cli.utils")


if __name__ == "__main__":
    unittest.main()
