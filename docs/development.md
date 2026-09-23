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
window. Final tool results preserve JSON Lines and whitespace up to 16,000
UTF-8 bytes. Larger results return a code-point-safe byte preview, an explicit
truncation notice and the absolute path of the complete UTF-8 artifact. Bounding
happens only at the handler boundary, after combined share listings are labeled
and text downloads are decoded; internal CLI reads remain complete. Explicit
local file downloads still save exact bytes without overwriting.
Data-type creation does not expose the optional timeline-preference update.

Artifacts use `get_hermes_home()` at call time and live in `fulcra-output/` under
that profile. The implementation rejects symlink components, opens directories
with `O_NOFOLLOW`, and requires an owned 0700 output directory. Random basenames
from `secrets.token_hex` are created with `os.open(O_CREAT|O_EXCL|O_WRONLY, 0600)`
relative to the pinned directory descriptor, retrying collisions without
overwriting existing files. Directory identity is checked after writing;
failed writes are removed through the pinned descriptor.
This requires POSIX descriptor-relative file APIs and `O_NOFOLLOW`, not procfs.
The ancestor-symlink policy is unchanged: use a canonical physical profile path,
including on macOS where `/var` commonly links to `/private/var`. Unsupported
hosts or unsafe/unwritable paths get a bounded storage error, not false success.
Complete results are captured in memory before storage; this is a context-size
limit, not a subprocess memory or disk quota.

Artifacts persist until manually deleted. They can contain sensitive health data
and should not be shared or publicly backed up. There is no automatic cleanup.
Errors retain exception types and details, with only the supplied device code
explicitly redacted; the adapter trusts the CLI for other sanitization, including
in saved artifacts. Successful auth output is never persisted;
oversized responses retain the pinned CLI's complete URL/code lines or success
message, or report that usable fields could not be retained. Auth codes still
appear in the tool conversation as required for the device flow. There is no
adapter-level generic secret or terminal-control sanitization. Storage errors
warn that the operation may already have completed and writes must be verified
before retrying.

Settings and the credential-scrubbed child environment are resolved at call time
through Hermes's profile-aware helpers. Older Hermes versions without
`served_profile_child_env` are unsupported. Inherited Python/uv overrides are
removed and local uv configuration is ignored; custom `UV_*` settings and private
indexes are not supported.

When `security.allow_lazy_installs` is false, the adapter refuses to launch uv,
even if dependencies are cached. It has no offline/cache-only mode.

## Limitations

Share time bounds limit the accessible time range of time-series data types
only, never file access. File/all-data shares can carry bounds for data types.
The adapter validates timestamps and conflicting flags, but does not fetch
outgoing share state before updates. `set_data_types` replaces all selectors;
`clear` also disables all-data scope; file removals are exact selector matches.
Inspect shares before changing access and verify afterward.

- The CLI owns credentials at `~/.config/fulcra/credentials.json`. This is shared
  OS-user storage, not per-profile or per-Discord-user storage. Separate accounts
  need a follow-up change to the CLI; uv isolation is not a security sandbox.
- Authentication output is text. The CLI accepts the device code in argv, where
  local process inspection may expose it. Errors retain their exception type and
  useful diagnostics, with only the supplied device code explicitly redacted.
  The CLI owns all other sanitization; the adapter does not scan environment
  values, redact generic credentials, or strip terminal controls.
  Timeout argv and partial output are never returned: outcomes are uncertain,
  so verify writes before retrying. Successful stderr warnings are discarded.
  The adapter does not log command lines. Structured output and
  stdin-based code input remain CLI follow-ups.
- The CLI version is pinned, but transitive dependencies are not fully locked.
  Cache eviction can require new downloads and resolution.
- No hooks are added by this plugin. Future hooks can use the adapter, but avoid
  cold-start installation or long auth polling inside latency-sensitive callbacks.
