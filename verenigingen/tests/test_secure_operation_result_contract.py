"""Contract tests for SecureOperationResult API surface.

The canonical attribute for the document reference is `.document`.
Several historical callers wrote `.doc` instead, which silently raised
AttributeError that broad `except Exception:` blocks (notably in
web_form/donation_form.py and the Mollie chargeback webhook)
swallowed into a generic 'please try again' message.

This module pins the contract so future regressions surface at the
call site instead of corrupting user-facing flows.
"""

import unittest


class TestSecureOperationResultContract(unittest.TestCase):
    """Pin the SecureOperationResult attribute surface."""

    def test_document_is_the_canonical_attribute(self):
        from verenigingen.utils.secure_operations import SecureOperationResult

        result = SecureOperationResult(success=True, operation_id="test-op-1")
        self.assertTrue(hasattr(result, "document"))
        self.assertIsNone(result.document)
        result.document = "sentinel"
        self.assertEqual(result.document, "sentinel")

    def test_dot_doc_loudly_raises_attribute_error(self):
        from verenigingen.utils.secure_operations import SecureOperationResult

        result = SecureOperationResult(success=True, operation_id="test-op-2")
        with self.assertRaises(AttributeError) as ctx:
            _ = result.doc
        self.assertIn("document", str(ctx.exception))

    def test_hasattr_doc_returns_false_due_to_property(self):
        """Pin the counter-intuitive `hasattr` semantics of the loud-fail property.

        `hasattr(obj, 'doc')` returns False when accessing `obj.doc` raises
        AttributeError. So `if hasattr(result, 'doc'):` to probe for backwards
        compat will silently skip rather than raise loudly. Direct attribute
        access is the path that surfaces the typo — pinned here so future
        callers know which idiom to use.
        """
        from verenigingen.utils.secure_operations import SecureOperationResult

        result = SecureOperationResult(success=True, operation_id="test-op-hasattr")
        self.assertFalse(hasattr(result, "doc"))

    def test_result_has_expected_attributes(self):
        from verenigingen.utils.secure_operations import SecureOperationResult

        result = SecureOperationResult(success=True, operation_id="test-op-3")
        for name in ("success", "operation_id", "errors", "warnings",
                     "audit_trail", "doc_name", "document", "duration"):
            self.assertTrue(
                hasattr(result, name),
                f"SecureOperationResult missing expected attribute: {name}",
            )
