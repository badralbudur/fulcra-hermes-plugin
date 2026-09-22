# Development

## Run tests

The default suite needs Python 3.11+ and does not install or import the Fulcra SDK:

```bash
python3 -m unittest discover -s tests -v
```

The opt-in integration test downloads the pinned CLI via uv. It tests credential
loading and refresh persistence using temporary fixtures and a stubbed API
response, without authenticating or accessing real Fulcra data:

```bash
FULCRA_CLI_SMOKE=1 python3 -m unittest discover -s tests -v
```

Validate the plugin with Hermes:

```bash
hermes plugins validate .
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
starting a subprocess. `tools.py` invokes **fulcra-api==0.1.42** through uvx,
falling back to `uv tool run`:

```bash
uvx --isolated --no-config --from fulcra-api==0.1.42 fulcra-api catalog
```

uv creates and caches the external environment. It may download a compatible
Python interpreter when needed. The plugin does not install uv itself.

The manifest retains `python_runtime: external` to keep this runtime outside
Hermes's shared dependency management. The host dependency list is empty; the
marker documents that boundary and protects it if dependencies are added later.
See [Hermes Python dependencies](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#python-dependencies).

The adapter uses argument arrays without a shell, closes stdin, and captures
stdout and stderr separately. Ordinary calls time out after 180 seconds.
Authentication completion allows 1080 seconds, including a 900-second polling
window. Catalog JSON Lines are converted to a JSON array.

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
  local process inspection may expose it. The adapter redacts that code from
  failure messages and does not log command lines. Structured output and
  stdin-based code input remain CLI follow-ups.
- The CLI version is pinned, but transitive dependencies are not fully locked.
  Cache eviction can require new downloads and resolution.
- No hooks are added by this plugin. Future hooks can use the adapter, but avoid
  cold-start installation or long auth polling inside latency-sensitive callbacks.
