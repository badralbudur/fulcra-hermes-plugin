"""Agent-facing handler safety regressions; no account requests."""
import ast
import unittest
from test_tools import ROOT, load_tools


class DocumentationTests(unittest.TestCase):
    def test_all_functions_have_docstrings_including_wrappers(self):
        tree = ast.parse((ROOT / "tools.py").read_text())
        missing = [node.name for node in ast.walk(tree)
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and not ast.get_docstring(node)]
        self.assertEqual(missing, [])
