"""The validator must flag an unchecked result AND stay quiet on a checked one.

A rule that only ever fires is as useless as one that never does. Each case below
pairs a positive with the negative it has to be told apart from.
"""

import pathlib
import sys
import textwrap
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "scripts" / "validation"))

from secure_operation_result_validator import scan_file  # noqa: E402


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
