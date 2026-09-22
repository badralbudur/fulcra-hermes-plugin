# Fulcra Hermes Plugin

Connect [Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
to Fulcra. This plugin handles sign-in and lists the data types available in your
Fulcra account. It includes native Hermes tools and a usage skill.

## Install

You need a current Hermes installation and [uv](https://docs.astral.sh/uv/getting-started/installation/)
on the machine running it. The plugin appends Hermes's managed bin directory
(`$HERMES_HOME/bin`, obtained through Hermes's managed-runtime helper) to the
subprocess PATH if missing, then looks for `uvx` or `uv`. The parent process PATH
is unchanged; no shell configuration changes are needed.

```bash
hermes plugins install fulcradynamics/fulcra-hermes-plugin --no-enable
hermes plugins enable context
```

Start a fresh Hermes session. For Discord or other messaging platforms, restart
the gateway to load the plugin.

The first tool call downloads the Fulcra CLI into uv's isolated cache. Later calls
reuse it. This needs network access on first use, but no separate setup command
and no changes to Hermes's Python dependencies.

## Use

Ask Hermes:

> Show me my Fulcra data catalog.

If you aren't signed in, Hermes gives you a verification link and code. Open the
link, authorize Fulcra, then tell Hermes you've finished. An existing Fulcra CLI
login can also be reused.

Credentials live at `~/.config/fulcra/credentials.json` under the host OS account.
**Hermes profiles and Discord users running under that account share the login.**
Use this plugin only with trusted users; its isolated Python runtime does not
isolate accounts.

## Troubleshooting

- **Tools missing:** check that the plugin is enabled and start a fresh session.
  If you previously disabled its toolset, run `hermes tools enable context --platform cli`
  or `hermes tools enable context --platform discord`. Use `hermes -p NAME ...`
  when configuring a named profile. See [plugin toolsets](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference#plugin-toolsets).
- **uv not found:** install uv on the Hermes host and make it available on the
  process's PATH, including the gateway service's PATH.
- **Lazy installs disabled:** this version requires `security.allow_lazy_installs`,
  even with a populated cache. Ask the operator before changing that policy.

## Development

See [the developer guide](docs/development.md) for tests, runtime details,
limitations, and instructions for trying a PR.
