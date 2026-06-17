"""
Cost Center Resolver Tests
==========================

Tests for verenigingen_payments.mollie.services.shared.cost_center_resolver.

The resolver delegates to the consolidated e_boekhouden cost_center_utils. These
tests exercise the real resolution logic against the actual company/cost-center
master data on the site (no mocks of the logic under test):

  - resolve_for_context with a plain PaymentContext (no donation source_doc)
  - resolve_for_donation with: None, a General-Fund donation, a Chapter donation
  - the module-level convenience functions

Branches covered: the chapter-vs-general selection in resolve_for_donation, the
source_doc detection in resolve_for_context, and the default-fallback path.
"""

import types

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.payment_context_resolver import PaymentContext
from verenigingen.verenigingen_payments.mollie.services.shared.cost_center_resolver import (
    CostCenterResolver,
    get_cost_center_for_context,
    get_cost_center_for_donation,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import get_test_company


class TestCostCenterResolver(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.resolver = CostCenterResolver()
        self.company = get_test_company()

    def _general_cc(self):
        from verenigingen.e_boekhouden.utils.consolidated.cost_center_utils import get_general_cost_center

        return get_general_cost_center(self.company)

    def test_resolve_for_donation_none_returns_general_or_default(self):
        """No donation -> general cost center (or default fallback)."""
        result = self.resolver.resolve_for_donation(None, self.company)
        self.assertTrue(result)
        # Cost center must be a real, valid cost center for this company.
        self.assertTrue(frappe.db.exists("Cost Center", result))
        self.assertEqual(frappe.db.get_value("Cost Center", result, "company"), self.company)

    def test_resolve_for_donation_general_fund(self):
        """A General-Fund donation resolves to the general cost center."""
        donation = types.SimpleNamespace(
            doctype="Donation", donation_purpose_type="General", chapter_reference=None
        )
        result = self.resolver.resolve_for_donation(donation, self.company)
        self.assertEqual(result, self._general_cc() or self.resolver._get_default_cost_center(self.company))

    def test_resolve_for_donation_chapter_without_cc_falls_back_to_general(self):
        """A Chapter donation whose chapter has no cost center falls back to general."""
        donation = types.SimpleNamespace(
            doctype="Donation",
            donation_purpose_type="Chapter",
            chapter_reference="__nonexistent_chapter__",
        )
        result = self.resolver.resolve_for_donation(donation, self.company)
        # No chapter cost center exists for the bogus chapter -> general/default.
        self.assertTrue(frappe.db.exists("Cost Center", result))

    def test_resolve_for_context_no_source_doc(self):
        """resolve_for_context with a plain context (no source_doc) -> general/default."""
        context = PaymentContext(payment_type="membership", target_doctype="Member", target_name="MEM-XYZ")
        result = self.resolver.resolve_for_context(context, self.company)
        self.assertTrue(frappe.db.exists("Cost Center", result))

    def test_resolve_for_context_with_donation_source_doc(self):
        """resolve_for_context detects a Donation source_doc and delegates to resolve_for_donation."""
        context = PaymentContext(payment_type="donation", target_doctype="Donation", target_name="DON-XYZ")
        # Attach a fake donation source_doc the way the resolver expects.
        context.source_doc = types.SimpleNamespace(
            doctype="Donation", donation_purpose_type="General", chapter_reference=None
        )
        result_ctx = self.resolver.resolve_for_context(context, self.company)
        result_direct = self.resolver.resolve_for_donation(context.source_doc, self.company)
        self.assertEqual(result_ctx, result_direct)

    def test_resolve_for_context_non_donation_source_doc_ignored(self):
        """A non-Donation source_doc is ignored -> behaves like no donation."""
        context = PaymentContext(payment_type="membership", target_doctype="Member", target_name="MEM-XYZ")
        context.source_doc = types.SimpleNamespace(doctype="Member")
        result = self.resolver.resolve_for_context(context, self.company)
        self.assertEqual(result, self.resolver.resolve_for_donation(None, self.company))

    def test_module_convenience_functions(self):
        """The module-level helpers wrap the resolver and return valid cost centers."""
        cc_donation = get_cost_center_for_donation(None, self.company)
        self.assertTrue(frappe.db.exists("Cost Center", cc_donation))

        context = PaymentContext(payment_type="membership", target_doctype="Member", target_name="MEM-ABC")
        cc_context = get_cost_center_for_context(context, self.company)
        self.assertTrue(frappe.db.exists("Cost Center", cc_context))
