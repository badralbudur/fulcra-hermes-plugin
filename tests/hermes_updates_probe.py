"""Run with Hermes's interpreter and its source directory as argv[1]; no network."""
import argparse
import copy
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

from test_updates import load_plugin
from test_workspace import FileStore
from test_setup_mesh import OWN, PEER, CHANNEL, GRANT, MID


def main():
    """Exercise real Hermes hooks and settings in disposable profile homes."""
    sys.path.insert(0, sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='fulcra-hermes-probe-', dir=os.environ['TMPDIR']) as directory:
        root = Path(directory)
        os.environ.update(HOME=str(root), HERMES_HOME=str(root / 'launch'), XDG_CONFIG_HOME=str(root / 'xdg'))
        (root / 'launch').mkdir()
        from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
        from agent.secret_scope import set_secret_scope, reset_secret_scope, set_multiplex_active, get_secret
        from hermes_cli.plugins import PluginContext, get_plugin_manager, get_plugin_command_handler
        from hermes_cli.plugins_settings import plugin_settings_fields, save_plugin_settings
        from hermes_cli.plugins_manifest import PluginManifest
        from hermes_cli.lifecycle import invoke_hook
        from agent.turn_context import _collect_pre_llm_call_context, compose_user_api_content
        from tools.registry import registry
        import yaml

        set_multiplex_active(True)
        plugin = load_plugin()
        now = [1800000000.0]
        seen = []
        contexts = {}
        managers = {}
        stores = {'a': FileStore(), 'b': FileStore()}
        manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / 'plugin.yaml').read_text())
        assert {k: {f: v for f, v in spec.items() if f != 'label'}
                for k, spec in manifest['config_schema'].items()} == plugin.plugin_setup.SETTINGS
        mesh_seen = []
        mesh_mid = [MID]

        @contextmanager
        def scope(name):
            """Activate a disposable profile and its isolated secret scope."""
            home = root / name
            home.mkdir(exist_ok=True)
            token = set_hermes_home_override(home)
            secret = set_secret_scope({'FULCRA_PROBE_SECRET': name})
            try:
                yield home
            finally:
                reset_secret_scope(secret)
                reset_hermes_home_override(token)

        def configure(values):
            """Invoke the registered update configuration tool and check success."""
            entry = next(e for e in registry.get_all_entries() if e.name == 'fulcra_configure_updates')
            result = entry.handler(values)
            assert not result.startswith('Error:'), result
            return json.loads(result)

        def pre(session='same-chat', parent='', platform='cli', first=False):
            """Compose hook context through Hermes without mutating history."""
            agent = SimpleNamespace(session_id=session, model='fixture', platform=platform,
                                    _parent_session_id=parent, _user_id='fixture')
            history = [{'role': 'system', 'content': 'unchanged'}, {'role': 'user', 'content': 'old task'}]
            before = copy.deepcopy(history)
            text = _collect_pre_llm_call_context(agent, effective_task_id='task', turn_id='turn',
                                                original_user_message='current task', messages=history,
                                                conversation_history=[] if first else history)
            assert history == before
            if text:
                assert compose_user_api_content('current task', '', text) == 'current task\n\n' + text
            return text

        def cli(argv, timeout):
            """Serve fixtures while verifying copied profile and secret context."""
            home = get_hermes_home()
            allowed, env = plugin.tools._runtime_context()  # Real profile-aware runtime resolution.
            assert allowed and env['HERMES_HOME'] == str(home)
            assert get_secret('FULCRA_PROBE_SECRET') == home.name
            if argv[0] == 'file':
                assert 0 < timeout <= 25
                return stores[home.name](argv, timeout)
            if argv[0] != 'data-updates':
                assert 0 < timeout <= 30
                mesh_seen.append(home.name)
                if argv == ['user-info']:
                    return json.dumps({'userid': OWN})
                if argv == ['share', 'list-incoming']:
                    return json.dumps(dict(sharing_fulcra_userid=PEER, datashare_id=GRANT,
                                           grant_type='user', share_all_data=False, fulcra_data_types=[CHANNEL]))
                assert argv[0] == 'get-records' and argv[-2:] == ['--user-id', PEER]
                return json.dumps({'note': json.dumps(dict(v=1, mid=mesh_mid[0], to='helper', to_user=OWN,
                    kind='response', pri='P2', slug='probe', body=home.name + '-mesh'))})
            assert timeout == 30
            seen.append(home.name)
            return json.dumps(dict(start_time=argv[1], end_time=argv[2],
                                   data_types={home.name + '-type': 1}, file_changes=[]))

        def finish():
            """Wait for bounded fixture workers outside the active profile scope."""
            for thread in threading.enumerate():
                if thread.name in ('fulcra-updates', 'fulcra-mesh-updates'):
                    thread.join(5)
                    assert not thread.is_alive()

        with patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')), \
             patch.object(plugin.tools, '_run_cli', side_effect=cli), \
             patch.object(plugin.updates.time, 'time', side_effect=lambda: now[0]):
            for name in ('a', 'b'):
                with scope(name) as home:
                    manager = get_plugin_manager()
                    manager._discovered = True  # Only this plugin, never installed user plugins.
                    managers[name] = manager
                    ctx = PluginContext(PluginManifest(name='context', path=str(Path(__file__).resolve().parents[1])), manager)
                    contexts[name] = ctx
                    before = sorted(home.rglob('*'))
                    plugin.register(ctx)
                    assert sorted(home.rglob('*')) == before, 'register wrote persistent data'
                    assert configure({})['updates_enabled'] is False
                    configure({'updates_enabled': True, 'update_interval': 60})
                    assert ctx.get_config('updates_enabled') is True
                    assert ctx.get_config('update_interval') == 60
                    assert yaml.safe_load((home / 'config.yaml').read_text())['plugins']['entries']['context']['settings']['updates_enabled'] is True
                    unset = object()
                    assert ctx.get_config('workspace_context_enabled', unset) is unset
                    assert not pre('offer-cron', platform='cron', first=True)
                    assert not pre('child', 'same-chat', first=True)
                    assert ctx.get_config('workspace_context_enabled', unset) is unset
                    assert not pre()  # Ordinary turns must leave discovery available.
                    assert ctx.state.get(plugin.plugin_setup.HINT_KEY) is None
                    text = pre('new-session', first=True)
                    assert all(option in text for option in ('options', 'workspace context.md loading',
                        "what's-new notices", 'configurable shared check interval',
                        'automatic mesh message checks', 'automatic mesh invitation checks',
                        'independent', '/fulcra setup', 'hermes fulcra setup', 'Desktop Capabilities'))
                    assert PluginContext(ctx.manifest, manager).state.get(plugin.plugin_setup.HINT_KEY) is True
                    saved = yaml.safe_load((home / 'config.yaml').read_text())
                    assert 'workspace_context_enabled' not in saved['plugins']['entries']['context']['settings']
                    assert not stores[name].calls  # Offering never accesses Fulcra files.
                    assert not pre('already-offered', first=True)
                    slash = get_plugin_command_handler('fulcra')
                    assert slash is not None
                    assert 'Mesh' in slash('setup')
                    assert '--mesh-messages' in slash('setup --help')
                    assert slash('setup --updates off --interval 1').startswith('Error:')
                    assert ctx.get_config('updates_enabled') is True
                    assert slash('setup --mesh-messages on').startswith('Error:')
                    assert 'helper' in slash('setup --mesh-agent helper --mesh-messages on')
                    command = manager._cli_commands['fulcra']
                    parser = argparse.ArgumentParser()
                    command['setup_fn'](parser)
                    command['handler_fn'](parser.parse_args(['setup', '--mesh-invites', 'on']))
                    assert ctx.get_config('mesh_invites_enabled') is True
                    fields = {f['key']: f for f in plugin_settings_fields('context', Path(ctx.manifest.path))}
                    assert fields.keys() == plugin.plugin_setup.SETTINGS.keys()
                    assert fields['mesh_messages_enabled']['value'] is True
                    assert fields['mesh_agent']['type'] == 'string'
                    assert fields['update_interval']['type'] == 'number'
                    assert all(f['label'] != k and f['description'] for k, f in fields.items())
                    save_plugin_settings('context', Path(ctx.manifest.path), {'workspace_context_enabled': False})
                    assert ctx.get_config('workspace_context_enabled') is False
                    assert 'false' in slash('status')
                    assert not pre('setup-handled', first=True)
                    invoke_hook('post_llm_call', session_id='child', platform='cli', conversation_history=[])
                    now[0] += 61
                    invoke_hook('post_llm_call', session_id='same-chat', platform='cli', conversation_history=[])
                finish()  # Parent has left scope: worker must retain the copied context.

            assert seen == ['a', 'b'], seen
            for name in ('a', 'b', 'a'):
                with scope(name):
                    assert not pre('scheduled', platform='cron')
                    invoke_hook('post_tool_call', session_id='scheduled', tool_name='fulcra_record',
                                args={'data_type': name + '-type'}, result='Submitted', status='ok')
                    invoke_hook('post_llm_call', session_id='scheduled', platform='cron')
                    finish()
                    text = pre('new-chat')  # New sessions inherit the profile feed.
                    if name == 'a' and seen.count('delivered-a'):
                        assert not text
                    else:
                        assert name + '-type' in text and ('b' if name == 'a' else 'a') + '-type' not in text
                        assert name + '-mesh' in text and ('b' if name == 'a' else 'a') + '-mesh' not in text
                        assert '"kind": "invitation_candidate"' in text
                        seen.append('delivered-' + name)
                    assert not pre('same-chat')  # No replay in the originating session.
                    assert contexts[name].state.path.is_relative_to(root / name)
                    assert contexts[name].state.get(plugin.mesh.STATE_KEY) is None
            assert set(mesh_seen) == {'a', 'b'}
            with scope('a'):
                configure({'updates_enabled': False})
                assert not pre()
                now[0] += 61
                invoke_hook('post_llm_call', session_id='same-chat', platform='cli', conversation_history=[])
                finish()
                assert len(seen) == 4
            for name in ('a', 'b', 'a'):
                with scope(name) as home:
                    ctx = contexts[name]
                    # Intentional standard config writes, isolated to disposable homes.
                    ctx.set_config('workspace_name', 'work-' + name)
                    ctx.set_config('workspace_role', 'researcher')
                    ctx.set_config('workspace_context_enabled', True)
                    saved = yaml.safe_load((home / 'config.yaml').read_text())
                    assert saved['plugins']['entries']['context']['settings']['workspace_name'] == 'work-' + name
                    count = len(stores[name].calls)
                    assert not pre('workspace-cron', platform='cron', first=True)
                    assert not pre('workspace-child', parent='parent', first=True)
                    assert not pre('workspace-ordinary')
                    text = pre('workspace-chat', first=True)
                    if count:
                        assert not text and len(stores[name].calls) == count
                    else:
                        assert 'user-owned reference' in text and 'researcher' in text
                        assert 'missing seeds verified' in text
                        assert all(path.startswith('/workspace/work-' + name + '/') for path in stores[name].files)
                        base = '/workspace/work-' + name + '/'
                        path = base + 'context.md'
                        stores[name].files[base + 'knowledge/user-preferences.md'] = 'LINKED PRIVATE SENTINEL'
                        stores[name].files[path] = '---\ntype: Reference\n---\nPrivate preference ' + name + '\n[Details](knowledge/user-preferences.md)'
                        before = stores[name].files.copy()
                        count = len(stores[name].calls)
                        text = pre('workspace-new', first=True)
                        assert len(stores[name].calls) == count + 1
                        assert stores[name].calls[-1][0][1:3] == ['download', path]
                        assert stores[name].files == before
                        assert 'LINKED PRIVATE SENTINEL' not in text
                        assert 'Private preference ' + name in text
                        assert 'Private preference ' + ('b' if name == 'a' else 'a') not in text
                        stores[name].files[path] = '\x01' * 9000
                        text = pre('workspace-bounded', first=True)
                        assert len(text) < 10000 and '"truncated": true' in text
                        assert path in text and 'UNTRUSTED DATA' in text
                        assert len(stores[name].calls) == count + 2
                    assert not any(path.exists() for path in stores[name].locals)
                    ctx.set_config('workspace_context_enabled', False)
                    assert not pre('workspace-disabled', first=True)
            with scope('a'):
                ctx = contexts['a']
                assert not get_plugin_command_handler('fulcra')(
                    'setup --workspace on --updates on').startswith('Error:')
                stores['a'].files['/workspace/work-a/context.md'] = 'Combined workspace context'
                mesh_mid[0] = '99999999-9999-4999-8999-999999999999'
                assert not pre('combined-baseline')
                now[0] += 61
                invoke_hook('post_llm_call', session_id='combined-baseline', platform='cli')
                finish()
                # New PluginContext reads the same durable automatic state, not a session cache.
                assert PluginContext(ctx.manifest, managers['a']).state.get(
                    plugin.mesh_updates.STATE_KEY) == ctx.state.get(plugin.mesh_updates.STATE_KEY)
                text = pre('combined-first-turn', first=True)
                assert all(part in text for part in ('Combined workspace context', 'a-type', 'a-mesh', mesh_mid[0]))
                assert not pre('combined-later')
        for manager in managers.values():
            manager.unload()
        print('PASS: real PluginContext/PluginState, config readback, hook dispatch, current-user context, '
              'A→B→A isolation, cross-session single delivery, copied worker/runtime scope, cron/child exclusion, cron writes remain visible, disable; '
              'first-session options with ordinary-turn marker preservation, no config writes, registered slash/CLI setup, native settings recognition/readback, '
              'automatic mesh message/invite notices and separate manual state, workspace single-context injection, '
              'private links not loaded, bounded reload and hook coexistence, no overwrite or persistent staging; network blocked.')


if __name__ == '__main__':
    main()
