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
File selectors require literal absolute POSIX paths (root `/` is allowed);
relative paths, dot segments, backslashes, double slashes and NUL are rejected.
Time bounds limit the accessible time range of time-series data types only,
never file access. File/all-data shares can carry bounds for their data types.
The adapter does not fetch outgoing share state before updates; inspect shares
before changing access and verify afterward.
Authentication uses `fulcra_auth` and `fulcra_auth_device`.

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
