"""Guard tests for the EUR test-company resolver.

``get_eur_test_company`` backs 52 test modules. It used to fall back to "the
first EUR company whose Fiscal Year covers today", which silently borrowed the
deliberately Chart-of-Accounts-less companies that two e_boekhouden modules
build (``EBH Migration Test Co``, ``EBH Account Migration Test Co``). On CI run
31168194632 that produced 101 failures across two shards -- and only after the
test shards were rebalanced by measured runtime, because that reordering was
what first put an e_boekhouden module ahead of the SEPA/payment modules.

These tests pin the two properties that prevent a recurrence:
  1. a company with no Chart of Accounts is REPORTED unusable, and
  2. the resolver builds its own company rather than borrowing one.

Base class note: plain ``FrappeTestCase``, deliberately, matching
``test_ponto_bank_account_creator``. ``EnhancedTestCase.setUp`` runs the
once-per-session seeding block (fiscal years, default company, fixture
validation), which is exactly the shared state these tests are trying to reason
about -- and none of the member/volunteer factories it provides are needed here.
The test-quality enforcer warns about this; the warning is expected.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.support.test_sepa_test_company
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.support import sepa_test_company
from verenigingen.tests.support.sepa_test_company import (
    _unusable_reasons,
    get_eur_test_company,
)

# Mirrors test_e_boekhouden_migration.setUpClass -- a EUR company with an EMPTY
# Chart of Accounts. Named distinctly so this module never races the real thing.
_COA_LESS_COMPANY = "TEST-CoA-Less-Guard-Co"
_COA_LESS_ABBR = "TCLGC"


def _create_coa_less_eur_company():
    """Get-or-create a EUR company with NO accounts, carrying a current Fiscal Year.

    The Fiscal Year matters: it is what made such a company pass the old
    currency-and-fiscal-year-only check. Without it these tests would pass for
    the wrong reason.
    """
    if not frappe.db.exists("Company", _COA_LESS_COMPANY):
        frappe.local.flags.ignore_chart_of_accounts = True
        try:
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": _COA_LESS_COMPANY,
                    "abbr": _COA_LESS_ABBR,
                    "default_currency": "EUR",
                    "country": "Netherlands",
                }
            )
            company.flags.ignore_permissions = True
            company.insert(ignore_permissions=True)
        finally:
            frappe.local.flags.ignore_chart_of_accounts = False

    from verenigingen.e_boekhouden.utils.consolidated.date_utils import (
        ensure_fiscal_year_exists,
    )

    ensure_fiscal_year_exists(frappe.utils.today(), _COA_LESS_COMPANY)
    frappe.db.commit()
    return _COA_LESS_COMPANY


class TestEurTestCompanyResolver(FrappeTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.coa_less = _create_coa_less_eur_company()

    def test_chart_of_accounts_less_company_is_reported_unusable(self):
        """The check the old borrow lacked: no CoA means unusable, with reasons."""
        reasons = _unusable_reasons(self.coa_less)

        self.assertTrue(reasons, f"{self.coa_less} has no accounts and must be rejected")
        joined = "; ".join(reasons)
        # Each of these maps to a distinct CI failure signature.
        self.assertIn("default_income_account is not set", joined)
        self.assertIn("default_receivable_account is not set", joined)
        self.assertIn("Income account", joined)
        self.assertIn("Bank account", joined)

    def test_currency_and_fiscal_year_alone_would_not_have_caught_it(self):
        """Pins WHY the old predicate passed this company, so the fix is not weakened.

        If someone reduces the predicate back to currency + fiscal year, this test
        documents that the company still satisfies both and would sail through.
        """
        from erpnext.accounts.utils import get_fiscal_year

        self.assertEqual(
            frappe.db.get_value("Company", self.coa_less, "default_currency"), "EUR"
        )
        # Does not raise -> the fiscal-year half of the old check passed.
        get_fiscal_year(date=frappe.utils.today(), company=self.coa_less, as_dict=True)

    def test_resolved_company_is_usable(self):
        """Whatever the resolver hands back must be able to back a Sales Invoice."""
        resolved = get_eur_test_company()

        self.assertEqual(_unusable_reasons(resolved), [])
        self.assertNotEqual(resolved, self.coa_less)

    def test_resolver_builds_its_own_company_rather_than_borrowing(self):
        """The actual regression.

        Point the resolver at a company that does not exist yet, so its preferred
        short-circuit cannot fire and it must choose between borrowing the
        CoA-less company that is sitting right there and building its own. The old
        borrow loop returned the CoA-less one; this asserts it builds.
        """
        guard_company = "TEST-SEPA-Resolver-Guard-Co"
        self.addCleanup(self._delete_company, guard_company)

        with self.patch_preferred_company(guard_company, "TSRGC"):
            resolved = get_eur_test_company()

        self.assertEqual(
            resolved,
            guard_company,
            f"resolver returned {resolved!r} -- it borrowed another test's company "
            "instead of building its own",
        )
        self.assertEqual(_unusable_reasons(guard_company), [])

    # -- helpers ---------------------------------------------------------------

    def patch_preferred_company(self, name, abbr):
        """Point the resolver at a company that does not exist yet.

        The abbreviation must be patched alongside the name -- Company rejects an
        abbreviation another company already holds, and the real one owns 'TPIC'.
        """
        from unittest.mock import patch

        return patch.multiple(
            sepa_test_company,
            _PREFERRED_EUR_COMPANY=name,
            _PREFERRED_EUR_COMPANY_ABBR=abbr,
        )

    def _delete_company(self, name):
        """Remove the company the guard test built.

        ``_create_eur_test_company`` commits, so this cannot be left to the test
        framework's rollback.
        """
        if not frappe.db.exists("Company", name):
            return
        frappe.delete_doc("Company", name, force=True, ignore_permissions=True)
        frappe.db.commit()
