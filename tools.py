"""Tool handlers for interacting with the Fulcra API."""

import json
import logging
import datetime
import subprocess

logger = logging.getLogger(__name__)

def run_uvx_command(command_args):
    """Run a command using uvx in an ephemeral environment with fulcra-api."""
    base_command = ["uvx", "--from", "fulcra-api", "python", "-c"]
    script = (
        "import json, sys\n"
        "from fulcra_api.core import FulcraAPI\n"
        "from fulcra_api.cli.auth import save_creds\n"
        "import datetime\n"
        f"{command_args}"
    )
    
    result = subprocess.run(
        base_command + [script],
        capture_output=True,
        text=True,
        check=False
    )
    
    if result.returncode != 0:
        raise Exception(result.stderr)
        
    return result.stdout.strip()

def fulcra_get_auth_url(args, **kwargs):
    """Get the URL and device code to authenticate with Fulcra."""
    try:
        script = (
            "api = FulcraAPI()\n"
            "device_code, uri, code, timeout, interval = api.oidc.get_device_code()\n"
            "result = {\n"
            "    'device_code': device_code,\n"
            "    'uri': uri,\n"
            "    'code': code\n"
            "}\n"
            "print(json.dumps(result))"
        )
        
        output = run_uvx_command(script)
        data = json.loads(output)
        
        return (
            f"Open the web auth URL in a browser, verify the web auth code, and complete the web auth flow.\n\n"
            f"Web auth URL: {data['uri']}\n"
            f"- Web auth code: {data['code']}\n"
            f"- Device code: {data['device_code']}\n\n"
            f"Wait for the user to complete the browser authorization, then call submit_device_code with device_code=\"{data['device_code']}\"."
        )
    except Exception as e:
        logger.error("Fulcra get_auth_url error", exc_info=True)
        return f"Error: {e}"

def fulcra_submit_device_code(args, **kwargs):
    """Submit the device code after the user has authorized in the browser."""
    device_code = args.get("device_code")
    if not device_code:
        return "Error: device_code is required."
    
    try:
        script = (
            "api = FulcraAPI()\n"
            f"creds = api.oidc.poll_for_token(device_code='{device_code}', poll_timeout=datetime.timedelta(seconds=900), poll_interval=datetime.timedelta(seconds=5))\n"
            "save_creds(creds)\n"
            "print('Success')"
        )
        run_uvx_command(script)
        return "Authentication successful. Credentials saved. You can now use other Fulcra tools."
    except Exception as e:
        logger.error("Fulcra submit_device_code error", exc_info=True)
        return f"Error checking authorization status: {e}"

def fulcra_get_data_catalog(args, **kwargs):
    """Return a list of queryable Fulcra data types and metadata."""
    try:
        script = (
            "api = FulcraAPI()\n"
            "response = api.v1_catalog()\n"
            "print(json.dumps(response, indent=2))"
        )
        return run_uvx_command(script)
    except Exception as e:
        logger.error("Fulcra get_data_catalog error", exc_info=True)
        return f"Error retrieving catalog: {e}\n\nIf this is an authentication error, please run the get_auth_url tool."