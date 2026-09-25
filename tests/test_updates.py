"""Focused hook workflows, with no Fulcra account access."""
import contextvars
import copy
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    spec = importlib.util.spec_from_file_location('updates_fixture_plugin', ROOT / '__init__.py',
                                                 submodule_search_locations=[str(ROOT)])
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class State:
    def __init__(self):
        self.profile = contextvars.ContextVar('profile', default='a')
        self.values = {}

    @property
    def path(self):
        return Path('/fixture') / self.profile.get() / 'state.json'

    def get(self, key, default=None):
        return copy.deepcopy(self.values.get((str(self.path), key), default))

    def set(self, key, value):
        self.values[str(self.path), key] = copy.deepcopy(value)


class Context:
    def __init__(self):
        self.state = State()
        self.config = {}
        self.hooks = {}
        self.tools = {}

    def get_config(self, key, default=None):
        return self.config.get((str(self.state.path), key), default)

    def set_config(self, key, value):
        self.config[str(self.state.path), key] = value

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_tool(self, name, handler, **kwargs):
        self.tools[name] = handler

    def register_skill(self, *args):
        pass

    def register_command(self, *args, **kwargs):
        """Accept slash registration without installing a real command."""
        pass

    def register_cli_command(self, **kwargs):
        """Accept native CLI registration without modifying the host."""
        pass


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.plugin = load_plugin()
        self.ctx = Context()
        self.now = 1800000000.0
        self.clock = patch.object(self.plugin.updates.time, 'time', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.plugin.register(self.ctx)
        self.calls = []
        self.types = {'Steps': 3}
        self.files = []
        self.cli = patch.object(self.plugin.tools, '_run_cli', side_effect=self.response)
        self.cli.start()
        self.addCleanup(self.cli.stop)

    def response(self, argv, timeout):
        self.calls.append((argv, timeout, self.ctx.state.profile.get()))
        return json.dumps(dict(start_time=argv[1], end_time=argv[2],
                               data_types=self.types, file_changes=self.files))

    def pre(self, session='chat', **kwargs):
        return self.ctx.hooks['pre_llm_call'](session_id=session, **kwargs)

    def post(self, session='chat'):
        self.ctx.hooks['post_llm_call'](session_id=session)

    def configure(self, **kwargs):
        result = self.ctx.tools['fulcra_configure_updates'](kwargs)
        self.assertNotIn('Error:', result)

    def finish(self):
        # Tests may join; production turn hooks must never do so.
        for thread in threading.enumerate():
            if thread.name == 'fulcra-updates':
                thread.join(2)
                self.assertFalse(thread.is_alive())

    def poll(self):
        self.now += 61
        self.post()
        self.finish()

    def enable(self):
        self.configure(updates_enabled=True, update_interval=60)
        self.pre()

    def file(self, name, ident=None):
        return dict(id=ident or name, full_name='/notes/' + name, state='uploaded',
                    uploaded_at=self.plugin.updates._iso(self.now), archived_at=None,
                    deleted_at=None, scan_state='complete', last_scanned=None, size=10)

    def test_consent_baseline_restart_and_single_delivery(self):
        self.assertEqual(self.ctx.state.values, {})
        for args in ({'update_interval': True}, {'update_interval': 0},
                     {'updates_data_types': 'Steps'}, {'unexpected': True}):
            self.assertTrue(self.ctx.tools['fulcra_configure_updates'](args).startswith('Error:'))
        self.assertEqual(self.ctx.config, {})
        self.pre(); self.post()
        self.assertEqual(self.calls, [])
        self.enable()
        self.poll()
        self.assertEqual(self.calls[0][1], 30)
        self.plugin.register(self.ctx)  # Restart hook owner; durable state survives.
        result = self.pre()
        self.assertIn('Steps', result['context'])
        self.assertLessEqual(len(result['context']), 3000)
        self.assertIsNone(self.pre())
        self.poll()
        self.assertEqual(self.calls[0][0][2], self.calls[1][0][1])

    def test_failure_retries_identical_window_after_cooldown(self):
        self.enable()
        with patch.object(self.plugin.tools, '_run_cli', return_value='{"data_types": {}}') as failed:
            self.poll()
            argv = failed.call_args.args[0]
            self.post(); self.finish()
            self.assertEqual(failed.call_count, 1)
        self.plugin.register(self.ctx)
        self.assertIsNone(self.pre())
        self.poll()
        self.assertEqual(self.calls[0][0], argv)
        self.assertIn('Steps', self.pre()['context'])

    def test_filters_reapplied_coalescing_and_file_version_dedup(self):
        self.enable()
        self.files = [self.file('visible'), self.file('ignored')]
        self.poll(); self.poll()
        self.configure(updates_data_types=['Other'], updates_file_prefixes=['/notes/'],
                       updates_ignore_prefixes=['/notes/ignored'])
        text = self.pre()['context']
        self.assertNotIn('Steps', text)
        self.assertNotIn('ignored', text)
        self.assertEqual(text.count('/notes/visible'), 1)
        self.poll()
        self.assertIsNone(self.pre())
        self.files[0]['archived_at'] = self.plugin.updates._iso(self.now)
        self.poll()
        self.assertIn('visible', self.pre()['context'])
        self.configure(updates_include_files=False, updates_data_types=[])
        self.files.append(self.file('hidden'))
        self.poll()
        text = self.pre()['context']
        self.assertIn('Steps', text)
        self.assertNotIn('/notes/', text)
        self.configure(updates_include_files=True)
        self.types = {}
        self.poll()
        self.assertIsNone(self.pre())  # Expansion does not replay filtered files.

    def test_known_mutations_before_and_after_poll_and_failed_writes(self):
        self.enable()
        self.files = [self.file('report'), self.file('failed'), self.file('other'), self.file('restored', 'version')]
        self.poll()
        hook = self.ctx.hooks['post_tool_call']
        for name, args, result in [
            ('fulcra_file_upload', {'path': '/notes/./report'}, 'Uploaded'),
            ('fulcra_file_delete', {'path': 'notes/./deleted'}, 'Deleted'),
            ('fulcra_file_delete', {'path': '/notes/failed'}, 'Error: CLI failure'),
            ('fulcra_file_restore', {'version_id': 'old-version'},
             'fulcra:/notes/restored  old-version (2027-01-15) ➡️ version (2027-01-16)'),
            ('fulcra_record', {'data_type': 'Steps'}, 'Submitted'),
        ]:
            hook(session_id='chat', tool_name=name, args=args, result=result, status='ok')
        hook(session_id='chat', tool_name='fulcra_file_delete', args={'path': '/notes/other'},
             result='cancelled', status='error')
        text = self.pre()['context']
        self.assertNotIn('/notes/report', text)
        self.assertNotIn('Steps', text)
        self.assertNotIn('restored', text)
        self.assertIn('/notes/failed', text)
        self.assertIn('/notes/other', text)
        self.files[0]['uploaded_at'] = self.plugin.updates._iso(self.now)
        self.poll()
        self.assertIsNone(self.pre())  # Delayed ingestion of our path is suppressed.
        self.configure(update_interval=7200)
        hook(session_id='chat', tool_name='fulcra_file_upload', args={'path': '/notes/./report'},
             result='Uploaded', status='ok')
        written = self.now
        self.files = [self.file('report', 'long-interval'), self.file('deleted')]
        self.files[0]['uploaded_at'] = self.plugin.updates._iso(written + 4000)
        self.files[1]['deleted_at'] = self.plugin.updates._iso(written)
        later = self.file('report', 'after-horizon')
        later.update(state='archived', archived_at=self.plugin.updates._iso(written + 8000))
        self.files.append(later)
        self.now += 86400  # No checks while idle; markers must survive returning to chat.
        self.assertIsNone(self.pre())
        self.post(); self.finish()
        text = self.pre()['context']
        self.assertEqual(text.count('/notes/report'), 1)
        self.assertIn('archived', text)  # Same path, but beyond the marker horizon.
        self.assertNotIn('/notes/deleted', text)
        self.assertNotIn('Steps', text)
        state = self.ctx.state.get(self.plugin.updates.FEED_KEY)
        assert state is not None
        self.assertEqual(state['known'], {})  # Cursor has now passed the horizons.
        self.types = {}
        self.files = [self.file('report', 'external-later')]
        self.now += 7201
        self.post(); self.finish()
        self.assertIn('/notes/report', self.pre()['context'])

    def test_nonblocking_disable_and_no_lost_concurrent_write(self):
        self.enable()
        started, release = threading.Event(), threading.Event()
        def blocked(argv, timeout):
            started.set()
            release.wait(2)
            return self.response(argv, timeout)
        self.files = [self.file('own')]
        self.types = {}
        with patch.object(self.plugin.tools, '_run_cli', side_effect=blocked) as run:
            self.now += 61
            self.post()
            self.assertTrue(started.wait(1))
            self.pre('other'); self.post('other')
            self.assertIsNone(self.pre())
            self.assertEqual(run.call_count, 1)
            self.ctx.hooks['post_tool_call'](session_id='other', tool_name='fulcra_file_upload',
                                           args={'path': '/notes/own'}, result='Uploaded', status='ok')
            release.set(); self.finish()
        self.assertIsNone(self.pre())
        started.clear(); release.clear()
        self.files = [self.file('fresh')]
        with patch.object(self.plugin.tools, '_run_cli', side_effect=blocked):
            self.now += 61; self.post()
            self.assertTrue(started.wait(1))
            self.configure(updates_enabled=False)
            self.assertIsNone(self.pre())
            self.post()
            self.configure(updates_enabled=True)
            self.assertIsNone(self.pre())
            release.set(); self.finish()
        self.assertIsNone(self.pre())
        self.assertEqual(len(self.calls), 2)

    def test_profiles_sessions_and_delegated_turns(self):
        self.enable()
        self.pre('child', parent_session_id='chat'); self.post('child')
        self.post('unseen')
        self.pre('scheduled')  # A cron turn must clear any previous eligibility.
        self.files = [self.file('third-party')]
        self.poll()
        self.assertIsNone(self.pre('scheduled', platform='cron'))
        self.ctx.hooks['post_tool_call'](
            session_id='scheduled', tool_name='fulcra_file_upload',
            args={'path': '/notes/third-party'}, result='Uploaded', status='ok')
        self.ctx.hooks['post_tool_call'](
            session_id='child', tool_name='fulcra_record',
            args={'data_type': 'Steps'}, result='Submitted', status='ok')
        self.now += 61
        self.post('scheduled'); self.finish()
        self.assertEqual(len(self.calls), 1)
        text = self.pre('other')['context']
        self.assertIn('Steps', text)
        self.assertIn('/notes/third-party', text)
        self.assertIsNone(self.pre())  # Offered once across all profile sessions.
        self.post('other'); self.finish()
        self.assertEqual(len(self.calls), 2)
        self.post(); self.finish()
        self.assertEqual(len(self.calls), 2)  # Shared cooldown, not per-session.
        self.assertEqual(self.calls[0][0][2], self.calls[1][0][1])
        token = self.ctx.state.profile.set('b')
        self.assertIsNone(self.pre()); self.post()
        self.enable(); self.poll()
        self.assertEqual(self.calls[-1][2], 'b')
        self.assertIn('Steps', self.pre()['context'])
        self.ctx.state.profile.reset(token)
        self.assertIn('Steps', self.pre()['context'])
        self.assertEqual(len(self.calls), 3)


if __name__ == '__main__':
    unittest.main()
