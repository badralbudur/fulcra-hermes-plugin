"""Tool handlers for interacting with the Fulcra CLI."""

import subprocess
import json
import logging

logger = logging.getLogger(__name__)

def fulcra_get_auth_url(args, **kwargs):
    """Get the URL and device code to authenticate with Fulcra."""
    try:
        # Run the non-interactive get-auth-url command
        result = subprocess.run(
            ["fulcra", "auth", "login", "--get-auth-url"],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Fulcra get_auth_url error: {e.stderr}")
        return f"Error: {e.stderr}"

def fulcra_submit_device_code(args, **kwargs):
    """Submit the device code after the user has authorized in the browser."""
    device_code = args.get("device_code")
    if not device_code:
        return "Error: device_code is required."
    
    try:
        # Complete the authentication flow using the device code
        result = subprocess.run(
            ["fulcra", "auth", "login", "--device-code", device_code],
            capture_output=True,
            text=True,
            check=True
        )
        return "Authentication successful. Credentials saved. You can now use other Fulcra tools."
    except subprocess.CalledProcessError as e:
        logger.error(f"Fulcra submit_device_code error: {e.stderr}")
        return f"Error: {e.stderr}"

def fulcra_get_data_catalog(args, **kwargs):
    """Return a list of queryable Fulcra data types and metadata."""
    try:
        # Use the CLI which natively returns JSON-lines
        result = subprocess.run(
            ["fulcra", "catalog"],
            capture_output=True,
            text=True,
            check=True
        )
        
        # Parse output line by line as JSON objects and return as a clean JSON list
        lines = result.stdout.strip().split("\n")
        catalog = [json.loads(line) for line in lines if line]
        return json.dumps(catalog, indent=2)
    except subprocess.CalledProcessError as e:
        logger.error(f"Fulcra get_data_catalog error: {e.stderr}")
        return f"Error executing catalog: {e.stderr}\n\nIf this is an authentication error, please run the get_auth_url tool."
