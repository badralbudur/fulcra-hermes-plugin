---
name: context
description: Guidelines for interacting with the Fulcra Context tools.
---

# Fulcra Context Usage Guidelines

When the user asks to query their data, check their context, or use Fulcra:

1. You have access to Fulcra Context tools. Use `get_data_catalog` to see what data is available.
2. If the user hasn't provided a specific time frame, default to recent relevant events.
3. If an authentication error occurs, or the user hasn't logged in, follow the two-step authentication process:
   - Call `get_auth_url` and show the resulting URL and verification code to the user.
   - Wait for the user to confirm they have authorized the app in their browser.
   - Call `submit_device_code` with the device code to finalize authentication.
4. Keep your summaries concise and reference the data retrieved directly.
