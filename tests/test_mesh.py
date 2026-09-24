"""Mesh workflows with synthetic accounts; no network or real credentials."""
import copy
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OWN = "11111111-1111-4111-8111-111111111111"
PEER = "22222222-2222-4222-8222-222222222222"
CHANNEL = "MomentAnnotation/33333333-3333-4333-8333-333333333333"
SHARE = "44444444-4444-4444-8444-444444444444"
MID = "55555555-5555-4555-8555-555555555555"


def load_plugin():
    spec = importlib.util.spec_from_file_location("mesh_fixture_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class State:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return copy.deepcopy(self.data.get(key, default))

    def set(self, key, value):
        self.data[key] = copy.deepcopy(value)


class MeshTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()
        self.mesh = self.plugin.mesh
        self.state = State()
        self.handler = self.mesh.make_handler(self.state)
        self.own = OWN
        self.outgoing = []
        self.incoming = []
        self.records = []
        self.uploads = []
        self.calls = []
        self.fail_share = False
        self.fail_record = False
        self.partial = False
        self.broaden_created_share = False
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        constants = types.ModuleType("hermes_constants")
        constants.get_hermes_home = lambda: Path(temp.name)
        stub = patch.dict(sys.modules, {"hermes_constants": constants})
        stub.start()
        self.addCleanup(stub.stop)
        boundary = patch.object(self.plugin.tools, "_run_cli", side_effect=self.cli)
        boundary.start()
        self.addCleanup(boundary.stop)

    def cli(self, argv):
        self.calls.append(argv)
        if argv == ["user-info"]:
            return json.dumps({"userid": self.own, "intercom_token": "never-retain"})
        if argv[:2] == ["data-type", "create"]:
            return json.dumps({"id": CHANNEL.split('/')[1]})
        if argv[0] == "catalog":
            return json.dumps({"id": CHANNEL, "fulcra_userid": self.own})
        if argv == ["share", "list-outgoing"]:
            return '\n'.join(map(json.dumps, self.outgoing))
        if argv[:2] == ["share", "create"]:
            if self.fail_share:
                raise subprocess.TimeoutExpired("fixture", 1)
            self.outgoing = [{"id": SHARE, "fulcra_data_types": [CHANNEL], "share_all_data": False,
                              "permissions": [{"allowed_fulcra_userid": PEER}], "group_permissions": []}]
            receipt = json.dumps({"datashare": self.outgoing[0]})
            if self.broaden_created_share:
                self.outgoing[0]["share_all_data"] = True
            return receipt
        if argv[0] == "record":
            self.uploads.extend(json.loads(line) for line in Path(argv[-1]).read_text().splitlines())
            self.assertNotIn("--no-validate", argv)
            self.assertEqual(Path(argv[-1]).stat().st_mode & 0o777, 0o600)
            if self.fail_record:
                raise subprocess.TimeoutExpired("fixture", 1)
            return "Recorded 1 record\nUpload ID: " + MID
        if argv == ["share", "list-incoming"]:
            return '\n'.join(map(json.dumps, self.incoming))
        if argv[0] == "get-records":
            raw = '\n'.join(map(json.dumps, self.records))
            return raw + ('\n{"partial":' if self.partial else '')
        raise AssertionError(argv)

    def call(self, action, **kwargs):
        args = {"action": action, "local_agent": "ours"}
        if action != "receive":
            args.update(peer_userid=PEER, peer_agent="theirs")
        return self.handler({**args, **kwargs})

    def invite(self):
        result = json.loads(self.call("invite", confirm_share=True))
        self.assertEqual(result["status"], "awaiting_reply")
        return result

    def inbox(self, body="hello"):
        self.incoming = [{"datashare_id": SHARE, "sharing_fulcra_userid": PEER,
                          "fulcra_data_types": [CHANNEL], "share_all_data": False, "grant_type": "user"}]
        envelope = {"v": 1, "mid": MID, "to": "ours", "to_user": OWN, "kind": "directive",
                    "pri": "P1", "slug": "thread", "body": body}
        self.records = [{"note": json.dumps(envelope)}]
        return envelope

    def test_consent_create_reuse_and_invite_are_not_sends(self):
        self.assertIn("confirm_share", self.call("invite"))
        self.assertEqual(self.calls, [])
        handoff_args = {"action": "invite", "local_agent": "ours", "purpose": "dinner", "peer_agent": "friend"}
        handoff = json.loads(self.handler(handoff_args))
        self.assertEqual(handoff, json.loads(self.handler(handoff_args)))
        self.assertEqual(self.calls, [["user-info"], ["user-info"]])
        self.assertEqual(handoff["status"], "handoff_only")
        for value in (OWN, "ours", "friend", "dinner", "mesh-handshake:", self.mesh.SKILL_URL):
            self.assertIn(value, handoff["onboarding_prompt"])
        self.assertNotIn("onboarding_prompt", json.dumps(self.state.data))
        other = json.loads(self.handler({**handoff_args, "purpose": "work"}))
        self.assertNotEqual(handoff["onboarding_prompt"], other["onboarding_prompt"])
        created = json.loads(self.call("create"))
        self.assertIn("different", self.call("create", existing_outbox="MomentAnnotation/" + MID))
        self.assertEqual(json.loads(self.call("create", existing_outbox=CHANNEL))["outbox"], CHANNEL)
        self.assertIn("another", self.call("create", peer_agent="other", existing_outbox=CHANNEL))
        self.assertEqual(created["outbox"], CHANNEL)
        result = self.invite()
        self.invite()
        self.assertEqual(sum(c[:2] == ["data-type", "create"] for c in self.calls), 1)
        self.assertEqual(sum(c[:2] == ["share", "create"] for c in self.calls), 1)
        self.assertEqual(self.uploads, [])
        prompt = result["onboarding_prompt"]
        for value in (OWN, CHANNEL, '"theirs"', "case-sensitive", "mesh-handshake:", self.mesh.SKILL_URL, "share"):
            self.assertIn(value, prompt)
        self.assertNotIn("never-retain", json.dumps(self.state.data) + json.dumps(result))
        self.outgoing[0]["fulcra_data_types"].append("HeartRate")
        self.assertIn("scope", self.call("send", body="private", slug="thread"))
        self.assertEqual(self.uploads, [])

    def test_partial_share_retains_outbox_and_reconciles_without_retry(self):
        self.fail_share = True
        result = self.call("invite", confirm_share=True)
        self.assertIn(CHANNEL, result)
        self.fail_share = False
        self.assertIn("reconcile", self.call("invite", confirm_share=True).lower())
        self.assertEqual(sum(c[:2] == ["data-type", "create"] for c in self.calls), 1)
        self.assertEqual(sum(c[:2] == ["share", "create"] for c in self.calls), 1)
        self.outgoing = [{"id": SHARE, "fulcra_data_types": [CHANNEL], "share_all_data": False,
                          "permissions": [{"allowed_fulcra_userid": PEER}], "group_permissions": []}]
        self.invite()
        self.state = State()
        self.handler = self.mesh.make_handler(self.state)
        original = self.cli
        def uncertain_create(argv):
            if argv[:2] == ["data-type", "create"]:
                raise subprocess.TimeoutExpired("fixture", 1)
            return original(argv)
        with patch.object(self.plugin.tools, "_run_cli", side_effect=uncertain_create) as run:
            self.assertIn("creation uncertain", self.call("create"))
            self.assertIn("No automatic recreate", self.call("create"))
            self.assertEqual(sum(c.args[0][:2] == ["data-type", "create"] for c in run.call_args_list), 1)
            self.assertEqual(json.loads(self.call("create", existing_outbox=CHANNEL))["outbox"], CHANNEL)
        self.state = State()
        self.handler = self.mesh.make_handler(self.state)
        self.assertIn("MomentAnnotation", self.call("create", existing_outbox="MomentAnnotation/not-uuid"))
        self.assertIn("owned", self.call("create", existing_outbox="MomentAnnotation/" + MID))
        self.assertEqual(self.state.data, {})
        original = self.cli
        def foreign_catalog(argv):
            if argv[0] == "catalog":
                return json.dumps({"id": CHANNEL, "fulcra_userid": PEER})
            return original(argv)
        with patch.object(self.plugin.tools, "_run_cli", side_effect=foreign_catalog):
            self.assertIn("owned", self.call("create", existing_outbox=CHANNEL))
        self.assertEqual(self.state.data, {})
        self.outgoing[0]["permissions"] = [{"allowed_fulcra_userid": OWN}]
        self.assertIn("scope", self.call("create", existing_outbox=CHANNEL))
        self.assertEqual(self.state.data, {})
        self.outgoing[0]["permissions"] = [{"allowed_fulcra_userid": PEER}]
        before = len(self.calls)
        self.assertEqual(json.loads(self.call("invite", confirm_share=True, existing_outbox=CHANNEL))["share_id"], SHARE)
        self.assertFalse(any(c[:2] in (["data-type", "create"], ["share", "create"]) for c in self.calls[before:]))

    def test_send_note_roundtrip_acceptance_readback_and_uncertain_mid(self):
        self.invite()
        body = "  café 🐈\n'quote' \"double\" \\ path\n"
        result = json.loads(self.call("send", body=body, slug=" exact -ack "))
        envelope = json.loads(self.uploads[-1]["note"])
        self.assertEqual(envelope, {"v": 1, "mid": result["mid"], "to": "theirs", "to_user": PEER,
                                   "kind": "directive", "pri": "P2", "slug": " exact -ack ", "body": body})
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["readback"], "not_observed")
        self.assertFalse(result["peer_acknowledged"])
        self.fail_record = True
        uncertain = json.loads(self.call("send", body=body, slug="thread"))
        self.assertEqual(uncertain["status"], "uncertain")
        self.assertEqual(uncertain["mid"], json.loads(self.uploads[-1]["note"])["mid"])
        self.assertNotEqual(result["mid"], uncertain["mid"])
        self.assertEqual(len(self.uploads), 2)

    def test_receive_filters_proven_origin_and_durable_dedup(self):
        env = self.inbox()
        self.incoming[0]["grant_type"] = "group"
        self.records += [{"note": "bad"}, {"note": json.dumps({**env, "to_user": PEER})},
                         {"note": json.dumps({**env, "to": "other"})}, {"note": json.dumps({**env, "v": True})}]
        self.incoming += [{**self.incoming[0], "share_all_data": True},
                          {**self.incoming[0], "fulcra_data_types": [CHANNEL, "HeartRate"]}]
        result = json.loads(self.call("receive"))
        self.assertEqual(result["messages"][0]["origin_userid"], PEER)
        self.assertEqual(result["messages"][0]["grant_type"], "group")
        self.assertEqual(result["windows"][0]["grant_type"], "group")
        self.assertEqual(result["messages"][0]["envelope"], env)
        self.assertTrue(result["untrusted_peer_content"])
        self.assertEqual(result["ignored_notes"], 4)
        self.assertEqual(result["ignored_shares"], 2)
        self.handler = self.mesh.make_handler(self.state)
        self.assertEqual(json.loads(self.call("receive"))["messages"], [])
        read = [c for c in self.calls if c[0] == "get-records"][-1]
        self.assertEqual(read[-2:], ["--user-id", PEER])
        self.assertEqual(datetime.fromisoformat(read[2]),
                         datetime.fromisoformat(result["windows"][0]["until"]) - self.mesh.OVERLAP)
        before_queries = len([c for c in self.calls if c[0] == "get-records"])
        self.call("receive", incoming_channel="MomentAnnotation/" + MID)
        self.assertEqual(len([c for c in self.calls if c[0] == "get-records"]), before_queries)
        bulk = [{"note": json.dumps({**env, "mid": str(self.mesh.uuid4())})}
                for _ in range(self.mesh.DEDUP_LIMIT + 2)]
        self.records = bulk
        output = self.call("receive", since="2026-01-01T00:00:00Z")
        path = Path(output.split("Complete UTF-8 text: ", 1)[1].splitlines()[0])
        self.assertEqual(len(json.loads(path.read_text())["messages"]), len(bulk))
        cursor = next(iter(self.state.data[self.mesh.STATE_KEY]["receives"].values()))
        self.assertEqual(len(cursor["mids"]), self.mesh.DEDUP_LIMIT)

    def test_failed_parse_and_artifact_failure_do_not_consume_messages(self):
        self.inbox("é" * 20000)
        before = copy.deepcopy(self.state.data)
        self.partial = True
        self.assertIn("Error", self.call("receive"))
        self.assertEqual(self.state.data, before)
        self.partial = False
        original = self.cli
        def failed_read(argv):
            if argv[0] == "get-records":
                raise RuntimeError("fixture read failed")
            return original(argv)
        with patch.object(self.plugin.tools, "_run_cli", side_effect=failed_read):
            self.assertIn("Error", self.call("receive"))
        self.assertEqual(self.state.data, before)
        with patch.object(self.plugin.tools, "_save_output", side_effect=OSError("fixture full")):
            self.assertIn("Error", self.call("receive"))
        self.assertEqual(self.state.data, before)
        output = self.call("receive")
        path = Path(output.split("Complete UTF-8 text: ", 1)[1].splitlines()[0])
        self.assertEqual(json.loads(path.read_text())["messages"][0]["envelope"]["body"], "é" * 20000)
        self.assertEqual(json.loads(self.call("receive"))["messages"], [])

    def test_account_and_local_agent_separation_and_share_readback(self):
        self.invite()
        self.inbox()
        self.call("receive")
        self.own = PEER
        self.assertIn("create", self.call("send", body="no", slug="thread"))
        self.assertEqual(json.loads(self.call("receive"))["messages"], [])
        self.own = OWN
        self.assertEqual(json.loads(self.call("receive"))["messages"], [])
        self.assertIn("create", self.call("send", local_agent="other", body="no", slug="thread"))
        self.outgoing[0]["permissions"] = [{"allowed_fulcra_userid": OWN}]
        self.assertIn("scope", self.call("invite", confirm_share=True))
        self.assertEqual(self.uploads, [])
        self.state = State()
        self.handler = self.mesh.make_handler(self.state)
        self.outgoing = []
        self.broaden_created_share = True
        self.assertIn("scope", self.call("invite", confirm_share=True))
        self.assertIn(CHANNEL, json.dumps(self.state.data))
        self.assertEqual(self.uploads, [])
