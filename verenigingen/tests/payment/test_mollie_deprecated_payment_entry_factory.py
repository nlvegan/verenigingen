"""
Tests for the deprecated back-compat shim ``services/payment_entry_factory.py``.

This module is SUPERSEDED by ``services/shared/payment_entry_factory.py`` but is
NOT dead: ``services/payment_processors.py`` still imports and instantiates the
``PaymentEntryFactory`` defined here (a deprecated subclass of the shared one).

These tests verify the shim's live contract:
- The deprecated PaymentEntryFactory subclasses the shared implementation and
  inherits its real behaviour (validation extraction).
- Instantiating it emits a DeprecationWarning (so callers are nudged).
- get_appropriate_cost_center_for_context delegates to the shared resolver and
  warns.

The dead ``_LegacyPaymentEntryFactory`` class in the same file is explicitly
archived ("do not use") and is intentionally NOT exercised.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_deprecated_payment_entry_factory
"""

import warnings
from decimal import Decimal

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_entry_factory import (
    PaymentEntryFactory as DeprecatedFactory,
)
from verenigingen.verenigingen_payments.mollie.services.shared.payment_entry_factory import (
    PaymentEntryFactory as SharedFactory,
)


class TestDeprecatedPaymentEntryFactoryShim(EnhancedTestCase):
    def test_is_subclass_of_shared(self):
        self.assertTrue(issubclass(DeprecatedFactory, SharedFactory))

    def test_instantiation_warns_deprecation(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            DeprecatedFactory()
        messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        self.assertTrue(
            any("deprecated" in m.lower() for m in messages),
            f"Expected a DeprecationWarning, got: {messages}",
        )

    def test_inherits_real_validation(self):
        # The shim inherits the shared validation/extraction logic.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            factory = DeprecatedFactory()
        pid, amount = factory._validate_and_extract_mollie_data(
            {"payment_id": "tr_shim", "amount": "12.34"}
        )
        self.assertEqual(pid, "tr_shim")
        self.assertEqual(amount, Decimal("12.34"))


class TestDeprecatedCostCenterWrapper(EnhancedTestCase):
    def test_cost_center_wrapper_delegates_and_warns(self):
        import frappe

        from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import (
            PaymentContext,
        )
        from verenigingen.verenigingen_payments.mollie.services.payment_entry_factory import (
            get_appropriate_cost_center_for_context,
        )

        ctx = PaymentContext("membership", "Member", "M-1")
        company = frappe.get_single("Verenigingen Settings").company

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = get_appropriate_cost_center_for_context(ctx, company)

        messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
        self.assertTrue(any("deprecated" in m.lower() for m in messages))
        # Result is whatever the shared resolver returns (cost center name or None);
        # we only assert it does not raise and returns the resolver's value type.
        self.assertTrue(result is None or isinstance(result, str))
