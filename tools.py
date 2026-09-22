"""Native Hermes tools backed by an isolated, pinned Fulcra CLI."""

import json
import os
import shutil
import subprocess

FULCRA_PACKAGE = "fulcra-api==0.1.42"


def _runtime_context():
    # Resolve settings and secrets at call time for the active Hermes profile.
    from hermes_cli.config import load_config
    from hermes_constants import get_hermes_home
    from tools.environments.local import served_profile_child_env

    allowed = load_config().get("security", {}).get("allow_lazy_installs", True)
    env = served_profile_child_env(target_home=get_hermes_home(), inherit_credentials=False)
    return allowed, env


def _run_cli(arguments, *, timeout=180):
    """Execute only plugin-selected CLI operations outside Hermes's Python environment."""
    allowed, env = _runtime_context()
    if not allowed:
        raise RuntimeError("Fulcra's uvx runtime requires security.allow_lazy_installs; it is disabled.")
    # Ignore ambient Python/uv overrides: only this pinned package belongs in the child.
    env = {key: value for key, value in env.items()
           if not key.startswith(("UV_", "PYTHON")) and key not in {"VIRTUAL_ENV", "CONDA_PREFIX"}}
    env["PYTHONIOENCODING"] = "utf-8"
    from hermes_cli.managed_uv import managed_uv_path

    # Extend only the child PATH; direct subprocesses do not load shell setup.
    managed_bin = str(managed_uv_path().parent)
    path = env.get("PATH", "")
    if managed_bin not in path.split(os.pathsep):
        env["PATH"] = path + os.pathsep + managed_bin if path else managed_bin
    uvx = shutil.which("uvx", path=env.get("PATH", ""))
    uv = None if uvx else shutil.which("uv", path=env.get("PATH", ""))
    if not uvx and not uv:
        raise RuntimeError("Install uv and put uvx or uv on the Hermes host's PATH, then retry.")
    launcher = [uvx] if uvx else [uv, "tool", "run"]
    command = [*launcher, "--isolated", "--no-config", "--from", FULCRA_PACKAGE, "fulcra-api", *arguments]
    try:
        result = subprocess.run(
            command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # TimeoutExpired contains argv (including the device code); don't expose it.
        raise RuntimeError(f"Fulcra CLI timed out after {timeout} seconds; retry the operation.") from None
    except OSError:
        raise RuntimeError("Could not start Fulcra CLI; check the host's uv installation.") from None
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        if "--device-code" in arguments:
            detail = detail.replace(arguments[arguments.index("--device-code") + 1], "[redacted]")
        raise RuntimeError(f"Fulcra CLI exited with status {result.returncode}: {detail[:2000]}")
    output = result.stdout.strip()
    if not output and arguments != ["catalog"]:
        raise RuntimeError("Fulcra CLI returned an empty response.")
    return output


def fulcra_get_auth_url(args, **kwargs):
    """Start the noninteractive device flow; never open a browser on the host."""
    try:
        output = _run_cli(["auth", "login", "--get-auth-url"])
        return output + (
            "\n\nWait for the user to complete browser authorization, then call "
            "submit_device_code with the returned device code. Use the tool rather "
            "than running the printed CLI command."
        )
    except Exception as exc:
        return f"Error: {exc}"


def fulcra_submit_device_code(args, **kwargs):
    """Finish the device flow and let the CLI persist its own credentials."""
    device_code = args.get("device_code")
    if (not isinstance(device_code, str) or not device_code.strip()
            or "\x00" in device_code or device_code.startswith("-")):
        return "Error: device_code must be a nonempty device code returned by get_auth_url."
    try:
        return _run_cli(
            ["auth", "login", "--device-code", device_code,
             "--poll-timeout", "900", "--poll-interval", "5"],
            timeout=1080,
        )
    except Exception as exc:
        return f"Error checking authorization status: {str(exc).replace(device_code, '[redacted]')}"


def fulcra_get_data_catalog(args, **kwargs):
    """Return catalog JSON; the CLI loads and refreshes saved credentials."""
    try:
        output = _run_cli(["catalog"])
        try:
            # The CLI streams JSON objects, one per line (including zero lines).
            rows = json.loads(output) if output.startswith("[") else [
                json.loads(line) for line in output.splitlines() if line.strip()
            ]
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("catalog must contain objects")
        except ValueError:
            raise RuntimeError("Fulcra CLI returned invalid catalog JSON.") from None
        return json.dumps(rows, indent=2)
    except Exception as exc:
        return (
            f"Error retrieving catalog: {exc}\n\n"
            "If this is an authentication error, please run the get_auth_url tool."
        )
