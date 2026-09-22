# Fulcra Hermes Plugin

A native [Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
plugin with tools and a bundled skill for Fulcra authentication and catalog queries.

## Installation

```bash
hermes plugins install fulcradynamics/fulcra-hermes-plugin --no-enable
hermes plugins enable context
```

Start a new Hermes session after installation. Restart a running gateway to load
the new plugin before testing it in Discord or another messaging platform.
The plugin registers the `context` toolset. If it was previously disabled:

```bash
hermes tools enable context --platform cli
hermes tools enable context --platform discord
```

Run those commands in the profile serving the conversation (`hermes -p NAME ...`
for a named profile). They are not a mandatory additional setup step for a newly
loaded plugin. See [plugin toolsets](https://hermes-agent.nousresearch.com/docs/reference/toolsets-reference#plugin-toolsets).

### External runtime: no separate setup command

The host running Hermes must have `uvx` or `uv` on its PATH. The adapter prefers
`uvx` and falls back to the equivalent `uv tool run`. Missing uv produces an
installation hint; the plugin does not bootstrap uv itself.

On the first tool call, uv installs **fulcra-api==0.1.42** and its dependencies
into an isolated, cached tool environment. Subsequent calls reuse that cache.
The first invocation requires network access and can take longer. No Fulcra
packages are installed into Hermes's virtualenv; no `hermes context setup` is
needed. A compatible Python interpreter is also needed; uv may download one
according to its normal behavior.

The underlying catalog command is:

```bash
uvx --isolated --no-config --from fulcra-api==0.1.42 fulcra-api catalog
```

The manifest retains `python_runtime: external` to explicitly opt out of Hermes's
shared dependency management. With an empty host dependency list the marker is
not strictly necessary today, but documents and preserves this boundary. See
[Hermes Python dependencies](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#python-dependencies).

The adapter checks `security.allow_lazy_installs` before launching uv. When it is
false, these tools return an error, even if an environment is already cached: this
initial implementation does not attempt an offline/cache-only policy bypass.
Do not enable the setting merely to circumvent an administrator's policy.

## Authentication

Ask Hermes to retrieve your Fulcra catalog. If authentication is needed:

1. `get_auth_url` runs `auth login --get-auth-url` without opening a browser on the host.
2. Hermes shows the verification URL/code and waits for you to authorize.
3. `submit_device_code` runs the CLI's noninteractive completion command.
4. `get_data_catalog` returns the CLI's catalog JSON.

Credentials are managed by the Fulcra CLI at
`~/.config/fulcra/credentials.json`, relative to the child process's OS-user home.
The CLI loads and refreshes them, so an existing CLI login can be reused.
**This is OS-user credential storage, not separate storage per Hermes profile or
Discord user.** Do not use this experiment to serve mutually untrusted users or
accounts under the same OS account. Profile-scoped credentials require a follow-up
CLI change; an isolated uv environment is not a credential sandbox.

The CLI currently returns authentication instructions as text and accepts the
device code in argv (potentially visible to local process inspection). The adapter
redacts the submitted device code from failure messages and does not log command
lines. Structured auth output and stdin-based code input are follow-up CLI work.

## Implementation and limitations

- `__init__.py` registers native tools and the bundled `context` skill. No SDK
  imports, subprocesses, or downloads occur during registration.
- `tools.py` uses a pinned CLI, argument arrays (no shell), closed stdin, separate
  stdout/stderr, and timeouts (180 seconds normally; 1080 seconds for completion,
  including a 900-second authentication polling window).
- The adapter obtains the active profile's settings and a credential-scrubbed
  child environment through Hermes's helpers at call time. It removes inherited
  Python/uv overrides and ignores local uv configuration so those overrides cannot
  redirect the selected runtime. Custom `UV_*` settings/private indexes are not
  supported by this experiment.
- The Fulcra version is pinned, but transitive dependencies are not fully locked.
  Cache eviction can require fresh downloads and resolution.
- Hooks can use the same adapter, but no new hooks are added here. Avoid cold-start
  installation or long authentication polling inside latency-sensitive hooks.
- Uses the current Hermes `served_profile_child_env` helper; older Hermes releases
  without it are not supported by this experiment.

## Testing

The default suite needs only Python 3.11+; it does not install or import the SDK:

```bash
python3 -m unittest discover -s tests -v
```

An opt-in integration test downloads the pinned CLI via uv, then verifies saved
credential loading and refresh persistence with temporary fixtures and a stubbed
API response. It does not authenticate or access real Fulcra data:

```bash
FULCRA_CLI_SMOKE=1 python3 -m unittest discover -s tests -v
```

Also validate with Hermes:

```bash
hermes plugins validate .
```

To test a PR before merging, install the contributor's repository at its exact
40-character commit SHA with `hermes plugins install OWNER/REPO --ref SHA
--no-enable`. Replacing an existing installation requires `--force`; review local
changes first. Then enable `context` and start a fresh session. Test in a private
conversation before enabling access on a shared Discord server.
