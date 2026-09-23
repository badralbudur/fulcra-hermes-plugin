"""Remote path regressions; no account requests."""
import unittest
from unittest.mock import patch
from test_tools import load_tools


class ShareGuardTests(unittest.TestCase):
    ID = '01234567-89ab-cdef-0123-456789abcdef'

    def test_paths_are_guarded_in_every_selector(self):
        tools = load_tools()
        for field in ('path', 'files', 'add_files', 'remove_files', 'set_files'):
            for path in ('relative', '/a/../b', '/./a', '/a\\b', '//a', '/a//b', '/a\x00'):
                name = 'fulcra_file_stat' if field == 'path' else ('fulcra_create_share' if field == 'files' else 'fulcra_update_share')
                args = ({'path': path} if field == 'path' else
                        {'files': [path], 'user_ids': [self.ID]} if field == 'files' else
                        {'share_id': self.ID, field: [path]})
                with self.subTest(field=field, path=path), patch.object(tools, '_run_cli') as run:
                    self.assertTrue(getattr(tools, name)(args).startswith('Error'))
                    run.assert_not_called()
        with patch.object(tools, '_run_cli', return_value='ok'):
            self.assertEqual(tools.fulcra_create_share({'files': ['/'], 'user_ids': [self.ID]}), 'ok')
