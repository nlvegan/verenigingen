"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/payment_entry_cleanup.py
(previously ~0% coverage).

This module bulk-deletes Payment Entry documents, first scrubbing their
references out of Member Payment History child tables to avoid LinkExistsError,
optionally cascading to cancelled Sales Invoices and orphaned GL / Payment
Ledger entries.

Approach
--------
* All paths run against REAL Member / Customer / Payment Entry / Sales Invoice /
  Member Payment History documents built with the SEPA/enhanced factories. No
  business logic is mocked.
* Payment Entries are inserted then marked submitted directly in the DB
  (docstatus=1) per the project convention — a bare ``.submit()`` trips
  EUR-account currency validation on the test company and is irrelevant to the
  cleanup logic (which deletes with ``force=True``).
* The cleanup module commits inside its body. Inside the test transaction the
  commit is a no-op w.r.t. the outer rollback, but the in-process DB state is
  updated so we can assert post-state (deleted docs no longer ``frappe.db.exists``)
  before the harness rolls back at tearDown.
* Tests run as Administrator, satisfying the @critical_api(FINANCIAL) gates.

NOTE: every test that hits a real-delete path passes
``delete_cancelled_invoices=False`` and ``cleanup_ledger_entries=False`` unless
that specific behaviour is under test, so we never touch ambient site
Sales Invoices / GL Entries.
"""

import unittest

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.utils import payment_entry_cleanup as cleanup


class CleanupBase(EnhancedTestCase):
    """Shared fixtures for payment-entry-cleanup tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        cls._bank_account = frappe.db.get_value(
            "Bank Account", {"is_company_account": 1}, "name"
        ) or frappe.db.get_value("Bank Account", {}, "name")
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.company = self._company
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    # --- fixture builders -------------------------------------------------

    def _make_member_with_customer(self, first_name="Cleanup"):
        member = self.sepa.create_test_member(first_name=first_name)
        if not member.customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
            member.reload()
        return member

    def _make_payment_entry(self, customer=None, docstatus=1, posting_date=None):
        """Create a Payment Entry and mark it at the requested docstatus directly
        in the DB. We bypass real .submit()/GL wiring (irrelevant to the cleanup
        code, which uses force=True deletes).

        ``posting_date`` defaults to today(); pass a unique date for date-range
        tests so the window catches only this PE and not sibling-shard PEs that
        also happen to be dated today() (a submitted sibling PE would otherwise be
        swept into a docstatus-unfiltered delete and fail the force-delete)."""
        receivable = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Receivable", "is_group": 0},
            "name",
        )
        bank = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Bank", "is_group": 0},
            "name",
        )
        posting_date = posting_date or today()
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = self.company
        pe.posting_date = posting_date
        pe.party_type = "Customer"
        pe.party = customer
        pe.paid_amount = 10.0
        pe.received_amount = 10.0
        pe.reference_no = frappe.generate_hash(length=10)
        pe.reference_date = posting_date
        pe.paid_from = receivable
        pe.paid_to = bank
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True, ignore_mandatory=True)
        if docstatus:
            frappe.db.set_value("Payment Entry", pe.name, "docstatus", docstatus, update_modified=False)
        pe.reload()
        return pe

    def _persist_payment_history(self, member, pe_name, transaction_type="Regular Invoice"):
        """Append a Member Payment History row referencing the given Payment
        Entry (helper-only DB write per test-quality rules)."""
        member.append(
            "payment_history",
            {
                "transaction_type": transaction_type,
                "amount": 10.0,
                "payment_entry": pe_name,
                # payment_entry is a Dynamic Link keyed on payment_entry_doctype.
                "payment_entry_doctype": "Payment Entry",
            },
        )
        member.flags.ignore_validate = True
        member.save(ignore_permissions=True)
        member.reload()


# =============================================================================
# input validation / argument coercion
# =============================================================================
class TestBulkDeleteValidation(CleanupBase):
    def test_throws_when_neither_names_nor_filters(self):
        with self.assertRaises(frappe.ValidationError):
            cleanup.bulk_delete_payment_entries()

    def test_preview_throws_when_neither_names_nor_filters(self):
        with self.assertRaises(frappe.ValidationError):
            cleanup.get_payment_entry_cleanup_preview()

    def test_json_string_payment_entry_names_accepted(self):
        """A JSON-string ``payment_entry_names`` (as sent by the HTTP layer) is
        accepted and json.loads'd by the body.

        Regression for a fixed BUG: the parameter was annotated
        ``payment_entry_names: List[str] = None`` while the body handles a JSON
        string. Under Frappe v16 the @frappe.whitelist runtime type gate (active
        in tests via in_test) rejected the str argument BEFORE the body ran,
        raising FrappeTypeError. The annotation is now
        ``Union[List[str], str, None]`` to match the documented JSON-string
        contract."""
        import json

        pe = self._make_payment_entry(docstatus=0)
        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=json.dumps([pe.name]),
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["payment_entries_deleted"], 1)

    def test_json_string_filters_accepted(self):
        """A JSON-string ``filters`` arg (from the HTTP layer) is accepted and
        json.loads'd by the body.

        Regression for a fixed BUG: same as the payment_entry_names case — the
        ``filters`` parameter was annotated ``Dict = None`` while the body
        json.loads a str, so the v16 whitelist gate rejected the str arg pre-body.
        The annotation is now ``Union[dict, str, None]``."""
        import json

        result = cleanup.bulk_delete_payment_entries(
            filters=json.dumps({"name": "PE-DOES-NOT-EXIST"}),
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["total_requested"], 0)


# =============================================================================
# core deletion behaviour
# =============================================================================
class TestBulkDeleteCore(CleanupBase):
    def test_deletes_named_payment_entry_and_scrubs_history(self):
        member = self._make_member_with_customer("ScrubHist")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)
        self._persist_payment_history(member, pe.name)

        # Precondition: history row references the PE.
        self.assertTrue(any(r.payment_entry == pe.name for r in member.payment_history))

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )

        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["payment_entries_deleted"], 1)
        self.assertEqual(result["member_history_cleaned"], 1)
        self.assertEqual(result["errors"], 0)
        # PE is gone.
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))
        # History row removed.
        member.reload()
        self.assertFalse(any(r.payment_entry == pe.name for r in member.payment_history))

    def test_spares_unrelated_payment_entries_and_history(self):
        """Only the targeted PE/history row is touched; a sibling PE referenced by
        the same member is left intact."""
        member = self._make_member_with_customer("Spare")
        target = self._make_payment_entry(customer=member.customer, docstatus=0)
        keep = self._make_payment_entry(customer=member.customer, docstatus=0)
        self._persist_payment_history(member, target.name)
        self._persist_payment_history(member, keep.name)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[target.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )

        self.assertEqual(result["payment_entries_deleted"], 1)
        self.assertEqual(result["member_history_cleaned"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", target.name))
        # Sibling PE + its history row survive.
        self.assertTrue(frappe.db.exists("Payment Entry", keep.name))
        member.reload()
        self.assertTrue(any(r.payment_entry == keep.name for r in member.payment_history))
        self.assertFalse(any(r.payment_entry == target.name for r in member.payment_history))

    def test_delete_by_filters_pluck_path(self):
        """No explicit names -> the filter branch (frappe.get_all pluck) selects
        the PE."""
        member = self._make_member_with_customer("ByFilter")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        result = cleanup.bulk_delete_payment_entries(
            filters={"name": pe.name},
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["payment_entries_deleted"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))

    def test_no_member_history_still_deletes(self):
        """A PE with no Member Payment History references is deleted with
        member_history_cleaned == 0."""
        member = self._make_member_with_customer("NoHist")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["payment_entries_deleted"], 1)
        self.assertEqual(result["member_history_cleaned"], 0)

    def test_multiple_history_rows_same_pe_all_removed(self):
        """Two history rows on one member referencing the same PE are both
        scrubbed (member_history_cleaned counts rows, not members)."""
        member = self._make_member_with_customer("DupRows")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)
        self._persist_payment_history(member, pe.name)
        self._persist_payment_history(member, pe.name)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["member_history_cleaned"], 2)
        member.reload()
        self.assertFalse(any(r.payment_entry == pe.name for r in member.payment_history))

    def test_nonexistent_payment_entry_force_delete_is_noop(self):
        """A name that does not exist: ``frappe.delete_doc(..., force=True)``
        silently succeeds (force ignores the missing doc) rather than raising, so
        it is counted as 'deleted' with no error. This documents the force=True
        contract the cleanup relies on."""
        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=["ACC-PAY-DOES-NOT-EXIST-XYZ"],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["payment_entries_deleted"], 1)
        self.assertEqual(result["errors"], 0)
        statuses = [d.get("status") for d in result["details"]]
        self.assertIn("deleted", statuses)

    def test_idempotent_second_run_does_not_raise(self):
        """Deleting the same PE twice: the second run still 'succeeds' because
        force=True deletion of an already-gone doc is a silent no-op. The key
        guarantee is that re-running never raises and the PE remains absent."""
        member = self._make_member_with_customer("Idem")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        first = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(first["payment_entries_deleted"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))

        second = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(second["errors"], 0)
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))

    def test_result_summary_and_shape(self):
        member = self._make_member_with_customer("Shape")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        for key in (
            "total_requested",
            "member_history_cleaned",
            "payment_entries_deleted",
            "sales_invoices_deleted",
            "gl_entries_deleted",
            "payment_ledger_entries_deleted",
            "errors",
            "details",
            "timestamp",
            "total_records_affected",
            "summary",
        ):
            self.assertIn(key, result)
        self.assertIn("Deleted 1 payment entries", result["summary"])
        self.assertEqual(result["total_records_affected"], 1)
        # Nested UI-formatter blocks populated.
        self.assertEqual(result["payment_entries"]["count"], 1)
        self.assertEqual(result["payment_entries"]["deleted"], 1)


# =============================================================================
# cascade: cancelled sales invoices
# =============================================================================
class TestCancelledInvoiceCascade(CleanupBase):
    def test_cancelled_sales_invoice_deleted_when_enabled(self):
        """A cancelled (docstatus=2) Sales Invoice is deleted when
        delete_cancelled_invoices=True. We bound the scope to a known invoice and
        assert it specifically disappears (ambient cancelled invoices on the test
        site are out of our control but harmless to delete in the rolled-back
        test transaction)."""
        member = self._make_member_with_customer("CancelSI")
        si = self.sepa.create_test_sales_invoice(
            customer=member.customer, grand_total=10.0, submit=True, company=self.company
        )
        # Cancel -> docstatus 2.
        si.reload()
        si.cancel()
        self.assertEqual(frappe.db.get_value("Sales Invoice", si.name, "docstatus"), 2)

        pe = self._make_payment_entry(customer=member.customer, docstatus=0)
        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=True,
            cleanup_ledger_entries=False,
        )
        self.assertGreaterEqual(result["sales_invoices_deleted"], 1)
        self.assertFalse(frappe.db.exists("Sales Invoice", si.name))

    def test_cancelled_invoice_spared_when_disabled(self):
        member = self._make_member_with_customer("KeepSI")
        si = self.sepa.create_test_sales_invoice(
            customer=member.customer, grand_total=10.0, submit=True, company=self.company
        )
        si.reload()
        si.cancel()
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=False,
        )
        self.assertEqual(result["sales_invoices_deleted"], 0)
        self.assertTrue(frappe.db.exists("Sales Invoice", si.name))


# =============================================================================
# cascade: orphaned ledger entries
# =============================================================================
class TestLedgerCleanup(CleanupBase):
    def test_ledger_cleanup_runs_without_error(self):
        """The orphaned-GL/PL DELETE-JOIN queries execute and populate the
        ledger_entries result block. We don't assert a specific count (the site
        may legitimately have or lack orphans), only that the branch runs cleanly
        and the keys are populated."""
        member = self._make_member_with_customer("Ledger")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        result = cleanup.bulk_delete_payment_entries(
            payment_entry_names=[pe.name],
            delete_cancelled_invoices=False,
            cleanup_ledger_entries=True,
        )
        self.assertEqual(result["errors"], 0)
        self.assertIn("ledger_entries", result)
        self.assertIn("deleted", result["ledger_entries"])
        self.assertGreaterEqual(result["gl_entries_deleted"], 0)
        self.assertGreaterEqual(result["payment_ledger_entries_deleted"], 0)


# =============================================================================
# delete_payment_entries_by_date_range
# =============================================================================
class TestDeleteByDateRange(CleanupBase):
    # The date-range delete builds a site-wide `posting_date between` filter, so
    # sibling-shard PEs dated today() would be swept in too (and a submitted one
    # fails the force-delete). Pin each fixture to a unique far-past posting_date
    # and use a 1-day window around it so the query matches only this test's PE.
    def _isolated_window_date(self):
        # A date far in the past that the EnhancedTestDataFactory's frozen "today"
        # range never reaches, made unique-ish per test via the instance seed.
        return add_days("2000-01-01", self.sepa.seed % 3000)

    def test_date_range_selects_pe_in_window(self):
        member = self._make_member_with_customer("DateRange")
        d = self._isolated_window_date()
        pe = self._make_payment_entry(customer=member.customer, docstatus=0, posting_date=d)
        result = cleanup.delete_payment_entries_by_date_range(
            from_date=add_days(d, -1),
            to_date=add_days(d, 1),
            docstatus=0,
        )
        self.assertGreaterEqual(result["payment_entries_deleted"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))

    def test_date_range_excludes_pe_outside_window(self):
        member = self._make_member_with_customer("OutWindow")
        d = self._isolated_window_date()
        pe = self._make_payment_entry(customer=member.customer, docstatus=0, posting_date=d)
        # Window entirely before our PE's date -> our PE is excluded.
        result = cleanup.delete_payment_entries_by_date_range(
            from_date=add_days(d, -30),
            to_date=add_days(d, -20),
            docstatus=0,
        )
        # Our PE must still exist (it was not in the window).
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))

    def test_date_range_without_docstatus_filter(self):
        """docstatus=None branch: the filter dict omits docstatus entirely."""
        member = self._make_member_with_customer("NoDocstatus")
        d = self._isolated_window_date()
        pe = self._make_payment_entry(customer=member.customer, docstatus=0, posting_date=d)
        result = cleanup.delete_payment_entries_by_date_range(
            from_date=add_days(d, -1),
            to_date=add_days(d, 1),
        )
        self.assertGreaterEqual(result["payment_entries_deleted"], 1)
        self.assertFalse(frappe.db.exists("Payment Entry", pe.name))


# =============================================================================
# get_payment_entry_cleanup_preview
# =============================================================================
class TestCleanupPreview(CleanupBase):
    def test_preview_reports_affected_members_without_deleting(self):
        member = self._make_member_with_customer("Preview")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)
        self._persist_payment_history(member, pe.name)
        self._persist_payment_history(member, pe.name)

        preview = cleanup.get_payment_entry_cleanup_preview(payment_entry_names=[pe.name])

        self.assertEqual(preview["total_payment_entries"], 1)
        self.assertEqual(preview["total_history_rows"], 2)
        self.assertIn(member.name, preview["affected_members"])
        self.assertEqual(preview["total_affected_members"], 1)
        self.assertEqual(preview["payment_entries"][0]["name"], pe.name)
        self.assertEqual(preview["payment_entries"][0]["history_rows"], 2)
        # Crucially: nothing was deleted.
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))

    def test_preview_via_filters(self):
        member = self._make_member_with_customer("PreviewFilter")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)

        preview = cleanup.get_payment_entry_cleanup_preview(filters={"name": pe.name})
        self.assertEqual(preview["total_payment_entries"], 1)
        self.assertEqual(preview["payment_entries"][0]["name"], pe.name)
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))

    def test_preview_no_history_rows(self):
        member = self._make_member_with_customer("PreviewNoHist")
        pe = self._make_payment_entry(customer=member.customer, docstatus=0)
        preview = cleanup.get_payment_entry_cleanup_preview(payment_entry_names=[pe.name])
        self.assertEqual(preview["total_history_rows"], 0)
        self.assertEqual(preview["total_affected_members"], 0)
        self.assertEqual(preview["affected_members"], [])


# =============================================================================
# Module-targeting sanity check
# =============================================================================
class TestModuleTarget(unittest.TestCase):
    def test_targets_verenigingen_payments_copy(self):
        self.assertIn(
            "verenigingen_payments/utils/payment_entry_cleanup.py",
            cleanup.__file__,
        )


if __name__ == "__main__":
    unittest.main()
