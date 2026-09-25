# Fulcra setup (PLAT-470)

## Choose the active profile's features

Install/enable the plugin and authenticate Fulcra separately. Configuration does
not authenticate, call Fulcra, bootstrap files, or start workers. All four features
are off by default and independent. Use only profiles whose chats/users you trust
with the OS-user Fulcra account; profile isolation is not account isolation.

The canonical form is **Desktop → Capabilities → Plugins → Context**. Its fields
come from `plugin.yaml`'s `config_schema`, under
`plugins.entries.context.settings`. Labels prefix the logical groups below;
the current Hermes renderer need not render separate group sections.

In a chat, `/fulcra setup` shows current values and choices without enabling
anything. `/fulcra status` and `/fulcra help` are read-only settings views.
`/fulcra setup --help` explains flags. The terminal equivalents are
`hermes fulcra setup`, `hermes fulcra status`, and `hermes fulcra setup --help`.
Use `hermes -p NAME fulcra ...` for an explicitly selected profile.

For example, after explicitly choosing all features for trusted chats:

```text
/fulcra setup --workspace on --updates on --interval 900 --mesh-messages on --mesh-invites on --mesh-agent personal-assistant
```

Or from a terminal (same settings and implementation):

```bash
hermes fulcra setup --workspace on --updates on --interval 900 --mesh-messages on --mesh-invites on --mesh-agent personal-assistant
hermes fulcra status
```

Use the **exact, stable, case-sensitive** `local_agent` name supplied to your
mesh peers, not an ephemeral Hermes session ID. Configuration does not create a
mesh connection: use the explicit `fulcra_mesh` invitation/share workflow first.
No agent name is required for invitation candidates alone:

```bash
hermes fulcra setup --workspace off --updates off --mesh-messages off --mesh-invites on
```

Only supplied flags are written, through `ctx.set_config`; all inputs and the
proposed resulting configuration are validated before the first config write.
Current values are read back, including omitted advanced interests. Multiple
settings writes are not a filesystem transaction: a persistence failure can
leave a partial change; inspect status before retrying. No stdin prompts, no
always-loaded setup tool, no automatic enabling, and no questionnaire. Bad slash
arguments and help return text rather than raising `SystemExit` in the gateway.

The first eligible new session receives a concise options offer: workspace
`context.md` loading; what's-new notices and a configurable shared check interval;
independent automatic mesh message checks and invitation checks. It includes
native Desktop settings, `/fulcra setup` and `hermes fulcra setup` entrypoints,
not just a pointer to settings. No automatic enablement or forced questionnaire.
`plugin_setup.py` requires `is_first_turn is True`, a session ID, no parent and a
non-cron platform before reading or consuming the discovery marker. Missing/false
first-turn flags and ordinary turns leave it untouched for the next eligible new
session. Only a per-profile marker is persisted in `ctx.state`; no feature flags
are written. Explicit setup/status/help invocation handles discovery. Profiles
with all four feature flags already explicitly configured need no offer; all
prior true/false choices remain intact. The marker survives sessions/restarts and
means offered to the model or explicitly handled, not proof of delivery or decline.
Cron, child and sessionless turns also cannot consume automatic notifications.

## Settings and runtime consumers

Every key below is declared in the manifest, with a label and description.

| Logical group | Setting | Default | Consumer / effect |
| --- | --- | --- | --- |
| Workspace | `workspace_context_enabled` | `false` | First-turn `context.md` loading; missing-only bootstrap |
| Workspace | `workspace_name` | `general` | Remote `/workspace/<name>` namespace |
| Workspace | `workspace_role` | `assistant` | Durable `member/<role>` bootstrap responsibility |
| Updates | `updates_enabled` | `false` | Turn-triggered `data-updates` (what's new) digest |
| Shared checks | `update_interval` | `900` | Minimum seconds between attempts for each of updates and mesh, 60–86400 |
| Updates | `updates_data_types` | `[]` | Exact type allowlist; empty means all |
| Updates | `updates_include_files` | `true` | Include file change metadata |
| Updates | `updates_file_prefixes` | `[]` | Literal path prefix allowlist; empty means all |
| Updates | `updates_ignore_prefixes` | `[]` | Exclusions override includes |
| Mesh | `mesh_messages_enabled` | `false` | Read peer records for exact own userid + `mesh_agent` |
| Mesh | `mesh_invites_enabled` | `false` | List incoming narrow share candidates, without reading peer records when messages are off |
| Mesh | `mesh_agent` | `""` | Exact canonical `local_agent`, required when message checks are enabled |

Workspace names/roles are single ASCII path segments (1–64 characters, initially
alphanumeric, then alphanumeric/hyphen/underscore). Agent names are strings of at
most 128 characters, without ASCII control characters, nonblank for message reads.
The native renderer currently enforces types, not every range or cross-field rule;
set the agent name before enabling messages. Runtime readers fail closed on invalid
settings. Use the form or existing `fulcra_configure_updates` tool for advanced
update interests; the compatibility tool continues working unchanged. The shared
interval deliberately avoids a second cadence knob; independent workers have
independent cooldowns, so enabling mesh never requires enabling updates.

## Automatic mesh behavior and limits

`post_llm_call` launches a due daemon worker without waiting. It carries the
active profile/secret context using `contextvars.copy_context()` and spends one
30-second deadline across pinned CLI calls. `pre_llm_call` only consumes cached
compact notifications; it never performs mesh network work. There is **no idle
timer**: checks need eligible turns and notifications need a later turn. Updates
baseline at current time; mesh initially checks the canonical recent seven days,
then uses its own cursor with a ten-minute overlap and 2,048-mid dedup per channel.
First invitation checking may offer already-existing candidates once.

The worker reuses canonical `mesh._receive`, channel validation, JSONL parsing,
narrow-share selection, envelope validation and addressing, injecting a bounded
CLI callable rather than patching shared module globals. It never parses the
public tool's potentially truncated response. Manual `mesh.v1` state is untouched;
automatic cursors live separately in `mesh-notifications.v1`, so manual receive
can still retrieve full messages. Previews retain up to 80 body characters, plus
mid/owner/channel lookup identifiers. Use explicit `fulcra_mesh receive` with
`local_agent`, `peer_userid`, `incoming_channel`, and optionally `since` to inspect
full details. No automatic acceptance, sharing, sends, replies, or peer instruction
execution. Incoming bodies and provenance fields are untrusted data.

Invitation candidates require a valid sharing account, a share UUID and exactly
one `MomentAnnotation/<uuid>` selector, `share_all_data: false`, no files or file
paths. Notices label share ID, grant type and grant ID when provided. The sharing
account comes from `sharing_fulcra_userid`, never a claimed sender in a message.
A narrow share is neither acceptance nor proof of exclusive readership; group
grants remain labeled. The canonical mesh protocol and authorization boundaries
are described in [mesh.md](mesh.md).

Bounds are deliberately summaries, not a durable inbox: consider the first 64
sorted narrow candidates; rotate through at most eight of those per message
check. Retain automatic cursors only for currently selected channels, the last
2,048 invitation fingerprints, and at most 32 pending items. Offer at most eight
items in fewer than 3,000 characters; escaped previews count against that budget.
Overflow is omitted, not retried as a delivery queue. Removed/re-added channels,
config resets and dedup eviction may replay recent history. A failing cycle
commits no new cursors or dedup markers and retains the last-attempt cooldown;
slow or inaccessible channels can delay the batch. Full CLI responses are parsed
in memory (as with manual receive); these are not subprocess memory quotas.

State is durable and shared across eligible sessions in the active profile.
Transactions use a per-profile, process-local lock, with no network under it.
Completion merges into fresh state so turns consuming pending items aren't
undone. Disabling either mesh flag or changing the agent invalidates pending and
in-flight mesh work, resets its automatic history, and preserves cooldown. A CLI
already running may finish; results from an invalidated epoch cannot be queued.
Direct UI changes are noticed on the next hook/worker check; an off/on toggle
entirely between observations is not detectable. Do not run multiple polling
Hermes processes on the same profile; this is not a distributed lease.

The CLI login is OS-user shared. Observed account changes during mesh polling
clear/reinitialize its cache and invalidate update digests/workers too. A pre hook
cannot observe an external login change without network, and updates alone do
not query account identity. **Before switching the external Fulcra login, disable
updates and both mesh checks in every affected active profile, let existing CLI
calls finish, switch login, then re-enable the intended choices before resuming
trusted chats.** No cross-profile cache or discovery marker is shared. Stored
previews, IDs and paths are sensitive profile data; do not publicly back them up.
Old conversation excerpts cannot be withdrawn. Other top-level autonomous contexts
are still indistinguishable from trusted user turns; cron/parent/session gating is
not a complete automation classifier. Notifications are offered to the model at
most once per queued item, not guaranteed user delivery or peer acknowledgement.

## Why this setup surface

Authoritative reference: [Hermes plugin developer guide](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins).
The live `PluginContext` API and `hermes_cli/plugins_settings.py` confirm that
`config_schema` produces native Desktop/TUI plugin settings and `get_config` /
`set_config` are the canonical settings path. `register_command` provides slash
commands across CLI and gateways; `register_cli_command` supplies `hermes fulcra`.

| Option | Decision |
| --- | --- |
| Native settings form | Canonical, discoverable, all declared settings, shared writer |
| `/fulcra setup` and `hermes fulcra setup` | Explicit noninteractive frontends sharing validation and readback; useful without Desktop |
| Install/setup callback | No general callback found in the authoritative plugin API; current `hermes plugins --help` has no config/setup command. Do not invent one or perform setup during registration |
| First-session options offer | Retained because native settings are not proactively presented; lists independent choices and entrypoints without a forced questionnaire |
| New setup model tool | Unnecessary permanent tool-schema cost; existing update configuration tool retained for compatibility |

Nothing runs at import/registration except registration itself. No Hermes core
changes or host dependencies are needed. See [development.md](development.md) for
fixture tests and real-Hermes temporary-profile probes; none require a live account.
