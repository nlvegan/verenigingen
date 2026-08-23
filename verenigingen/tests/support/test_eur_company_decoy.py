"""The control for ``eur_company_decoy``: prove the decoy actually wins the buggy query.

Every pin in this change asserts "the resolved company is the owned one, even with a newer
EUR company present". If the decoy did not in fact win
``get_value("Company", {"default_currency": "EUR"}, "name")``, all of those pins would pass
vacuously and would keep passing after the fix was reverted. A check without a control
proves nothing, so this file is the control.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.eur_company_decoy import newest_eur_company, scan_by_currency
from verenigingen.tests.support.sepa_test_company import get_eur_test_company


class TestEURCompanyDecoy(EnhancedTestCase):
    def test_the_decoy_wins_the_currency_scan(self):
        """Without this, every pin built on the decoy could pass for the wrong reason."""
        before = scan_by_currency()
        with newest_eur_company() as decoy:
            self.assertEqual(
                scan_by_currency(),
                decoy,
                "the decoy is not the newest EUR company, so it does not discriminate",
            )
        self.assertEqual(scan_by_currency(), before, "the decoy outlived its context manager")

    def test_the_owned_helper_ignores_the_decoy(self):
        """``get_eur_test_company`` resolves by NAME, so a newer EUR company cannot win."""
        with newest_eur_company():
            self.assertEqual(get_eur_test_company(), "TEST-Payment-Integration-Company")

    def test_the_decoy_leaves_no_row_behind(self):
        with newest_eur_company() as decoy:
            pass
        self.assertFalse(
            frappe.db.sql("SELECT 1 FROM `tabCompany` WHERE `name` = %s", decoy),
            "decoy row survived",
        )
