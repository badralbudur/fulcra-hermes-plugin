# Fulcra Hermes Plugin

This is a [Portable Agent Plugins v1.0.0](https://agent-plugins.org/) wrapper for the [Fulcra Context MCP Server](https://github.com/fulcradynamics/fulcra-context-mcp).

It allows [Hermes Agent](https://github.com/NousResearch/hermes-agent) to seamlessly connect to your Fulcra data by pointing to the hosted, OAuth-secured MCP server at `mcp.fulcradynamics.com`.

## Installation

You can install this plugin directly into your Hermes Agent environment:

```bash
hermes plugins install fulcradynamics/fulcra-hermes-plugin --no-enable
hermes plugins enable context
```

## Authentication

Fulcra secures your data using an OAuth2 flow on the hosted MCP server. Because this plugin uses HTTP transport instead of launching a local subprocess, Hermes handles the OAuth flow directly.

When you attempt to use a Context tool in Hermes for the first time, Hermes will recognize that the `mcp.fulcradynamics.com` server requires OAuth2 authorization. It will provide you with a browser URL to log in and approve the connection. 

Once approved, Hermes manages the OAuth tokens for you and attaches them to subsequent MCP requests. **You do not need to install the Fulcra CLI or manually manage API keys.**

## How it works

This repository contains:
1. `plugin.json`: Metadata identifying this as a portable Hermes plugin.
2. `mcp.json`: Configuration telling Hermes to connect to `https://mcp.fulcradynamics.com/mcp` using the Streamable HTTP transport.
3. `skills/context/SKILL.md`: Guidance prompts teaching Hermes how to correctly utilize the Fulcra Context tools.

Since the actual tools are hosted securely by Fulcra, this plugin remains lightweight and automatically benefits from upstream improvements to the MCP server.