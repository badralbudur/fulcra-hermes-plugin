"""Adapter regressions. No SDK, network, or real credentials are needed."""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_tools():
    spec = importlib.util.spec_from_file_location("context_adapter", ROOT / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.managed_bin = Path(temporary.name) / "managed bin"
        self.managed_bin.mkdir()
        # Stub only Hermes's path provider; executable lookup uses real files.
        managed_uv = types.ModuleType("hermes_cli.managed_uv")
        managed_uv.managed_uv_path = lambda: self.managed_bin / "uv"
        modules = patch.dict(sys.modules, {"hermes_cli.managed_uv": managed_uv})
        modules.start()
        self.addCleanup(modules.stop)

    def test_catalog_runs_pinned_cli_in_isolation(self):
        tools = load_tools()
        result = subprocess.CompletedProcess([], 0, '[{"id":"fixture"}]\n', '')
        with patch.object(tools, "_runtime_context", create=True, return_value=(True, {"PATH": "/bin"})), \
             patch("shutil.which", side_effect=lambda name, **kw: "/bin/uvx" if name == "uvx" else None), \
             patch("subprocess.run", return_value=result) as run:
            self.assertEqual(json.loads(tools.fulcra_get_data_catalog({})), json.loads(result.stdout))
        command = run.call_args.args[0]
        self.assertEqual(command, ["/bin/uvx", "--isolated", "--no-config", "--from", "fulcra-api==0.1.42", "fulcra-api", "catalog"])
        self.assertFalse(run.call_args.kwargs.get("shell", False))
        self.assertGreater(run.call_args.kwargs["timeout"], 0)

    def test_managed_uvx_is_found_outside_path(self):
        managed_bin = self.managed_bin
        uvx = managed_bin / ("uvx.exe" if os.name == "nt" else "uvx")
        uvx.touch()
        uvx.chmod(0o755)  # Discovery fixture only; subprocess execution is mocked.
        tools = load_tools()
        parent_path = os.environ.get("PATH")
        for path in ("", str(managed_bin.parent / "absent"), str(managed_bin)):
            env = {"PATH": path}
            with self.subTest(path=path), \
                 patch.object(tools, "_runtime_context", return_value=(True, env)), \
                 patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "[]", "")) as run:
                self.assertEqual(tools._run_cli(["catalog"]), "[]")
            self.assertEqual(run.call_args.args[0][0], str(uvx))
            child_path = run.call_args.kwargs["env"]["PATH"]
            expected = path if path == str(managed_bin) else os.pathsep.join(filter(None, (path, str(managed_bin))))
            self.assertEqual(child_path, expected)
            self.assertEqual(env["PATH"], path)
            self.assertEqual(os.environ.get("PATH"), parent_path)

    def test_authentication_uses_noninteractive_cli(self):
        tools = load_tools()
        with patch.object(tools, "_run_cli", return_value="Web auth URL: https://example.test\n- Device code: fixture") as run:
            output = tools.fulcra_get_auth_url({})
        run.assert_called_once_with(["auth", "login", "--get-auth-url"])
        self.assertIn("submit_device_code", output)
        self.assertIn("Wait for the user", output)

    def test_device_code_is_passed_as_a_single_argument(self):
        tools = load_tools()
        device_code = "fixture; not-a-shell-command"
        with patch.object(tools, "_run_cli", return_value="Authorization successful!") as run:
            output = tools.fulcra_submit_device_code({"device_code": device_code})
        run.assert_called_once_with(
            ["auth", "login", "--device-code", device_code, "--poll-timeout", "900", "--poll-interval", "5"],
            timeout=1080,
        )
        self.assertIn("successful", output)

    def test_invalid_device_code_does_not_launch_a_process(self):
        tools = load_tools()
        for value in (None, "", "   ", 5, [], "bad\x00code", "--help"):
            with self.subTest(value=value), patch.object(tools, "_run_cli") as run:
                self.assertTrue(tools.fulcra_submit_device_code({"device_code": value}).startswith("Error:"))
                run.assert_not_called()

    def test_uv_fallback_and_environment_isolation(self):
        tools = load_tools()
        env = {"PATH": "/bin", "HOME": "/home/fixture", "VIRTUAL_ENV": "/hermes/venv",
               "PYTHONPATH": "/hermes", "UV_PROJECT_ENVIRONMENT": "/hermes/venv", "UV_FROM": "untrusted"}
        with patch.object(tools, "_runtime_context", return_value=(True, env)), \
             patch("shutil.which", side_effect=lambda name, **kw: "/bin/uv" if name == "uv" else None), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            self.assertEqual(tools._run_cli(["catalog"]), "{}")
        self.assertEqual(run.call_args.args[0][:3], ["/bin/uv", "tool", "run"])
        child = run.call_args.kwargs["env"]
        for key in ("VIRTUAL_ENV", "PYTHONPATH", "UV_PROJECT_ENVIRONMENT", "UV_FROM"):
            self.assertNotIn(key, child)
        self.assertEqual(child["HOME"], env["HOME"])
        self.assertEqual(child["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(env["UV_FROM"], "untrusted")

    def test_missing_uv_is_actionable(self):
        tools = load_tools()
        with patch.object(tools, "_runtime_context", return_value=(True, {})), \
             patch("shutil.which", return_value=None), patch("subprocess.run") as run:
            result = tools.fulcra_get_data_catalog({})
        self.assertIn("Install uv", result)
        run.assert_not_called()

    def test_lazy_install_opt_out_never_launches_uv(self):
        tools = load_tools()
        with patch.object(tools, "_runtime_context", return_value=(False, {})), patch("subprocess.run") as run:
            self.assertIn("allow_lazy_installs", tools.fulcra_get_auth_url({}))
        run.assert_not_called()

    def test_timeout_does_not_leak_command_or_partial_output(self):
        tools = load_tools()
        error = subprocess.TimeoutExpired(["uvx", "sensitive-command"], 1, output="sensitive-output")
        with patch.object(tools, "_runtime_context", return_value=(True, {"PATH": "/bin"})), \
             patch("shutil.which", return_value="/bin/uvx"), patch("subprocess.run", side_effect=error):
            output = tools.fulcra_get_data_catalog({})
        self.assertIn("timed out", output)
        self.assertNotIn("sensitive", output)

    def test_cli_failure_is_bounded_and_device_code_redacted(self):
        tools = load_tools()
        result = subprocess.CompletedProcess([], 1, "", "fixture-device " + "x" * 5000)
        with patch.object(tools, "_runtime_context", return_value=(True, {"PATH": "/bin"})), \
             patch("shutil.which", return_value="/bin/uvx"), patch("subprocess.run", return_value=result):
            output = tools.fulcra_submit_device_code({"device_code": "fixture-device"})
        self.assertIn("[redacted]", output)
        self.assertLess(len(output), 2500)
        self.assertNotIn("fixture-device", output)

    def test_empty_success_is_an_error(self):
        tools = load_tools()
        with patch.object(tools, "_runtime_context", return_value=(True, {"PATH": "/bin"})), \
             patch("shutil.which", return_value="/bin/uvx"), \
             patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertIn("empty response", tools.fulcra_get_auth_url({}))

    def test_catalog_rejects_non_json_output(self):
        tools = load_tools()
        with patch.object(tools, "_run_cli", return_value="not json"):
            self.assertTrue(tools.fulcra_get_data_catalog({}).startswith("Error"))

    def test_catalog_normalizes_json_lines_and_empty_catalog(self):
        tools = load_tools()
        for raw, expected in (
            ('{"id":"one"}\n{"id":"two"}\n', [{"id": "one"}, {"id": "two"}]),
            ('{"id":"one"}\n', [{"id": "one"}]),
            ('', []),
        ):
            with self.subTest(raw=raw), \
                 patch.object(tools, "_runtime_context", return_value=(True, {"PATH": "/bin"})), \
                 patch("shutil.which", return_value="/bin/uvx"), \
                 patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, raw, "")):
                self.assertEqual(tools.fulcra_get_data_catalog({}), json.dumps(expected, indent=2))

    def test_plugin_registers_without_fulcra_sdk(self):
        # A separate, isolated interpreter proves the host needs no SDK install.
        probe = '''
import importlib.abc, importlib.util, sys
class NoSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == "fulcra_api" or fullname.startswith("fulcra_api."):
            raise ImportError("Fulcra SDK must not load in Hermes")
sys.meta_path.insert(0, NoSDK())
spec = importlib.util.spec_from_file_location("context_plugin", sys.argv[1], submodule_search_locations=[sys.argv[2]])
plugin = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = plugin
spec.loader.exec_module(plugin)
class Context:
    def __init__(self):
        self.tools = {}
        self.skills = {}
    def register_tool(self, **kwargs):
        self.tools[kwargs["name"]] = kwargs
    def register_skill(self, name, path):
        self.skills[name] = path
ctx = Context()
plugin.register(ctx)
assert set(ctx.tools) == {"get_auth_url", "submit_device_code", "get_data_catalog"}
assert all(t["toolset"] == "context" for t in ctx.tools.values())
assert ctx.skills["context"].is_file()
'''
        result = subprocess.run(
            [sys.executable, "-I", "-c", probe, str(ROOT / "__init__.py"), str(ROOT)],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
