"""
Tests for the PaymentContext container (payment_context_resolver.py).

Restored from the deleted test_payment_context_resolver.py (#2676): PaymentContext is live
(payment_entry_factory, cost_center_resolver, processors); only the resolver class was dead.
"""

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext


class TestPaymentContext(EnhancedTestCase):
    """
    Test PaymentContext data structure.
    """

    def test_payment_context_creation(self):
        """Test PaymentContext creation and properties"""
        context = PaymentContext(
            payment_type="donation",
            target_doctype="Donation",
            target_name="DON-2024-001",
            metadata={"test": "value"},
        )

        self.assertEqual(context.payment_type, "donation")
        self.assertEqual(context.target_doctype, "Donation")
        self.assertEqual(context.target_name, "DON-2024-001")
        self.assertEqual(context.metadata["test"], "value")

    def test_payment_context_rejects_empty_required_fields(self):
        """PaymentContext must reject empty/blank payment_type, target_doctype, or
        target_name at construction -- a context without a concrete target cannot
        attribute a payment and must not masquerade as a resolved one."""
        for bad_args in (
            ("", "Donation", "DON-1"),
            ("donation", "", "DON-1"),
            ("donation", "Donation", ""),
            ("donation", "Donation", "   "),  # whitespace-only is still empty
        ):
            with self.assertRaises(ValueError):
                PaymentContext(*bad_args)

        # A fully-specified context still constructs normally.
        ctx = PaymentContext("donation", "Donation", "DON-1")
        self.assertEqual(ctx.target_name, "DON-1")

    def test_payment_context_string_representation(self):
        """Test PaymentContext string representation for logging"""
        context = PaymentContext("membership", "Member", "MEM-2024-001")
        str_repr = str(context)

        self.assertIn("membership", str_repr)
        self.assertIn("Member", str_repr)
        self.assertIn("MEM-2024-001", str_repr)
