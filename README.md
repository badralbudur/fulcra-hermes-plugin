# Fulcra Hermes Plugin

This is a Native Python Plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that seamlessly connects to your Fulcra data.

## Installation

You can install this plugin directly into your Hermes Agent environment:

```bash
hermes plugins install fulcradynamics/fulcra-hermes-plugin --no-enable
hermes plugins enable context
```

Hermes will automatically install the `fulcra-api` package into its isolated environment.

## Authentication

Authentication is handled completely seamlessly within the chat!

If you haven't authenticated yet, simply ask Hermes to check your Fulcra data. Hermes will intelligently realize it needs to authenticate, provide you with an authorization link to open in your browser, and finalize the login process automatically once you approve it.

## How it works

This repository contains a native Hermes Python plugin that interacts with the `fulcra-api` CLI:
1. `plugin.yaml`: Manifest identifying this as a Hermes Native Python plugin and declaring the `fulcra-api` dependency.
2. `__init__.py` & `tools.py`: Exposes tools for two-step interactive authentication and retrieving the data catalog.
3. `skills/context/SKILL.md`: Guidance prompts teaching Hermes how to orchestrate the tools to authenticate users and query data.
