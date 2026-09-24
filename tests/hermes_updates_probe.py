"""Run with Hermes's interpreter and its source directory as argv[1]; no network."""
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


def main():
    sys.path.insert(0, sys.argv[1])
    with tempfile.TemporaryDirectory(prefix='fulcra-hermes-probe-', dir=os.environ['TMPDIR']) as directory:
        root = Path(directory)
        os.environ.update(HOME=str(root), HERMES_HOME=str(root / 'launch'), XDG_CONFIG_HOME=str(root / 'xdg'))
        (root / 'launch').mkdir()
        from hermes_constants import get_hermes_home, set_hermes_home_override, reset_hermes_home_override
        from agent.secret_scope import set_secret_scope, reset_secret_scope, set_multiplex_active, get_secret
        from hermes_cli.plugins import PluginContext, get_plugin_manager
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
        assert manifest['config_schema'] == {**plugin.updates.SETTINGS, **plugin.workspace.SETTINGS}

        @contextmanager
        def scope(name):
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
            entry = next(e for e in registry.get_all_entries() if e.name == 'fulcra_configure_updates')
            result = entry.handler(values)
            assert not result.startswith('Error:'), result
            return json.loads(result)

        def pre(session='same-chat', parent='', platform='cli', first=False):
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
            home = get_hermes_home()
            allowed, env = plugin.tools._runtime_context()  # Real profile-aware runtime resolution.
            assert allowed and env['HERMES_HOME'] == str(home)
            assert get_secret('FULCRA_PROBE_SECRET') == home.name
            if argv[0] == 'file':
                assert 0 < timeout <= 25
                return stores[home.name](argv, timeout)
            assert timeout == 30
            seen.append(home.name)
            return json.dumps(dict(start_time=argv[1], end_time=argv[2],
                                   data_types={home.name + '-type': 1}, file_changes=[]))

        def finish():
            for thread in threading.enumerate():
                if thread.name == 'fulcra-updates':
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
                    assert not pre('child', 'same-chat')
                    assert ctx.get_config('workspace_context_enabled', unset) is unset
                    assert 'ask the user' in pre()
                    saved = yaml.safe_load((home / 'config.yaml').read_text())
                    assert saved['plugins']['entries']['context']['settings']['workspace_context_enabled'] is False
                    assert not stores[name].calls  # Offering never accesses Fulcra files.
                    assert not pre('already-offered', first=True)
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
                        seen.append('delivered-' + name)
                    assert not pre('same-chat')  # No replay in the originating session.
                    assert contexts[name].state.path.is_relative_to(root / name)
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
        for manager in managers.values():
            manager.unload()
        print('PASS: real PluginContext/PluginState, config readback, hook dispatch, current-user context, '
              'A→B→A isolation, cross-session single delivery, copied worker/runtime scope, cron/child exclusion, cron writes remain visible, disable; '
              'workspace one-time opt-in/config readback, single-context current-user injection, private links not loaded, bounded reload and update-hook coexistence, no overwrite or persistent staging; network blocked.')


if __name__ == '__main__':
    main()
