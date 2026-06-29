"""
Coverage sweep for verenigingen/e_boekhouden/utils/cleanup_utils.py

Complements (does NOT duplicate) test_cleanup_utils.py and test_cleanup_utils_coverage.py.
Targets the large still-uncovered blocks:

  - cleanup_chart_of_accounts FORCE + delete_all multi-pass: refetch across passes,
    force-mode root-system-account SKIP (Asset/Liability/Income/Expense/Equity), and
    the "no deletions this pass -> stop" break.
  - nuclear_cleanup_all_imported_data: the orchestration loop that cancels+deletes the
    four eBoekhouden-tagged doctypes and the provisional Customer/Supplier deletion.
  - delete_all_payment_entries SUCCESS path: cascade-delete Payment Entries plus their
    linked Bank Transactions, with results accounting.
  - _cleanup_orphaned_bank_transactions: the "linked to a Payment Entry that no longer
    exists -> orphaned" branch (the existing suite only covers the no-links branch).
  - test_cleanup_small_batch: the dev/admin helper success path.

SAFETY / why enumeration is scoped
----------------------------------
nuclear_cleanup_all_imported_data, delete_all_payment_entries and test_cleanup_small_batch
are GLOBAL, unscoped wipes (no company filter -- e.g. delete_all_payment_entries deletes
EVERY Payment Entry in the DB). veg11 is a shared, non-reset site with thousands of real
Payment Entries and other fixtures, so running them unscoped would permanently destroy
shared data. We therefore patch ONLY the record-enumeration seam (frappe.get_all for the
specific doctypes the function sweeps) so the function operates on REAL rows we seeded.
The cleanup logic itself -- frappe.delete_doc, doc.cancel(), the cascade into linked Bank
Transactions, batch commits and results accounting -- runs FOR REAL and is never mocked.
Every assertion checks a real DB side effect (our seeded rows deleted, control rows
preserved) that would fail on a regression of the cleanup logic.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_cleanup_utils_sweep
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.e_boekhouden.utils import cleanup_utils
from verenigingen.e_boekhouden.utils.cleanup_utils import (
    _cleanup_orphaned_bank_transactions,
    cleanup_chart_of_accounts,
    delete_all_payment_entries,
    nuclear_cleanup_all_imported_data,
    test_cleanup_small_batch,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class _SweepBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls._persist_company("TEST EBkh Cleanup Sweep Co", "TECSW")
        cls.abbr = frappe.db.get_value("Company", cls.company, "abbr")

    @classmethod
    def _persist_company(cls, name, abbr):
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

    def _acct(self, root_type="Expense", account_type=None):
        filters = {"company": self.company, "is_group": 0, "root_type": root_type}
        if account_type:
            filters["account_type"] = account_type
        return frappe.db.get_value("Account", filters, "name")

    def _bank_account(self):
        return self._acct("Asset", "Bank") or self._acct("Asset")

    def _db_insert_draft(self, doctype, fields):
        """Direct-insert a draft (docstatus=0) parent row, bypassing full validation.

        The cleanup functions only get_doc(...).delete()/cancel() the parent -- they
        never read child items -- so an item-less parent is enough to exercise the
        delete path without standing up invoice/fiscal-year machinery.
        """
        doc = frappe.new_doc(doctype)
        for k, v in fields.items():
            setattr(doc, k, v)
        doc.db_insert()
        return doc.name

    def _persist_party(self, doctype, name_field, name):
        """Factory helper: persist a provisional Customer/Supplier for cleanup tests."""
        doc = frappe.new_doc(doctype)
        setattr(doc, name_field, name)
        doc.insert(ignore_permissions=True)
        return doc

    def _make_draft_payment_entry(self):
        account = self._bank_account()
        return self._db_insert_draft(
            "Payment Entry",
            {
                "payment_type": "Receive",
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "paid_amount": 1,
                "received_amount": 1,
                "paid_to": account,
                "paid_from": account,
            },
        )

    def _link_bank_transaction(self, payment_entry_name, ref="EB-SWEEP-LINKED"):
        """Create a Bank Transaction with a child row linking it to a Payment Entry."""
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.reference_number = ref
        bt.deposit = 1
        bt.company = self.company
        bt.db_insert()
        link = frappe.new_doc("Bank Transaction Payments")
        link.parent = bt.name
        link.parenttype = "Bank Transaction"
        link.parentfield = "payment_entries"
        link.payment_document = "Payment Entry"
        link.payment_entry = payment_entry_name
        link.db_insert()
        return bt.name


class TestCleanupChartOfAccountsForceMultiPass(_SweepBase):
    def test_force_delete_all_preserves_roots_and_multi_passes(self):
        # FORCE + delete_all on a throwaway company: every leaf/group is force-deleted
        # across multiple passes (children before parents), but the five root system
        # accounts are SKIPPED even in force mode. This exercises the force-mode root
        # skip branch, the per-pass refetch, and the "no deletions -> stop" break.
        company = self._persist_company("TEST EBkh Cleanup Sweep Force Co", "TECSWF")

        # Sanity: the vanilla CoA exists with the protected root names.
        roots_before = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 1,
                "account_name": ["in", ["Asset", "Liability", "Income", "Expense", "Equity"]],
            },
            pluck="account_name",
        )
        self.assertTrue(roots_before, "expected vanilla CoA root system accounts to exist")
        leaf_count_before = frappe.db.count("Account", {"company": company, "is_group": 0})
        self.assertGreater(leaf_count_before, 0)

        result = cleanup_chart_of_accounts(company, delete_all_accounts=1, force_delete=1)
        self.assertTrue(result["success"], msg=result)

        # Force mode must delete the leaf accounts (real side effect).
        self.assertGreaterEqual(result["results"]["accounts_deleted"], 1)
        # The protected root system accounts must SURVIVE and be reported as skipped.
        self.assertGreaterEqual(result["results"]["accounts_skipped"], 1)
        self.assertTrue(
            any("Root system account" in e for e in result["results"]["errors"]),
            msg=f"errors: {result['results']['errors'][:10]}",
        )
        for root_name in roots_before:
            self.assertTrue(
                frappe.db.exists(
                    "Account", {"company": company, "account_name": root_name, "is_group": 1}
                ),
                msg=f"force mode wrongly deleted protected root {root_name}",
            )
        # Virtually all non-root accounts gone -> far fewer leaves remain than before.
        leaf_count_after = frappe.db.count("Account", {"company": company, "is_group": 0})
        self.assertLess(leaf_count_after, leaf_count_before)


class TestCleanupOrphanedBankTransactionsLinkedToDeletedPE(_SweepBase):
    def test_orphaned_when_linked_payment_entry_no_longer_exists(self):
        # A Bank Transaction (EB- ref) WITH a child link row, but whose linked Payment
        # Entry does not exist, is orphaned and must be deleted. This is the "has links
        # but no valid payment" branch -- distinct from the existing suite's "no links
        # at all" test.
        bt = frappe.new_doc("Bank Transaction")
        bt.date = frappe.utils.today()
        bt.reference_number = "EB-SWEEP-DEAD-PE"
        bt.deposit = 1
        bt.company = self.company
        bt.db_insert()
        link = frappe.new_doc("Bank Transaction Payments")
        link.parent = bt.name
        link.parenttype = "Bank Transaction"
        link.parentfield = "payment_entries"
        link.payment_document = "Payment Entry"
        link.payment_entry = "PE-SWEEP-DOES-NOT-EXIST"
        link.db_insert()
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Bank Transaction", bt.name))
        self.assertFalse(frappe.db.exists("Payment Entry", "PE-SWEEP-DOES-NOT-EXIST"))

        result = _cleanup_orphaned_bank_transactions()

        self.assertGreaterEqual(result["deleted"], 1)
        self.assertFalse(frappe.db.exists("Bank Transaction", bt.name))


class TestDeleteAllPaymentEntriesSuccess(_SweepBase):
    def test_deletes_enumerated_pes_and_cascades_bank_transactions(self):
        # SUCCESS path. Seed two draft PEs (one with a linked Bank Transaction) plus a
        # control PE. We scope the function's "all Payment Entries" enumeration to the
        # two target PEs (see module docstring) -- the deletes themselves run for real.
        pe_a = self._make_draft_payment_entry()
        pe_b = self._make_draft_payment_entry()
        pe_control = self._make_draft_payment_entry()
        bt_name = self._link_bank_transaction(pe_b)
        frappe.db.commit()

        for n in (pe_a, pe_b, pe_control):
            self.assertTrue(frappe.db.exists("Payment Entry", n))
        self.assertTrue(frappe.db.exists("Bank Transaction", bt_name))

        targets = [frappe._dict(name=pe_a, docstatus=0), frappe._dict(name=pe_b, docstatus=0)]
        orig_get_all = frappe.get_all

        def scoped_get_all(doctype, *args, **kwargs):
            if doctype == "Payment Entry":
                return list(targets)
            return orig_get_all(doctype, *args, **kwargs)

        with patch.object(frappe, "get_all", side_effect=scoped_get_all):
            result = delete_all_payment_entries()

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["results"]["deleted"], 2)
        # Cascade: the Bank Transaction linked to pe_b was deleted too.
        self.assertEqual(result["results"]["bank_transactions_deleted"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", pe_a))
        self.assertFalse(frappe.db.exists("Payment Entry", pe_b))
        self.assertFalse(frappe.db.exists("Bank Transaction", bt_name))
        # The control PE was NOT enumerated -> proves the deletes are scoped & real,
        # not a blanket no-op or a global wipe.
        self.assertTrue(frappe.db.exists("Payment Entry", pe_control))

        frappe.delete_doc("Payment Entry", pe_control, force=True, ignore_permissions=True)
        frappe.db.commit()


class TestNuclearCleanup(_SweepBase):
    def test_orchestration_deletes_tagged_docs_and_provisional_parties(self):
        # nuclear_cleanup sweeps four eBoekhouden-tagged doctypes plus provisional
        # parties. We scope the enumeration to our seeded rows and neutralise the two
        # GLOBAL orphan sub-routines (already covered by other tests) so this stays
        # safe on the shared site; the orchestration's cancel/delete/results logic runs
        # for real and we assert our rows are actually deleted.
        bank = self._bank_account()
        receivable = self._acct("Asset", "Receivable")
        payable = self._acct("Liability", "Payable")

        si = self._db_insert_draft(
            "Sales Invoice",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "EUR",
                "debit_to": receivable,
            },
        )
        pi = self._db_insert_draft(
            "Purchase Invoice",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "EUR",
                "credit_to": payable,
            },
        )
        pe = self._db_insert_draft(
            "Payment Entry",
            {
                "payment_type": "Receive",
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "paid_amount": 1,
                "received_amount": 1,
                "paid_to": bank,
                "paid_from": bank,
            },
        )
        je = self._db_insert_draft(
            "Journal Entry",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "voucher_type": "Journal Entry",
            },
        )

        cust = self._persist_party("Customer", "customer_name", "Provisional Customer SWEEP-TEST")
        supp = self._persist_party("Supplier", "supplier_name", "Provisional Supplier SWEEP-TEST")
        frappe.db.commit()

        scoped = {
            "Sales Invoice": [frappe._dict(name=si, docstatus=0)],
            "Purchase Invoice": [frappe._dict(name=pi, docstatus=0)],
            "Payment Entry": [frappe._dict(name=pe, docstatus=0)],
            "Journal Entry": [frappe._dict(name=je, docstatus=0)],
        }
        orig_get_all = frappe.get_all

        def scoped_get_all(doctype, *args, **kwargs):
            if doctype in scoped:
                return list(scoped[doctype])
            if doctype == "Customer":
                return [frappe._dict(name=cust.name)]
            if doctype == "Supplier":
                return [frappe._dict(name=supp.name)]
            return orig_get_all(doctype, *args, **kwargs)

        with patch.object(frappe, "get_all", side_effect=scoped_get_all), patch.object(
            cleanup_utils, "cleanup_orphaned_gl_entries", return_value={"success": True, "deleted_entries": 0}
        ), patch.object(
            cleanup_utils, "_cleanup_orphaned_bank_transactions", return_value={"deleted": 0, "errors": []}
        ):
            result = nuclear_cleanup_all_imported_data()

        self.assertTrue(result["success"], msg=result)
        res = result["results"]

        # Sales/Purchase Invoices: deleted AND correctly counted.
        self.assertFalse(frappe.db.exists("Sales Invoice", si))
        self.assertFalse(frappe.db.exists("Purchase Invoice", pi))
        self.assertEqual(res["sales_invoices"], 1)
        self.assertEqual(res["purchase_invoices"], 1)

        # Provisional parties: deleted AND correctly counted.
        self.assertFalse(frappe.db.exists("Customer", cust.name))
        self.assertFalse(frappe.db.exists("Supplier", supp.name))
        self.assertEqual(res["customers"], 1)
        self.assertEqual(res["suppliers"], 1)

        # Payment Entry / Journal Entry: deleted AND correctly counted.
        #
        # Regression guard for a fixed bug: the per-doctype counter used to be
        #     results[doctype.lower().replace(" ", "_") + "s"] += 1
        # which builds "payment_entrys"/"journal_entrys" -- keys that do not exist
        # in `results` -- so the increment raised KeyError *after* delete_doc had
        # already run, counting each successful PE/JE delete as an error. The fix
        # uses an explicit result key per doctype, so the counters now increment
        # and no KeyError artifact lands in errors.
        self.assertFalse(frappe.db.exists("Payment Entry", pe))
        self.assertFalse(frappe.db.exists("Journal Entry", je))
        self.assertEqual(res["payment_entries"], 1)
        self.assertEqual(res["journal_entries"], 1)
        self.assertFalse(
            any("payment_entrys" in e or "journal_entrys" in e for e in res["errors"]),
            msg=f"counter KeyError artifacts should be gone; errors={res['errors'][:10]}",
        )


class TestCleanupSmallBatch(_SweepBase):
    def test_deletes_seeded_sales_invoice(self):
        # Dev/admin helper that deletes the first few eBoekhouden-tagged Sales Invoices.
        # Scope the enumeration to a single seeded draft SI (see module docstring) and
        # assert it is really deleted with a deleted count of 1.
        receivable = self._acct("Asset", "Receivable")
        si = self._db_insert_draft(
            "Sales Invoice",
            {
                "company": self.company,
                "posting_date": frappe.utils.today(),
                "due_date": frappe.utils.today(),
                "currency": "EUR",
                "debit_to": receivable,
            },
        )
        frappe.db.commit()
        self.assertTrue(frappe.db.exists("Sales Invoice", si))

        targets = [frappe._dict(name=si, docstatus=0)]
        orig_get_all = frappe.get_all

        def scoped_get_all(doctype, *args, **kwargs):
            if doctype == "Sales Invoice":
                return list(targets)
            return orig_get_all(doctype, *args, **kwargs)

        # test_cleanup_small_batch is guarded by @development_only(), which raises on
        # a production-like CI site (no developer_mode). Enable it for this test only;
        # frappe.conf is process-global and not transaction-scoped, so restore it.
        prev_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        try:
            with patch.object(frappe, "get_all", side_effect=scoped_get_all):
                result = test_cleanup_small_batch()
        finally:
            if prev_dev_mode is None:
                frappe.conf.pop("developer_mode", None)
            else:
                frappe.conf["developer_mode"] = prev_dev_mode

        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["results"]["sales_invoices"], 1)
        self.assertFalse(frappe.db.exists("Sales Invoice", si))


if __name__ == "__main__":
    unittest.main()
