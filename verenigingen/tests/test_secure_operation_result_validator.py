"""The validator must flag an unchecked result AND stay quiet on a checked one.

A rule that only ever fires is as useless as one that never does. Each case below
pairs a positive with the negative it has to be told apart from.
"""

import importlib.util
import pathlib
import sys
import textwrap
import unittest

# Loaded by path, NOT via sys.path.insert. Prepending scripts/validation/ would put
# 17 top-level module names (doctype_loader, hooks_parser, test_quality_enforcer, ...)
# on the import path for every other test sharing this process -- a latent collision
# for the whole shard. The sibling validator suites load by spec for the same reason.
_VALIDATOR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "scripts"
    / "validation"
    / "secure_operation_result_validator.py"
)
_spec = importlib.util.spec_from_file_location("_secop_validator", _VALIDATOR)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
scan_file = _module.scan_file


class SecureOperationResultValidatorTest(unittest.TestCase):
    def _scan(self, source: str):
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write(textwrap.dedent(source))
            path = pathlib.Path(fh.name)
        try:
            return scan_file(path)
        finally:
            path.unlink()

    def _kinds(self, source: str):
        return sorted(f.kind for f in self._scan(source))

    # ------------------------------------------------------------- flagged
    def test_a_discarded_result_is_flagged(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    secure_document_operation(operation="save", doc=doc)
                """),
            ["DISCARDED"],
        )

    def test_an_assigned_but_unread_result_is_flagged(self):
        """The branch with no real-world hits today, so it needs its own case."""
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    result = secure_document_operation(operation="save", doc=doc)
                    return doc.name
                """),
            ["UNCHECKED"],
        )

    def test_reading_a_different_attribute_is_not_a_check(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    result = secure_document_operation(operation="save", doc=doc)
                    return result.doc_name
                """),
            ["UNCHECKED"],
        )

    # --------------------------------------------------------- not flagged
    def test_a_checked_result_is_not_flagged(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    result = secure_document_operation(operation="save", doc=doc)
                    if not result.success:
                        frappe.throw("nope")
                    return doc.name
                """),
            [],
        )

    def test_a_returned_result_is_not_flagged(self):
        """Returning it hands the result -- and the responsibility -- to the caller."""
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    return secure_document_operation(operation="save", doc=doc)
                """),
            [],
        )

    def test_an_opt_out_on_the_call_line_silences_it(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    secure_document_operation(operation="save", doc=doc)  # secure-op-ok: best-effort
                """),
            [],
        )

    def test_an_unrecognised_opt_out_reason_is_still_flagged(self):
        """The pragma is the ONLY escape hatch on a rule with no baseline.

        Unpoliced, it is also the only way the rule can quietly die: anyone could
        write `# secure-op-ok: whatever` and the site would vanish. The two
        opt-out tests below both use a VALID reason, so neither can tell "the
        reason is checked" from "any text after the colon wins".
        """
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    secure_document_operation(operation="save", doc=doc)  # secure-op-ok: nah
                """),
            ["BAD_OPT_OUT"],
        )

    def test_an_opt_out_with_no_reason_at_all_is_flagged(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    secure_document_operation(operation="save", doc=doc)  # secure-op-ok:
                """),
            ["BAD_OPT_OUT"],
        )

    def test_a_result_that_is_returned_is_not_flagged(self):
        """Assigning then returning hands off exactly as `return <call>` does."""
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    result = secure_document_operation(operation="save", doc=doc)
                    return result
                """),
            [],
        )

    def test_an_attribute_target_is_tracked(self):
        """`self.result = ...` is the service-class shape; a Name-only check missed it."""
        self.assertEqual(
            self._kinds("""
                def f(self, doc):
                    self.result = secure_document_operation(operation="save", doc=doc)
                    return doc.name
                """),
            ["UNCHECKED"],
        )
        self.assertEqual(
            self._kinds("""
                def f(self, doc):
                    self.result = secure_document_operation(operation="save", doc=doc)
                    if not self.result.success:
                        raise RuntimeError("no")
                """),
            [],
        )

    def test_using_the_call_as_a_condition_is_flagged(self):
        """`if secure_document_operation(...):` is ALWAYS true.

        `SecureOperationResult` defines no `__bool__`, so every instance is truthy.
        This reads as a check and is not one -- the worst shape of the three,
        because it looks handled.
        """
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    if secure_document_operation(operation="save", doc=doc):
                        return doc.name
                """),
            ["TRUTHINESS"],
        )

    def test_a_finding_inside_a_nested_function_is_reported_once(self):
        findings = self._scan("""
            def outer(doc):
                def inner():
                    secure_document_operation(operation="save", doc=doc)
                inner()
            """)
        self.assertEqual(len(findings), 1, f"double-reported: {[f.func for f in findings]}")
        self.assertEqual(findings[0].func, "inner")

    def test_a_finding_carries_the_fields_the_hook_output_shows(self):
        """kind alone is not what a developer reads; line and function are."""
        findings = self._scan("""
            def handle_it(doc):
                secure_document_operation(operation="save", doc=doc)
            """)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].lineno, 3)
        self.assertEqual(findings[0].func, "handle_it")
        self.assertIn("invisible", findings[0].detail)

    def test_an_opt_out_on_the_line_above_silences_it(self):
        self.assertEqual(
            self._kinds("""
                def f(doc):
                    # secure-op-ok: caller-verifies
                    secure_document_operation(operation="save", doc=doc)
                """),
            [],
        )

    def test_a_file_that_never_calls_it_is_not_scanned(self):
        self.assertEqual(self._kinds("def f(doc):\n    doc.save()\n"), [])

    # ------------------------------------------------- the live repository
    def test_the_repository_is_clean(self):
        """Zero violations is the point: this rule has no baseline to grandfather.

        The full sweep of all non-test call sites found exactly three, and all
        three are fixed in the commit that introduced this validator. Anything
        this finds now is a genuine regression, not inherited debt.
        """
        import subprocess

        repo_root = pathlib.Path(__file__).resolve().parents[2]
        proc = subprocess.run(
            [sys.executable, "scripts/validation/secure_operation_result_validator.py"],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"validator reported violations:\n{proc.stdout}")
