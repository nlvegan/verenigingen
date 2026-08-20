"""
Tests for verenigingen/e_boekhouden/utils/cleanup_utils.py

These exercise the cleanup functions along SAFE, deterministic paths that do not
require a live eBoekhouden connection and do not destroy shared fixture data:

  - cleanup_chart_of_accounts: safe-mode (skips GL-linked / system / group accts),
    and successfully deleting a fresh leaf account flagged as eBoekhouden-imported.
  - cleanup_orphaned_gl_entries: seeds an orphan GL Entry and asserts it is deleted.
  - cleanup_cancelled_payment_gl_entries: seeds a cancelled PE + GL Entry, asserts deletion.
  - _cleanup_orphaned_bank_transactions: seeds an EB- orphan Bank Transaction, asserts deletion.
  - get_cleanup_dependencies: returns the expected count dict + exact seeded GL count.
  - cleanup_payment_entries / cleanup_sales_invoices / cleanup_purchase_invoices:
    helper functions on empty + missing-name input.

Tests run as Administrator (EnhancedTestCase), which holds Account delete perms.

Run with:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_cleanup_utils
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.cleanup_utils import (
    _cleanup_linked_bank_transactions,
    _cleanup_orphaned_bank_transactions,
    cleanup_cancelled_payment_gl_entries,
    cleanup_chart_of_accounts,
    cleanup_orphaned_gl_entries,
    cleanup_payment_entries,
    cleanup_purchase_invoices,
    cleanup_sales_invoices,
    get_cleanup_dependencies,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _CleanupTestBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_eur_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_eur_company(cls):
        name = "TEST EBkh Cleanup Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECL"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        return name

    def _persist_eboekhouden_account(self, acct_name, grootboek="99999"):
        """Create a fresh leaf account flagged as imported from eBoekhouden."""
        parent = frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Expense", "is_group": 1},
            "name",
        )
        full = f"{acct_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            return full
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = "Expense"
        doc.is_group = 0
        if doc.meta.has_field("eboekhouden_grootboek_nummer"):
            doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert(ignore_permissions=True)
        return doc.name

    @classmethod
    def _persist_isolated_company(cls):
        """A separate, freshly-created company with zero migrated docs.

        Used so dependency / orphan counts are deterministic and not polluted by
        whatever else lives in the shared test DB.
        """
        name = "TEST EBkh Cleanup Iso Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECI"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return name

    def _seed_gl_entry(self, company, voucher_no, voucher_type="Journal Entry"):
        """Directly insert a GL Entry row for ``company``.

        GL Entries are normally produced by submitting a parent document, but a
        direct db_insert is sufficient to exercise the count/delete logic under
        test without standing up the full submit (+ fiscal year) machinery.
        ``voucher_no`` points at a non-existent voucher so the row is "orphaned".
        """
        account = frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
        )
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        ge = frappe.new_doc("GL Entry")
        ge.posting_date = frappe.utils.today()
        ge.account = account
        ge.company = company
        ge.debit = 5
        ge.credit = 0
        ge.cost_center = cost_center
        ge.voucher_type = voucher_type
        ge.voucher_no = voucher_no
        ge.name = self.unique_seed_name("GLE")
        ge.db_insert()
        return ge.name


class TestCleanupChartOfAccounts(_CleanupTestBase):
    def test_string_boolean_args_parsed(self):
        # delete_all_accounts="false" / force_delete="0" must be parsed, not crash.
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts="false", force_delete="0")
        self.assertTrue(result["success"])
        self.assertIn("results", result)
        # "false" must parse to falsy: delete_all_accounts=False scopes to eBoekhouden
        # accounts only, and this fresh company has none -> nothing deleted. If the
        # string were mis-parsed as truthy it would attempt to delete the default CoA.
        self.assertEqual(result["results"]["accounts_deleted"], 0)

    def test_deletes_fresh_eboekhouden_leaf_account(self):
        if not frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")
        acct = self._persist_eboekhouden_account("EBkh Cleanup Leaf")
        self.assertTrue(frappe.db.exists("Account", acct))

        # Safe mode, only eBoekhouden accounts. Fresh leaf has no GL entries,
        # is not a system account, and has no children -> should be deleted.
        result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)
        self.assertTrue(result["success"])
        self.assertFalse(frappe.db.exists("Account", acct))
        self.assertGreaterEqual(result["results"]["accounts_deleted"], 1)

    def test_no_eboekhouden_accounts_is_noop(self):
        # Self-contained: do NOT rely on another test method having run first.
        # Delete any flagged leaf accounts for this company up front, assert none
        # remain, THEN assert the cleanup is a genuine no-op (zero deletions).
        if frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            flagged = frappe.get_all(
                "Account",
                filters={"company": self.company, "eboekhouden_grootboek_nummer": ["!=", ""]},
                pluck="name",
            )
            for acct in flagged:
                frappe.delete_doc("Account", acct, force=True, ignore_permissions=True)
            frappe.db.commit()
            remaining = frappe.db.count(
                "Account",
                {"company": self.company, "eboekhouden_grootboek_nummer": ["!=", ""]},
            )
            self.assertEqual(remaining, 0, "Expected no flagged accounts before the no-op cleanup")

        result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)
        self.assertTrue(result["success"])
        self.assertEqual(result["results"]["accounts_deleted"], 0)


class TestCleanupOrphanedGLEntries(_CleanupTestBase):
    def test_deletes_seeded_orphan_gl_entry(self):
        # Seed a GL Entry whose voucher does not exist -> it is orphaned and must
        # be deleted. (cleanup_orphaned_gl_entries is global, so other orphans in
        # the shared DB may also be removed; we assert >= 1 deleted AND that OUR
        # specific seeded row is gone.)
        company = self._persist_isolated_company()
        orphan = self._seed_gl_entry(company, voucher_no="EBKH-NOEXIST-VOUCHER-A")
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("GL Entry", orphan))

        result = cleanup_orphaned_gl_entries()
        self.assertTrue(result["success"])
        self.assertIn("deleted_entries", result)  # backward-compat aggregate key
        self.assertGreaterEqual(result["deleted_gl_entries"], 1)
        self.assertFalse(frappe.db.exists("GL Entry", orphan))


class TestCleanupCancelledPaymentGLEntries(_CleanupTestBase):
    def _seed_cancelled_pe_with_gl(self, company):
        """Direct-insert a cancelled (docstatus=2) Payment Entry and a GL Entry
        referencing it, matching the function's JOIN on pe.docstatus = 2."""
        account = frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
        )
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = company
        pe.posting_date = frappe.utils.today()
        pe.paid_amount = 1
        pe.received_amount = 1
        pe.paid_to = account
        pe.paid_from = account
        pe.docstatus = 2  # cancelled
        pe.name = self.unique_seed_name("PE")
        pe.db_insert()
        ge = frappe.new_doc("GL Entry")
        ge.posting_date = frappe.utils.today()
        ge.account = account
        ge.company = company
        ge.debit = 1
        ge.credit = 0
        ge.cost_center = cost_center
        ge.voucher_type = "Payment Entry"
        ge.voucher_no = pe.name
        ge.name = self.unique_seed_name("GLE")
        ge.db_insert()
        frappe.db.commit()
        return pe.name, ge.name

    def test_deletes_gl_for_cancelled_payment(self):
        # Seed a cancelled PE + its GL Entry; the cleanup must delete that GL row.
        company = self._persist_isolated_company()
        pe_name, gl_name = self._seed_cancelled_pe_with_gl(company)
        self.assertTrue(frappe.db.exists("GL Entry", gl_name))

        result = cleanup_cancelled_payment_gl_entries()
        self.assertTrue(result["success"])
        self.assertIn("message", result)
        self.assertFalse(frappe.db.exists("GL Entry", gl_name))
        # Cleanup of cancelled-payment data; remove the seeded PE.
        frappe.delete_doc("Payment Entry", pe_name, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestCleanupOrphanedBankTransactions(_CleanupTestBase):
    def test_deletes_seeded_orphan_bank_transaction(self):
        # A Bank Transaction with EB- reference and no linked payment is orphaned
        # and must be deleted. (Global op; assert >= 1 deleted AND our row gone.)
        company = self._persist_isolated_company()
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.reference_number = "EB-CLEANUP-TEST-ORPHAN"
        bt.deposit = 1
        bt.company = company
        bt.name = self.unique_seed_name("BT")
        bt.db_insert()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Bank Transaction", bt.name))

        result = _cleanup_orphaned_bank_transactions()
        self.assertIn("deleted", result)
        self.assertIn("errors", result)
        self.assertGreaterEqual(result["deleted"], 1)
        self.assertFalse(frappe.db.exists("Bank Transaction", bt.name))


class TestGetCleanupDependencies(_CleanupTestBase):
    def test_returns_count_dict(self):
        deps = get_cleanup_dependencies(self.company)
        expected_keys = {"gl_entries", "invoices", "purchases", "payments", "journals"}
        self.assertEqual(set(deps.keys()), expected_keys)
        for v in deps.values():
            self.assertIsInstance(v, int)
            self.assertGreaterEqual(v, 0)

    def test_counts_seeded_gl_entries_exactly(self):
        # On a fresh isolated company every count starts at 0; seeding two GL
        # Entries must move gl_entries to exactly 2 (the other counts stay 0).
        company = self._persist_isolated_company()
        # Clear any GL Entries left by sibling tests on this shared isolated company.
        frappe.db.delete("GL Entry", {"company": company})
        frappe.db.commit()
        before = get_cleanup_dependencies(company)
        self.assertEqual(before["gl_entries"], 0)

        names = [
            self._seed_gl_entry(company, voucher_no="EBKH-DEPS-COUNT-1"),
            self._seed_gl_entry(company, voucher_no="EBKH-DEPS-COUNT-2"),
        ]
        frappe.db.commit()
        try:
            after = get_cleanup_dependencies(company)
            self.assertEqual(after["gl_entries"], 2)
            # Submitted-doc counts unaffected by raw GL seeding.
            self.assertEqual(after["invoices"], 0)
            self.assertEqual(after["purchases"], 0)
            self.assertEqual(after["payments"], 0)
            self.assertEqual(after["journals"], 0)
        finally:
            for n in names:
                if frappe.db.exists("GL Entry", n):
                    frappe.delete_doc("GL Entry", n, force=True, ignore_permissions=True)
            frappe.db.commit()


class TestCleanupListHelpers(_CleanupTestBase):
    def test_cleanup_payment_entries_empty(self):
        result = cleanup_payment_entries([], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["errors"], [])

    def test_cleanup_sales_invoices_empty(self):
        result = cleanup_sales_invoices([], "test")
        self.assertEqual(result["deleted"], 0)

    def test_cleanup_purchase_invoices_empty(self):
        result = cleanup_purchase_invoices([], "test")
        self.assertEqual(result["deleted"], 0)

    def test_cleanup_payment_entries_missing_name_collects_error(self):
        # A non-existent PE name -> get_doc raises -> error captured, no crash.
        result = cleanup_payment_entries(["NO-SUCH-PE-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_cleanup_sales_invoices_missing_name_collects_error(self):
        result = cleanup_sales_invoices(["NO-SUCH-SI-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)

    def test_cleanup_purchase_invoices_missing_name_collects_error(self):
        result = cleanup_purchase_invoices(["NO-SUCH-PI-XYZ"], "test")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["errors"]), 1)


class TestCleanupChartOfAccountsForceMode(_CleanupTestBase):
    def _insert_eboekhouden_leaf(self, company, acct_name, grootboek):
        """Create a fresh eBoekhouden-flagged leaf Expense account on ``company``."""
        abbr = frappe.db.get_value("Company", company, "abbr")
        full = f"{acct_name} - {abbr}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account", {"company": company, "root_type": "Expense", "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = company
        doc.parent_account = parent
        doc.root_type = "Expense"
        doc.is_group = 0
        doc.eboekhouden_grootboek_nummer = grootboek
        doc.insert(ignore_permissions=True)
        return doc.name

    def _insert_plain_company(self, name, abbr):
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = abbr
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return name

    def _seed_account_gl(self, company, account):
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        ge = frappe.new_doc("GL Entry")
        ge.posting_date = frappe.utils.today()
        ge.account = account
        ge.company = company
        ge.debit = 3
        ge.credit = 0
        ge.cost_center = cost_center
        ge.voucher_type = "Journal Entry"
        ge.voucher_no = "EBKH-CLEANUP-FORCE-VOUCHER"
        ge.name = self.unique_seed_name("GLE")
        ge.db_insert()
        return ge.name

    def test_force_delete_removes_account_and_its_gl_entries(self):
        # An eBoekhouden leaf with a GL entry is SKIPPED in safe mode but FORCE
        # mode deletes its GL entries first and then force-deletes the account.
        if not frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")
        company = self._persist_isolated_company()
        full = self._insert_eboekhouden_leaf(company, "EBkh Force Leaf", "98877")
        gl_name = self._seed_account_gl(company, full)
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("GL Entry", gl_name))

        result = cleanup_chart_of_accounts(company, delete_all_accounts=0, force_delete=1)
        self.assertTrue(result["success"])
        self.assertFalse(frappe.db.exists("Account", full))
        self.assertFalse(frappe.db.exists("GL Entry", gl_name))
        self.assertGreaterEqual(result["results"]["accounts_deleted"], 1)

    def test_safe_mode_skips_account_with_gl_entries(self):
        # In SAFE mode, an eBoekhouden leaf with a GL entry must be preserved.
        if not frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")
        company = self._persist_isolated_company()
        full = self._insert_eboekhouden_leaf(company, "EBkh Safe GL Leaf", "98866")
        gl_name = self._seed_account_gl(company, full)
        frappe.db.commit()

        result = cleanup_chart_of_accounts(company, delete_all_accounts=0, force_delete=0)
        self.assertTrue(result["success"])
        # Account preserved because it carries transaction history.
        self.assertTrue(frappe.db.exists("Account", full))
        self.assertGreaterEqual(result["results"]["accounts_skipped"], 1)
        self.assertTrue(any("has GL entries" in e for e in result["results"]["errors"]))

        # Cleanup our seeded rows.
        frappe.db.delete("GL Entry", {"name": gl_name})
        frappe.delete_doc("Account", full, force=True, ignore_permissions=True)
        frappe.db.commit()

    def test_delete_all_skips_root_system_accounts(self):
        # delete_all=1 enumerates ALL accounts, including the "Asset"/"Income"/...
        # root group accounts which must be SKIPPED as system accounts.
        # Use a throwaway company so wiping its accounts doesn't disturb siblings.
        company = self._insert_plain_company("TEST EBkh Cleanup DelAll Co", "TECDA")
        result = cleanup_chart_of_accounts(company, delete_all_accounts=1, force_delete=0)
        self.assertTrue(result["success"])
        # Any account whose name is one of the five protected system names must be
        # flagged as a skipped system account (never deleted). The vanilla ERPNext
        # CoA exposes "Income" and "Equity" under those exact names.
        skipped_system = [e for e in result["results"]["errors"] if "System account" in e]
        self.assertTrue(skipped_system, msg=f"errors: {result['results']['errors'][:10]}")
        # Each protected-name account that exists must still exist after cleanup.
        for root_name in ("Income", "Equity"):
            self.assertTrue(
                frappe.db.exists(
                    "Account",
                    {"company": company, "account_name": root_name, "is_group": 1},
                ),
                msg=f"protected system account {root_name} was deleted",
            )

    def test_insufficient_permissions_raises_handled(self):
        # Run as a user WITHOUT Account delete permission -> the upfront permission
        # check throws, caught and returned as {"success": False}.
        with self.set_user("Guest"):
            result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)
        self.assertFalse(result["success"])
        self.assertIn("error", result)
        # The failure must specifically be the permission gate, not an unrelated crash.
        self.assertIn("ermission", result["error"])


class TestCleanupOrphanedReferences(_CleanupTestBase):
    def test_deletes_orphaned_payment_entry_reference(self):
        # Seed a Payment Entry Reference child row pointing at a non-existent Sales
        # Invoice -> cleanup_orphaned_gl_entries must remove it.
        company = self._persist_isolated_company()
        account = frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 0, "root_type": "Asset", "account_type": "Bank"},
            "name",
        ) or frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
        )
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = company
        pe.posting_date = frappe.utils.today()
        pe.paid_amount = 1
        pe.received_amount = 1
        pe.paid_to = account
        pe.paid_from = account
        pe.docstatus = 1
        pe.name = self.unique_seed_name("PE")
        pe.db_insert()
        per = frappe.new_doc("Payment Entry Reference")
        per.parent = pe.name
        per.parenttype = "Payment Entry"
        per.parentfield = "references"
        per.reference_doctype = "Sales Invoice"
        per.reference_name = "SINV-NOEXIST-EBKH-9999"
        per.allocated_amount = 1
        per.db_insert()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Payment Entry Reference", per.name))

        result = cleanup_orphaned_gl_entries()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["deleted_payment_references"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry Reference", per.name))

        # Cleanup the seeded PE.
        frappe.db.delete("Payment Entry", {"name": pe.name})
        frappe.db.commit()


class TestCleanupLinkedBankTransactions(_CleanupTestBase):
    def test_deletes_bank_transaction_linked_to_payment_entry(self):
        # Seed a Bank Transaction with a child Bank Transaction Payments row that
        # references a (non-existent) Payment Entry name, then assert the helper
        # finds + deletes the parent Bank Transaction.
        company = self._persist_isolated_company()
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.reference_number = "EB-LINKED-PE-TEST"
        bt.deposit = 1
        bt.company = company
        bt.name = self.unique_seed_name("BT")
        bt.db_insert()
        link = frappe.new_doc("Bank Transaction Payments")
        link.parent = bt.name
        link.parenttype = "Bank Transaction"
        link.parentfield = "payment_entries"
        link.payment_document = "Payment Entry"
        link.payment_entry = "PE-EBKH-LINK-TARGET"
        link.db_insert()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Bank Transaction", bt.name))

        result = _cleanup_linked_bank_transactions("PE-EBKH-LINK-TARGET")
        self.assertGreaterEqual(result["deleted"], 1)
        self.assertFalse(frappe.db.exists("Bank Transaction", bt.name))

    def test_no_links_returns_zero(self):
        result = _cleanup_linked_bank_transactions("PE-EBKH-NO-LINKS-AT-ALL")
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["errors"], [])


if __name__ == "__main__":
    unittest.main()
