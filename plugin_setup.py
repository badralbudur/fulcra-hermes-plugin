"""Native settings plus explicit, noninteractive slash/CLI frontends."""
import argparse
import json
import re
import shlex

from . import mesh_updates, updates, workspace

SETTINGS = {**workspace.SETTINGS, **updates.SETTINGS, **mesh_updates.SETTINGS}
FLAGS = {
    'workspace': 'workspace_context_enabled', 'updates': 'updates_enabled',
    'interval': 'update_interval', 'mesh-messages': 'mesh_messages_enabled',
    'mesh-invites': 'mesh_invites_enabled', 'mesh-agent': 'mesh_agent',
    'workspace-name': 'workspace_name', 'workspace-role': 'workspace_role',
}
FEATURES = ('workspace_context_enabled', 'updates_enabled', 'mesh_messages_enabled', 'mesh_invites_enabled')
HINT_KEY = 'setup-discovered.v1'  # Offered to the model or explicitly handled, not delivered/declined.
HINT = ('Briefly offer these Fulcra setup options: workspace context.md loading; what\'s-new notices '
        'and a configurable shared check interval; independent automatic mesh message checks '
        'and automatic mesh invitation checks. Use Desktop Capabilities → Plugins → Context, '
        '/fulcra setup, or hermes fulcra setup to choose. '
        'Preserve all prior explicit choices; never auto-enable a feature. '
        'No feature was enabled or configuration changed for this offer. All choices are explicit, '
        'profile-wide and appropriate only for trusted chats sharing the OS Fulcra login. '
        'Do not launch a questionnaire or block the current task.')


class Parser(argparse.ArgumentParser):
    def error(self, message):
        """Return parsing errors without exiting the host."""
        raise ValueError(message)


def arguments(parser):
    """Add the shared slash and native CLI settings arguments."""
    parser.add_argument('action', nargs='?', choices=('setup', 'status', 'help'), default='setup')
    for flag, key in FLAGS.items():
        spec = SETTINGS[key]
        options = {'dest': key, 'default': argparse.SUPPRESS, 'help': spec['description']}
        if spec['type'] == 'boolean':
            options['choices'] = ('on', 'off')
        elif spec['type'] == 'integer':
            options['type'] = int
        parser.add_argument('--' + flag, **options)


class Setup:
    def __init__(self, ctx):
        """Bind setup to the active profile's plugin context."""
        self.ctx = ctx

    def pre(self, session_id='', parent_session_id='', platform='', is_first_turn=False, **kwargs):
        """Offer options once per profile, only on an eligible new-session first turn."""
        if is_first_turn is not True or not session_id or parent_session_id or platform == 'cron':
            return
        with updates._lock(self.ctx):
            if self.ctx.state.get(HINT_KEY, False):
                return
            if all(type(self.ctx.get_config(k)) is bool for k in FEATURES):
                return
            self.ctx.state.set(HINT_KEY, True)
            return {'context': HINT}

    def command(self, raw_args=''):
        """Handle explicit slash setup without prompts or host exits."""
        # argparse's default help/error paths exit the host, including gateways.
        parser = Parser(prog='/fulcra', add_help=False, allow_abbrev=False)
        arguments(parser)
        parser.add_argument('-h', '--help', action='store_true')
        try:
            with updates._lock(self.ctx):
                self.ctx.state.set(HINT_KEY, True)
            args = vars(parser.parse_args(shlex.split(raw_args)))
            if args.pop('help'):
                return parser.format_help() + '\n' + self.status()
            return self.apply(args)
        except (ValueError, OSError) as exc:
            return 'Error: ' + str(exc)

    def cli_setup(self, parser):
        """Register native CLI arguments using the shared schema."""
        arguments(parser)

    def cli(self, args):
        """Apply explicit native CLI choices and print their readback."""
        # Only our namespace keys, not Hermes's global parser options.
        values = {k: v for k, v in vars(args).items() if k in SETTINGS or k == 'action'}
        try:
            with updates._lock(self.ctx):
                self.ctx.state.set(HINT_KEY, True)
            text = self.apply(values)
        except (ValueError, OSError) as exc:
            text = 'Error: ' + str(exc)
        print(text)
        return text

    def apply(self, args):
        """Validate proposed settings and write only explicitly supplied choices."""
        action = args.pop('action', 'setup')
        if action != 'setup' and args:
            raise ValueError('Only setup accepts settings flags')
        if not args:
            return self.status()
        changes = {k: (v == 'on' if SETTINGS[k]['type'] == 'boolean' else v) for k, v in args.items()}
        with updates._lock(self.ctx):
            current = {k: self.ctx.get_config(k, spec['default']) for k, spec in SETTINGS.items()}
            merged = {**current, **changes}
            # Validate the complete proposed configuration before the first config write.
            updates._validate_settings({k: merged[k] for k in updates.SETTINGS})
            for key in ('workspace_name', 'workspace_role'):
                if not isinstance(merged[key], str) or not re.fullmatch(workspace.SEGMENT, merged[key]):
                    raise ValueError(key + ' must be a single alphanumeric, hyphen or underscore segment (1–64 characters)')
            mesh_updates.validate(merged)
            for key in FEATURES:
                if type(merged[key]) is not bool:
                    raise ValueError(key + ' must be boolean')
            for key, value in changes.items():
                self.ctx.set_config(key, value)
            if changes:
                mesh_updates.sync(self.ctx)
                updates._control(self.ctx, updates._settings(self.ctx))
            return self.status()

    def status(self):
        """Show current grouped values and available setup controls."""
        lines = ['Fulcra settings (active profile; trusted chats only):']
        for group, keys in (('Workspace', workspace.SETTINGS), ('Updates / shared check interval', updates.SETTINGS),
                            ('Mesh', mesh_updates.SETTINGS)):
            lines.append(group + ':')
            for key, spec in keys.items():
                value = self.ctx.get_config(key, spec['default'])
                lines.append('  ' + key + ' = ' + json.dumps(value, ensure_ascii=True))
        lines += ['Use Desktop Capabilities → Plugins, /fulcra setup --help, or hermes fulcra setup --help.',
                  'Choose --workspace on/off --updates on/off --interval 900 --mesh-messages on/off',
                  '       --mesh-invites on/off --mesh-agent NAME. Omitted choices are preserved.',
                  'Checks are turn-triggered; notices arrive on a later turn, never while idle.',
                  'No automatic accept/share/reply/send. Workspace loads on a new session first turn.']
        return '\n'.join(lines)


def register(ctx):
    """Register setup frontends and discovery without persistent writes."""
    setup = Setup(ctx)
    ctx.register_command('fulcra', setup.command, description='Fulcra setup, settings and status',
                         args_hint='[setup|status|help] [options]')
    ctx.register_cli_command(name='fulcra', help='Fulcra setup and status',
                             setup_fn=setup.cli_setup, handler_fn=setup.cli)
    ctx.register_hook('pre_llm_call', setup.pre)
