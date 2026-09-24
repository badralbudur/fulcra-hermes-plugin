"""Pinned CLI/core file workflow; only HTTP transport is replaced by a fake store."""
import io
import json
from pathlib import PurePosixPath
import socket
from urllib.error import HTTPError
from unittest.mock import patch

from fulcra_api.core import FulcraAPI
from test_updates import Context, load_plugin


def run(runner, cli, real_file_methods):
    """Exercise exact missing diagnostics, disk downloads, uploads and readback offline."""
    plugin = load_plugin()
    ctx = Context()
    ctx.set_config('workspace_context_enabled', True)
    hook = plugin.workspace.Workspace(ctx).pre
    files, metadata, pending, calls = {}, {}, {}, []
    denied = set()

    def api(self, endpoint, query=None, data=None, method='GET', **kwargs):
        """Replace only Fulcra HTTP responses; retain core file methods."""
        if endpoint.endswith('/download'):
            ident = endpoint.split('/')[-2]
            return io.BytesIO(files[ident])
        assert endpoint == '/input/v1/file_upload', endpoint
        if method == 'POST':
            path = str(PurePosixPath(data['path']) / data['name'])
            ident = str(len(metadata) + 1)
            metadata[path] = dict(id=ident, path=data['path'], name=data['name'],
                                  size=data['content_length'], uploaded_at='2026-01-01T00:00:00Z', state='uploaded')
            pending[ident] = path
            return json.dumps({'file': metadata[path], 'url': 'https://fixture.invalid/' + ident})
        path = str(PurePosixPath(query['path']) / query['name'])
        if path in denied:
            raise HTTPError('https://fixture.invalid', 403, 'Forbidden', {}, io.BytesIO(b'private detail'))
        info = metadata.get(path)
        return json.dumps({'files': [info] if info else []})

    def upload(request):
        """Capture the real core upload stream instead of opening a socket."""
        ident = request.full_url.rsplit('/', 1)[-1]
        assert ident in pending
        files[ident] = request.data.read()
        return io.BytesIO(b'')

    def boundary(argv, timeout):
        """Match the adapter's exit diagnostic while executing real Click commands."""
        assert 0 < timeout <= 25
        calls.append(argv)
        result = runner.invoke(cli, argv)
        if result.exit_code:
            raise RuntimeError(f'Fulcra CLI exited with status {result.exit_code}: {(result.stderr or result.stdout).strip()}')
        return result.stdout

    with patch.multiple(FulcraAPI, **real_file_methods), \
         patch.object(FulcraAPI, 'fulcra_api', api), \
         patch('urllib.request.urlopen', side_effect=upload), \
         patch.object(socket.socket, 'connect', side_effect=AssertionError('Network forbidden')), \
         patch.object(plugin.tools, '_run_cli', side_effect=boundary):
        text = hook(is_first_turn=True, session_id='real-cli-cold')['context']
        assert 'missing seeds verified' in text, text
        expected = plugin.workspace.templates('assistant')
        assert {path: files[info['id']].decode() for path, info in metadata.items()} == {
            '/workspace/general/' + path: content for path, content in expected.items()}
        preference = '/workspace/general/knowledge/user-preferences.md'
        files[metadata[preference]['id']] = b'---\ntype: Custom\nextra: preserve\n---\nUser-owned preference'
        calls.clear()
        text = hook(is_first_turn=True, session_id='real-cli-warm')['context']
        assert 'User-owned preference' in text
        assert all(argv[1] == 'download' for argv in calls)
        denied.add('/workspace/general/role.md')
        del metadata['/workspace/general/knowledge/fulcra-context.md']
        calls.clear()
        text = hook(is_first_turn=True, session_id='real-cli-denied')['context']
        assert 'incomplete' in text and 'User-owned preference' in text
        assert 'private detail' not in text
        assert all(argv[1] == 'download' for argv in calls)
    print('Pinned workspace CLI/core files: PASS (cold seeds/readback, warm reuse, HTTP 403 != missing; networking blocked)')
