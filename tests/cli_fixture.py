"""Run only inside the pinned CLI environment, with fixtures and networking blocked."""
import datetime
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

from click.testing import CliRunner
from fulcra_api import records
from fulcra_api.cli import cli, utils
from fulcra_api.core import FulcraAPI
from fulcra_api.credentials import FulcraCredentials
REAL_GET_RECORDS = records.get_records

REAL_METHODS = {name: getattr(FulcraAPI, name) for name in (
    "create_datashare", "get_datashares", "get_shared_datasets", "get_user_info",
    "validate_records", "record_data_type", "v1_catalog", "v1_catalog_data_type",
    "v1_catalog_schema", "resolve_data_type")}

ID = "01234567-89ab-cdef-0123-456789abcdef"
DT = "NumericAnnotation/" + ID
root, directory = Path(sys.argv[1]), Path(sys.argv[2])
utils.CONFIG_PATH = directory
utils.CREDS_FILE = directory / "credentials.json"
utils.save_creds(FulcraCredentials(access_token="fixture", access_token_expiration=datetime.datetime.now() + datetime.timedelta(hours=1)))
spec = importlib.util.spec_from_file_location("adapter", root / "tools.py")
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)

calls = []
real_file_methods = {name: getattr(FulcraAPI, name) for name in
                     ('resolve_filepath', 'upload_file', 'download_file')}


def entry(data_type=DT):
    return {"id": data_type, "name": "Fixture", "categories": ["base_type"], "api_version": "v1alpha1",
            "recordable": True, "queryable": True, "fulcra_userid": ID, "record_spec": {"type": "metric", "schema": {"type": "object"}}}


def resolve(self, data_type, **kwargs):
    return [entry(data_type)]


def record(self, data_type, rows=None, **kwargs):
    payload = rows if rows is not None else kwargs["records"]
    calls.append(("record", data_type, payload))
    return {"upload_id": ID}


file_info = {"id": ID, "path": "/notes", "name": "test.txt", "size": 6, "uploaded_at": "2026-01-01T00:00:00Z"}
FulcraAPI.get_fulcra_userid = lambda self: ID
FulcraAPI.v1_catalog = lambda self, **kwargs: [entry(kwargs.get("data_type") or DT)]
FulcraAPI.v1_catalog_data_type = lambda self, **kwargs: entry(kwargs["data_type"])
FulcraAPI.resolve_data_type = resolve
FulcraAPI.create_annotation = lambda self, **kwargs: {"id": ID, **kwargs}
FulcraAPI.delete_annotation = lambda self, **kwargs: calls.append(("archive", kwargs))
FulcraAPI.restore_annotation = lambda self, **kwargs: {"id": ID}
FulcraAPI.validate_records = lambda self, *args, **kwargs: []
FulcraAPI.record_data_type = record
FulcraAPI.create_tags = lambda self, names: [{"id": ID} for name in names]
records.get_records = lambda *args, **kwargs: [{"record_id": ID, "value": 2}]
FulcraAPI.data_updates = lambda self, **kwargs: {"fixture_updates": []}
FulcraAPI.create_datashare = lambda self, **kwargs: {"id": ID, **{k: str(v) if isinstance(v, datetime.datetime) else v for k, v in kwargs.items()}}
FulcraAPI.update_datashare = lambda self, **kwargs: {"id": ID, **kwargs}
FulcraAPI.get_datashare = lambda self, *args: {"fulcra_data_types": ["HeartRate"], "permissions": [{"allowed_fulcra_userid": ID}], "group_permissions": []}
FulcraAPI.get_datashares = lambda self: [{"id": ID}]
FulcraAPI.get_shared_datasets = lambda self: [{"grant_type": "self"}, {"grant_type": "user", "grant_id": ID}]
FulcraAPI.delete_datashare = lambda self, *args: None
FulcraAPI.delete_dataset_permission = lambda self, *args: None
FulcraAPI.list_shared_data_types = lambda self, *args: {"all_data_types": True, "fulcra_data_types": []}
FulcraAPI.list_files = lambda self, *args, **kwargs: {"folders": ["folder"], "files": [file_info]}
FulcraAPI.resolve_filepath = lambda self, *args, **kwargs: [file_info]
FulcraAPI.upload_file = lambda self, stream, *args: {"file": file_info} if stream.read() else {"file": file_info}
FulcraAPI.download_file = lambda self, *args, **kwargs: io.BytesIO(b"hello\n")
FulcraAPI.delete_file = lambda self, *args: None
FulcraAPI.get_file_by_version = lambda self, *args: file_info
FulcraAPI.restore_file = lambda self, *args: file_info

runner = CliRunner()
operations = []


def boundary(argv, **kwargs):
    result = runner.invoke(cli, argv)
    assert result.exit_code == 0, (argv, result.output, repr(result.exception))
    operations.append(argv[:2])
    return result.stdout


def check(name, args):
    result = getattr(tools, name)(args)
    assert not result.startswith("Error"), (name, result)
    return result


tools._run_cli = boundary
with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in CLI fixture")):
    check("fulcra_data_catalog", {"data_type": DT, "name": "fixture", "base_types_only": True, "recordable_only": True, "queryable_only": True, "category": "base_type", "api_version": "v1alpha1", "user_id": ID})
    check("fulcra_create_data_type", {"base_type": "NumericAnnotation", "name": "Fixture", "description": "test", "tags": ["fixture"], "metric_kind": "discrete", "default_value": "-2.5", "unit": "points"})
    check("fulcra_create_data_type", {"base_type": "ScaleAnnotation", "name": "Scale", "scale_labels": ["1", "2", "3", "4", "5"]})
    check("fulcra_data_type_schema", {"data_type": DT, "api_version": "v1alpha1", "user_id": ID})
    check("fulcra_data_type_lifecycle", {"data_type": DT, "action": "archive"})
    with patch.object(FulcraAPI, "resolve_data_type", side_effect=ValueError("archived fixture")):
        check("fulcra_data_type_lifecycle", {"data_type": DT, "action": "restore"})
    check("fulcra_record", {"data_type": DT, "records": [{"value": -2, "note": "--no-validate"}, {"value": 3}], "tags": ["fixture"], "sources": ["fixture"], "api_version": "v1alpha1"})
    assert calls[-1][2][0]["value"] == -2
    assert calls[-1][2][0]["note"] == "--no-validate"
    check("fulcra_delete_records", {"data_type": DT, "records": [{"record_id": ID}], "api_version": "v1alpha1"})
    assert calls[-1][1] == "DeletedRecord"
    assert calls[-1][2][0]["record_id"] == ID
    check("fulcra_get_records", {"data_type": DT, "time_range": ["latest"], "user_id": ID})
    check("fulcra_get_records", {"data_type": DT, "time_range": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"]})
    check("fulcra_data_updates", {"time_range": ["2 days"], "user_id": ID})
    check("fulcra_create_share", {"name": "Fixture", "data_types": [DT], "files": ["/notes/"], "user_ids": [ID], "group_ids": [ID], "start_time": "2026-01-01T00:00:00Z"})
    check("fulcra_update_share", {"share_id": ID, "set_data_types": [DT], "set_files": ["/notes/"], "set_user_ids": [ID], "no_group_ids": True, "share_all": False, "no_start_time": True, "no_end_time": True})
    assert '"grant_id": "' + ID + '"' in check("fulcra_list_shares", {"direction": "both"})
    check("fulcra_shared_data_types", {"user_id": ID, "time_range": ["1 week"]})
    check("fulcra_delete_share", {"share_id": ID})
    check("fulcra_leave_share", {"grant_id": ID})
    check("fulcra_file_upload", {"path": "/notes/test.txt", "content": "hello\n"})
    assert check("fulcra_file_download", {"path": "/notes/test.txt", "user_id": ID}) == "hello\n"
    check("fulcra_file_list", {"path": "/notes/", "user_id": ID})
    check("fulcra_file_stat", {"path": "/notes/test.txt"})
    check("fulcra_file_delete", {"path": "/notes/test.txt"})
    check("fulcra_file_restore", {"version_id": ID})
    check("fulcra_file_share", {"path": "/notes/", "user_ids": [ID], "name": "Notes"})
print(f"Pinned CLI expansion fixtures: PASS ({len(operations)} command invocations; networking blocked)")
from workspace_cli_fixture import run
run(runner, cli, real_file_methods)

# Mesh also exercises SDK request construction, not just CLI argument parsing.
for name, method in REAL_METHODS.items():
    setattr(FulcraAPI, name, method)
sys.path.insert(0, str(root / "tests"))
from test_mesh import load_plugin, State, OWN, PEER, CHANNEL, SHARE, MID

plugin = load_plugin()
plugin.tools._run_cli = boundary
state = State()
mesh = plugin.mesh.make_handler(state)
shares, sent, reads = [], [], []


def api(self, path, **kwargs):
    if path == "/data/v1/catalog":
        query = kwargs["query"]
        data_type = query.get("data_type", CHANNEL)
        assert data_type in (CHANNEL, "MomentAnnotation"), query
        return json.dumps([mesh_entry(data_type, query.get("fulcra_userid", OWN))])
    if path in ("/data/v1/catalog/" + CHANNEL + "/v1alpha1", "/data/v1/catalog/MomentAnnotation/v1alpha1"):
        return json.dumps(mesh_entry(path.removeprefix("/data/v1/catalog/").removesuffix("/v1alpha1"),
                                     kwargs["query"].get("fulcra_userid", OWN)))
    if path in ("/data/v1/catalog/MomentAnnotation/v1alpha1/schema", "/data/v1/catalog/" + CHANNEL + "/v1alpha1/schema"):
        return json.dumps(mesh_entry("MomentAnnotation")["record_spec"]["schema"])
    if path == "/user/v1alpha1/info":
        return json.dumps({"userid": OWN, "intercom_token": "never-retain"})
    if path == "/user/v1/datashare":
        if kwargs.get("method") == "POST":
            body = kwargs["data"]
            assert body["fulcra_data_types"] == [CHANNEL], body
            assert body["permissions"] == [{"allowed_fulcra_userid": PEER}], body
            assert body["group_permissions"] == [] and body["share_all_data"] is False, body
            assert body["time_start"] is None and body["time_end"] is None, body
            shares.append({"id": SHARE, **body})
            return json.dumps({"datashare": shares[0]})
        return json.dumps(shares)
    if path == "/user/v1/dataset":
        return json.dumps([{"grant_type": "self", "share_all_data": True}, {
            "datashare_id": SHARE, "grant_type": "user", "sharing_fulcra_userid": PEER,
            "fulcra_data_types": [CHANNEL], "share_all_data": False}])
    if path == "/ingest/v1/record/MomentAnnotation":
        assert kwargs["content_type"] == "application/x-jsonl"
        assert "com.fulcradynamics.annotation." + CHANNEL.split('/')[1] in kwargs["data"][0]["sources"]
        sent.extend(kwargs["data"])
        return json.dumps({"upload_id": MID})
    if path == "/data/v1alpha1/event/" + CHANNEL:
        query = kwargs["query"]
        assert set(query) in ({"start_time", "end_time"}, {"start_time", "end_time", "fulcra_userid"}), query
        assert query["start_time"] < query["end_time"]
        reads.append(query)
        if "fulcra_userid" in query:
            assert query["fulcra_userid"] == PEER, query
            rows = [{"note": json.dumps({"v": 1, "mid": MID, "to": "ours", "to_user": OWN,
                     "kind": "response", "pri": "P2", "slug": "thread-ack", "body": "peer 🐈"})}]
        else:
            rows = sent
        return json.dumps(rows).encode()
    raise AssertionError((path, kwargs))


def mesh_entry(data_type=CHANNEL, owner=OWN):
    # Minimal mesh-relevant schema projection, not a fabricated record type.
    # Note is nullable in ordinary annotation records; mesh rejects non-string notes.
    return {**entry(data_type), "fulcra_userid": owner,
            "record_spec": {"type": "event", "schema": {"type": "object", "properties": {"note": {"type": ["string", "null"]}}}}}



FulcraAPI.fulcra_api = api
FulcraAPI.get_fulcra_userid = lambda self: OWN
FulcraAPI.create_annotation = lambda self, **kwargs: {"id": CHANNEL.split('/')[1], **kwargs}

records.get_records = REAL_GET_RECORDS
base = {"local_agent": "ours", "peer_userid": PEER, "peer_agent": "theirs"}
with patch.object(socket.socket, "connect", side_effect=AssertionError("Network forbidden in mesh fixture")):
    handoff = json.loads(mesh({"action": "invite", "local_agent": "ours", "purpose": "coordinate"}))
    assert handoff["status"] == "handoff_only" and not shares and not sent
    assert handoff == json.loads(mesh({"action": "invite", "local_agent": "ours", "purpose": "coordinate"}))
    adopted = json.loads(mesh({"action": "create", "existing_outbox": CHANNEL, **base}))
    assert adopted["outbox"] == CHANNEL and not shares and not sent
    invitation_raw = mesh({"action": "invite", "confirm_share": True, **base})
    assert not invitation_raw.startswith("Error"), invitation_raw
    invitation = json.loads(invitation_raw)
    assert invitation["share_id"] == SHARE, invitation
    body = " café 🐈\n'quote' \"double\" \\ literal\n"
    result = json.loads(mesh({"action": "send", "body": body, "slug": "thread", **base}))
    assert result["status"] == "accepted" and result["readback"] == "ingested", result
    assert json.loads(sent[0]["note"])["body"] == body, sent
    received = json.loads(mesh({"action": "receive", "local_agent": "ours", "incoming_channel": CHANNEL}))
    assert received["messages"][0]["origin_userid"] == PEER, (received, reads)
    assert received["messages"][0]["envelope"]["body"] == "peer 🐈", received
    assert len(reads) == 2 and "fulcra_userid" not in reads[0] and reads[1]["fulcra_userid"] == PEER, reads
    assert "never-retain" not in json.dumps(state.data) + json.dumps(invitation)
print("Pinned CLI mesh fixture: PASS (Click + SDK bodies, JSONL, validation; networking blocked)")
