# Development

## Run tests

The default suite needs Python 3.11+ and does not install or import the Fulcra SDK:

```bash
python3 -m unittest discover -s tests -v
```

The opt-in integration tests download the pinned CLI via uv. They test credential
loading/refresh persistence and execute the expansion through the real Click
parser and CLI command bodies against fixture APIs. The expansion fixture blocks
socket connections. Neither test authenticates or accesses real Fulcra data:

```bash
FULCRA_CLI_SMOKE=1 python3 -m unittest discover -s tests -v
```

Validate the plugin with Hermes:

```bash
hermes plugins doctor . --ci
git diff --check
```

## Try a PR

Install the contributor's repository at the PR head's full 40-character commit SHA:

```bash
hermes plugins install OWNER/REPO --ref SHA --no-enable
hermes plugins enable context
```

To replace an existing installation, add `--force` after reviewing any local
changes. Start a fresh CLI session, or restart the gateway and begin a fresh
private conversation. Use the profile serving that conversation (`hermes -p NAME ...`
for a named profile).

Newly loaded plugin toolsets are normally available without a separate enable
step. If `context` was previously disabled, enable it for the intended platform
as described in the [README](../README.md#troubleshooting).

## Runtime

`__init__.py` registers the tools and bundled skill without importing the SDK or
starting a subprocess. `tools.py` invokes **fulcra-api==0.1.42** through `uv tool run`:

```bash
uv tool run --isolated --no-config --from fulcra-api==0.1.42 fulcra-api catalog
```

uv creates and caches the external environment. It may download a compatible
Python interpreter when needed. The plugin does not install uv itself.

The host dependency list is empty. The adapter imports only the standard library
and Hermes runtime helpers; Fulcra and its dependencies stay in the uv child.
See [Hermes Python dependencies](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#python-dependencies).

The adapter uses argument arrays without a shell, closes stdin, and captures
stdout and stderr separately. Ordinary calls time out after 180 seconds.
Authentication completion allows 1080 seconds, including a 900-second polling
window. Tools preserve CLI output, including JSON Lines and whitespace, without
plugin-imposed size caps or truncation. Combined share listings add direction
labels; file downloads return full UTF-8 text or save exact local bytes.
Data-type creation does not expose the optional timeline-preference update.

Settings and the credential-scrubbed child environment are resolved at call time
through Hermes's profile-aware helpers. Older Hermes versions without
`served_profile_child_env` are unsupported. Inherited Python/uv overrides are
removed and local uv configuration is ignored; custom `UV_*` settings and private
indexes are not supported.

When `security.allow_lazy_installs` is false, the adapter refuses to launch uv,
even if dependencies are cached. It has no offline/cache-only mode.

## Limitations

- The CLI owns credentials at `~/.config/fulcra/credentials.json`. This is shared
  OS-user storage, not per-profile or per-Discord-user storage. Separate accounts
  need a follow-up change to the CLI; uv isolation is not a security sandbox.
- Authentication output is text. The CLI accepts the device code in argv, where
  local process inspection may expose it. The adapter returns full CLI failure
  diagnostics, redacts the device code, and does not log command lines. Structured output and
  stdin-based code input remain CLI follow-ups.
- The CLI version is pinned, but transitive dependencies are not fully locked.
  Cache eviction can require new downloads and resolution.
- No hooks are added by this plugin. Future hooks can use the adapter, but avoid
  cold-start installation or long auth polling inside latency-sensitive callbacks.
