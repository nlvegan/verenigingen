"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/payment_processing_recovery.py
(previously ~0% coverage).

This module provides idempotency/status checks, gap analysis, partial-payment
completion (recovery mode) and GL-entry repair for Mollie payment processing.

IMPORTANT: this targets the **verenigingen_payments** copy
(`verenigingen.verenigingen_payments.utils.payment_processing_recovery`), NOT
`verenigingen.utils.payment_processing_recovery`. See the import below.

Approach
--------
* get_payment_processing_status / analyze_payment_gaps / get_incomplete_payments
  and the dry-run path of complete_partial_payments are all pure DB-driven and
  are exercised against REAL Member / Customer / Bank Transaction / Payment Entry
  / Sales Invoice documents built with EnhancedTestDataFactory. No business logic
  is mocked.
* The ONLY external boundary stubbed is the Mollie HTTP fetch reached inside the
  orchestrator's process_payment()/process_orphaned_payment_with_invoice() — and
  only for the non-dry-run recovery branches, where we replace those two
  orchestrator methods with deterministic stand-ins so we can assert the
  recovery-loop's result-mapping / counter logic without live Mollie creds.
* repair_invoices_missing_gl_entries is exercised on its dry-run and
  already-has-GL (skip) branches with real submitted Sales Invoices.

Tests run as Administrator, satisfying the @critical_api(FINANCIAL) gates.
"""

import unittest

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.utils import payment_processing_recovery as rec


def _make_status_obj(payment_id, status="partial", member=None, missing=None):
    """Lightweight stand-in for the orchestrator's ProcessingStatus used by the
    dry-run / status iteration paths. We import the real one so to_dict matches."""
    from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
        ProcessingStatus,
    )

    obj = ProcessingStatus(payment_id=payment_id)
    obj.status = status
    obj.member = member
    obj.missing_documents = missing or []
    return obj


class _FakeResult:
    """Stand-in for PaymentProcessingResult emitted by a stubbed process_payment."""

    def __init__(self, payment_id, status, **kw):
        self.payment_id = payment_id
        self.status = status
        self.error = kw.get("error")
        self.member = kw.get("member")
        self.bank_transaction = kw.get("bank_transaction")
        self.payment_entry = kw.get("payment_entry")
        self.sales_invoice = kw.get("sales_invoice")
        self.actions_taken = kw.get("actions_taken", [])
        self.skipped_reason = kw.get("skipped_reason")


class RecoveryBase(EnhancedTestCase):
    """Shared fixtures for payment-processing-recovery tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._company = get_eur_test_company()
        cls._bank_account = cls._ensure_bank_account(cls._company)
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.company = self._company
        # Dedicated SEPA factory (handles EUR company/currency on invoices).
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        # Unique Mollie-style payment id per test instance.
        self.pid = f"tr_{frappe.generate_hash(length=20)}"
        # The recovery code constructs the Mollie orchestrator (-> MollieClient)
        # even on the dry-run path. On a fresh CI shard the ambient Mollie
        # Settings can carry test_mode=1 with an empty test_secret_key but a
        # populated live_secret_key (left by a sibling test), which defeats the
        # in_test "both keys empty" bypass in MollieClient._get_api_key and makes
        # construction raise "Mollie test API key not configured". We never do
        # real Mollie I/O here, so force the api-key getter to hand back a dummy
        # for the duration of each test, and reset the orchestrator singleton so a
        # client built under polluted settings is not reused.
        self._isolate_mollie_client()

    def _isolate_mollie_client(self):
        """Make MollieClient construction independent of ambient Mollie Settings."""
        from verenigingen.verenigingen_payments.mollie.core import client as client_mod
        from verenigingen.verenigingen_payments.services import (
            mollie_payment_orchestrator as orch_mod,
        )

        real_get_key = client_mod.MollieClient._get_api_key
        client_mod.MollieClient._get_api_key = lambda self: "test_dummy_key_for_tests"
        self.addCleanup(setattr, client_mod.MollieClient, "_get_api_key", real_get_key)

        # The orchestrator is a module-level singleton; a stale instance built
        # under polluted settings would otherwise be reused across tests/shards.
        prev = orch_mod._orchestrator_instance
        orch_mod._orchestrator_instance = None
        self.addCleanup(setattr, orch_mod, "_orchestrator_instance", prev)

    @classmethod
    def _ensure_bank_account(cls, company):
        # We pin bt.currency = "EUR" below, so the chosen Bank Account MUST be an
        # EUR account or Bank Transaction.validate_currency throws. A bare
        # is_company_account lookup can pick up a non-EUR account left by sibling
        # modules in a shared CI process; resolve an EUR-currency account first.
        for filters in (
            {"is_company_account": 1},
            {},
        ):
            for ba in frappe.get_all("Bank Account", filters=filters, pluck="name"):
                account = frappe.db.get_value("Bank Account", ba, "account")
                if account and frappe.db.get_value("Account", account, "account_currency") == "EUR":
                    return ba
        # Fallback: any account (currency check below is skipped if unset).
        return frappe.db.get_value("Bank Account", {"is_company_account": 1}, "name") or frappe.db.get_value(
            "Bank Account", {}, "name"
        )

    # --- fixture builders -------------------------------------------------

    def _make_member_with_customer(self, first_name="Recov"):
        member = self.sepa.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        # The status code resolves member from Customer via the Member.customer
        # back-reference query, so the Customer must point back too in some paths.
        frappe.db.set_value("Customer", customer, "member", member.name)
        member.reload()
        self.assertTrue(member.customer, "member should have a customer")
        return member

    def _make_bank_transaction(self, reference_number, party=None, deposit=10.0, date=None):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or today()
        bt.description = "Mollie payment"
        bt.deposit = deposit
        bt.withdrawal = 0
        bt.currency = "EUR"
        bt.reference_number = reference_number
        if party:
            bt.party_type = "Customer"
            bt.party = party
        if self._bank_account:
            bt.bank_account = self._bank_account
        bt.insert()
        return bt

    def _make_payment_entry(self, reference_no, customer=None):
        """Build a Payment Entry carrying reference_no + party, then mark it
        submitted directly in the DB (docstatus=1). The status logic only reads
        reference_no / party / docstatus=1 — going through real .submit() would
        require full GL/account currency wiring that is irrelevant to the code
        under test (and the EUR test company's accounts trip currency
        validation on a bare PE)."""
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
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.company = self.company
        pe.posting_date = today()
        pe.party_type = "Customer"
        pe.party = customer
        pe.paid_amount = 10.0
        pe.received_amount = 10.0
        pe.reference_no = reference_no
        pe.reference_date = today()
        pe.paid_from = receivable
        pe.paid_to = bank
        pe.flags.ignore_validate = True
        pe.flags.ignore_mandatory = True
        pe.insert(ignore_permissions=True, ignore_mandatory=True)
        frappe.db.set_value("Payment Entry", pe.name, "docstatus", 1, update_modified=False)
        pe.reload()
        return pe

    def _make_sales_invoice(self, customer, coverage_start, coverage_end, submit=True, outstanding=10.0):
        si = self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=outstanding,
            status="Unpaid",
            company=self.company,
            posting_date=today(),
            due_date=today(),
            custom_coverage_start_date=coverage_start,
            custom_coverage_end_date=coverage_end,
            submit=submit,
        )
        return si

    def _link_bt_pe(self, bt_name, pe_name):
        bt = frappe.get_doc("Bank Transaction", bt_name)
        bt.append(
            "payment_entries",
            {"payment_document": "Payment Entry", "payment_entry": pe_name, "allocated_amount": 10.0},
        )
        bt.save(ignore_permissions=True)
        return bt

    def _make_pe_reference(self, pe_name, si_name, allocated_amount=10.0):
        # Add a Payment Entry Reference child row pointing at the SINV directly
        # in DB to avoid re-submitting an already-submitted Payment Entry.
        ref = frappe.new_doc("Payment Entry Reference")
        ref.parent = pe_name
        ref.parenttype = "Payment Entry"
        ref.parentfield = "references"
        ref.reference_doctype = "Sales Invoice"
        ref.reference_name = si_name
        ref.allocated_amount = allocated_amount
        ref.insert(ignore_permissions=True)
        return ref


# =============================================================================
# get_payment_processing_status
# =============================================================================
class TestGetPaymentProcessingStatus(RecoveryBase):
    def test_unprocessed_when_nothing_exists(self):
        status = rec.get_payment_processing_status(self.pid)
        self.assertEqual(status["status"], "unprocessed")
        self.assertFalse(status["has_bank_transaction"])
        self.assertFalse(status["has_payment_entry"])
        self.assertFalse(status["has_sales_invoice"])
        self.assertEqual(
            status["missing_documents"],
            ["Bank Transaction", "Payment Entry", "Sales Invoice"],
        )
        self.assertIsNone(status["member"])

    def test_partial_with_only_bank_transaction(self):
        self._make_bank_transaction(self.pid)
        status = rec.get_payment_processing_status(self.pid)
        self.assertEqual(status["status"], "partial")
        self.assertTrue(status["has_bank_transaction"])
        self.assertIn("Payment Entry", status["missing_documents"])
        self.assertIn("Sales Invoice", status["missing_documents"])
        self.assertNotIn("Bank Transaction", status["missing_documents"])

    def test_member_resolved_from_bank_transaction_party(self):
        member = self._make_member_with_customer("PartyMember")
        self._make_bank_transaction(self.pid, party=member.customer)
        status = rec.get_payment_processing_status(self.pid)
        self.assertEqual(status["member"], member.name)
        self.assertTrue(status["has_bank_transaction"])

    def test_payment_entry_matched_by_reference_no(self):
        member = self._make_member_with_customer("PEref")
        self._make_payment_entry(self.pid, customer=member.customer)
        status = rec.get_payment_processing_status(self.pid)
        self.assertTrue(status["has_payment_entry"])
        self.assertEqual(status["status"], "partial")
        # member resolved from PE party since no BT
        self.assertEqual(status["member"], member.name)

    def test_cancelled_payment_entry_not_matched(self):
        member = self._make_member_with_customer("PEcancel")
        pe = self._make_payment_entry(self.pid, customer=member.customer)
        # Cancel -> docstatus 2, must NOT be picked up (query filters docstatus=1)
        frappe.db.set_value("Payment Entry", pe.name, "docstatus", 2, update_modified=False)
        status = rec.get_payment_processing_status(self.pid)
        self.assertFalse(status["has_payment_entry"])

    def test_unlinked_sales_invoice_found_by_coverage_period(self):
        """Exercises the coverage-period lookup branch: a SINV that matches the
        member's coverage window but is not linked to a PE is found and flagged
        sinv_unlinked, producing a 'partial' status with 'Sales Invoice Link'
        missing."""
        from verenigingen.services.billing.coverage_calculator import (
            calculate_coverage_for_payment_date,
        )

        member = self._make_member_with_customer("CovMember")
        bt = self._make_bank_transaction(self.pid, party=member.customer)
        pe = self._make_payment_entry(self.pid, customer=member.customer)
        self._link_bt_pe(bt.name, pe.name)

        cstart, cend = calculate_coverage_for_payment_date(member.name, today())
        self._make_sales_invoice(member.customer, cstart, cend, outstanding=10.0)

        status = rec.get_payment_processing_status(self.pid)
        self.assertTrue(status["has_sales_invoice"])
        self.assertTrue(status.get("sinv_unlinked"))
        self.assertEqual(status["status"], "partial")
        self.assertIn("Sales Invoice Link", status["missing_documents"])

    def test_partial_when_bt_pe_present_but_not_linked(self):
        """BT + PE + linked SINV via PE reference, but BT not linked to PE ->
        partial with 'Bank Transaction → Payment Entry Link' missing."""
        member = self._make_member_with_customer("NoLink")
        bt = self._make_bank_transaction(self.pid, party=member.customer)
        pe = self._make_payment_entry(self.pid, customer=member.customer)
        # Linked SINV via PE reference (avoids coverage-period unlinked flag).
        si = self._make_sales_invoice(member.customer, today(), today())
        self._make_pe_reference(pe.name, si.name)

        status = rec.get_payment_processing_status(self.pid)
        self.assertTrue(status["has_bank_transaction"])
        self.assertTrue(status["has_payment_entry"])
        self.assertTrue(status["has_sales_invoice"])
        self.assertEqual(status["status"], "partial")
        self.assertIn("Bank Transaction → Payment Entry Link", status["missing_documents"])
        self.assertFalse(status.get("bt_pe_linked"))

    def test_complete_when_all_linked(self):
        """BT linked to PE, SINV linked to PE reference -> complete."""
        member = self._make_member_with_customer("Complete")
        bt = self._make_bank_transaction(self.pid, party=member.customer)
        pe = self._make_payment_entry(self.pid, customer=member.customer)
        self._link_bt_pe(bt.name, pe.name)
        si = self._make_sales_invoice(member.customer, today(), today())
        self._make_pe_reference(pe.name, si.name)

        status = rec.get_payment_processing_status(self.pid)
        self.assertTrue(status.get("bt_pe_linked"))
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["missing_documents"], [])


# =============================================================================
# analyze_payment_gaps
# =============================================================================
class TestAnalyzePaymentGaps(RecoveryBase):
    def test_gap_analysis_counts_partial_payment(self):
        # One BT with tr_ reference, only BT present -> a gap.
        self._make_bank_transaction(self.pid)
        analysis = rec.analyze_payment_gaps()
        self.assertGreaterEqual(analysis["total_bank_transactions"], 1)
        pids = [g["payment_id"] for g in analysis["gap_details"]]
        self.assertIn(self.pid, pids)
        gap = next(g for g in analysis["gap_details"] if g["payment_id"] == self.pid)
        self.assertIn("Payment Entry", gap["missing"])
        self.assertIn("Sales Invoice", gap["missing"])

    def test_gap_analysis_keys_present(self):
        analysis = rec.analyze_payment_gaps()
        for key in (
            "total_bank_transactions",
            "missing_invoices",
            "missing_payment_entries",
            "missing_both",
            "complete",
            "gap_details",
            "timestamp",
        ):
            self.assertIn(key, analysis)


# =============================================================================
# get_incomplete_payments
# =============================================================================
class TestGetIncompletePayments(RecoveryBase):
    def test_explicit_unprocessed_ids_counted(self):
        result = rec.get_incomplete_payments(payment_ids=[self.pid])
        self.assertEqual(result["total_checked"], 1)
        self.assertEqual(result["unprocessed"], 1)
        self.assertEqual(len(result["incomplete_payments"]), 1)
        self.assertEqual(result["incomplete_payments"][0]["payment_id"], self.pid)

    def test_json_string_payment_ids_accepted(self):
        """REGRESSION: get_incomplete_payments accepts a JSON-string payment_ids
        from the HTTP layer. Its body handles `if isinstance(payment_ids, str):
        json.loads`, so the annotation is `Union[List[str], str, None]`; under
        Frappe v16 a bare `List[str]` annotation made the whitelist type gate
        reject the str arg before the body ran (FrappeTypeError). Fixed."""
        import json

        result = rec.get_incomplete_payments(payment_ids=json.dumps([self.pid]))
        self.assertEqual(result["total_checked"], 1)
        self.assertEqual(result["unprocessed"], 1)

    def test_partial_payment_classified(self):
        # A BT alone (with member party) -> orchestrator reports 'partial'.
        member = self._make_member_with_customer("IncPartial")
        self._make_bank_transaction(self.pid, party=member.customer)
        result = rec.get_incomplete_payments(payment_ids=[self.pid])
        self.assertEqual(result["total_checked"], 1)
        self.assertEqual(result["partial"] + result["unprocessed"], 1)
        self.assertEqual(len(result["incomplete_payments"]), 1)


# =============================================================================
# complete_partial_payments
# =============================================================================
class TestCompletePartialPaymentsDryRun(RecoveryBase):
    def test_dry_run_reports_without_changes(self):
        member = self._make_member_with_customer("DryRun")
        self._make_bank_transaction(self.pid, party=member.customer)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total_requested"], 1)
        self.assertEqual(result["completed"], 0)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["status"], "dry_run")
        self.assertEqual(result["results"][0]["payment_id"], self.pid)

    def test_dry_run_string_flag_coerced(self):
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run="true")
        self.assertTrue(result["dry_run"])

    def test_invalid_payment_id_skipped(self):
        result = rec.complete_partial_payments(payment_ids=["not-a-mollie-id"], dry_run=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["results"][0]["status"], "skipped")
        self.assertIn("Invalid payment ID format", result["results"][0]["reason"])

    def test_max_payments_limit_applied(self):
        ids = [f"tr_{frappe.generate_hash(length=18)}" for _ in range(3)]
        result = rec.complete_partial_payments(payment_ids=ids, dry_run=True, max_payments=2)
        self.assertTrue(result.get("limited"))
        self.assertEqual(result["total_found"], 3)
        self.assertEqual(result["total_requested"], 2)

    def test_max_payments_string_coerced(self):
        ids = [f"tr_{frappe.generate_hash(length=18)}" for _ in range(3)]
        result = rec.complete_partial_payments(payment_ids=ids, dry_run=True, max_payments="2")
        self.assertEqual(result["total_requested"], 2)

    def test_json_string_payment_ids(self):
        """REGRESSION: complete_partial_payments accepts a JSON-string payment_ids.
        Its body handles `if isinstance(payment_ids, str): json.loads`, so the
        annotation is `Union[List[str], str, None]`; a bare `List[str]` made the
        Frappe v16 whitelist type gate reject the str arg before the body ran
        (FrappeTypeError). Fixed."""
        import json

        result = rec.complete_partial_payments(payment_ids=json.dumps([self.pid]), dry_run=True)
        self.assertEqual(result["total_requested"], 1)

    def test_auto_discovery_no_incomplete_returns_message(self):
        """When no ids are given and discovery finds nothing incomplete, a
        message is returned. We stub get_incomplete_payments to return an empty
        set (config boundary: avoids scanning ambient site BTs)."""
        import verenigingen.verenigingen_payments.utils.payment_processing_recovery as mod

        orig = mod.get_incomplete_payments
        mod.get_incomplete_payments = lambda *a, **k: {"incomplete_payments": []}
        try:
            result = rec.complete_partial_payments(payment_ids=None, dry_run=True)
        finally:
            mod.get_incomplete_payments = orig
        self.assertEqual(result.get("message"), "No incomplete payments found")


class TestCompletePartialPaymentsRecovery(RecoveryBase):
    """Non-dry-run recovery loop. The Mollie HTTP boundary inside
    orchestrator.process_payment is stubbed; everything else is real."""

    def _patch_orchestrator(self, process_payment=None, process_orphan=None):
        from verenigingen.verenigingen_payments.services import (
            mollie_payment_orchestrator as orch_mod,
        )

        real_get = orch_mod.get_payment_orchestrator
        orchestrator = real_get()
        if process_payment:
            orchestrator.process_payment = process_payment
        if process_orphan:
            orchestrator.process_orphaned_payment_with_invoice = process_orphan

        # Patch BOTH the module-level symbol and the recovery module's import.
        import verenigingen.verenigingen_payments.utils.payment_processing_recovery as mod

        orch_mod.get_payment_orchestrator = lambda: orchestrator
        self.addCleanup(setattr, orch_mod, "get_payment_orchestrator", real_get)
        # the recovery module imports get_payment_orchestrator lazily inside the
        # function via `from ... import get_payment_orchestrator`, so patching the
        # source module attribute is sufficient.
        return orchestrator, mod

    def test_recovery_success_counted_as_completed(self):
        def fake_process(payment_id, create_missing_invoice=False):
            return _FakeResult(
                payment_id,
                "success",
                member="MEM-X",
                bank_transaction="BT-X",
                payment_entry="PE-X",
                sales_invoice="SI-X",
                actions_taken=["created_pe"],
            )

        self._patch_orchestrator(process_payment=fake_process)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=False)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(result["results"][0]["status"], "completed")
        self.assertEqual(result["results"][0]["sales_invoice"], "SI-X")

    def test_recovery_already_processed_counted_as_skipped(self):
        def fake_process(payment_id, create_missing_invoice=False):
            return _FakeResult(payment_id, "already_processed", skipped_reason="exists")

        self._patch_orchestrator(process_payment=fake_process)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=False)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["results"][0]["status"], "skipped")
        self.assertEqual(result["results"][0]["reason"], "exists")

    def test_recovery_error_counted(self):
        def fake_process(payment_id, create_missing_invoice=False):
            return _FakeResult(payment_id, "error", error="boom")

        self._patch_orchestrator(process_payment=fake_process)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=False)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertEqual(result["results"][0]["error"], "boom")

    def test_orphan_processing_path(self):
        """member-not-found error + process_orphans=True -> orphan handler runs
        and a success increments orphans_processed."""

        def fake_process(payment_id, create_missing_invoice=False):
            return _FakeResult(payment_id, "error", error="Cannot determine member for payment")

        def fake_orphan(payment_id):
            return _FakeResult(payment_id, "success", sales_invoice="ORPH-SI")

        self._patch_orchestrator(process_payment=fake_process, process_orphan=fake_orphan)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=False, process_orphans=True)
        self.assertEqual(result["orphans_processed"], 1)
        self.assertEqual(result["completed"], 1)
        self.assertEqual(result["results"][0]["sales_invoice"], "ORPH-SI")

    def test_orphan_flag_string_coerced(self):
        def fake_process(payment_id, create_missing_invoice=False):
            return _FakeResult(payment_id, "error", error="Cannot determine member for payment")

        def fake_orphan(payment_id):
            return _FakeResult(payment_id, "success")

        self._patch_orchestrator(process_payment=fake_process, process_orphan=fake_orphan)
        result = rec.complete_partial_payments(payment_ids=[self.pid], dry_run=False, process_orphans="true")
        self.assertEqual(result["process_orphans"], True)
        self.assertEqual(result["orphans_processed"], 1)


# =============================================================================
# repair_invoices_missing_gl_entries
# =============================================================================
class TestRepairInvoicesMissingGLEntries(RecoveryBase):
    def test_dry_run_with_explicit_invoice_having_gl_is_skipped(self):
        """A normally-submitted invoice has GL entries, so it is skipped even in
        dry_run (the GL-count check precedes the dry_run branch)."""
        member = self._make_member_with_customer("GLskip")
        si = self._make_sales_invoice(member.customer, today(), today())
        gl_count = frappe.db.count("GL Entry", {"voucher_type": "Sales Invoice", "voucher_no": si.name})
        self.assertGreater(gl_count, 0, "submitted SINV should have GL entries")

        result = rec.repair_invoices_missing_gl_entries(invoice_names=[si.name], dry_run=True)
        self.assertEqual(result["total_checked"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["repaired"], 0)
        self.assertEqual(result["results"][0]["status"], "skipped")

    def test_json_string_invoice_names_and_dry_run_flag(self):
        """REGRESSION: repair_invoices_missing_gl_entries accepts a JSON-string
        invoice_names. Its body handles `if isinstance(invoice_names, str):
        json.loads`, so the annotation is `Union[List[str], str, None]`; a bare
        `List[str]` made the Frappe v16 whitelist type gate reject the str arg
        before the body ran (FrappeTypeError). Fixed."""
        import json

        member = self._make_member_with_customer("GLjson")
        si = self._make_sales_invoice(member.customer, today(), today())
        result = rec.repair_invoices_missing_gl_entries(invoice_names=json.dumps([si.name]), dry_run="true")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total_checked"], 1)

    def test_error_path_for_nonexistent_invoice(self):
        result = rec.repair_invoices_missing_gl_entries(
            invoice_names=["SINV-DOES-NOT-EXIST-XYZ"], dry_run=False
        )
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertIsNotNone(result["results"][0]["error"])

    def test_result_keys_present(self):
        # NOTE: an empty list is falsy, so this triggers AUTO-DISCOVERY of all
        # submitted invoices lacking GL entries; we assert only the result shape
        # + dry_run flag, never touching ambient site state.
        result = rec.repair_invoices_missing_gl_entries(invoice_names=["SINV-NONE-XYZ"], dry_run=True)
        for key in ("total_checked", "repaired", "skipped", "errors", "results", "dry_run", "timestamp"):
            self.assertIn(key, result)
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["total_checked"], 1)


# =============================================================================
# Module-targeting sanity check
# =============================================================================
class TestModuleTarget(unittest.TestCase):
    def test_targets_verenigingen_payments_copy(self):
        self.assertIn(
            "verenigingen_payments/utils/payment_processing_recovery.py",
            rec.__file__,
        )


if __name__ == "__main__":
    unittest.main()
