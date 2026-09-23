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
