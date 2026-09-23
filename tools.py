"""Native Hermes tools backed by an isolated, pinned Fulcra CLI."""

import json
import os
import shutil
import subprocess
import functools
import math
import tempfile
from datetime import datetime
from pathlib import Path


TOOL_SCHEMAS = {}
STRING = {"type": "string", "minLength": 1}
BOOLEAN = {"type": "boolean"}

UUID_PATTERN = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
UUID = {"type": "string", "pattern": "^" + UUID_PATTERN + "$"}
DATA_TYPE = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_.-]*(?:/" + UUID_PATTERN + r")?$"}
BASE_TYPES = ["MomentAnnotation", "DurationAnnotation", "BooleanAnnotation", "NumericAnnotation", "ScaleAnnotation"]


def _array(items=STRING):
    return {"type": "array", "items": items, "minItems": 1}


def _enum(*values):
    return {"type": "string", "enum": list(values)}


def _pos(value):
    """Keep a user-supplied positional argument from becoming a CLI option."""
    if not isinstance(value, str) or not value.strip() or value.startswith("-") or "\x00" in value:
        raise ValueError("CLI arguments must be nonempty strings without a leading dash or NUL.")
    return value


def _tool(name, description, properties, required=()):
    schema = {"description": description, "parameters": {
        "type": "object", "properties": properties, "required": list(required), "additionalProperties": False}}
    TOOL_SCHEMAS[name] = schema

    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(args, **kwargs):
            try:
                if not isinstance(args, dict) or args.keys() - properties.keys():
                    raise ValueError("Unknown tool arguments.")
                if "path" in args:
                    path = _pos(args["path"])
                    if not path.startswith("/") or "\\" in path or "//" in path or any(p in (".", "..") for p in path.split("/")):
                        raise ValueError("Use an explicit absolute remote path without dot segments.")
                return fn(args)
            except (ValueError, RuntimeError) as exc:
                return f"Error: {exc}"
            except Exception:
                return "Error: Fulcra operation failed locally; check inputs, file permissions and the CLI installation."
        return wrapped
    return decorate


def _options(args, mapping):
    result = []
    for key, flag in mapping.items():
        if key not in args:
            continue
        value = args[key]
        if isinstance(value, bool):
            if value:
                result.append(flag)
        else:
            for item in value if isinstance(value, list) else [value]:
                if "\x00" in str(item):
                    raise ValueError("CLI option values must contain no NUL.")
                if str(item).startswith("-"):
                    result.append(flag + "=" + str(item))
                else:
                    result.extend([flag, str(item)])
    return result



FULCRA_PACKAGE = "fulcra-api==0.1.42"


def _runtime_context():
    # Resolve settings and secrets at call time for the active Hermes profile.
    from hermes_cli.config import load_config
    from hermes_constants import get_hermes_home
    from tools.environments.local import served_profile_child_env

    allowed = load_config().get("security", {}).get("allow_lazy_installs", True)
    env = served_profile_child_env(target_home=get_hermes_home(), inherit_credentials=False)
    return allowed, env


def _run_cli(arguments, *, timeout=180):
    """Execute only plugin-selected CLI operations outside Hermes's Python environment."""
    allowed, env = _runtime_context()
    if not allowed:
        raise RuntimeError("Fulcra's uv runtime requires security.allow_lazy_installs; it is disabled.")
    # Ignore ambient Python/uv overrides: only this pinned package belongs in the child.
    env = {key: value for key, value in env.items()
           if not key.startswith(("UV_", "PYTHON")) and key not in {"VIRTUAL_ENV", "CONDA_PREFIX"}}
    env["PYTHONIOENCODING"] = "utf-8"
    from hermes_cli.managed_uv import managed_uv_path

    # Extend only the child PATH; direct subprocesses do not load shell setup.
    managed_bin = str(managed_uv_path().parent)
    path = env.get("PATH", "")
    if managed_bin not in path.split(os.pathsep):
        env["PATH"] = path + os.pathsep + managed_bin if path else managed_bin
    uv = shutil.which("uv", path=env.get("PATH", ""))
    if not uv:
        raise RuntimeError("Install uv and put it on the Hermes host's PATH, then retry.")
    command = [uv, "tool", "run", "--isolated", "--no-config", "--from", FULCRA_PACKAGE, "fulcra-api", *arguments]
    try:
        result = subprocess.run(
            command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # TimeoutExpired contains argv (including the device code); don't expose it.
        raise RuntimeError(f"Fulcra CLI timed out after {timeout} seconds; retry the operation.") from None
    except OSError:
        raise RuntimeError("Could not start Fulcra CLI; check the host's uv installation.") from None
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or "no diagnostic output"
        if "--device-code" in arguments:
            detail = detail.replace(arguments[arguments.index("--device-code") + 1], "[redacted]")

        raise RuntimeError(f"Fulcra CLI exited with status {result.returncode}: {detail}")
    output = result.stdout
    # Empty read/mutation output is valid; authentication must return its codes.
    if not output and arguments[:2] == ["auth", "login"]:
        raise RuntimeError("Fulcra CLI returned an empty response.")
    return output


@_tool("fulcra_auth", "Start noninteractive browser authentication; return an auth URL and device code. Wait for browser approval before fulcra_auth_device. Does not reset existing credentials.", {})
def fulcra_auth(args):
    """Start the noninteractive device flow; never open a browser on the host."""
    return _run_cli(["auth", "login", "--get-auth-url"])


@_tool("fulcra_auth_device", "Finish authentication only after browser approval using the device_code from fulcra_auth. CLI persists credentials in OS-user storage, shared by Hermes profiles.", {"device_code": STRING}, ("device_code",))
def fulcra_auth_device(args):
    """Finish the device flow and let the CLI persist its own credentials."""
    return _run_cli(
        ["auth", "login", "--device-code", _pos(args["device_code"]),
         "--poll-timeout", "900", "--poll-interval", "5"], timeout=1080)


@_tool("fulcra_data_catalog", "Discover data type IDs before querying or writing. Filter by name, category, owner, API version, or recordable/queryable/base types. Returns the CLI catalog output.", {
    "data_type": DATA_TYPE, "name": STRING, "base_types_only": BOOLEAN,
    "recordable_only": BOOLEAN, "queryable_only": BOOLEAN, "category": STRING,
    "api_version": STRING, "user_id": UUID})
def fulcra_data_catalog(args):
    command = ["catalog"] + _options(args, {
        "data_type": "--data-type", "name": "--name", "base_types_only": "--base-types-only",
        "recordable_only": "--recordable-only", "queryable_only": "--queryable-only",
        "category": "--category", "api_version": "--api-version", "user_id": "--user-id"})
    return _run_cli(command)


@_tool("fulcra_create_data_type", "Create a user-defined annotation type, not records. Discover base types with fulcra_data_catalog, then inspect fulcra_data_type_schema and use fulcra_record. ScaleAnnotation requires five labels; metric options apply only to metrics.", {
    "base_type": _enum(*BASE_TYPES), "name": STRING, "description": STRING,
    "tags": _array(), "metric_kind": _enum("cumulative", "discrete"),
    "default_value": STRING, "unit": STRING, "scale_labels": _array()}, ("base_type", "name"))
def fulcra_create_data_type(args):
    base = args["base_type"]
    # The CLI validates units, labels and defaults; these two gaps need guarding.
    if "default_value" in args and base == "ScaleAnnotation":
        raise ValueError("The CLI ignores default_value for ScaleAnnotation; omit it.")
    if "default_value" in args and base == "NumericAnnotation" and not math.isfinite(float(args["default_value"])):
        raise ValueError("default_value must be a finite number.")
    command = ["data-type", "create", _pos(base), _pos(args["name"])] + _options(args, {
        "description": "--description", "tags": "--tag", "metric_kind": "--kind",
        "default_value": "--value", "unit": "--unit", "scale_labels": "--scale-label"})
    return _run_cli(command)


@_tool("fulcra_data_type_schema", "Read the JSON record schema before fulcra_record. Use api_version to disambiguate catalog entries; user_id selects a shared owner's schema.", {
    "data_type": DATA_TYPE, "api_version": STRING, "user_id": UUID}, ("data_type",))
def fulcra_data_type_schema(args):
    command = ["data-type", "schema", _pos(args["data_type"])] + _options(args, {"api_version": "--api-version", "user_id": "--user-id"})
    return _run_cli(command)


@_tool("fulcra_data_type_lifecycle", "Archive or restore your user-defined annotation type. This changes availability of the type, not a request to delete individual records. Requires the complete BaseAnnotation/UUID ID.", {
    "data_type": DATA_TYPE, "action": _enum("archive", "restore")}, ("data_type", "action"))
def fulcra_data_type_lifecycle(args):
    if args["action"] not in ("archive", "restore"):
        raise ValueError("action must be archive or restore.")
    parts = args["data_type"].split("/")
    if len(parts) != 2 or parts[0] not in BASE_TYPES:
        raise ValueError("data_type must be a complete BaseAnnotation/UUID ID from fulcra_data_catalog.")
    raw = _run_cli(["data-type", args["action"], _pos(args["data_type"])])
    return raw


TIME_RANGE = {"type": "array", "items": STRING, "minItems": 1, "maxItems": 2,
              "description": "Two ISO8601 timestamps with timezone and end after start, or one CLI time expression such as '2 days' or 'yesterday'. Only get_records accepts 'latest'."}


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed
    except ValueError:
        raise ValueError("Times must be ISO8601 with timezone, e.g. 2026-01-01T00:00:00Z.") from None


def _times(args, *, latest=False):
    values = args["time_range"]
    if not isinstance(values, list) or len(values) not in (1, 2):
        raise ValueError("time_range must contain one interval or two timestamps.")
    if len(values) == 2:
        if _timestamp(values[1]) <= _timestamp(values[0]):
            raise ValueError("end time must be after start time.")
    elif values[0].lower() == "latest" and not latest:
        raise ValueError("latest is supported only by fulcra_get_records.")
    return [_pos(value) for value in values]


def _record_file(command, rows):
    payload = "\n".join(json.dumps(row, allow_nan=False) for row in rows)
    with tempfile.TemporaryDirectory(prefix="fulcra-record-") as directory:
        path = Path(directory) / "records.jsonl"
        with path.open("x", encoding="utf-8") as stream:
            path.chmod(0o600)
            stream.write(payload + "\n")
        return _run_cli(command + ["--file", str(path)])


@_tool("fulcra_record", "Write one structured record or a batch to your recordable data type. Inspect fulcra_data_type_schema first; provide exactly one of record/records. CLI schema validation stays enabled. Tags may create tags; sources include the CLI and annotation source. Upload acceptance is not ingestion completion; use fulcra_data_updates/get_records afterward.", {
    "data_type": DATA_TYPE, "record": {"type": "object"}, "records": _array({"type": "object"}),
    "api_version": STRING, "tags": _array(), "sources": _array()}, ("data_type",))
def fulcra_record(args):
    if ("record" in args) == ("records" in args):
        raise ValueError("Provide exactly one of record or records.")
    rows = [args["record"]] if "record" in args else args["records"]
    command = ["record", _pos(args["data_type"])] + _options(args, {"api_version": "--api-version", "tags": "--tag", "sources": "--source"})
    return _record_file(command, rows)


DELETION = {"type": "object", "properties": {"record_id": UUID}, "required": ["record_id"], "additionalProperties": False}


@_tool("fulcra_delete_records", "Delete only explicitly identified records from your recordable data type. Provide exactly one of record_id, record {record_id: UUID}, or records [{record_id: UUID}]. No time-range or all-record deletion. Retrieve IDs with fulcra_get_records first; deletion uploads may process asynchronously.", {
    "data_type": DATA_TYPE, "record_id": UUID, "record": DELETION, "records": _array(DELETION), "api_version": STRING}, ("data_type",))
def fulcra_delete_records(args):
    if sum(key in args for key in ("record_id", "record", "records")) != 1:
        raise ValueError("Provide exactly one of record_id, record or records.")
    command = ["delete", _pos(args["data_type"])]
    if "record_id" in args:
        command.append(_pos(args["record_id"]))
    command += _options(args, {"api_version": "--api-version"})
    if "record_id" in args:
        raw = _run_cli(command)
    else:
        rows = [args["record"]] if "record" in args else args["records"]
        raw = _record_file(command, rows)
    return raw


@_tool("fulcra_get_records", "Read raw records using IDs from fulcra_data_catalog. Raw sources can overlap; do not sum without prioritizing/deduplicating. Use fulcra_shared_data_types before reading another user's data.", {
    "data_type": DATA_TYPE, "time_range": TIME_RANGE, "user_id": UUID,
    "group_id": UUID, "participant_id": STRING}, ("data_type", "time_range"))
def fulcra_get_records(args):
    if ("group_id" in args) != ("participant_id" in args) or ("group_id" in args and "user_id" in args):
        raise ValueError("Use user_id OR the pair group_id and participant_id.")
    command = ["get-records", _pos(args["data_type"]), *_times(args, latest=True)] + _options(args, {
        "user_id": "--user-id", "group_id": "--group-id", "participant_id": "--participant-id"})
    return _run_cli(command)


@_tool("fulcra_data_updates", "Read data/file processing updates during a time range, not record event times. Useful after fulcra_record or upload; no latest mode. user_id requires shared access.", {
    "time_range": TIME_RANGE, "user_id": UUID}, ("time_range",))
def fulcra_data_updates(args):
    command = ["data-updates", *_times(args)] + _options(args, {"user_id": "--user-id"})
    return _run_cli(command)


REMOTE_PATH = {"type": "string", "pattern": r"^/[^\x00]*$", "description": "Explicit absolute POSIX remote path. '/' shares/lists the entire file tree; directory prefixes include future files."}
SHARE_TIMES = {"start_time": STRING, "end_time": STRING}


def _share_times(args):
    for key in SHARE_TIMES:
        if key in args:
            _timestamp(args[key])
        if key in args and args.get("no_" + key):
            raise ValueError(f"{key} conflicts with no_{key}.")
    if all(key in args for key in SHARE_TIMES) and _timestamp(args["end_time"]) <= _timestamp(args["start_time"]):
        raise ValueError("end_time must be after start_time.")


@_tool("fulcra_create_share", "Grant read access to explicit data_types/files OR share_all=true, with explicit user_ids/group_ids. Never infer all-data scope. Group access follows current membership, including future joiners. File prefixes share latest versions, not history; '/' covers all files. Missing time bounds are open-ended. Inspect fulcra_list_shares afterward.", {
    "name": STRING, "data_types": _array(DATA_TYPE), "files": _array(REMOTE_PATH),
    "user_ids": _array(UUID), "group_ids": _array(UUID), "share_all": BOOLEAN, **SHARE_TIMES})
def fulcra_create_share(args):
    if type(args.get("share_all", False)) is not bool:
        raise ValueError("share_all must be an explicit boolean.")
    if not (args.get("user_ids") or args.get("group_ids")):
        raise ValueError("Specify at least one user_ids or group_ids recipient.")
    scoped = bool(args.get("data_types") or args.get("files"))
    if scoped == bool(args.get("share_all")):
        raise ValueError("Specify explicit data_types/files OR share_all=true, never both or neither.")
    _share_times(args)
    command = ["share", "create"] + _options(args, {
        "name": "--name", "data_types": "--data-type", "files": "--file", "user_ids": "--user-id",
        "group_ids": "--group-id", "start_time": "--start-time", "end_time": "--end-time", "share_all": "--share-all"})
    return _run_cli(command)


SHARE_LIST_FIELDS = {"data_types": (DATA_TYPE, "data-type"), "files": (REMOTE_PATH, "file"),
                     "user_ids": (UUID, "user-id"), "group_ids": (UUID, "group-id")}
SHARE_UPDATE_FIELDS = {f"{action}_{key}": _array(schema)
                       for key, (schema, flag) in SHARE_LIST_FIELDS.items()
                       for action in ("add", "remove", "set")}
SHARE_UPDATE_FLAGS = {f"{action}_{key}": f"--{action}-{flag}"
                      for key, (schema, flag) in SHARE_LIST_FIELDS.items()
                      for action in ("add", "remove", "set")}


@_tool("fulcra_update_share", "Change only explicitly supplied share fields. Read fulcra_list_shares outgoing first. set_data_types replaces ALL shared type/file selectors (CLI semantics); set_files replaces file selectors only. clear removes selectors and disables all-data before additions. Empty set lists are rejected; use clear/no_group_ids. Turning on share_all or removing time bounds broadens access. Review recipients and verify afterward.", {
    "share_id": UUID, "name": STRING, **SHARE_UPDATE_FIELDS, "no_group_ids": BOOLEAN,
    "share_all": BOOLEAN, **SHARE_TIMES, "no_start_time": BOOLEAN,
    "no_end_time": BOOLEAN, "clear": BOOLEAN}, ("share_id",))
def fulcra_update_share(args):
    if type(args.get("share_all", False)) is not bool:
        raise ValueError("share_all must be an explicit boolean.")
    if not any(value or key == "share_all" for key, value in args.items() if key != "share_id"):
        raise ValueError("Specify at least one change to the share.")
    for key in SHARE_LIST_FIELDS:
        add, remove, replace = (args.get(f"{action}_{key}", []) for action in ("add", "remove", "set"))
        if replace and (add or remove):
            raise ValueError(f"set_{key} conflicts with add/remove_{key}.")
        if set(add) & set(remove):
            raise ValueError(f"Cannot add and remove the same {key}.")
    if args.get("no_group_ids") and any(key in args for key in ("set_group_ids", "add_group_ids", "remove_group_ids")):
        raise ValueError("no_group_ids conflicts with other group changes.")
    if args.get("clear") and (args.get("share_all") or any(key in args for key in ("set_data_types", "set_files", "remove_data_types", "remove_files"))):
        raise ValueError("clear conflicts with replacement/removal selectors or share_all=true; use additions after clear.")
    if args.get("share_all") and any(key in args for key in SHARE_UPDATE_FIELDS if key.endswith(("data_types", "files"))):
        raise ValueError("share_all=true conflicts with explicit selector changes.")
    _share_times(args)
    command = ["share", "update", _pos(args["share_id"])] + _options(args, {
        "name": "--name", **SHARE_UPDATE_FLAGS, "no_group_ids": "--no-group-id",
        "start_time": "--start-time", "end_time": "--end-time", "no_start_time": "--no-start-time",
        "no_end_time": "--no-end-time", "clear": "--clear"})
    if "share_all" in args:
        command.append("--share-all-data" if args["share_all"] else "--no-share-all-data")
    return _run_cli(command)


@_tool("fulcra_list_shares", "List incoming grants, outgoing shares, or both (default). With both, CLI outputs are labeled by direction. Incoming grant_id is for fulcra_leave_share; outgoing share ID is for fulcra_update_share/delete_share. Group grants cannot be left individually.", {
    "direction": _enum("incoming", "outgoing", "both")})
def fulcra_list_shares(args):
    direction = args.get("direction", "both")
    if direction not in ("incoming", "outgoing", "both"):
        raise ValueError("direction must be incoming, outgoing or both.")
    if direction != "both":
        return _run_cli(["share", "list-" + direction])
    return "\n\n".join(f"{current}:\n{_run_cli(['share', 'list-' + current])}"
                       for current in ("incoming", "outgoing"))


@_tool("fulcra_delete_share", "Revoke an entire outgoing share you created, removing every recipient's access through it. Read fulcra_list_shares outgoing and confirm scope first. This does not delete underlying records/files.", {"share_id": UUID}, ("share_id",))
def fulcra_delete_share(args):
    return _run_cli(["share", "delete", _pos(args["share_id"])])


@_tool("fulcra_leave_share", "Give up your individual incoming grant. Use grant_id (not share ID) from fulcra_list_shares. Group grants cannot be left with this tool; group membership management is outside this surface.", {"grant_id": UUID}, ("grant_id",))
def fulcra_leave_share(args):
    return _run_cli(["share", "leave", _pos(args["grant_id"])])


@_tool("fulcra_shared_data_types", "Check what an owner shares with you before querying their records. Request a window strictly inside the grant's boundaries: its end comparison is strict. all_data_types=true with an empty type list means everything is shared, not nothing. Includes group grants.", {
    "user_id": UUID, "time_range": TIME_RANGE}, ("user_id", "time_range"))
def fulcra_shared_data_types(args):
    return _run_cli(["share", "shared-data-types", _pos(args["user_id"]), *_times(args)])


def _local_path(value, *, new=False):
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("local_path must be an absolute local file path.")
    if new:
        if path.exists() or path.is_symlink():
            raise ValueError("Destination already exists; choose a new local file path (no overwrites).")
        if not path.parent.is_dir():
            raise ValueError("Destination parent directory must already exist.")
    elif not path.is_file():
        raise ValueError("local_path must name an existing regular file.")
    return path


@_tool("fulcra_file_upload", "Upload local bytes OR UTF-8 text content to an explicit remote file path; exactly one source is required. Uploading an existing remote path creates a new version. Text is staged privately; binary files use local_path. Verify with fulcra_file_stat. Do not upload secrets or unrelated files.", {
    "path": REMOTE_PATH, "local_path": STRING,
    "content": {"type": "string", "description": "Literal UTF-8 text (may be empty); never treated as CLI options."}}, ("path",))
def fulcra_file_upload(args):
    if ("local_path" in args) == ("content" in args):
        raise ValueError("Provide exactly one of local_path or content.")
    if "local_path" in args:
        path = _local_path(args["local_path"])
        raw = _run_cli(["file", "upload", str(path), args["path"]])
    else:
        with tempfile.TemporaryDirectory(prefix="fulcra-upload-") as directory:
            path = Path(directory) / "content.txt"
            with path.open("x", encoding="utf-8", newline="") as stream:
                path.chmod(0o600)
                stream.write(args["content"])
            raw = _run_cli(["file", "upload", str(path), args["path"]])
            raw = raw.replace(str(path), "[text content]")
    return raw


@_tool("fulcra_file_download", "Download the latest remote file version. With local_path, save exact bytes to a new absolute local file without overwriting. Otherwise return the full UTF-8 text. Binary files require local_path; user_id selects a shared owner.", {
    "path": REMOTE_PATH, "local_path": STRING, "user_id": UUID}, ("path",))
def fulcra_file_download(args):
    target = _local_path(args["local_path"], new=True) if "local_path" in args else None
    with tempfile.TemporaryDirectory(prefix="fulcra-download-") as directory:
        staged = Path(directory) / "download"
        _run_cli(["file", "download", args["path"], str(staged)] + _options(args, {"user_id": "--user-id"}))
        if not staged.is_file():
            raise RuntimeError("CLI reported success but did not create the downloaded file.")

        if target is not None:
            # Exclusive create also protects against destination races and symlinks.
            with target.open("xb") as destination:
                target.chmod(0o600)
                with staged.open("rb") as source:
                    shutil.copyfileobj(source, destination)
            return f"Downloaded {args['path']} to {target}"
        try:
            return staged.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError("File is not UTF-8 text; supply local_path to download exact bytes.") from None


@_tool("fulcra_file_list", "List a remote directory (default '/'), optionally for a shared owner. Returns CLI text. Use fulcra_file_stat for versions and fulcra_file_download for contents.", {
    "path": REMOTE_PATH, "user_id": UUID})
def fulcra_file_list(args):
    raw = _run_cli(["file", "list", args.get("path", "/")] + _options(args, {"user_id": "--user-id"}))
    return raw


@_tool("fulcra_file_stat", "Read file size, upload time and version IDs as CLI text lines. Your own files include previous versions usable by fulcra_file_restore; shared owners' files expose latest version only.", {
    "path": REMOTE_PATH, "user_id": UUID}, ("path",))
def fulcra_file_stat(args):
    raw = _run_cli(["file", "stat", args["path"]] + _options(args, {"user_id": "--user-id"}))
    return raw


@_tool("fulcra_file_delete", "Delete your file at an explicit remote path. Inspect fulcra_file_stat first and retain version IDs if restoration may be needed. This is not a recursive directory delete and does not revoke shares.", {"path": REMOTE_PATH}, ("path",))
def fulcra_file_delete(args):
    return _run_cli(["file", "delete", args["path"]])


@_tool("fulcra_file_restore", "Restore a previous file version using its exact version UUID from fulcra_file_stat. This changes the current version at the original path; inspect stat afterward.", {"version_id": UUID}, ("version_id",))
def fulcra_file_restore(args):
    return _run_cli(["file", "restore", _pos(args["version_id"])])


@_tool("fulcra_file_share", "Grant explicit users access to the latest file versions at a path/prefix using the CLI file share command. Directories include future files; '/' grants all files. No history is granted. For groups or time bounds use fulcra_create_share with files instead. Verify with fulcra_list_shares outgoing.", {
    "path": REMOTE_PATH, "user_ids": _array(UUID), "name": STRING}, ("path", "user_ids"))
def fulcra_file_share(args):
    command = ["file", "share", args["path"]] + _options(args, {"user_ids": "--to", "name": "--name"})
    return _run_cli(command)
