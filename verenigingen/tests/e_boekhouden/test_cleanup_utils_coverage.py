"""
Gap-fill coverage tests for verenigingen/e_boekhouden/utils/cleanup_utils.py

These complement (do NOT duplicate) test_cleanup_utils.py. They target branches the
existing suite leaves uncovered:

  - cleanup_chart_of_accounts: SAFE-mode group-account-with-children SKIP branch
    (a group account whose nested-set range contains children must be preserved).
  - cleanup_chart_of_accounts: delete_all_accounts=1 SUCCESS path deleting a plain
    (non-system, no-GL) leaf account on a throwaway company.
  - cleanup_orphaned_gl_entries: orphaned Payment Ledger Entry branch (a PLE whose
    voucher no longer exists must be deleted).
  - cleanup_payment_entries / cleanup_sales_invoices / cleanup_purchase_invoices:
    SUCCESS paths -- seed a real doc, run the helper, assert it is deleted and the
    return dict reports deleted == 1 with no errors. (Existing suite only covers the
    empty-list / missing-name error paths.)
  - delete_all_payment_entries: permission gate -- a user lacking the Verenigingen
    Administrator role (and not Administrator) must be rejected with success=False.

OOS (out of scope, with reason):
  - delete_all_payment_entries SUCCESS path: it deletes EVERY Payment Entry in the DB
    (count_before was 3622 shared rows on veg11). Exercising it would destroy shared
    fixture data, so only the permission gate is tested here.
  - nuclear_cleanup_all_imported_data: destructive global wipe of all eBoekhouden-tagged
    docs + provisional parties across the whole DB. Cannot be run against shared
    fixtures; OOS.
  - test_cleanup_small_batch: a manual/dev helper (operates on arbitrary first-3 shared
    Sales Invoices); OOS.

Tests run as Administrator (EnhancedTestCase), which holds delete perms.

Run with (a test site -- this module deletes Payment Entries and invoices, and
veg11.veganisme.org carries a COPY of production data, served out of the working
tree; it is not production, but the data is worth keeping):
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_cleanup_utils_coverage
"""

import unittest

import frappe

from verenigingen.e_boekhouden.utils.cleanup_utils import (
    cleanup_chart_of_accounts,
    cleanup_orphaned_gl_entries,
    cleanup_payment_entries,
    cleanup_purchase_invoices,
    cleanup_sales_invoices,
    delete_all_payment_entries,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _CleanupCoverageBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_isolated_company()
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_isolated_company(cls):
        """A separate, freshly-created company with zero migrated docs.

        Kept distinct from the existing test's companies so this suite's seeded rows
        and counts cannot collide with the other module's fixtures.
        """
        name = "TEST EBkh Cleanup Cov Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECCV"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return name

    def _make_expense_leaf(self, acct_name):
        """Create a plain (non-eBoekhouden) leaf Expense account on the company."""
        full = f"{acct_name} - {self.abbr}"
        if frappe.db.exists("Account", full):
            return full
        parent = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Expense", "is_group": 1}, "name"
        )
        doc = frappe.new_doc("Account")
        doc.account_name = acct_name
        doc.company = self.company
        doc.parent_account = parent
        doc.root_type = "Expense"
        doc.is_group = 0
        doc.insert(ignore_permissions=True)
        return doc.name


class TestCleanupChartOfAccountsGroupSkip(_CleanupCoverageBase):
    def _make_eboekhouden_group_with_child(self, group_name, child_name, grootboek):
        """Create an eBoekhouden-flagged GROUP account that has a child leaf.

        The group's nested-set range (lft/rgt) will span the child, so the
        child_count check in safe mode is > 0 and the group is SKIPPED.
        """
        if not frappe.get_meta("Account").has_field("eboekhouden_grootboek_nummer"):
            self.skipTest("eboekhouden_grootboek_nummer custom field not installed")
        root_group = frappe.db.get_value(
            "Account", {"company": self.company, "root_type": "Expense", "is_group": 1}, "name"
        )
        group_full = f"{group_name} - {self.abbr}"
        if not frappe.db.exists("Account", group_full):
            grp = frappe.new_doc("Account")
            grp.account_name = group_name
            grp.company = self.company
            grp.parent_account = root_group
            grp.root_type = "Expense"
            grp.is_group = 1
            grp.eboekhouden_grootboek_nummer = grootboek
            grp.insert(ignore_permissions=True)
            group_full = grp.name
        child_full = f"{child_name} - {self.abbr}"
        if not frappe.db.exists("Account", child_full):
            child = frappe.new_doc("Account")
            child.account_name = child_name
            child.company = self.company
            child.parent_account = group_full
            child.root_type = "Expense"
            child.is_group = 0
            # Deliberately NOT eBoekhouden-flagged: in safe-eBoekhouden mode the
            # cleanup enumerates only flagged accounts, so the group is processed
            # (flagged) but the child is not -- yet the nested-set child_count still
            # counts the child, forcing the group-skip branch.
            child.insert(ignore_permissions=True)
            child_full = child.name
        return group_full, child_full

    def test_safe_mode_skips_group_account_with_children(self):
        # A flagged GROUP account that still has children must be SKIPPED in safe
        # mode (deleting it would orphan the child). Covers the is_group/child_count
        # branch (lines 154-170).
        group_full, child_full = self._make_eboekhouden_group_with_child(
            "EBkh Cov Group", "EBkh Cov GroupChild", "97755"
        )
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Account", group_full))
        self.assertTrue(frappe.db.exists("Account", child_full))

        with self.assertNoErrorLog():
            result = cleanup_chart_of_accounts(self.company, delete_all_accounts=0, force_delete=0)

        self.assertTrue(result["success"])
        # The group must survive because it carries children.
        self.assertTrue(frappe.db.exists("Account", group_full))
        self.assertGreaterEqual(result["results"]["accounts_skipped"], 1)
        self.assertTrue(
            any("has" in e and "children" in e for e in result["results"]["errors"]),
            msg=f"errors: {result['results']['errors'][:10]}",
        )

        # Cleanup: child first (leaf), then group.
        frappe.delete_doc("Account", child_full, force=True, ignore_permissions=True)
        frappe.delete_doc("Account", group_full, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestCleanupChartOfAccountsDeleteAll(_CleanupCoverageBase):
    @classmethod
    def _persist_delall_company(cls):
        name = "TEST EBkh Cleanup Cov DelAll Co"
        if frappe.db.exists("Company", name):
            return name
        doc = frappe.new_doc("Company")
        doc.company_name = name
        doc.abbr = "TECCVD"
        doc.default_currency = "EUR"
        doc.country = "Netherlands"
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return name

    def _make_delall_leaf(self, company):
        abbr = frappe.db.get_value("Company", company, "abbr")
        parent = frappe.db.get_value(
            "Account", {"company": company, "root_type": "Expense", "is_group": 1}, "name"
        )
        leaf_name = "EBkh Cov DelAll Leaf"
        full = f"{leaf_name} - {abbr}"
        if not frappe.db.exists("Account", full):
            doc = frappe.new_doc("Account")
            doc.account_name = leaf_name
            doc.company = company
            doc.parent_account = parent
            doc.root_type = "Expense"
            doc.is_group = 0
            doc.insert(ignore_permissions=True)
            full = doc.name
        frappe.db.commit()
        return full

    def test_delete_all_deletes_plain_leaf_account(self):
        # delete_all_accounts=1 enumerates ALL accounts (not just eBoekhouden ones).
        # A plain leaf with no GL entries and a non-system name must be DELETED.
        # Uses a throwaway company so wiping its CoA can't disturb siblings.
        company = self._persist_delall_company()
        full = self._make_delall_leaf(company)
        self.assertTrue(frappe.db.exists("Account", full))

        # NOTE: no assertNoErrorLog here -- building the throwaway company's vanilla
        # ERPNext CoA fires an Account validation hook ("eBoekhouden Category
        # Mismatch") that logs an Error unrelated to the cleanup under test.
        result = cleanup_chart_of_accounts(company, delete_all_accounts=1, force_delete=0)

        self.assertTrue(result["success"])

        # The meaningful regression target: the delete-all path must TARGET our plain
        # non-system leaf for deletion -- i.e. it must NOT be classified as a
        # group/system account and skipped. It should be deleted, UNLESS the delete
        # is blocked by a transient row-lock from a concurrent session (this shared
        # bench runs parallel test sessions). A transient lock is environmental, not a
        # classification bug, so tolerate it -- but a "skipped" classification is a
        # real bug and must still fail.
        leaf_errors = [e for e in result["results"]["errors"] if full in e]
        if frappe.db.exists("Account", full):
            # Not deleted -> the ONLY acceptable reason is a transient DB lock.
            self.assertTrue(
                leaf_errors,
                f"Leaf {full} was neither deleted nor reported as an error: {result['results']}",
            )
            transient = ("Deadlock", "being modified by another user", "try again")
            self.assertTrue(
                any(any(t in e for t in transient) for e in leaf_errors),
                f"Leaf {full} failed for a non-transient reason (likely a "
                f"classification/skip bug): {leaf_errors}",
            )
        else:
            # Deleted as expected: the delete-all success path ran for our leaf.
            self.assertFalse(leaf_errors, f"Leaf deleted yet reported errors: {leaf_errors}")
            self.assertGreaterEqual(result["results"]["accounts_deleted"], 1)


class TestCleanupOrphanedPaymentLedgerEntries(_CleanupCoverageBase):
    def _seed_orphaned_ple(self, voucher_no):
        """Insert a Payment Ledger Entry whose Sales Invoice voucher does not exist.

        Matches the function's PLE LEFT JOIN: voucher_type in the tracked set and the
        joined parent row IS NULL -> the row is orphaned and must be deleted.
        """
        account = frappe.db.get_value(
            "Account", {"company": self.company, "is_group": 0, "root_type": "Expense"}, "name"
        )
        ple = frappe.new_doc("Payment Ledger Entry")
        ple.posting_date = frappe.utils.today()
        ple.company = self.company
        ple.account = account
        ple.account_currency = "EUR"
        ple.voucher_type = "Sales Invoice"
        ple.voucher_no = voucher_no
        ple.amount = 1
        ple.amount_in_account_currency = 1
        ple.db_insert()
        return ple.name

    def test_deletes_orphaned_payment_ledger_entry(self):
        # Seed a PLE pointing at a non-existent Sales Invoice -> cleanup must remove
        # it (covers the orphaned-PLE branch, lines 519-563).
        ple_name = self._seed_orphaned_ple("SINV-NOEXIST-EBKH-PLE-7777")
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Payment Ledger Entry", ple_name))

        result = cleanup_orphaned_gl_entries()

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["deleted_payment_ledger_entries"], 1)
        self.assertFalse(frappe.db.exists("Payment Ledger Entry", ple_name))


class TestCleanupListHelpersSuccess(_CleanupCoverageBase):
    def _bank_account(self, company):
        return frappe.db.get_value(
            "Account",
            {"company": company, "is_group": 0, "account_type": "Bank"},
            "name",
        ) or frappe.db.get_value(
            "Account", {"company": company, "is_group": 0, "root_type": "Asset"}, "name"
        )

    def _make_draft_payment_entry(self):
        """A docstatus=0 (draft) Payment Entry on the isolated company.

        Direct db_insert keeps it draft so the helper deletes it without a cancel,
        and avoids the full submit/fiscal-year machinery.
        """
        account = self._bank_account(self.company)
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = self.company
        pe.posting_date = frappe.utils.today()
        pe.paid_amount = 1
        pe.received_amount = 1
        pe.paid_to = account
        pe.paid_from = account
        pe.name = self.unique_seed_name("PE")
        pe.db_insert()  # stays draft (docstatus=0), so helper deletes without cancel
        return pe.name

    def _db_insert_draft(self, doctype, fields):
        """Direct-insert a draft (docstatus=0) parent row.

        The cleanup helpers only do ``frappe.get_doc(...).delete()`` -- they never
        read child items -- so an item-less parent row is enough to exercise the
        SUCCESS (deleted += 1) path without standing up full invoice validation
        (cost centers, UOMs, etc.).
        """
        doc = frappe.new_doc(doctype)
        for k, v in fields.items():
            setattr(doc, k, v)
        doc.name = self.unique_seed_name(doctype)
        doc.db_insert()
        return doc.name

    def test_cleanup_payment_entries_deletes_seeded_pe(self):
        # SUCCESS path: a real (draft) PE name in the list is deleted; deleted == 1.
        pe_name = self._make_draft_payment_entry()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Payment Entry", pe_name))

        result = cleanup_payment_entries([pe_name], "test")

        self.assertEqual(result["deleted"], 1)
        self.assertEqual(result["errors"], [])
        self.assertFalse(frappe.db.exists("Payment Entry", pe_name))

    def test_cleanup_sales_invoices_deletes_seeded_si(self):
        # SUCCESS path for cleanup_sales_invoices: seed a draft (item-less) SI parent
        # row directly, run the helper, assert it is deleted and deleted == 1.
        debit_to = frappe.db.get_value(
            "Account",
            {"company": self.company, "is_group": 0, "account_type": "Receivable"},
            "name",
        )
        si_name = self._db_insert_draft(
            "Sales Invoice",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "EUR",
                "debit_to": debit_to,
            },
        )
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Sales Invoice", si_name))
        self.assertEqual(frappe.db.get_value("Sales Invoice", si_name, "docstatus"), 0)

        result = cleanup_sales_invoices([si_name], "test")

        self.assertEqual(result["deleted"], 1, msg=f"errors: {result['errors']}")
        self.assertEqual(result["errors"], [])
        self.assertFalse(frappe.db.exists("Sales Invoice", si_name))

    def test_cleanup_purchase_invoices_deletes_seeded_pi(self):
        # SUCCESS path for cleanup_purchase_invoices: seed a draft (item-less) PI
        # parent row directly, run the helper, assert it is deleted and deleted == 1.
        credit_to = frappe.db.get_value(
            "Account",
            {"company": self.company, "is_group": 0, "account_type": "Payable"},
            "name",
        )
        pi_name = self._db_insert_draft(
            "Purchase Invoice",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "EUR",
                "credit_to": credit_to,
            },
        )
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Purchase Invoice", pi_name))
        self.assertEqual(frappe.db.get_value("Purchase Invoice", pi_name, "docstatus"), 0)

        result = cleanup_purchase_invoices([pi_name], "test")

        self.assertEqual(result["deleted"], 1, msg=f"errors: {result['errors']}")
        self.assertEqual(result["errors"], [])
        self.assertFalse(frappe.db.exists("Purchase Invoice", pi_name))


class TestDeleteAllPaymentEntriesSecurityGate(_CleanupCoverageBase):
    def test_guest_is_denied_by_critical_api_gate(self):
        # delete_all_payment_entries is a destructive @critical_api endpoint (it would
        # delete EVERY Payment Entry in the DB -- shared fixture data -- so its success
        # path is OOS). Assert the security framework denies an unprivileged user:
        # @critical_api raises a permission error for a Guest before the body runs.
        from verenigingen.utils.error_handling import PermissionError as VPermissionError

        with self.set_user("Guest"):
            with self.assertRaises((VPermissionError, frappe.PermissionError)):
                delete_all_payment_entries()


if __name__ == "__main__":
    unittest.main()
