"""Real Hermes registration/state probe; run with Hermes's Python, no network."""
import json
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from hermes_cli.plugins import PluginContext, PluginManager
from hermes_cli.plugins_manifest import PluginManifest
from tools.registry import registry
from test_mesh import load_plugin, OWN, PEER, CHANNEL, SHARE, MID

plugin = load_plugin()
manifest = PluginManifest(name='context', path=str(Path(__file__).resolve().parents[1]), source='project')
account = OWN
calls = []


def cli(argv):
    calls.append(argv)
    if argv == ['user-info']:
        return json.dumps({'userid': account, 'intercom_token': 'must-not-persist'})
    if argv[0] == 'catalog':
        return json.dumps({'id': CHANNEL, 'fulcra_userid': account})
    if argv == ['share', 'list-outgoing']:
        return json.dumps({'id': SHARE, 'fulcra_data_types': [CHANNEL], 'share_all_data': False,
                           'permissions': [{'allowed_fulcra_userid': PEER}], 'group_permissions': []})
    if argv == ['share', 'list-incoming']:
        return json.dumps({'sharing_fulcra_userid': PEER, 'fulcra_data_types': [CHANNEL],
                           'share_all_data': False, 'grant_type': 'group'})
    if argv[0] == 'get-records':
        return json.dumps({'note': json.dumps({'v': 1, 'mid': MID, 'to': 'ours', 'to_user': OWN,
                          'kind': 'response', 'pri': 'P2', 'slug': 'probe-ack', 'body': 'fixture'})})
    raise AssertionError(argv)


with tempfile.TemporaryDirectory(prefix='mesh-hermes-probe-') as root, \
        patch.object(plugin.tools, '_run_cli', side_effect=cli), \
        patch.object(socket.socket, 'connect', side_effect=AssertionError('No networking')):
    homes = [Path(root) / name for name in ('a', 'b')]
    for home in homes:
        home.mkdir()
    prompts = {}
    for iteration, index in enumerate((0, 1, 0)):
        token = set_hermes_home_override(homes[index])
        try:
            manager = PluginManager()
            ctx = PluginContext(manifest, manager)
            plugin.register(ctx)
            entry = registry.get_entry('fulcra_mesh', scope=manager.scope_key)
            assert entry is not None
            handler = entry.handler
            invitation_args = {'action': 'invite', 'local_agent': 'ours', 'purpose': 'private-purpose'}
            before = len(calls)
            invitation = json.loads(handler(invitation_args))
            assert calls[before:] == [['user-info']]
            assert invitation['status'] == 'handoff_only'
            if index in prompts:
                assert invitation['onboarding_prompt'] == prompts[index]
            prompts[index] = invitation['onboarding_prompt']
            assert invitation == json.loads(handler(invitation_args))
            received = json.loads(handler({'action': 'receive', 'local_agent': 'ours'}))
            assert len(received['messages']) == (0 if iteration == 2 else 1)
            assert received['windows'][0]['grant_type'] == 'group'
            if received['messages']:
                assert received['messages'][0]['origin_userid'] == PEER
            result = json.loads(handler({'action': 'invite', 'local_agent': 'ours', 'peer_agent': 'theirs',
                                         'peer_userid': PEER, 'confirm_share': True, 'existing_outbox': CHANNEL}))
            assert result['outbox'] == CHANNEL and result['share_id'] == SHARE
            saved = json.loads(ctx.state.path.read_text())
            for text in ('must-not-persist', 'private-purpose', 'onboarding_prompt'):
                assert text not in json.dumps(saved)
            assert ctx.state.path.stat().st_mode & 0o777 == 0o600
            assert PluginContext(manifest, manager).state.get('mesh.v1') == saved['mesh.v1']
            assert not (homes[index] / 'fulcra-output').exists(), 'Small responses must remain inline'
        finally:
            reset_hermes_home_override(token)
    assert prompts[0] != prompts[1]
    assert not any(c[0] in ('record', 'data-type') or c[:2] == ['share', 'create'] for c in calls)
    assert 'fulcra_api' not in sys.modules
print('Real Hermes PluginContext + ctx.state: PASS (A→B→A stable handoff, explicit adoption, group provenance, dedup, private metadata, inline-only small responses; network blocked)')
