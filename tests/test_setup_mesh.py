"""Setup and automatic mesh workflows; CLI fixtures only, never account access."""
import argparse
import json
import threading
import unittest
from unittest.mock import patch

from test_updates import Context, load_plugin

OWN = '11111111-1111-4111-8111-111111111111'
PEER = '22222222-2222-4222-8222-222222222222'
CHANNEL = 'MomentAnnotation/33333333-3333-4333-8333-333333333333'
GRANT = '44444444-4444-4444-8444-444444444444'
ACTUAL_GRANT = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
MID = '55555555-5555-4555-8555-555555555555'


class SetupMeshTests(unittest.TestCase):
    def setUp(self):
        """Create profile-local fixtures and intercept every CLI request."""
        self.plugin = load_plugin()
        self.ctx = Context()
        self.setup = self.plugin.plugin_setup.Setup(self.ctx)
        self.watcher = self.plugin.mesh_updates.MeshUpdates(self.ctx)
        self.now = 1800000000.0
        self.calls = []
        self.own = OWN
        self.shares = [dict(sharing_fulcra_userid=PEER, id=GRANT, grant_id=ACTUAL_GRANT, grant_type='group',
                            share_all_data=False, fulcra_data_types=[CHANNEL])]
        self.env = dict(v=1, mid=MID, to='helper', to_user=OWN, kind='directive',
                        pri='P2', slug='hello', body='untrusted preview')
        self.rows = [dict(note=json.dumps(self.env))]
        for stub in (patch.object(self.plugin.tools, '_run_cli', side_effect=self.cli),
                     patch.object(self.plugin.mesh_updates.time, 'time', side_effect=lambda: self.now)):
            stub.start()
            self.addCleanup(stub.stop)
        self.addCleanup(self.finish)

    def cli(self, argv, timeout=None):
        """Serve account, share and record fixtures while recording scope."""
        self.calls.append((argv, timeout, self.ctx.state.profile.get()))
        if argv == ['user-info']:
            return json.dumps({'userid': self.own})
        if argv == ['share', 'list-incoming']:
            return '\n'.join(map(json.dumps, self.shares))
        if argv[0] == 'get-records':
            return '\n'.join(map(json.dumps, self.rows))
        raise AssertionError(argv)

    def finish(self):
        """Join test workers and fail if any outlive the bounded wait."""
        for thread in threading.enumerate():
            if thread.name == 'fulcra-mesh-updates':
                thread.join(3)
                self.assertFalse(thread.is_alive())

    def cycle(self):
        """Advance beyond cooldown and finish one automatic check."""
        self.now += 901
        self.watcher.post(session_id='chat')
        self.finish()

    def enable(self, flags='--mesh-messages on --mesh-invites on --mesh-agent helper'):
        """Apply explicit mesh choices and establish session eligibility."""
        self.assertNotIn('Error:', self.setup.command('setup ' + flags))
        self.watcher.pre(session_id='chat')

    def test_setup_readback_validation_preservation_and_cli(self):
        text = self.setup.command('setup')
        self.assertIn('Workspace', text)
        self.assertIn('Mesh', text)
        self.assertEqual(self.ctx.config, {})
        self.assertIsNone(self.setup.pre(session_id='chat', is_first_turn=True))
        self.ctx.set_config('updates_data_types', ['Steps'])
        text = self.setup.command('setup --workspace off --updates on --interval 120 --mesh-invites on')
        self.assertIn('120', text)
        self.assertIs(self.ctx.get_config('workspace_context_enabled'), False)
        self.assertEqual(self.ctx.get_config('updates_data_types'), ['Steps'])
        before = self.ctx.config.copy()
        for text in ('setup --workspace on --interval 1', 'setup --mesh-messages on',
                     'setup --bogus', 'setup --mesh-agent "', 'status --updates off'):
            self.assertTrue(self.setup.command(text).startswith('Error:'), text)
            self.assertEqual(self.ctx.config, before)
        self.assertIn('--mesh-messages', self.setup.command('setup --help'))
        self.assertEqual(self.ctx.config, before)
        parser = argparse.ArgumentParser()
        self.setup.cli_setup(parser)
        self.setup.cli(parser.parse_args(['setup', '--mesh-agent', 'helper', '--mesh-messages', 'on']))
        self.assertIs(self.ctx.get_config('mesh_messages_enabled'), True)
        self.assertIn('helper', self.setup.command('status'))

    def test_discovery_once_no_config_writes_and_native_choices(self):
        self.ctx.set_config('updates_enabled', True)
        before = self.ctx.config.copy()
        for args in ({}, {'is_first_turn': True}, {'session_id': 'ordinary'},
                     *({'session_id': 'ordinary', 'is_first_turn': value} for value in (False, None, 1, 'true')),
                     {'session_id': 'cron', 'platform': 'cron', 'is_first_turn': True},
                     {'session_id': 'child', 'parent_session_id': 'chat', 'is_first_turn': True}):
            with patch.object(self.ctx.state, 'get', side_effect=AssertionError('Ineligible marker read')):
                self.assertIsNone(self.setup.pre(**args))
            self.assertIsNone(self.ctx.state.get(self.plugin.plugin_setup.HINT_KEY))
        text = self.setup.pre(session_id='new-chat', is_first_turn=True)['context']
        for option in ('options', 'workspace context.md loading', "what's-new notices",
                       'configurable shared check interval', 'automatic mesh message checks',
                       'automatic mesh invitation checks', 'independent', '/fulcra setup',
                       'hermes fulcra setup', 'Desktop Capabilities'):
            self.assertIn(option, text)
        self.assertEqual(self.ctx.config, before)
        self.assertIs(self.ctx.state.get(self.plugin.plugin_setup.HINT_KEY), True)
        self.assertIsNone(self.plugin.plugin_setup.Setup(self.ctx).pre(session_id='other', is_first_turn=True))
        token = self.ctx.state.profile.set('b')
        for key in ('workspace_context_enabled', 'updates_enabled', 'mesh_messages_enabled', 'mesh_invites_enabled'):
            self.ctx.set_config(key, False)
        self.assertIsNone(self.setup.pre(session_id='chat', is_first_turn=True))
        self.ctx.state.profile.reset(token)

    def test_messages_filter_dedup_restart_and_manual_cursor_independence(self):
        self.enable('--mesh-messages on --mesh-agent helper')
        for change in ({'to': 'other'}, {'to_user': PEER}):
            self.rows.append(dict(note=json.dumps({**self.env, **change})))
        self.rows.append(dict(note='malformed'))
        self.cycle()
        self.assertIsNone(self.ctx.state.get(self.plugin.mesh.STATE_KEY))
        self.watcher = self.plugin.mesh_updates.MeshUpdates(self.ctx)
        text = self.watcher.pre(session_id='chat')['context']
        self.assertIn(MID, text)
        self.assertIn(PEER, text)
        self.assertIn('UNTRUSTED', text)
        self.assertNotIn('"kind": "invitation_candidate"', text)
        self.assertEqual(text.count(MID), 1)
        self.cycle()
        self.assertIsNone(self.watcher.pre(session_id='other'))
        manual = json.loads(self.plugin.mesh.make_handler(self.ctx.state)({'action': 'receive', 'local_agent': 'helper'}))
        self.assertEqual(manual['messages'][0]['envelope']['mid'], MID)
        self.assertTrue(all(0 < timeout <= 30 for _, timeout, _ in self.calls if timeout is not None))

    def test_invites_independent_narrow_provenance_and_account_reset(self):
        self.enable('--mesh-invites on')
        self.shares += [{**self.shares[0], 'share_all_data': True},
                        {**self.shares[0], 'sharing_fulcra_userid': 'bad'},
                        {**self.shares[0], 'fulcra_data_types': ['MomentAnnotation']},
                        {**self.shares[0], 'id': None}]
        self.cycle()
        self.assertFalse(any(a[0] == 'get-records' for a, _, _ in self.calls))
        text = self.watcher.pre(session_id='chat')['context']
        self.assertEqual(text.count('"kind": "invitation_candidate"'), 1)
        for value in (PEER, CHANNEL, 'group'):
            self.assertIn(value, text)
        self.assertIn('"share_id": "' + GRANT + '"', text)
        self.assertIn('"grant_id": "' + ACTUAL_GRANT + '"', text)
        self.cycle()
        self.assertIsNone(self.watcher.pre(session_id='chat'))
        self.own = '66666666-6666-4666-8666-666666666666'
        self.ctx.state.set(self.plugin.updates.FEED_KEY, {'pending': ['old-account']})
        self.cycle()
        self.assertIn('invitation_candidate', self.watcher.pre(session_id='chat')['context'])
        self.assertEqual(self.ctx.state.get(self.plugin.updates.FEED_KEY), {})
        # A login change observed at final identity verification also drops old queues.
        self.own = OWN
        def switch_during_list(argv, timeout=None):
            """Simulate a login switch before final account verification."""
            result = self.cli(argv, timeout)
            if argv == ['share', 'list-incoming']:
                self.own = '77777777-7777-4777-8777-777777777777'
            return result
        with patch.object(self.plugin.tools, '_run_cli', side_effect=switch_during_list):
            self.cycle()
        self.assertIsNone(self.watcher.pre(session_id='chat'))
        self.assertEqual(self.ctx.state.get(self.plugin.mesh_updates.STATE_KEY)['data'], {})

    def test_nonblocking_inflight_disable_agent_changes_and_profile_gates(self):
        self.enable()
        started, release = threading.Event(), threading.Event()
        def blocked(argv, timeout=None):
            """Pause a CLI read to exercise concurrent settings or queue changes."""
            started.set()
            self.assertTrue(release.wait(2))
            return self.cli(argv, timeout)
        with patch.object(self.plugin.tools, '_run_cli', side_effect=blocked):
            self.now += 901
            self.watcher.post(session_id='chat')
            self.assertTrue(started.wait(1))
            self.assertIsNone(self.watcher.pre(session_id='other'))
            self.setup.command('setup --mesh-messages off --mesh-invites off')
            self.setup.command('setup --mesh-messages on --mesh-agent changed')
            token = self.ctx.state.profile.set('b')
            self.assertIsNone(self.watcher.pre(session_id='chat'))
            self.watcher.post(session_id='chat')
            release.set(); self.finish()
            self.ctx.state.profile.reset(token)
        self.assertIsNone(self.watcher.pre(session_id='chat'))
        self.assertTrue(all(profile == 'a' for _, _, profile in self.calls))
        self.calls.clear()
        self.now += 901
        for args in ({'session_id': ''}, {'session_id': 'chat', 'platform': 'cron'},
                     {'session_id': 'child', 'parent_session_id': 'chat'}):
            self.watcher.pre(**args)
            self.watcher.post(**args)
        self.watcher.post(session_id='unseen')
        self.assertEqual(self.calls, [])

    def test_failure_cooldown_bounded_notices_and_fresh_pending_merge(self):
        self.enable()
        self.cycle()
        state = self.ctx.state.get(self.plugin.mesh_updates.STATE_KEY)
        assert state is not None
        started, release = threading.Event(), threading.Event()
        def blocked(argv, timeout=None):
            """Pause a CLI read to exercise concurrent settings or queue changes."""
            started.set()
            self.assertTrue(release.wait(2))
            return self.cli(argv, timeout)
        with patch.object(self.plugin.tools, '_run_cli', side_effect=blocked):
            self.now += 901
            self.watcher.post(session_id='chat')
            self.assertTrue(started.wait(1))
            self.assertIn(MID, self.watcher.pre(session_id='other')['context'])
            release.set(); self.finish()
        self.assertIsNone(self.watcher.pre(session_id='chat'))  # No stale pending resurrection.
        state = self.ctx.state.get(self.plugin.mesh_updates.STATE_KEY)
        assert state is not None
        with patch.object(self.plugin.tools, '_run_cli', side_effect=RuntimeError('private token')) as run:
            self.cycle()
            self.watcher.post(session_id='chat'); self.finish()
            self.assertEqual(run.call_count, 1)
        failed = self.ctx.state.get(self.plugin.mesh_updates.STATE_KEY)
        assert failed is not None
        self.assertEqual(failed['data'], state['data'])
        self.assertEqual(failed['pending'], [])
        second = 'MomentAnnotation/88888888-8888-4888-8888-888888888888'
        self.shares.append({**self.shares[0], 'fulcra_data_types': [second]})
        def partial(argv, timeout=None):
            """Fail the second channel after a successful partial read."""
            if argv[0] == 'get-records' and argv[1] == second:
                return '{bad JSONL'
            return self.cli(argv, timeout)
        with patch.object(self.plugin.tools, '_run_cli', side_effect=partial):
            self.cycle()
        self.assertEqual(self.ctx.state.get(self.plugin.mesh_updates.STATE_KEY)['data'], state['data'])
        self.shares.pop()
        self.rows = [dict(note=json.dumps({**self.env, 'mid': f'{i:08x}-5555-4555-8555-555555555555', 'body': '\x01' * 9000})) for i in range(40)]
        self.cycle()
        text = self.watcher.pre(session_id='chat')['context']
        self.assertLessEqual(len(text), 3000)
        self.assertIn('preview', text)
        self.assertIsNone(self.watcher.pre(session_id='other'))
        self.assertIsNone(self.ctx.state.get(self.plugin.mesh.STATE_KEY))
        self.ctx.set_config('mesh_agent', '\ninvalid')
        self.assertIsNone(self.watcher.pre(session_id='chat'))
        self.ctx.set_config('mesh_agent', 'helper')
        self.assertIsNone(self.watcher.pre(session_id='chat'))
