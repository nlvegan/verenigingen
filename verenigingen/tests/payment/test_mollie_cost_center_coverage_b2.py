"""
Real-DB coverage for cost-center resolution in payment_webhook.py.

Target: verenigingen/verenigingen_payments/mollie/api/payment_webhook.py
        -> get_appropriate_cost_center()

get_appropriate_cost_center is a pure DB-lookup function (no Mollie HTTP, no
external boundary): it inspects a Donation document's donation_purpose_type /
chapter_reference and resolves a Cost Center for a given company via
frappe.db.get_value. We exercise its branches against REAL Cost Center rows on
the EUR test company (which ships a non-group "Main" cost center) plus a
chapter-named cost center we create in a helper.

GAP-FILL: this DB-lookup function is not exercised by the existing
test_mollie_payment_webhook_helpers.py (which only covers the pure-Python
SimpleNamespace helpers).
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.mollie.api import payment_webhook as pw


class TestGetAppropriateCostCenter(EnhancedTestCase):
    """get_appropriate_cost_center branch coverage against real Cost Centers."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        frappe.db.commit()

    def _ensure_chapter_cost_center(self, chapter_token):
        """Create (idempotently) a non-group cost center whose name contains the
        chapter token so the chapter LIKE branch can resolve it."""
        cc_name = f"Chapter {chapter_token} CC"
        existing = frappe.db.get_value(
            "Cost Center",
            {"company": self._company, "cost_center_name": cc_name, "is_group": 0},
            "name",
        )
        if existing:
            return existing
        parent = frappe.db.get_value(
            "Cost Center", {"company": self._company, "is_group": 1}, "name"
        )
        cc = frappe.new_doc("Cost Center")
        cc.cost_center_name = cc_name
        cc.company = self._company
        cc.parent_cost_center = parent
        cc.is_group = 0
        cc.insert(ignore_permissions=True)
        frappe.db.commit()
        return cc.name

    def test_no_donation_returns_default_cost_center(self):
        """donation=None -> falls straight to the default non-group cost center."""
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(None, self._company)
        # Default = first non-group cost center for the company.
        expected = frappe.db.get_value(
            "Cost Center", {"company": self._company, "is_group": 0}, "name"
        )
        self.assertEqual(cc, expected)
        self.assertTrue(cc)

    def test_general_fund_resolves_named_general_cost_center(self):
        """A non-Chapter purpose hits the General/Main/Operations name filter.

        The EUR test company ships a 'Main' cost center which is in the allowed
        name list, so this branch must return it.
        """
        donation = SimpleNamespace(donation_purpose_type="General")
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(donation, self._company)
        main_cc = frappe.db.get_value(
            "Cost Center",
            {
                "company": self._company,
                "is_group": 0,
                "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
            },
            "name",
        )
        self.assertTrue(main_cc, "EUR test company should have a Main cost center")
        self.assertEqual(cc, main_cc)

    def test_chapter_purpose_resolves_chapter_specific_cost_center(self):
        """Chapter purpose + chapter_reference matching a cost-center name LIKE
        returns the chapter-specific cost center (not the general one)."""
        token = frappe.generate_hash(length=6)
        chapter_cc = self._ensure_chapter_cost_center(token)
        donation = SimpleNamespace(
            donation_purpose_type="Chapter", chapter_reference=token
        )
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(donation, self._company)
        self.assertEqual(cc, chapter_cc)

    def test_chapter_purpose_without_matching_cc_falls_back_to_general(self):
        """Chapter purpose whose reference matches no cost center falls through
        to the general/default resolution rather than returning None."""
        donation = SimpleNamespace(
            donation_purpose_type="Chapter",
            chapter_reference=f"NoSuchChapter{frappe.generate_hash(length=8)}",
        )
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(donation, self._company)
        # Should resolve to general/main (or default), never None.
        self.assertTrue(cc)
        general_or_default = frappe.db.get_value(
            "Cost Center",
            {
                "company": self._company,
                "is_group": 0,
                "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
            },
            "name",
        ) or frappe.db.get_value(
            "Cost Center", {"company": self._company, "is_group": 0}, "name"
        )
        self.assertEqual(cc, general_or_default)

    def _general_or_default_cc(self):
        return frappe.db.get_value(
            "Cost Center",
            {
                "company": self._company,
                "is_group": 0,
                "cost_center_name": ["in", ["General", "Main", "General Fund", "Operations"]],
            },
            "name",
        ) or frappe.db.get_value("Cost Center", {"company": self._company, "is_group": 0}, "name")

    def test_chapter_purpose_missing_chapter_reference_attr(self):
        """Chapter purpose but the donation object lacks chapter_reference attr.

        get_appropriate_cost_center guards with hasattr; absence must not raise
        and should fall through to general resolution.
        """
        donation = SimpleNamespace(donation_purpose_type="Chapter")
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(donation, self._company)
        self.assertEqual(cc, self._general_or_default_cc())

    def test_unknown_purpose_type_uses_general_branch(self):
        """An unrecognized purpose type (not Chapter) still resolves via the
        general/default branch."""
        donation = SimpleNamespace(donation_purpose_type="Mystery")
        with self.assertNoErrorLog():
            cc = pw.get_appropriate_cost_center(donation, self._company)
        self.assertEqual(cc, self._general_or_default_cc())
