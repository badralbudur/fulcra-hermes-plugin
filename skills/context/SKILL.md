---
name: context
description: Use Fulcra tools for catalogs, records, sharing, updates and files.
---

# Fulcra Context

## Authentication and discovery

- Start with `fulcra_data_catalog`; use its filters to find exact data type IDs.
- If authentication is needed, call `fulcra_auth`, show the browser URL and user
  code, wait for approval, then call `fulcra_auth_device` with the device code.
- The CLI login is shared by Hermes profiles and messaging users under the same
  host OS account. Runtime isolation does not isolate Fulcra accounts.

## Data types and records

- `fulcra_create_data_type` creates annotation types. Read
  `fulcra_data_type_schema` before writing; `fulcra_data_type_lifecycle` archives
  or restores a type, not individual records.
- `fulcra_get_records` takes two timezone-aware timestamps, a CLI time expression
  such as `["2 days"]` or `["yesterday"]`, or `["latest"]`. Raw sources may overlap;
  don't blindly sum them. Translate results to the user's timezone when known.
- `fulcra_record` takes one `record` or a `records` array. `fulcra_delete_records`
  takes one `record_id`, one `{record_id}` record, or a batch. Use explicit targets.
- `fulcra_data_updates` reports processing changes, not event times. Record and
  deletion uploads can be asynchronous; read back before claiming completion.

## Sharing

- `fulcra_list_shares` lists incoming, outgoing, or both. `fulcra_leave_share`
  takes an incoming individual `grant_id`; update/delete use outgoing share IDs.
- Create shares with explicit recipients and data/file scope. Only use
  `share_all:true` when requested. Group recipients include future members.
- Updates change supplied fields: `set_data_types` replaces all data/file
  selectors; `set_files` replaces only files. `clear` clears shared selectors and
  all-data mode; `no_group_ids` clears groups. Removing time bounds broadens
  time-series data access only, not file access.
- Use `fulcra_shared_data_types` before querying another owner's data. Request a
  window strictly inside the grant's bounds. `all_data_types:true` with an empty
  type list means all data is shared. Pass the owner's `user_id` to read tools.
- Use explicit absolute POSIX remote paths. Root `/` selects all files;
  the CLI handles remote paths without adapter-specific path validation.
- Time bounds limit the accessible time range of time-series data types only,
  never file access. File/all-data shares can carry bounds for data types.
  The adapter does not fetch outgoing share state before updates; inspect it
  before changing access.
- Verify shares after changes. Deleting a share revokes access, not underlying data.

## Files and results

- `fulcra_file_list` and `fulcra_file_stat` return CLI text; stat includes your
  version history for `fulcra_file_restore`.
- Upload literal UTF-8 `content` or an existing absolute `local_path`. Updating a
  remote path creates a new version. Do not upload unrelated files or secrets.
- Download returns UTF-8 text subject to the result limit below, or saves exact
  bytes to a new `local_path`.
  Existing local files are not overwritten; binary downloads require a local path.
- File sharing grants latest-version access to path prefixes, including future
  files; `/` covers all files. Use `fulcra_create_share` for group recipients.
- Results up to 16,000 UTF-8 bytes are returned unchanged, except for explicit
  device-code redaction in errors and special timeout output.
  Larger results return a byte-bounded preview, an explicit truncation notice,
  and an absolute path to the complete local UTF-8 artifact. Read that file with
  local file tools, paging as needed; the preview is not a complete dataset or
  necessarily valid JSONL. Combined share listings add direction labels.
- Artifacts live in the active Hermes profile's `fulcra-output/` directory
  (0700), in private 0600 files. They may contain sensitive health data; do not
  share them or put them in public backups. Retention is manual: files remain
  until explicitly deleted, with no automatic cleanup. Errors retain exception
  types and details; only the supplied device code is explicitly redacted.
  The CLI owns other sanitization, including for saved errors. Successful stderr
  warnings are discarded; timeout errors omit argv and partial output.
- Successful auth output is never saved as an artifact. Oversized auth output
  retains complete URL/code lines or the success message when possible. If usable
  fields cannot be retained, check auth state before starting another flow.
  If artifact storage fails, the full result is unavailable; the operation may
  still have completed, so verify writes before retrying.
- After a write or timeout, check the relevant read tool before retrying or claiming
  success. Keep summaries concise and grounded in the returned data.
