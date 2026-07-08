"""
Payment Context Resolver Test Suite
===================================

Tests for PaymentContextResolver - the foundation of the payment-agnostic architecture.
This resolver determines payment type and context from Mollie payment data and metadata
without hardcoding specific payment types.

Key Test Areas:
- Metadata-based payment type detection
- Fallback resolution strategies
- Edge cases and malformed data handling
- Context creation and validation
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import (
    PaymentContext,
    PaymentContextResolver,
)


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

    def test_payment_context_string_representation(self):
        """Test PaymentContext string representation for logging"""
        context = PaymentContext("membership", "Member", "MEM-2024-001")
        str_repr = str(context)

        self.assertIn("membership", str_repr)
        self.assertIn("Member", str_repr)
        self.assertIn("MEM-2024-001", str_repr)


class TestPaymentContextResolver(EnhancedTestCase):
    """
    Test PaymentContextResolver for payment-agnostic context resolution.
    Uses real test data with minimal mocking.
    """

    def setUp(self):
        super().setUp()
        self.resolver = PaymentContextResolver()

        # Create real test data using Enhanced Test Factory
        self.test_member = self.create_test_member(
            first_name="Context", last_name="Test", email="context.test@example.com"
        )

        self.test_donation = self.create_test_donation(
            donor_email=self.test_member.email, amount=50.0, payment_id="test_context_payment_123"
        )

    def test_resolve_context_donation_by_metadata(self):
        """Test donation context resolution via metadata"""
        payment_id = "test_donation_meta_123"

        # Create mock payment data with donation metadata
        payment_data = self._create_mock_payment_data(
            payment_id=payment_id,
            metadata={
                "payment_type": "donation",
                "donation_id": self.test_donation.name,
                "record_type": "Donation",
            },
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Validate context
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "donation")
        self.assertEqual(context.target_doctype, "Donation")
        self.assertEqual(context.target_name, self.test_donation.name)
        self.assertEqual(context.metadata["donation_id"], self.test_donation.name)

    def test_resolve_context_membership_by_metadata(self):
        """Test membership context resolution via metadata"""
        payment_id = "test_membership_meta_123"

        payment_data = self._create_mock_payment_data(
            payment_id=payment_id,
            metadata={
                "payment_type": "membership",
                "member_id": self.test_member.name,
                "record_type": "Member",
            },
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Validate context
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "membership")
        self.assertEqual(context.target_doctype, "Member")
        self.assertEqual(context.target_name, self.test_member.name)

    def test_resolve_context_by_description_json(self):
        """Test context resolution via JSON description (legacy support)"""
        payment_id = "test_description_json_123"

        import json

        description_data = {"type": "donation", "donation_id": self.test_donation.name, "donor": "test-donor"}

        payment_data = self._create_mock_payment_data(
            payment_id=payment_id, description=json.dumps(description_data)
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Validate context
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "donation")
        self.assertEqual(context.target_doctype, "Donation")
        self.assertEqual(context.target_name, self.test_donation.name)

    def test_resolve_context_by_payment_reference(self):
        """Test context resolution by existing payment reference"""
        payment_id = "test_payment_ref_123"

        # Update donation with payment reference. The donation is submitted
        # (docstatus=1), so a plain .save() raises; use db.set_value to update the
        # field directly (the resolver reads it straight from the DB).
        frappe.db.set_value("Donation", self.test_donation.name, "payment_id", payment_id)
        self.test_donation.reload()

        payment_data = self._create_mock_payment_data(payment_id=payment_id)

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Validate context
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "donation")
        self.assertEqual(context.target_doctype, "Donation")
        self.assertEqual(context.target_name, self.test_donation.name)

    def test_resolve_context_subscription_indicates_membership(self):
        """Test that subscription_id in payment data suggests membership"""
        payment_id = "test_subscription_123"

        # The resolver maps a subscription payment to the Member that owns the
        # subscription, so the member must actually carry the subscription id.
        subscription_id = "sub_recurring_membership"
        frappe.db.set_value("Member", self.test_member.name, "mollie_subscription_id", subscription_id)

        payment_data = self._create_mock_payment_data(payment_id=payment_id, subscription_id=subscription_id)

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Should resolve to membership based on subscription presence
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "membership")
        self.assertEqual(context.target_name, self.test_member.name)
        # Note: This test depends on the actual implementation logic
        # If subscription_id doesn't automatically indicate membership,
        # this might resolve differently

    def test_resolve_context_malformed_metadata(self):
        """A non-dict metadata value falls through every resolution strategy to None.

        _extract_metadata() only treats a non-empty dict as authoritative; a string
        falls through to description-JSON parsing (fails here too, description is
        plain text). Strategy 3 (_resolve_from_document_lookup) finds no Donation for
        this payment_id and Strategy 4 (customer fallback) has no customer_id on the
        mock, so resolve_context() cleanly returns None -- via the real fallback chain
        (the former masked Member.payment_id DB error has been removed, see
        backlog-dead-code.md / the resolver fix).
        """
        payment_id = "test_malformed_meta_123"

        payment_data = self._create_mock_payment_data(
            payment_id=payment_id, metadata="invalid_metadata_format"  # Should be dict, not string
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        self.assertIsNone(context)

    def test_resolve_context_invalid_json_description(self):
        """Unparseable JSON in description is swallowed by json.JSONDecodeError, then
        strategy 3 (document lookup) finds no Donation and strategy 4 has no customer_id,
        so resolve_context() cleanly returns None via the real fallback chain."""
        payment_id = "test_invalid_json_123"

        payment_data = self._create_mock_payment_data(
            payment_id=payment_id, description='{"type": "donation", invalid json'  # Malformed JSON
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        self.assertIsNone(context)

    def test_resolve_context_missing_payment_data(self):
        """payment_data=None: strategies 1-2 handle None safely (hasattr/getattr on
        None), strategy 3 finds no Donation for this fresh payment_id, and strategy 4
        returns None because payment_data is None -- resolve_context() returns None and
        never raises to the caller, which is the real, observable guarantee here."""
        payment_id = "test_missing_data_123"

        context = self.resolver.resolve_context(payment_id, None)

        self.assertIsNone(context)

    def test_resolve_context_empty_metadata(self):
        """An empty metadata dict is falsy, so _extract_metadata falls through to the
        description parse (default description "Test payment" is not JSON either),
        then strategy 3 finds no Donation and strategy 4 has no customer_id, so
        resolve_context() returns None via the clean fallback chain."""
        payment_id = "test_empty_meta_123"

        payment_data = self._create_mock_payment_data(payment_id=payment_id, metadata={})

        context = self.resolver.resolve_context(payment_id, payment_data)

        self.assertIsNone(context)

    def test_resolve_context_multiple_resolution_strategies(self):
        """Test that resolver tries multiple strategies in order"""
        payment_id = "test_multiple_strategies_123"

        # Create payment data with multiple potential indicators. Metadata carries a
        # resolvable donation target; the description JSON points at membership. The
        # resolver must prefer metadata (strategy 1) over the description fallback.
        payment_data = self._create_mock_payment_data(
            payment_id=payment_id,
            metadata={"payment_type": "donation", "donation_id": self.test_donation.name},
            description='{"type": "membership", "member_id": "%s"}' % self.test_member.name,
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        # Should prioritize metadata over description
        self.assertIsNotNone(context)
        self.assertEqual(context.payment_type, "donation")  # From metadata, not description
        self.assertEqual(context.target_name, self.test_donation.name)

    def test_resolve_context_nonexistent_target(self):
        """A donation_id that doesn't exist in the DB must not be trusted blindly:
        _resolve_from_metadata() calls frappe.db.exists() before returning a context,
        so a dangling reference is correctly rejected by strategy 1 (not a bogus
        PaymentContext). Control then falls to strategy 3 (no Donation match) and
        strategy 4 (no customer_id), landing cleanly on None."""
        payment_id = "test_nonexistent_123"

        payment_data = self._create_mock_payment_data(
            payment_id=payment_id,
            metadata={
                "payment_type": "donation",
                "donation_id": "NON-EXISTENT-DONATION",
                "record_type": "Donation",
            },
        )

        context = self.resolver.resolve_context(payment_id, payment_data)

        self.assertIsNone(context)

    def test_document_lookup_resolves_donation_by_payment_id(self):
        """Strategy 3 (_resolve_from_document_lookup) resolves a real Donation by its
        payment_id. Called directly (not via resolve_context) so the assertion pins
        strategy 3 itself, not an upstream strategy."""
        context = self.resolver._resolve_from_document_lookup("test_context_payment_123")
        self.assertIsNotNone(context)
        self.assertEqual(context.target_doctype, "Donation")
        self.assertEqual(context.target_name, self.test_donation.name)

    def test_document_lookup_no_crash_on_unknown_payment_id(self):
        """Regression guard: _resolve_from_document_lookup must return None WITHOUT
        raising for an unresolvable payment_id. Previously it also queried a
        `payment_id` column on Member (which does not exist -> OperationalError);
        resolve_context()'s outer `except` masked that crash and made Strategy 4
        unreachable. Calling the method DIRECTLY here exposes any such regression:
        re-introducing the Member.payment_id lookup makes this raise instead of
        returning None. See backlog-dead-code.md."""
        result = self.resolver._resolve_from_document_lookup("no_such_payment_id_xyz")
        self.assertIsNone(result)

    def _create_mock_payment_data(self, payment_id, metadata=None, description=None, subscription_id=None):
        """
        Helper to create realistic payment data structure.
        Mimics actual Mollie payment object structure.
        """

        class MockPayment:
            def __init__(self):
                self.id = payment_id
                self.amount = {"value": "50.00", "currency": "EUR"}
                self.status = "paid"
                self.method = "creditcard"
                self.metadata = metadata or {}
                self.description = description or "Test payment"
                self.subscription_id = subscription_id
                self.customer_id = None
                self.mandate_id = None
                self.created_at = frappe.utils.now_datetime()

        return MockPayment()


if __name__ == "__main__":
    unittest.main()
