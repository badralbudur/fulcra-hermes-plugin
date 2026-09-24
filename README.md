# Fulcra Hermes Plugin

Connect [Hermes Agent](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins)
to Fulcra. This plugin provides sign-in, filtered catalog discovery, data-type
management, record reads/writes/deletions, scoped sharing, processing updates,
and file operations. It includes native Hermes tools and a usage skill.

## Install

You need a current Hermes installation and [uv](https://docs.astral.sh/uv/getting-started/installation/)
on the machine running it. The plugin appends Hermes's managed bin directory
(`$HERMES_HOME/bin`, obtained through Hermes's managed-runtime helper) to the
subprocess PATH if missing, then runs the CLI with `uv tool run`. The parent process PATH
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

Use `fulcra_data_catalog` to discover IDs, `fulcra_data_type_schema` before writing
records, and `fulcra_list_shares` before changing access. Mutations require explicit
targets; sharing requires explicit recipients and scope. Read back changes before
claiming completion. Small results are unchanged. Results over 16,000 UTF-8 bytes
return a byte-bounded preview with an explicit truncation notice and an absolute
path to the complete UTF-8 text. Read that path with local file tools, rather
than treating the preview as complete JSON or a complete dataset.

Artifacts are private files (0600) in the active Hermes profile's
`fulcra-output/` directory (0700), resolved at each call. They may contain private
health data: do not share them or include them in public backups. They remain
until you explicitly delete them; there is no automatic retention cleanup.
Successful authentication output is never saved there; oversized auth responses
retain the URL and complete codes when possible. Errors retain exception types
and details, with only the supplied device code explicitly redacted; other
sanitization is the CLI's responsibility. Timeout errors omit argv and partial
output. Successful stderr warnings are discarded. If storage fails, the tool
reports that the full result is unavailable; the operation may still have
completed, so verify writes before
retrying. Secure artifact storage requires POSIX descriptor-relative file APIs
and `O_NOFOLLOW`, not Linux/procfs. The existing checks still require a profile
path without symlink components; use a canonical physical path (for example,
macOS `/var` commonly resolves through a symlink to `/private/var`).

The bundled [usage skill](skills/context/SKILL.md) explains the available tools.
Use explicit absolute POSIX remote paths (root `/` selects all files).
Remote paths are passed through to the CLI without custom path validation.
Time bounds limit the accessible time range of time-series data types only,
never file access. File/all-data shares can carry bounds for their data types.
The adapter does not fetch outgoing share state before updates; inspect shares
before changing access and verify afterward.
Authentication uses `fulcra_auth` and `fulcra_auth_device`.

Credentials live at `~/.config/fulcra/credentials.json` under the host OS account.
**Hermes profiles and Discord users running under that account share the login.**
Use this plugin only with trusted users; its isolated Python runtime does not
isolate accounts.

## Background updates (opt-in)

Ask Hermes to enable background Fulcra updates and specify your interests, for
example: “Check for new Fulcra data every 15 minutes; only mention my Mood data
and files under /notes/, ignoring /notes/drafts/.” Discover exact data type IDs
with the catalog first. Hermes uses `fulcra_configure_updates`, which persists
settings through `ctx.set_config`. Calling it with `{}` reads current settings.
The interval is seconds, e.g. `ctx.set_config("update_interval", 900)`.

Example tool arguments:

```json
{"updates_enabled": true, "update_interval": 900,
 "updates_data_types": ["Mood"], "updates_include_files": true,
 "updates_file_prefixes": ["/notes/"],
 "updates_ignore_prefixes": ["/notes/drafts/"]}
```

All settings are declared in the manifest and live under
`plugins.entries.context.settings` in the active profile:

| Setting | Default | Meaning |
| --- | --- | --- |
| `updates_enabled` | `false` | Explicit profile-wide consent; use `false` to stop. |
| `update_interval` | `900` | Minimum check interval, integer 60–86400 seconds. |
| `updates_data_types` | `[]` | Exact type allowlist; empty means **all**, not none. |
| `updates_include_files` | `true` | Include file changes. |
| `updates_file_prefixes` | `[]` | Literal path-prefix allowlist; empty means all files. |
| `updates_ignore_prefixes` | `[]` | Literal file prefixes to ignore; exclusions win. |

Prefixes are case-sensitive text matches, not globs or path normalization. Use a
trailing slash to select a directory rather than similarly named siblings.
Settings are read at call time; no restart is needed. Invalid settings are rejected
by the tool; invalid externally edited settings make hooks fail closed.
Filter expansion is forward-only: previously filtered windows are not replayed.

Consent is **profile-wide, not a per-user authorization boundary**. Enable only
in profiles whose chats/users you trust with the same OS-user Fulcra account.
One profile-level cursor, digest, deduplication history and known-write buffer
are shared across chats. The next eligible top-level conversation consumes the
pending digest once; delegated child turns do not poll or receive notices.
Only first use or disable/re-enable establishes a current-time baseline.
Starting a new session keeps the existing cursor and pending activity.
After changing the shared Fulcra login, disable/re-enable updates before resuming
chats to reset cursors and discard old-account digests. Coordination is within a
single process; do not run multiple Hermes processes polling the same profile.

After a turn finishes, a due check runs on a daemon worker with a 30-second CLI
timeout. There is no timer and **no checking while idle**. A completed digest is
offered to the model on a later turn, not guaranteed delivered to the user or sent
as a separate message. The model may stay
silent when updates are irrelevant; routine ingestion counts are not events or
medical findings. The plugin never reads full file contents or calls another LLM.

Successful native uploads/deletes/restores and record writes/deletions are treated
as already known across that profile. Suppression horizons cover at least one hour
or the configured interval, whichever is longer at write time. Markers survive
idle gaps until a successful fetch advances the cursor past their horizon.
File change timestamps, not fetch wall time, are compared with that horizon;
path identity follows the CLI's POSIX rules without changing tool inputs.
Record counts (and files without change timestamps) use window-start time as a
best-effort fallback. This can hide unrelated same-path/type changes, especially
counts in a long window. Changes timestamped beyond the horizon remain eligible;
ingestion arriving after the cursor has passed it may echo. Terminal writes and
facts learned outside these tools are not recognized. Failed
writes (including CLI `Error:` text) never suppress notices.

Cursors, a bounded metadata digest, deduplication hashes and recent-write markers
persist in private `ctx.state` storage under the profile's `plugin-data/` directory.
They can contain sensitive paths and type IDs: do not share or publicly back them
up. Disabling blocks future fetches/injection and discards in-flight results; an
already-running CLI call may finish. It does not erase previously stored metadata.
See [development limitations](docs/development.md#background-update-hooks).

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
