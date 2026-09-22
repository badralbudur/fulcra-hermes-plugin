"""Tool handlers for interacting with the Fulcra API."""

import json
import logging
import datetime
from fulcra_api.core import FulcraAPI
from fulcra_api.cli.auth import save_creds

logger = logging.getLogger(__name__)

def fulcra_get_auth_url(args, **kwargs):
    """Get the URL and device code to authenticate with Fulcra."""
    try:
        fulcra_api = FulcraAPI()
        device_code, uri, code, timeout, interval = fulcra_api.oidc.get_device_code()
        
        return (
            f"Open the web auth URL in a browser, verify the web auth code, and complete the web auth flow.\n\n"
            f"Web auth URL: {uri}\n"
            f"- Web auth code: {code}\n"
            f"- Device code: {device_code}\n\n"
            f"Wait for the user to complete the browser authorization, then call submit_device_code with device_code=\"{device_code}\"."
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
        fulcra_api = FulcraAPI()
        creds = fulcra_api.oidc.poll_for_token(
            device_code=device_code,
            poll_timeout=datetime.timedelta(seconds=900),
            poll_interval=datetime.timedelta(seconds=5),
        )
        save_creds(creds)
        return "Authentication successful. Credentials saved. You can now use other Fulcra tools."
    except Exception as e:
        logger.error("Fulcra submit_device_code error", exc_info=True)
        return f"Error checking authorization status: {e}"

def fulcra_get_data_catalog(args, **kwargs):
    """Return a list of queryable Fulcra data types and metadata."""
    try:
        fulcra_api = FulcraAPI()
        # fulcra_api.v1_catalog() retrieves the catalog natively
        response = fulcra_api.v1_catalog()
        return json.dumps(response, indent=2)
    except Exception as e:
        logger.error("Fulcra get_data_catalog error", exc_info=True)
        return f"Error retrieving catalog: {e}\n\nIf this is an authentication error, please run the get_auth_url tool."
