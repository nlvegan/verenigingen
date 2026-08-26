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
    _OWNED_GL_BANK_ACCOUNT_NAME,
    _bank_account_parent,
    _unusable_reasons,
    ensure_default_gl_bank_account,
    get_eur_bank_account,
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


class TestOwnedGlBankAccount(FrappeTestCase):
    """The GL bank account the payment suites share must be OWNED, not borrowed.

    ``ensure_default_gl_bank_account`` commits its result into
    ``Company.default_bank_account``, which five production readers consult -- the
    Mollie webhook, the Mollie dues processor, ``payment_entry_factory``,
    ``unified_payment_entry_creator`` and the Ponto payment-entry service. Resolving
    it by recency therefore does not merely pick an odd row in a test; it writes an
    arbitrary row into shared master data.

    Measured on ``test_site_1``..``test_site_5`` before this was owned: 3 / 4 / 2 / 1
    / 2 Bank-type leaf accounts on the test company, and the recency resolve landed
    on a *gateway clearing* account on all five (``Ponto Clearing``, ``Triodos 1``,
    ``Mollie``, ``Mollie``, ``Triodos 1``). On two of the five that borrow had
    already been committed as the company default. See #581.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def test_the_gl_bank_account_is_owned_not_borrowed(self):
        """Plant a decoy a recency resolve would prefer; require the owned one anyway.

        Asserting only "some Bank-type account of my company came back" does NOT
        discriminate -- the borrow satisfies that too. The decoy is created inside
        this test, so it is unambiguously the newest Bank-type leaf and therefore
        exactly what ``get_value``'s ``creation DESC`` returns.

        ``default_bank_account`` is cleared first because otherwise the old code
        short-circuits on it and never reaches the decoy. That is not a contrived
        state: a fresh CI site has the field unset, and
        ``test_payment_webhook_db_helpers.test_returns_none_when_bank_account_missing``
        clears it mid-shard.
        """
        decoy = self._plant_decoy_bank_gl()
        # Clearing the stamp is a committed write to shared master data, so it
        # must be undone even if the call below raises -- otherwise the rest of
        # the shard sees an unstamped company.
        self.addCleanup(ensure_default_gl_bank_account, self.company)
        frappe.db.set_value("Company", self.company, "default_bank_account", None)
        frappe.db.commit()

        resolved = ensure_default_gl_bank_account(self.company)

        self.assertNotEqual(
            resolved,
            decoy,
            "resolved the most recently created Bank-type account -- still borrowing",
        )
        self.assertEqual(
            frappe.db.get_value("Account", resolved, "account_name"),
            _OWNED_GL_BANK_ACCOUNT_NAME,
            "the resolved account is not the one this module owns by name",
        )
        self.assertEqual(
            frappe.db.get_value("Company", self.company, "default_bank_account"),
            resolved,
            "the owned account was resolved but not stamped as the company default",
        )

    def test_the_owned_bank_account_doc_is_keyed_on_the_owned_gl_account(self):
        """``get_eur_bank_account`` must hang off the owned GL account, not a rival.

        The two payment suites that carried their own copies of this helper each
        created a *different* Bank Account (``BTR Test Company Account``,
        ``ReconCov Test Company Account``) against a *different* GL account, so
        which one a shard ended up using depended on class ordering.
        """
        bank_account = get_eur_bank_account(self.company)

        self.assertTrue(bank_account, "no Bank Account resolved")
        gl_account = frappe.db.get_value("Bank Account", bank_account, "account")
        self.assertEqual(
            frappe.db.get_value("Account", gl_account, "account_name"),
            _OWNED_GL_BANK_ACCOUNT_NAME,
        )
        self.assertEqual(
            frappe.db.get_value("Bank Account", bank_account, "company"), self.company
        )

    def test_new_bank_accounts_are_parented_under_the_bank_group(self):
        """The parent must be the is_group **Bank** account, not the newest Asset group.

        ``_unusable_reasons`` already guarantees an is_group Bank account exists and
        says why. The predicate this replaced asked for ``{"is_group": 1,
        "root_type": "Asset"}``; the test company has 12 such groups, so that query
        was ambiguous and ``creation DESC`` decided it -- landing on
        ``Temporary Accounts`` on all five measured sites.

        This asserts the property rather than "not Temporary Accounts": on a fresh
        CI site the chart of accounts is built in one transaction, so which Asset
        group is newest is not something to pin. The final assertion is the control
        -- without more than one Asset group the old predicate was never ambiguous
        here, and this test would be passing for the wrong reason.
        """
        parent = _bank_account_parent(self.company)

        self.assertTrue(parent, "no is_group Bank account to parent under")
        self.assertEqual(frappe.db.get_value("Account", parent, "account_type"), "Bank")
        self.assertEqual(frappe.db.get_value("Account", parent, "is_group"), 1)
        self.assertGreater(
            frappe.db.count(
                "Account", {"company": self.company, "is_group": 1, "root_type": "Asset"}
            ),
            1,
            "only one Asset group exists, so the old predicate was not ambiguous here",
        )

    # -- helpers ---------------------------------------------------------------

    def _plant_decoy_bank_gl(self):
        """A Bank-type leaf account of the SAME company, newer than the owned one.

        Same company deliberately: a cross-company decoy is filtered out by the
        company clause both the old and the new code carry, so it could not tell
        them apart.
        """
        name = "TEST-581-Decoy-Bank"
        existing = frappe.db.get_value(
            "Account", {"company": self.company, "account_name": name, "is_group": 0}, "name"
        )
        if existing:
            frappe.delete_doc("Account", existing, force=True, ignore_permissions=True)
            frappe.db.commit()

        account = frappe.new_doc("Account")
        account.account_name = name
        account.company = self.company
        account.account_type = "Bank"
        account.parent_account = _bank_account_parent(self.company)
        account.account_currency = "EUR"
        # No ignore_permissions: tests run as Administrator, and the enforcer is
        # right that a test bypassing permissions proves less than one that does not.
        account.insert()
        frappe.db.commit()
        self.addCleanup(self._delete_decoy, account.name)
        return account.name

    def _delete_decoy(self, name):
        """``ensure_default_gl_bank_account`` commits, so the decoy outlives the rollback."""
        if frappe.db.exists("Account", name):
            frappe.delete_doc("Account", name, force=True, ignore_permissions=True)
            frappe.db.commit()
