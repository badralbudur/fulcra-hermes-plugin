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

## Background update hooks

`updates.py` registers `pre_llm_call`, `post_llm_call`, `post_tool_call` and
`fulcra_configure_updates`. Registration performs no network or persistent writes.
The six settings and defaults are documented in the README and declared in
`plugin.yaml`; tool writes go through `ctx.set_config`, including
`ctx.set_config("update_interval", 900)` in seconds. No SDK or new dependency
is imported into Hermes. Current Hermes with `ctx.state` is required.

- Pre hooks record eligible top-level sessions, establish the profile's baseline
  only on first use/reset, and consume its shared digest once through `{context: text}`. Hermes
  appends it to the **current user message**; history/system prompts are untouched.
  Post hooks have no sender ID, so eligibility comes from pre, not a global last
  sender. Unknown sessions and delegated children cannot trigger a fetch.
- A due post hook launches one daemon worker per profile, with a shared cooldown
  across sessions. The worker uses
  `contextvars.copy_context()` so active-home, secret and runtime environment
  resolution survive the thread hop. Hooks never join or await it. There is no
  polling timer: idle means no checks; a later turn gets the cached result.
- Polling calls `tools._run_cli(['data-updates', startISO, endISO], timeout=30)`
  directly, not the bounded agent-facing tool. The pinned 0.1.42 CLI emits an
  object containing `start_time`, `end_time`, `data_types: {id: count}` and
  `file_changes: [metadata]`. The SDK defines `[start, end)` processing windows.
  The echoed window and complete response shape are validated before cursor
  advancement. Failures retain the exact attempted window and retry after the
  configured cooldown, including across restarts. No auth flow is launched.
- The `updates-feed` key in `ctx.state` holds one profile-level cursor, pending digest,
  seen fingerprints and known-write markers. Session IDs only track in-memory
  eligibility; starting a new session never resets the feed. An enablement epoch
  invalidates the feed and in-flight results after disable/re-enable. Direct
  config edits are observed on the next hook/worker completion; toggling off and
  on entirely between observations cannot be detected. Disabling does not kill an
  already-running CLI subprocess or erase state.
- One per-profile lock covers the plugin's state read/modify/write operations.
  Network work is outside it. Completion re-reads state rather than overwriting
  a snapshot, preserving intervening known-write markers and digest consumption.
  This is **single-process coordination**, not a cross-process session lease:
  avoid running two Hermes processes polling the same profile.
- File metadata uses public OpenAPI `RecentFileChange.full_name`, passed through
  unchanged by SDK/CLI (not a directory/name pair). Version fingerprints include
  `id`, `state`, `uploaded_at`, `archived_at` and `deleted_at`. Scan metadata and
  size are not user-change identities. Keep the last 256 fingerprints
  and at most 32 pending metadata items; coalesce data-type counts. Delivery
  reapplies current interests and known-write suppression and returns at most
  eight short items, under 3000 characters, with processing-window end times.
  Oversized items and overflow are omitted, not queued indefinitely. Consumed
  means offered to the model, not necessarily mentioned to the user. There is no
  acknowledgement/retry after model failure, nor a complete change-feed guarantee.
  Filter expansion is forward-only; filtered windows are not replayed.
- Successful native writes suppress exact file paths/version IDs or data types
  with a horizon of write time plus max(3600, update_interval) seconds in the
  profile, regardless of which eligible session wrote it. Suppression alone uses `PurePosixPath('/', path)`, matching
  CLI `make_filepath`; tool inputs are neither rewritten nor newly rejected.
  Restore creates a new version; the
  pinned CLI's restore result supplies the original path for suppression.
  `status=ok` is insufficient if the handler returned `Error:`. A small
  `changed_at` event field uses the latest upload/archive/delete timestamp;
  absent timestamps and coarse type counts use window start as best effort.
  Filter pending and fetched events against marker horizons before retiring
  markers whose horizon the successful cursor has passed, never by fetch wall
  time. Thus returning after idle does not itself expire known-write suppression.
  Later timestamps remain eligible, but ingestion after marker retirement may
  echo. Record counts cannot identify individual records; unrelated same-type
  changes in a long overlapping window may be hidden, as can same-path changes
  within the horizon. Other paths/types remain eligible. This is deliberately
  a heuristic, not conversation NLP or terminal command parsing.
- After changing the shared OS Fulcra account, disable/re-enable via the tool
  before resuming chats to reset cursors and old-account digests. Consent is
  profile-wide and only appropriate for trusted chats/users.
- Prompt metadata is labeled untrusted, never treated as instructions. Guidance
  allows silence, forbids task interruption and medical inference, and requires
  relevance rather than reciting routine sync counts. No file contents or
  auxiliary LLM calls are fetched/stored. State has Hermes's quota;
  metadata persists until explicitly removed. Raw CLI output
  is held in memory during validation, not persisted or logged.

The six focused unit workflows exercise registered hooks at a fake CLI boundary.
For real Hermes configuration/state and hook dispatch, run this standalone probe
with Hermes's existing interpreter (no host dependency installation):

```bash
/path/to/hermes-agent/venv/bin/python tests/hermes_updates_probe.py /path/to/hermes-agent
```

The probe requires `TMPDIR` to point to a writable scratch directory. It creates
and removes isolated temporary homes, blocks socket connections, uses the real
registered configuration tool and lifecycle dispatcher, checks current-user
context composition, and switches A → B → A under multiplexing. Its worker also
executes the real `_runtime_context()` to verify profile/secret propagation.
It never authenticates or contacts Fulcra, and never loads installed user plugins.
