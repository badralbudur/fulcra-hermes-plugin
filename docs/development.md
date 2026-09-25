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

`__init__.py` registers the tools, hooks and bundled skills without importing the SDK or
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

## Mesh implementation

`mesh.py` registers one `fulcra_mesh` handler bound to `ctx.state`. It shares the
existing CLI, private record staging, and bounded-output helpers. No host SDK,
schedules, or LLM calls. `mesh_updates.py` reuses its receive helper with an
injected bounded CLI callable and separate automatic state; see [setup.md](setup.md).
A process-local lock covers manual connection changes
and receive commits; metadata keys include the current account and agent/peer
identity. Oversized output persistence precedes receive cursor commits; small
inline responses are not saved as files or guaranteed as a durable inbox.

Six mesh workflows cover handoff-only onboarding, consent/adoption/reuse,
pending-creation recovery, partial sharing, envelope/send outcomes,
receive filtering/dedup, parse/artifact failures, and account separation. The
opt-in CLI fixture also exercises real pinned Click bodies and SDK share/upload
request construction with temporary credentials and blocked socket connections.
Mesh restores the original `fulcra_api.records.get_records` dispatcher before
running: event catalog entries must route to the real v1alpha1 event endpoint,
with owner scope only for peer reads. Only its transport response is intercepted,
not the dispatcher. An invalid `moment_annotation` type fails this fixture.
Fixtures use `user-info.userid`, nested create-share `datashare`, outgoing `id`,
incoming `sharing_fulcra_userid`, and JSONL record streams. The SDK routes a
dedicated annotation write to base `MomentAnnotation` ingestion with its UUID
annotation source; the note remains a JSON string and validation stays enabled.

See [mesh protocol and limits](mesh.md) for the pinned reference, exact cursor
window/dedup limits, state recovery, and why invite is separate from send.

The standalone real-Hermes probe uses temporary profile homes and blocked
networking, without installing a plugin or changing configuration. Run with the
Hermes virtualenv and its source on `PYTHONPATH`, for example:

```bash
PYTHONPATH=/path/to/hermes-agent /path/to/hermes-agent/venv/bin/python tests/mesh_hermes_probe.py
```

It verifies A→B→A registration/state reload, stable handoff markers, explicit
adoption, group provenance, bounded dedup, private metadata, and no files for
small inline responses. The CLI fixture uses a minimal mesh-relevant schema
projection; it is not a captured full production catalog or live-account test.

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

## Workspace startup

`workspace.py` registers a separate `pre_llm_call` alongside the existing update
hook. Three manifest settings (also in `workspace.SETTINGS`) are read via
`ctx.get_config` at call time; standard Hermes config UI/CLI suffices. There is
no new tool or registration-time settings write. Load the bundled
[`workspace` skill](../skills/workspace/SKILL.md) for durable role and OKF rules.
It adapts the pinned fulcra-workspaces reference rather than depending on mesh.

- Setup discovery lives in `plugin_setup.py` (not setuptools's `setup.py`). It
  requires `is_first_turn is True`, a session ID, no parent and platform other
  than cron before checking the marker. Ordinary turns leave discovery available
  for the next eligible new session. The options offer includes workspace loading,
  what's-new notices/shared interval and independent mesh message/invitation checks.
  It writes only a durable `ctx.state` marker meaning offered, not delivered or
  declined, never feature configuration. Existing choices remain intact.
  See [setup frontends and rationale](setup.md).
- Enabled file loading also requires `is_first_turn is True`.
  An in-memory `(ctx.state.path, session_id)` marker
  suppresses repeated first-turn work. No downloaded content or completion cache
  is persisted; restarting the process permits another checked startup.
- A profile/workspace process lock serializes bootstrap across sessions. Read
  `/workspace/<workspace_name>/context.md` first. If present (even empty), this
  is exactly one CLI download: do not read scaffold/detail/role/progress files,
  follow links or maintain a newly selected role. Trust user-provided context as
  reference; the skill handles authorized layout maintenance on demand.
  Only when context.md is missing, read each explicit scaffold path and re-read
  confirmed missing paths before upload. Create context.md LAST, after all
  scaffold checks and upload readbacks succeed. Interrupted bootstrap resumes
  later without overwriting existing files or summarizing/migrating old detail.
  Only the exact pinned error `Fulcra CLI exited with status 1: Error: File not
  found in Fulcra: {path}` means absent. Auth/network/decode errors and all other
  failures stop that startup, without creating a premature context marker.
  Download after upload must match the seed before reporting files/readback checked,
  never full index completion. Track seeded paths within this startup and report
  index/log reconciliation pending after any seeding, not a complete inventory.
  Existing indexes/logs are untouched; newly seeded ones are skeletal, including
  in existing workspaces. The bundled skill directs authorized read/merge/upload/verify
  of links and major milestones, never replacement with templates. No automatic
  markdown merger or persisted reconciliation state.
- All CLI operations use `tools._run_cli` and the remaining portion of one
  monotonic 25-second deadline, including lock wait. Timeouts stop work, without
  retrying uncertain mutations. Local staging uses a private temporary directory
  cleaned up on exit. CLI stdout is an acknowledgement, never file content.
  This is not a disk quota: the CLI downloads a full file before bounded reading.
- Only context.md is injected: up to 8,000 content characters. The entire result
  is bounded below 10,000 characters, accounting for JSON escaping, the full remote
  filepath, status and untrusted guidance. A truncated flag and retrieval guidance
  direct manual full-file reads through normal file tools, not a persisted startup
  artifact. Unknown types/metadata are retained as user-owned untrusted data, not
  authority. No linked content, inboxes, tasks or unrelated files are auto-read/executed.
  Role/progress and knowledge files are on-demand detail, not automatic preloads.
- The Reference-type context seed has Basic preferences, Available Fulcra data
  and Further context sections: empty facts, relative links to detail and durable
  roles. Root-index seeds link context.md; existing indexes remain untouched.
  The skill curates concise user-stated/verified basic preferences and confirmed
  data categories/IDs during authorized normal work, with source/date/scope when
  known. Detailed domains, schemas and preferences stay behind relevance-driven
  links (progressive disclosure). No automatic full-catalog query, assumed data
  availability, fabricated preferences, or automatic migration/summarization.
- Seeds declare required OKF `type` except reserved index/log files. The root
  index declares `okf_version: "0.2"`; session/artifact directories are only
  linked conventions until files are intentionally created there. No local
  MEMORY changes, auth flows, shares, cron, or unrelated uploads.
- The CLI offers no conditional create. External processes and profiles sharing
  the OS account can race between re-read and upload; this is not a distributed
  lock. Partial setup may require several sessions on a slow connection or cold
  uv cache. Startup writes are not native tool callbacks and may appear in a
  later background-update digest; the usual relevance guidance still applies.

Five workspace unit workflows cover context-last cold seeding/readback and OKF,
single-read warm reuse (including a changed role, preserved files/links and private
sentinels not loaded), legacy preservation/reconciliation, no-I/O gates,
partial/error/timeout handling with no premature marker, and profile-scoped
new-session reload with bounded escaped context. The existing
`FULCRA_CLI_SMOKE=1` fixture also runs `workspace_cli_fixture.py`: real pinned
Click commands and core resolve/upload/download methods against a fake HTTP
file store, temporary credentials and blocked sockets (including HTTP 403 and
decode failures vs exact missing-path behavior). No real account is contacted.

The real-Hermes probe below also exercises unified discovery without feature
configuration writes, workspace configuration, first-turn current-user
injection, single-file warm reload without linked private detail, update-hook coexistence,
A → B → A isolation, no registration writes, and temporary staging cleanup.

## Background update hooks

`updates.py` registers `pre_llm_call`, `post_llm_call`, `post_tool_call` and
`fulcra_configure_updates`. Registration performs no network or persistent writes.
The update settings and defaults are documented in the README and declared in
`plugin.yaml`; tool writes go through `ctx.set_config`, including
`ctx.set_config("update_interval", 900)` in seconds. No SDK or new dependency
is imported into Hermes. Current Hermes with `ctx.state` is required.

- Pre hooks record eligible top-level sessions, establish the profile's baseline
  only on first use/reset, and consume its shared digest once through `{context: text}`. Hermes
  appends it to the **current user message**; history/system prompts are untouched.
  Post hooks have no sender ID, so eligibility comes from pre, not a global last
  sender. Unknown sessions, cron turns (`platform='cron'`) and delegated children
  cannot trigger a fetch or consume the digest. Pre removes their eligibility,
  so their successful tool writes also cannot create known-write markers: newly
  collected cron/subagent data remains available for the user's next conversation.
  This is not a complete automation classifier; other top-level contexts remain eligible.
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

## Unified setup and automatic mesh (PLAT-470)

See [setup.md](setup.md) for the native settings choice, slash/CLI frontends,
feature consumers, account-switch precautions and automatic notification limits.
Six additional workflow tests cover explicit-only setup/readback and invalid
arguments, one-time discovery, independent mesh flags, recipient filtering,
durable dedup/cursors, manual receive independence, deadlines/nonblocking workers,
in-flight config invalidation, cooldown/failure preservation and profile/session gates.
The existing pinned CLI fixture exercises the canonical parser/read protocol reused
by the worker; no second protocol fixture is needed.

`hermes_updates_probe.py` additionally resolves the real registered slash handler
and CLI parser/handler, uses real `PluginContext` settings writes/readback in
temporary homes, verifies native form field recognition/writes, and exercises
workspace/update/mesh hook coexistence under A→B→A multiplexing with blocked
network and copied worker contexts. `mesh_hermes_probe.py` retains coverage of
manual mesh registration/state reload. No installed profiles are modified.
