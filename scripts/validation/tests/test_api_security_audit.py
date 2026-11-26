#!/usr/bin/env python3
"""Tests for scripts/validation/api_security_audit.py (#1096).

ci.yml's api-security-audit used to match ``line.startswith('@frappe.whitelist')``,
which counted decorator-shaped text inside a string literal as an endpoint.
``_old_inline_decorator_lines`` reproduces that heuristic so the red is shown
against the real old logic, not a paraphrase.
"""
import importlib.util
import sys
import textwrap
import unittest
from pathlib import Path

_MOD_PATH = Path(__file__).resolve().parents[1] / "api_security_audit.py"
_spec = importlib.util.spec_from_file_location("api_security_audit", _MOD_PATH)
audit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = audit
_spec.loader.exec_module(audit)

_CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"

# optimize_payment_dashboard.py shape: the decorator text lives in a string used
# to rewrite another file.
_REWRITER_SOURCE = textwrap.dedent(
    '''
    content = content.replace(
        "@frappe.whitelist()\\ndef get_dashboard_data(",
        """@cache_with_ttl(ttl=300)
    @handle_api_errors
    @frappe.whitelist()
    def get_dashboard_data("""
    )
    '''
)


def _old_inline_decorator_lines(source):
    """The heuristic ci.yml used before #1096."""
    return [i + 1 for i, line in enumerate(source.split("\n")) if line.strip().startswith("@frappe.whitelist")]


class TestStringLiteralIsNotAnEndpoint(unittest.TestCase):
    def test_old_heuristic_flags_the_rewriter_shape(self):
        # Red evidence: the old logic does produce a finding here.
        self.assertTrue(_old_inline_decorator_lines(_REWRITER_SOURCE))

    def test_ast_audit_finds_no_endpoint_in_the_rewriter_shape(self):
        self.assertEqual(audit.find_api_endpoints(_REWRITER_SOURCE), [])

    def test_docstring_and_comment_mentions_are_not_endpoints(self):
        source = textwrap.dedent(
            '''
            def helper():
                """Usage:

                @frappe.whitelist()
                def example(): ...
                """
                # @frappe.whitelist()
            '''
        )
        self.assertEqual(audit.find_api_endpoints(source), [])


class TestRealEndpointsAreStillFound(unittest.TestCase):
    def _names(self, source):
        return [e[0] for e in audit.find_api_endpoints(textwrap.dedent(source))]

    def test_plain_decorator(self):
        self.assertEqual(self._names("@frappe.whitelist()\ndef a():\n    pass\n"), ["a"])

    def test_allow_guest_decorator(self):
        self.assertEqual(self._names("@frappe.whitelist(allow_guest=True)\ndef g():\n    pass\n"), ["g"])

    def test_bare_attribute_decorator(self):
        self.assertEqual(self._names("@frappe.whitelist\ndef b():\n    pass\n"), ["b"])

    def test_async_function(self):
        self.assertEqual(self._names("@frappe.whitelist()\nasync def c():\n    pass\n"), ["c"])

    def test_stacked_under_another_decorator_is_found_and_unprotected(self):
        found = audit.find_api_endpoints("@some_wrapper\n@frappe.whitelist()\ndef s():\n    pass\n")
        self.assertEqual([(e[0], e[2]) for e in found], [("s", False)])

    def test_security_decorator_stacked_either_side_marks_protected(self):
        above = "@critical_api()\n@frappe.whitelist()\ndef p():\n    pass\n"
        below = "@frappe.whitelist()\n@critical_api()\ndef q():\n    pass\n"
        self.assertEqual([e[2] for e in audit.find_api_endpoints(above)], [True])
        self.assertEqual([e[2] for e in audit.find_api_endpoints(below)], [True])

    def test_security_text_in_a_string_does_not_protect(self):
        source = '@frappe.whitelist()\ndef r():\n    return "@critical_api"\n'
        self.assertEqual([e[2] for e in audit.find_api_endpoints(source)], [False])

    def test_method_with_self_is_flagged_as_method(self):
        source = "class D:\n    @frappe.whitelist()\n    def m(self):\n        pass\n"
        self.assertEqual([e[3] for e in audit.find_api_endpoints(source)], [True])


class TestWholeTreeAndWorkflow(unittest.TestCase):
    def test_tree_has_no_unprotected_high_risk_endpoint_and_no_baseline_needed(self):
        import os

        root = Path(__file__).resolve().parents[3]
        cwd = os.getcwd()
        os.chdir(root)
        try:
            self.assertEqual(audit.find_unprotected_high_risk(), [])
        finally:
            os.chdir(cwd)

    def test_known_false_positive_file_is_not_an_endpoint_source(self):
        # Control with a real row: the file that motivated #1096 still contains the
        # decorator text, and the old heuristic still fires on it.
        path = Path(__file__).resolve().parents[2] / "optimization" / "optimize_payment_dashboard.py"
        source = path.read_text()
        self.assertTrue(_old_inline_decorator_lines(source))
        self.assertEqual(audit.find_api_endpoints(source), [])

    def test_ci_yml_uses_the_script_and_not_the_line_heuristic(self):
        text = _CI.read_text()
        self.assertIn("scripts/validation/api_security_audit.py audit", text)
        self.assertIn("scripts/validation/api_security_audit.py report", text)
        self.assertNotIn("startswith('@frappe.whitelist')", text)
        self.assertNotIn("KNOWN_FALSE_POSITIVES", text)


if __name__ == "__main__":
    unittest.main()
