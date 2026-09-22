---
name: context
description: Guidelines for interacting with the Fulcra Context MCP tools.
---

# Fulcra Context Usage Guidelines

When the user asks to query their data, check their context, or use Fulcra:

1. You have access to Fulcra Context tools via the `context` MCP server.
2. If the user hasn't provided a specific time frame, default to recent relevant events.
3. If an authentication error occurs, or the user hasn't logged in, instruct them to open their terminal and run `uvx --from fulcra-api fulcra auth login` to complete the secure OAuth flow.
4. Keep your summaries concise and reference the data retrieved directly.