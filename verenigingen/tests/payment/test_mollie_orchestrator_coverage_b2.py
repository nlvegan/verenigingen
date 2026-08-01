"""
Real-DB coverage gap-fill for the Mollie payment orchestrator.

Target: verenigingen/verenigingen_payments/services/mollie_payment_orchestrator.py

The existing test_payment_processing_recovery.py exercises get_processing_status
and the recovery loop (with a stubbed process_payment). This file gap-fills the
PURE-LOGIC and DB-DRIVEN helpers that don't require a live Mollie HTTP call:

  * is_payment_successful (pure status check)
  * ProcessingStatus / PaymentProcessingResult dataclass behaviour + to_dict
  * _determine_final_status (all branches)
  * _determine_failed_step (all branches)
  * find_matching_invoice (delegation against a real Sales Invoice)
  * _resolve_invoice / _resolve_invoice_fresh (cached-payable, cached-paid TOCTOU,
    discovery-mode no-create) against real invoices
  * _create_invoice_if_safe overlap branches (exact-unpaid reuse / no-customer)
  * _get_or_create_orphan_customer (create + idempotent reuse) - real Customer
  * process_payments_batch dry-run aggregation
  * _validate_payment_preconditions already-complete short-circuit
  * _create_orphan_payment_entry success path against a real clearing account

OUT OF SCOPE (require a live Mollie REST call / real token — skipped, not mocked):
  process_payment full flow (fetches payment from Mollie), process_orphaned_*
  with Mollie customer fetch, process_bt_only_payment fetch path. We exercise only
  the precondition/idempotency branches that short-circuit before any HTTP boundary.
"""

from datetime import datetime
from types import SimpleNamespace

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services import mollie_payment_orchestrator as orch_mod
from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
    PaymentProcessingResult,
    ProcessingStatus,
    is_payment_successful,
)


class OrchestratorBase(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.company = self._company
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.pid = f"tr_{frappe.generate_hash(length=20)}"
        self._isolate_mollie_client()

    def _isolate_mollie_client(self):
        """Make MollieClient construction independent of ambient Mollie Settings,
        so MolliePaymentOrchestrator() can be built without live creds."""
        from verenigingen.verenigingen_payments.mollie.core import client as client_mod

        real_get_key = client_mod.MollieClient._get_api_key
        client_mod.MollieClient._get_api_key = lambda self: "test_dummy_key_for_tests"
        self.addCleanup(setattr, client_mod.MollieClient, "_get_api_key", real_get_key)

        prev = orch_mod._orchestrator_instance
        orch_mod._orchestrator_instance = None
        self.addCleanup(setattr, orch_mod, "_orchestrator_instance", prev)

    def _make_member_with_customer(self, first_name="Orch"):
        member = self.sepa.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        frappe.db.set_value("Customer", customer, "member", member.name)
        member.reload()
        return member

    def _make_sales_invoice(self, customer, cov_start, cov_end, outstanding=10.0, submit=True):
        return self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=outstanding,
            status="Unpaid",
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,  # required by invoice_matcher SQL filter
            custom_coverage_start_date=cov_start,
            custom_coverage_end_date=cov_end,
            submit=submit,
        )


# =============================================================================
# Pure helpers / dataclasses
# =============================================================================
class TestPureHelpers(OrchestratorBase):
    def test_is_payment_successful(self):
        self.assertTrue(is_payment_successful(SimpleNamespace(status="paid")))
        self.assertFalse(is_payment_successful(SimpleNamespace(status="open")))
        self.assertFalse(is_payment_successful(SimpleNamespace(status="failed")))
        self.assertFalse(is_payment_successful(SimpleNamespace()))  # no status attr

    def test_processing_status_to_dict_and_properties(self):
        s = ProcessingStatus(payment_id="tr_x")
        s.status = "complete"
        d = s.to_dict()
        self.assertEqual(d["payment_id"], "tr_x")
        self.assertTrue(d["is_complete"])
        self.assertTrue(s.is_complete)
        self.assertFalse(s.is_partial)

        s2 = ProcessingStatus(payment_id="tr_y")
        s2.status = "partial"
        self.assertTrue(s2.is_partial)
        self.assertFalse(s2.is_complete)

    def test_result_to_dict_carries_all_fields(self):
        r = PaymentProcessingResult(payment_id="tr_z")
        r.status = "error"
        r.error = "boom"
        r.exception_type = "ValueError"
        r.failed_step = "create_bank_transaction"
        d = r.to_dict()
        self.assertEqual(d["payment_id"], "tr_z")
        self.assertEqual(d["status"], "error")
        self.assertEqual(d["error"], "boom")
        self.assertEqual(d["exception_type"], "ValueError")
        self.assertEqual(d["failed_step"], "create_bank_transaction")


# =============================================================================
# _determine_final_status
# =============================================================================
class TestDetermineFinalStatus(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_failed_step_marks_partial(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.failed_step = "create_payment_entry"
        self.orch._determine_final_status(r)
        self.assertEqual(r.status, "partial")
        self.assertIn("create_payment_entry", r.error)

    def test_both_docs_present_marks_success(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.bank_transaction = "BT-1"
        r.payment_entry = "PE-1"
        self.orch._determine_final_status(r)
        self.assertEqual(r.status, "success")

    def test_only_bt_marks_partial_missing_pe(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.bank_transaction = "BT-1"
        self.orch._determine_final_status(r)
        self.assertEqual(r.status, "partial")
        self.assertIn("Payment Entry", r.error)

    def test_only_pe_marks_partial_missing_bt(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.payment_entry = "PE-1"
        self.orch._determine_final_status(r)
        self.assertEqual(r.status, "partial")
        self.assertIn("Bank Transaction", r.error)

    def test_no_docs_marks_error(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        self.orch._determine_final_status(r)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.error, "No documents created")


# =============================================================================
# _determine_failed_step
# =============================================================================
class TestDetermineFailedStep(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_nothing_created_is_invoice_matching(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        self.orch._determine_failed_step(r)
        self.assertEqual(r.failed_step, "invoice_matching")

    def test_invoice_only_is_create_bank_transaction(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.sales_invoice = "SINV-1"
        self.orch._determine_failed_step(r)
        self.assertEqual(r.failed_step, "create_bank_transaction")

    def test_bt_no_pe_is_create_payment_entry(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.sales_invoice = "SINV-1"
        r.bank_transaction = "BT-1"
        self.orch._determine_failed_step(r)
        self.assertEqual(r.failed_step, "create_payment_entry")

    def test_bt_and_pe_is_link_step(self):
        r = PaymentProcessingResult(payment_id=self.pid)
        r.sales_invoice = "SINV-1"
        r.bank_transaction = "BT-1"
        r.payment_entry = "PE-1"
        self.orch._determine_failed_step(r)
        self.assertEqual(r.failed_step, "link_bt_pe")


# =============================================================================
# find_matching_invoice / _resolve_invoice
# =============================================================================
class TestInvoiceResolution(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()
        self.member = self._make_member_with_customer()
        self.customer = self.member.customer

    def test_find_matching_invoice_matches_real_invoice(self):
        cov_start = today()
        cov_end = add_days(today(), 30)
        si = self._make_sales_invoice(self.customer, cov_start, cov_end, outstanding=10.0)
        result = self.orch.find_matching_invoice(
            member_name=self.member.name,
            payment_date=getdate(today()),
            amount=10.0,
        )
        self.assertTrue(result.found)
        self.assertEqual(result.invoice_name, si.name)

    def test_resolve_invoice_uses_cached_when_still_payable(self):
        """status.sales_invoice present and still has outstanding -> returned as-is
        without a fresh lookup (TOCTOU short-circuit)."""
        si = self._make_sales_invoice(self.customer, today(), add_days(today(), 30), outstanding=10.0)
        status = ProcessingStatus(payment_id=self.pid)
        status.sales_invoice = si.name
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            resolved = self.orch._resolve_invoice(
                status, self.member.name, getdate(today()), 10.0, False, result
            )
        self.assertEqual(resolved, si.name)

    def test_resolve_invoice_discovery_mode_no_match_returns_none(self):
        """No cached invoice, no match, create_missing_invoice=False -> None and a
        diagnostic action is recorded."""
        status = ProcessingStatus(payment_id=self.pid)  # no sales_invoice
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            resolved = self.orch._resolve_invoice(
                status, self.member.name, getdate(today()), 999.0, False, result
            )
        self.assertIsNone(resolved)
        self.assertTrue(any("No matching invoice found" in a for a in result.actions_taken))

    def test_resolve_invoice_cached_paid_falls_back_to_fresh(self):
        """Cached invoice that is now fully paid (outstanding=0) triggers the
        TOCTOU fallback path searching for an alternative; with no alternative
        in discovery mode the result is None and a 'now fully paid' note added."""
        si_paid = self._make_sales_invoice(self.customer, today(), add_days(today(), 30), outstanding=10.0)
        # Force outstanding to 0 to simulate it being paid between status & exec.
        frappe.db.set_value("Sales Invoice", si_paid.name, "outstanding_amount", 0)
        status = ProcessingStatus(payment_id=self.pid)
        status.sales_invoice = si_paid.name
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            resolved = self.orch._resolve_invoice(
                status, self.member.name, getdate(today()), 999.0, False, result
            )
        # No alternative exists at amount 999 -> None
        self.assertIsNone(resolved)
        self.assertTrue(
            any("now fully paid" in a for a in result.actions_taken),
            result.actions_taken,
        )


# =============================================================================
# _create_invoice_if_safe overlap branches
# =============================================================================
class TestCreateInvoiceIfSafe(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_member_without_customer_returns_none(self):
        """No customer -> cannot create invoice, returns None with action note."""
        member = self.sepa.create_test_member(first_name="NoCust")
        # Ensure member has no customer for this branch.
        if member.customer:
            member.db_set("customer", None)
            member.reload()
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            invoice = self.orch._create_invoice_if_safe(member.name, today(), 10.0, result)
        self.assertIsNone(invoice)
        self.assertTrue(
            any("no customer" in a.lower() for a in result.actions_taken),
            result.actions_taken,
        )

    def test_exact_unpaid_overlap_invoice_is_reused(self):
        """When an exact-coverage unpaid invoice already exists, _create_invoice_if_safe
        returns it instead of creating a duplicate."""
        from verenigingen.services.billing.coverage_calculator import (
            calculate_coverage_for_payment_date,
        )

        member = self._make_member_with_customer(first_name="Overlap")
        pay_date = today()
        cov_start, cov_end = calculate_coverage_for_payment_date(member.name, pay_date)
        existing = self._make_sales_invoice(member.customer, cov_start, cov_end, outstanding=10.0)
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            invoice = self.orch._create_invoice_if_safe(member.name, pay_date, 10.0, result)
        self.assertEqual(invoice, existing.name)
        self.assertTrue(
            any("existing unpaid invoice" in a.lower() for a in result.actions_taken),
            result.actions_taken,
        )

    def test_exact_draft_overlap_is_neither_reused_nor_duplicated(self):
        """A DRAFT with exact coverage stops the path for manual review.

        A draft is not payable (Payment Entry refuses an unsubmitted reference) and it
        is not "already paid" either - ERPNext computes outstanding_amount on every
        non-cancelled save, so a draft carries its full grand_total and would otherwise
        be reused as an unpaid invoice. Creating a second invoice instead would
        duplicate the draft, so neither branch is correct: return None.
        """
        from verenigingen.services.billing.coverage_calculator import (
            calculate_coverage_for_payment_date,
        )

        member = self._make_member_with_customer(first_name="DraftOverlap")
        pay_date = today()
        cov_start, cov_end = calculate_coverage_for_payment_date(member.name, pay_date)
        draft = self._make_sales_invoice(
            member.customer, cov_start, cov_end, outstanding=10.0, submit=False
        )
        self.assertEqual(draft.docstatus, 0)
        result = PaymentProcessingResult(payment_id=self.pid)
        with self.assertNoErrorLog():
            invoice = self.orch._create_invoice_if_safe(
                member.name, pay_date, 10.0, result
            )
        self.assertIsNone(invoice)
        self.assertTrue(
            any("draft invoice" in a.lower() for a in result.actions_taken),
            result.actions_taken,
        )


# =============================================================================
# _get_or_create_orphan_customer (real Customer create + idempotent reuse)
# =============================================================================
class TestOrphanCustomer(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_create_then_reuse_idempotent(self):
        with self.assertNoErrorLog():
            first = self.orch._get_or_create_orphan_customer()
        self.assertTrue(first)
        # Second call must reuse the same customer (idempotent path).
        with self.assertNoErrorLog():
            second = self.orch._get_or_create_orphan_customer()
        self.assertEqual(first, second)
        self.assertEqual(
            frappe.db.get_value("Customer", first, "customer_name"),
            "Orphaned Mollie Payments",
        )


# =============================================================================
# process_payments_batch dry-run (no Mollie HTTP)
# =============================================================================
class TestProcessPaymentsBatchDryRun(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_dry_run_reports_status_without_changes(self):
        ids = [f"tr_{frappe.generate_hash(length=18)}" for _ in range(3)]
        with self.assertNoErrorLog():
            batch = self.orch.process_payments_batch(ids, dry_run=True)
        self.assertTrue(batch["dry_run"])
        self.assertEqual(batch["total_requested"], 3)
        self.assertEqual(len(batch["results"]), 3)
        # Nothing was processed in dry-run.
        self.assertEqual(batch["processed"], 0)
        self.assertEqual(batch["errors"], 0)
        for entry in batch["results"]:
            self.assertEqual(entry["status"], "dry_run")
            self.assertIn("current_status", entry)


# =============================================================================
# _validate_payment_preconditions already-complete short-circuit
# =============================================================================
class TestValidatePreconditions(OrchestratorBase):
    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_already_complete_short_circuits_before_mollie(self):
        """If get_processing_status returns complete, preconditions returns
        (None,None,None) and populates result as already_processed -- WITHOUT
        ever touching the Mollie client."""
        member = self._make_member_with_customer(first_name="Complete")

        # Force get_processing_status to report 'complete' via a real-ish status
        # object. We patch only the orchestrator's own status probe (a DB read),
        # not any business logic or external boundary, to drive the branch
        # deterministically without constructing the full BT/PE/SINV linkage.
        complete_status = ProcessingStatus(payment_id=self.pid)
        complete_status.status = "complete"
        complete_status.bank_transaction = "BT-x"
        complete_status.payment_entry = "PE-x"
        complete_status.sales_invoice = "SINV-x"
        complete_status.member = member.name

        original = self.orch.get_processing_status
        self.orch.get_processing_status = lambda pid: complete_status
        try:
            result = PaymentProcessingResult(payment_id=self.pid)
            s, p, m = self.orch._validate_payment_preconditions(self.pid, None, None, result)
        finally:
            self.orch.get_processing_status = original

        self.assertIsNone(s)
        self.assertEqual(result.status, "already_processed")
        self.assertEqual(result.bank_transaction, "BT-x")
        self.assertEqual(result.skipped_reason, "Already fully processed")


# =============================================================================
# _create_orphan_payment_entry (real DB, real clearing account)
#
# Previously listed OUT OF SCOPE in this file's header on the grounds that it
# "needs Mollie clearing account config". That config is fixture-able - the dues
# creation-unit suite already pins it - so the gap is closed here rather than
# left as the only success path in the orphan flow with no coverage.
# =============================================================================
class TestCreateOrphanPaymentEntry(OrchestratorBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
            ensure_mollie_bank_gl_account,
        )

        # A DEDICATED clearing account, always. Reusing whatever Bank account the
        # company happens to have can pick the company default, and then asserting
        # paid_to == clearing_account proves nothing: it would hold whether or not
        # bank_account reached ERPNext.
        cls.clearing_account = ensure_mollie_bank_gl_account(cls._company)

        # SETUP-only Single writes (class fixture, not a test body). Written with
        # set_single_value and restored via addClassCleanup: these Singles survive the
        # harness rollback, and Mollie Settings.mollie_clearing_account has no harness
        # restore at all, so leaving it repointed drifts every later suite in the shard
        # that reads it.
        for doctype, field, value in (
            ("Verenigingen Settings", "company", cls._company),
            ("Mollie Settings", "mollie_clearing_account", cls.clearing_account),
        ):
            previous = frappe.db.get_single_value(doctype, field)
            frappe.db.set_single_value(doctype, field, value)
            cls.addClassCleanup(frappe.db.set_single_value, doctype, field, previous)
        cls.addClassCleanup(frappe.db.commit)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.orch = MolliePaymentOrchestrator()

    def test_orphan_banner_survives_validation_and_lands_on_the_entry(self):
        """The "requires manual review" banner must reach the document an operator reads.

        This is the whole point of an orphan Payment Entry: nobody knows which member
        paid, so the entry itself has to say so. Assigning `remarks` is not enough -
        Payment Entry.validate() calls set_remarks(), which regenerates the field from
        the amount and party unless `custom_remarks` is set. The value is therefore
        read back from the DB; asserting the in-memory doc would pass even when the
        text is discarded on save.
        """
        member = self._make_member_with_customer(first_name="OrphanRemark")
        cov_start, cov_end = today(), today()
        invoice = self._make_sales_invoice(member.customer, cov_start, cov_end, outstanding=25.0)

        pe_name = self.orch._create_orphan_payment_entry(
            payment_id=self.pid,
            customer=member.customer,
            invoice_name=invoice.name,
            amount=25.0,
            payment_date=today(),
        )

        self.assertIsNotNone(pe_name, "the orphan payment must be recorded")
        pe = frappe.db.get_value(
            "Payment Entry", pe_name, ["docstatus", "remarks", "paid_to", "reference_no"], as_dict=True
        )
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.reference_no, self.pid)
        self.assertEqual(pe.paid_to, self.clearing_account, "orphan payments land in Mollie clearing")
        self.assertIn(
            "ORPHANED PAYMENT",
            pe.remarks or "",
            "the operator-facing banner was discarded by set_remarks()",
        )
