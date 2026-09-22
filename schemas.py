"""Tool schemas for the LLM."""

AUTH_GET_URL = {
    "description": "Start the authentication process. Returns a web auth URL for the user to visit, and a device code.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}

AUTH_SUBMIT_CODE = {
    "description": "Complete authentication by polling for the provided device code. Run this AFTER the user has authorized in the browser.",
    "parameters": {
        "type": "object",
        "properties": {
            "device_code": {
                "type": "string",
                "description": "The device code returned by the get_auth_url tool"
            }
        },
        "required": ["device_code"]
    }
}

GET_CATALOG = {
    "description": "Get all data types available for this user from Fulcra. Includes health, location, events, and annotations.",
    "parameters": {
        "type": "object",
        "properties": {}
    }
}
