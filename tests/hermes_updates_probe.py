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
        manifest = yaml.safe_load((Path(__file__).resolve().parents[1] / 'plugin.yaml').read_text())
        assert manifest['config_schema'] == plugin.updates.SETTINGS

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

        def pre(session='same-chat', parent=''):
            agent = SimpleNamespace(session_id=session, model='fixture', platform='cli',
                                    _parent_session_id=parent, _user_id='fixture')
            history = [{'role': 'system', 'content': 'unchanged'}, {'role': 'user', 'content': 'old task'}]
            before = copy.deepcopy(history)
            text = _collect_pre_llm_call_context(agent, effective_task_id='task', turn_id='turn',
                                                original_user_message='current task', messages=history,
                                                conversation_history=history)
            assert history == before
            if text:
                assert compose_user_api_content('current task', '', text) == 'current task\n\n' + text
            return text

        def cli(argv, timeout):
            assert timeout == 30
            home = get_hermes_home()
            allowed, env = plugin.tools._runtime_context()  # Real profile-aware runtime resolution.
            assert allowed and env['HERMES_HOME'] == str(home)
            assert get_secret('FULCRA_PROBE_SECRET') == home.name
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
                    assert not pre()
                    assert not pre('child', 'same-chat')
                    invoke_hook('post_llm_call', session_id='child', platform='cli', conversation_history=[])
                    now[0] += 61
                    invoke_hook('post_llm_call', session_id='same-chat', platform='cli', conversation_history=[])
                finish()  # Parent has left scope: worker must retain the copied context.

            assert seen == ['a', 'b'], seen
            for name in ('a', 'b', 'a'):
                with scope(name):
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
        for manager in managers.values():
            manager.unload()
        print('PASS: real PluginContext/PluginState, config readback, hook dispatch, current-user context, '
              'A→B→A isolation, cross-session single delivery, copied worker/runtime scope, child exclusion, disable; network blocked.')


if __name__ == '__main__':
    main()
