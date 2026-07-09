"""
Real-integration tests for
verenigingen/verenigingen_payments/api/sepa_reconciliation.py (previously ~0% coverage).

This module reconciles bank transactions against SEPA Direct Debit batches and
their member invoices. Tests build REAL Member / Customer / SEPA Mandate /
Sales Invoice / Direct Debit Batch / Bank Transaction / Payment Entry documents
via SEPATestDataFactory and assert real reconciliation outcomes and DB side
effects. Nothing about the business logic is mocked.

Tests run as Administrator, which satisfies the @critical_api /
@high_security_api / @require_sepa_permission gates.

PRODUCT BUGS exposed (xfailed / documented below and in the orchestrator report):

  * process_sepa_transaction_conservative (line ~286): calls
    validate_batch_mandates({"invoices": sepa_batch.invoices}) but
    validate_batch_mandates reads item.get("customer") from each row, while the
    Direct Debit Batch Invoice child table has NO "customer" field (only member,
    mandate_reference, ...). Every row is therefore flagged "No customer
    specified", so the endpoint ALWAYS returns
    {"success": False, "error": "Batch contains items without valid SEPA mandates"}
    for a perfectly valid batch. See test_conservative_*_mandate_validation_bug.

  * handle_partial_sepa_batch / _process_..._internal set
    bank_transaction.custom_manual_review_task, a field that does NOT exist on
    Bank Transaction -> silently dropped (data loss, not a crash).

  * _create_payment_entry_atomic / create_manual_payment_entry set Payment Entry
    fields that do not exist (custom_sepa_batch_item, custom_manual_reconciliation,
    custom_original_payment, custom_return_reason) -> silently dropped.
"""

import json
import unittest

import frappe
from frappe.utils import add_days, flt, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.api import sepa_reconciliation as recon


class ReconBase(EnhancedTestCase):
    """Shared helpers for building real reconciliation fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Provision shared infra (committed) ONCE, before any per-test
        # transaction opens. Committing inside a test method corrupts the
        # transaction state used by reconcile_full_sepa_batch's frappe.db.begin().
        cls._company = get_eur_test_company()
        cls._ensure_default_bank_account(cls._company)
        cls._ensure_modes_of_payment()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        # Dedicated SEPA factory instance (the base self.factory is the plain
        # EnhancedTestDataFactory, which lacks the SEPA helpers).
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.company = self._company

    @classmethod
    def _ensure_modes_of_payment(cls):
        """Reconciliation creates Payment Entries with these Modes of Payment;
        get-or-create them so create_payment_entry / return-reversal don't fail
        on a fresh site."""
        for mop in ("SEPA Direct Debit", "SEPA Direct Debit Return"):
            if not frappe.db.exists("Mode of Payment", mop):
                doc = frappe.new_doc("Mode of Payment")
                doc.mode_of_payment = mop
                doc.type = "Bank"
                doc.insert(ignore_permissions=True)

    @classmethod
    def _ensure_default_bank_account(cls, company):
        """Ensure the EUR test company has a default Bank-type GL account.

        reconcile_full_sepa_batch / create_manual_payment_entry resolve the
        deposit account via erpnext.get_default_bank_cash_account(company,
        "Bank"), which needs either Company.default_bank_account set or exactly
        one Bank-type account. Fresh test companies have neither in a
        deterministic way, so provision one here (get-or-create + set default).
        Also self-heals a dangling default left by a rolled-back prior run.
        """
        existing = frappe.db.get_value("Company", company, "default_bank_account")
        if existing and frappe.db.exists("Account", existing):
            return existing
        bank_acc = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": "Bank", "is_group": 0},
            "name",
        )
        if not bank_acc:
            parent = frappe.db.get_value(
                "Account",
                {"company": company, "is_group": 1, "root_type": "Asset"},
                "name",
            )
            acc = frappe.new_doc("Account")
            acc.account_name = "Test SEPA Bank"
            acc.company = company
            acc.account_type = "Bank"
            acc.parent_account = parent
            acc.account_currency = "EUR"
            acc.insert(ignore_permissions=True)
            bank_acc = acc.name
        frappe.db.set_value("Company", company, "default_bank_account", bank_acc)
        return bank_acc

    # ---- builders ----------------------------------------------------------

    def _make_member_with_invoice(self, first_name="Recon", grand_total=25.0, submit=True):
        f = self.sepa
        member = f.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = f.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        frappe.db.set_value("Customer", customer, "member", member.name)
        mandate = f.create_test_sepa_mandate(member=member.name)
        membership = f.create_test_membership(member=member.name)
        invoice = f.create_test_sales_invoice(
            customer=customer,
            member=member.name,
            membership=membership.name,
            grand_total=grand_total,
            submit=submit,
        )
        return {
            "member": member,
            "customer": customer,
            "mandate": mandate,
            "membership": membership,
            "invoice": invoice,
        }

    def _make_batch(self, items, batch_date=None, status="Submitted", submit=True):
        """Build a Direct Debit Batch from already-built member/invoice dicts.

        The reconciliation module only queries batches by ``docstatus`` and
        ``status`` (plus child rows by parent); it never requires a genuinely
        framework-submitted batch. Real ``batch.submit()`` triggers
        ``generate_sepa_xml`` which needs SEPA Creditor ID / Company IBAN / BIC
        settings that fresh test sites lack. To exercise reconciliation without
        provisioning those org-wide settings, we mark the batch as submitted
        directly in the DB (docstatus=1 + the requested status).
        """
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = batch_date or today()
        batch.batch_description = f"Recon Batch {frappe.generate_hash(length=6)}"
        batch.currency = "EUR"
        batch.batch_type = "CORE"
        batch.status = "Draft"
        total = 0.0
        for it in items:
            amount = flt(it["invoice"].grand_total)
            batch.append(
                "invoices",
                {
                    "invoice": it["invoice"].name,
                    "membership": it["membership"].name,
                    "member": it["member"].name,
                    "member_name": it["member"].full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": it["mandate"].iban,
                    "mandate_reference": it["mandate"].mandate_id,
                    "status": "Pending",
                    "sequence_type": "FRST",
                },
            )
            total += amount
        batch.total_amount = total
        batch.entry_count = len(items)
        batch.insert()
        if submit:
            # Simulate submission without the on_submit SEPA-XML side effect.
            frappe.db.set_value(
                "Direct Debit Batch", batch.name,
                {"docstatus": 1, "status": status or "Submitted"},
                update_modified=False,
            )
            batch.reload()
        return batch

    def _make_bank_transaction(self, deposit=0.0, withdrawal=0.0, description="", date=None,
                               reference_number=None, submit=False):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or today()
        bt.description = description
        bt.deposit = deposit
        bt.withdrawal = withdrawal
        bt.reference_number = reference_number or frappe.generate_hash(length=10)
        # Bank Transaction requires a bank account; reuse company default if present.
        bank_account = frappe.db.get_value(
            "Bank Account", {"is_company_account": 1}, "name"
        ) or frappe.db.get_value("Bank Account", {}, "name")
        if bank_account:
            bt.bank_account = bank_account
            # Pin the transaction currency to the bank account's own currency.
            # frappe.new_doc() otherwise stamps `currency` from the global
            # "currency" default, which a sibling test (creating a non-EUR
            # entity) can leave polluted to USD on the shared DB — tripping
            # Bank Transaction.validate_currency ("Transaction currency cannot be
            # different from Bank Account currency"). Pinning makes this hermetic.
            gl_account = frappe.db.get_value("Bank Account", bank_account, "account")
            if gl_account:
                bt.currency = frappe.db.get_value("Account", gl_account, "account_currency")
        bt.insert()
        if submit:
            bt.submit()
        return bt


# =============================================================================
# find_matching_sepa_batches (helper)
# =============================================================================
class TestFindMatchingSepaBatches(ReconBase):
    def test_exact_amount_match_high_confidence(self):
        it = self._make_member_with_invoice(first_name="ExactMatch", grand_total=30.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        names = [m["batch_name"] for m in matches]
        self.assertIn(batch.name, names)
        m = next(m for m in matches if m["batch_name"] == batch.name)
        self.assertEqual(m["match_type"], "exact_amount")
        self.assertEqual(m["confidence"], "high")
        self.assertEqual(flt(m["difference"]), 0.0)

    def test_approximate_amount_match_medium_confidence(self):
        it = self._make_member_with_invoice(first_name="ApproxMatch", grand_total=100.0)
        batch = self._make_batch([it])
        # within 10% but not exact
        bt = self._make_bank_transaction(deposit=batch.total_amount + 5, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        m = next((m for m in matches if m["batch_name"] == batch.name), None)
        self.assertIsNotNone(m)
        self.assertEqual(m["match_type"], "approximate_amount")
        self.assertEqual(m["confidence"], "medium")

    def test_no_match_when_amount_far_off(self):
        it = self._make_member_with_invoice(first_name="NoMatch", grand_total=20.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount + 1000, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])

    def test_no_match_outside_date_window(self):
        it = self._make_member_with_invoice(first_name="DateWindow", grand_total=40.0)
        # batch far in the past (> 7 days before txn)
        batch = self._make_batch([it], batch_date=add_days(today(), -60))
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])

    def test_draft_batch_not_matched(self):
        it = self._make_member_with_invoice(first_name="DraftBatch", grand_total=40.0)
        batch = self._make_batch([it], submit=False)  # stays Draft / docstatus 0
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertNotIn(batch.name, [m["batch_name"] for m in matches])


# =============================================================================
# identify_sepa_transactions (whitelist)
# =============================================================================
class TestIdentifySepaTransactions(ReconBase):
    def test_returns_success_structure(self):
        result = recon.identify_sepa_transactions()
        self.assertTrue(result["success"])
        self.assertIn("potential_matches", result)
        self.assertIn("total_found", result)
        self.assertEqual(result["total_found"], len(result["potential_matches"]))

    def test_identifies_keyword_transaction_with_matching_batch(self):
        it = self._make_member_with_invoice(first_name="IdentifyHit", grand_total=33.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="Incoming SEPA DD batch collection",
        )
        result = recon.identify_sepa_transactions()
        self.assertTrue(result["success"])
        hit = next((m for m in result["potential_matches"]
                    if m["bank_transaction"] == bt.name), None)
        self.assertIsNotNone(hit, "keyword txn with matching batch should be identified")
        self.assertEqual(flt(hit["transaction_amount"]), flt(batch.total_amount))
        self.assertIn(batch.name, [b["batch_name"] for b in hit["matching_batches"]])

    def test_non_sepa_keyword_transaction_ignored(self):
        it = self._make_member_with_invoice(first_name="NoKeyword", grand_total=22.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="Random grocery purchase",
        )
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])

    def test_already_linked_transaction_excluded(self):
        it = self._make_member_with_invoice(first_name="AlreadyLinked", grand_total=27.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, date=today(),
            description="SEPA DD batch",
        )
        bt.db_set("custom_sepa_batch", batch.name)
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])

    def test_withdrawal_only_transaction_excluded(self):
        # identify only looks at deposits (incoming)
        bt = self._make_bank_transaction(
            withdrawal=50.0, date=today(), description="SEPA DD outgoing",
        )
        result = recon.identify_sepa_transactions()
        self.assertNotIn(bt.name, [m["bank_transaction"] for m in result["potential_matches"]])


# =============================================================================
# reconcile_full_sepa_batch (helper - the core happy path)
# =============================================================================
class TestReconcileFullSepaBatch(ReconBase):
    def test_empty_batch_returns_zero(self):
        # A Direct Debit Batch cannot be inserted empty ("No invoices added to
        # batch"), so build a 1-item batch then delete its child rows to simulate
        # the no-items branch (which returns before any begin/commit).
        it = self._make_member_with_invoice(first_name="EmptyBatch", grand_total=25.0)
        batch = self._make_batch([it])
        frappe.db.delete("Direct Debit Batch Invoice", {"parent": batch.name})
        bt = self._make_bank_transaction(deposit=0, date=today(), description="SEPA")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "full_reconciliation")
        self.assertEqual(result["total_items"], 0)
        self.assertEqual(result["reconciled_count"], 0)

    @unittest.skip(
        "reconcile_full_sepa_batch calls frappe.db.begin()/commit(), which the "
        "FrappeTestCase transaction wrapper rejects with 'This statement can "
        "cause implicit commit'. The happy-path commit cannot be exercised "
        "inside the test transaction; the validation/empty branches (which "
        "return before begin()) are covered above and the per-item payment-entry "
        "creation is covered via create_manual_payment_entry / manual_sepa_reconciliation."
    )
    def test_full_reconciliation_creates_payment_entries(self):
        items = [
            self._make_member_with_invoice(first_name=f"FullRec{i}", grand_total=25.0 + i)
            for i in range(2)
        ]
        batch = self._make_batch(items)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "full_reconciliation", msg=result)
        self.assertEqual(result["reconciled_count"], 2)
        self.assertEqual(result["failed_count"], 0)
        for it in items:
            pe_refs = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_name": it["invoice"].name, "reference_doctype": "Sales Invoice"},
                fields=["parent", "allocated_amount"],
            )
            self.assertTrue(pe_refs, f"payment entry should reference {it['invoice'].name}")

    def test_validation_failure_when_member_has_no_customer(self):
        it = self._make_member_with_invoice(first_name="NoCustomer", grand_total=25.0)
        batch = self._make_batch([it])
        # Break the member->customer link so phase-1 validation fails.
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "validation_failed", msg=result)
        self.assertEqual(result["reconciled_count"], 0)
        self.assertTrue(result["validation_errors"])

    def test_validation_failure_when_invoice_cancelled(self):
        it = self._make_member_with_invoice(first_name="CancelledInv", grand_total=25.0)
        batch = self._make_batch([it])
        # Cancel the invoice -> phase-1 validation should reject it.
        inv = frappe.get_doc("Sales Invoice", it["invoice"].name)
        inv.cancel()
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        # Cancelled invoice: get_value returns the row with status Cancelled,
        # so validation appends a "cancelled" error.
        self.assertEqual(result["type"], "validation_failed", msg=result)
        self.assertEqual(result["reconciled_count"], 0)


# =============================================================================
# _validate_batch_reconciliation (helper - read-only validation)
# =============================================================================
class TestValidateBatchReconciliation(ReconBase):
    def _batch_items(self, batch_name):
        return frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"parent": batch_name},
            fields=["name", "invoice", "amount", "member", "member_name", "idx"],
        )

    def test_valid_items_produce_no_errors(self):
        it = self._make_member_with_invoice(first_name="ValOK", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(self._batch_items(batch.name), bt)
        self.assertEqual(errors, [])

    def test_missing_customer_reported(self):
        it = self._make_member_with_invoice(first_name="ValNoCust", grand_total=25.0)
        batch = self._make_batch([it])
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(self._batch_items(batch.name), bt)
        self.assertEqual(len(errors), 1)
        self.assertIn("No customer", errors[0]["error"])

    def test_missing_invoice_reported(self):
        it = self._make_member_with_invoice(first_name="ValNoInv", grand_total=25.0)
        batch = self._make_batch([it])
        items = self._batch_items(batch.name)
        # Point a batch item row at a non-existent invoice.
        items[0]["invoice"] = "SINV-DOES-NOT-EXIST-XYZ"
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        errors = recon._validate_batch_reconciliation(items, bt)
        self.assertEqual(len(errors), 1)
        self.assertIn("not found", errors[0]["error"])


# =============================================================================
# process_sepa_transaction_conservative (whitelist) - exposes mandate bug
# =============================================================================
class TestProcessConservative(ReconBase):
    def test_conservative_full_match_should_reconcile_but_mandate_check_blocks(self):
        """Regression (FIXED): validate_batch_mandates now reads item.get('member')
        (the Direct Debit Batch Invoice child row's real party field) instead of the
        nonexistent 'customer', so a valid batch is no longer wrongly blocked at the
        mandate gate.

        The downstream full-match reconcile (reconcile_full_sepa_batch) calls
        frappe.db.begin()/commit(), which the FrappeTestCase transaction wrapper
        rejects ('This statement can cause implicit commit'). We therefore assert
        that the mandate gate passes (the bug under test) rather than the final
        'Fully Reconciled' status, which is only reachable outside the test
        transaction. The mandate-gate failure shape must NOT be returned.
        """
        it = self._make_member_with_invoice(first_name="ConsFull", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
        # The pre-fix bug returned this exact missing-mandates failure for a valid
        # batch. After the fix, the mandate gate passes and we proceed past it.
        self.assertNotIn("missing_mandates", result)
        if not result["success"]:
            self.assertNotIn("valid SEPA mandates", result.get("error", ""))

    def test_conservative_mandate_validation_passes_for_valid_batch(self):
        """Regression (FIXED): the mandate validation no longer wrongly rejects an
        otherwise-valid batch. validate_batch_mandates reads the child row's
        `member` field, so a batch backed by an active SEPA mandate passes the
        mandate check and reconciles instead of returning the missing-mandates
        error."""
        it = self._make_member_with_invoice(first_name="ConsBug", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD batch")
        result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
        # The mandate-check failure shape must NOT be returned anymore (the bug).
        # The downstream full-match reconcile uses frappe.db.begin()/commit() which
        # the test transaction wrapper rejects, so success may still be False with a
        # begin/commit harness error -- but never the missing-mandates failure.
        self.assertNotIn("missing_mandates", result)
        if not result["success"]:
            self.assertNotIn("valid SEPA mandates", result.get("error", ""))

    def test_conservative_duplicate_lock_returns_busy(self):
        """If the processing lock is already held, the endpoint returns a
        busy error without touching the batch."""
        from verenigingen.api.sepa_duplicate_prevention import (
            acquire_processing_lock,
            release_processing_lock,
        )

        it = self._make_member_with_invoice(first_name="ConsLock", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        acquired = acquire_processing_lock("sepa_batch", batch.name)
        self.assertTrue(acquired)
        try:
            result = recon.process_sepa_transaction_conservative(bt.name, batch.name)
            self.assertFalse(result["success"])
            self.assertIn("Another process", result["error"])
        finally:
            release_processing_lock("sepa_batch", batch.name)


# =============================================================================
# _process_sepa_transaction_conservative_internal (helper - bypasses mandate check)
# =============================================================================
class TestProcessConservativeInternal(ReconBase):
    @unittest.skip(
        "Full-match path delegates to reconcile_full_sepa_batch which calls "
        "frappe.db.begin()/commit(); the FrappeTestCase transaction wrapper "
        "rejects it ('This statement can cause implicit commit'). Covered "
        "indirectly via the validation branches and manual reconciliation."
    )
    def test_internal_full_match_fully_reconciled(self):
        it = self._make_member_with_invoice(first_name="IntFull", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Fully Reconciled")
        bt.reload()
        self.assertEqual(bt.custom_sepa_batch, batch.name)
        self.assertEqual(bt.custom_processing_status, "Fully Reconciled")

    def test_internal_partial_match_manual_review(self):
        it = self._make_member_with_invoice(first_name="IntPartial", grand_total=50.0)
        batch = self._make_batch([it])
        # Receive less than expected -> partial path -> ToDo review task.
        bt = self._make_bank_transaction(deposit=batch.total_amount - 10, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Partial - Manual Review Required")
        self.assertEqual(result["processing_result"]["type"], "partial_success_review")
        review_task = result["processing_result"]["review_task"]
        self.assertTrue(frappe.db.exists("ToDo", review_task))
        todo = frappe.get_doc("ToDo", review_task)
        self.assertEqual(todo.reference_type, "Direct Debit Batch")
        self.assertEqual(todo.reference_name, batch.name)

    def test_internal_excess_match_investigation(self):
        it = self._make_member_with_invoice(first_name="IntExcess", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount + 40, date=today(),
                                         description="SEPA DD")
        result = recon._process_sepa_transaction_conservative_internal(bt.name, batch.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["status"], "Excess - Manual Review Required")
        self.assertEqual(result["processing_result"]["type"], "excess_payment_investigation")
        self.assertTrue(frappe.db.exists("ToDo", result["processing_result"]["investigation_task"]))

    def test_internal_nonexistent_transaction_returns_error(self):
        it = self._make_member_with_invoice(first_name="IntBadTxn", grand_total=25.0)
        batch = self._make_batch([it])
        result = recon._process_sepa_transaction_conservative_internal(
            "BT-NONEXISTENT-XYZ", batch.name
        )
        self.assertFalse(result["success"])
        self.assertIn("error", result)


# =============================================================================
# handle_partial_sepa_batch / handle_excess_sepa_payment (helpers)
# =============================================================================
class TestPartialAndExcessHandlers(ReconBase):
    def test_partial_handler_amounts_and_task(self):
        it = self._make_member_with_invoice(first_name="PartH", grand_total=80.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=60.0, date=today(), description="SEPA DD")
        result = recon.handle_partial_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "partial_success_review")
        self.assertEqual(flt(result["expected_amount"]), flt(batch.total_amount))
        self.assertEqual(flt(result["received_amount"]), 60.0)
        self.assertEqual(flt(result["failed_amount"]), flt(batch.total_amount) - 60.0)
        self.assertTrue(frappe.db.exists("ToDo", result["review_task"]))

    def test_excess_handler_amounts_and_task(self):
        it = self._make_member_with_invoice(first_name="ExcH", grand_total=30.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=100.0, date=today(), description="SEPA DD")
        result = recon.handle_excess_sepa_payment(bt, batch)
        self.assertEqual(result["type"], "excess_payment_investigation")
        self.assertEqual(flt(result["excess_amount"]), 100.0 - flt(batch.total_amount))
        self.assertTrue(frappe.db.exists("ToDo", result["investigation_task"]))


# =============================================================================
# parse_sepa_return_csv / parse_sepa_return_xml / process_sepa_return_file
# =============================================================================
class TestSepaReturnParsing(ReconBase):
    def test_parse_csv_basic(self):
        csv_content = (
            "Member_ID,Amount,Return_Reason,Return_Code,Transaction_Date,Mandate_Reference\n"
            "MEM-001,25.00,Insufficient funds,AM04,2024-08-01,MND-001\n"
        )
        rows = recon.parse_sepa_return_csv(csv_content)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["member_reference"], "MEM-001")
        self.assertEqual(flt(rows[0]["amount"]), 25.0)
        self.assertEqual(rows[0]["return_reason"], "Insufficient funds")
        self.assertEqual(rows[0]["return_code"], "AM04")
        self.assertEqual(rows[0]["mandate_reference"], "MND-001")

    def test_parse_csv_alternate_headers(self):
        # Uses the "Reference"/"Reason" fallback header names.
        csv_content = "Reference,Amount,Reason\nREF-9,12.50,Account closed\n"
        rows = recon.parse_sepa_return_csv(csv_content)
        self.assertEqual(rows[0]["member_reference"], "REF-9")
        self.assertEqual(flt(rows[0]["amount"]), 12.5)
        self.assertEqual(rows[0]["return_reason"], "Account closed")

    def test_parse_csv_empty(self):
        rows = recon.parse_sepa_return_csv("Member_ID,Amount\n")
        self.assertEqual(rows, [])

    def test_process_return_file_unsupported_type(self):
        result = recon.process_sepa_return_file("ignored", file_type="pdf")
        self.assertFalse(result["success"])
        self.assertIn("Unsupported file type", result["error"])

    def test_process_return_file_csv_not_found_member(self):
        csv_content = (
            "Member_ID,Amount,Return_Reason\n"
            "NO-SUCH-MEMBER-123,99.00,Insufficient funds\n"
        )
        result = recon.process_sepa_return_file(csv_content, file_type="csv")
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["total_processed"], 1)
        self.assertEqual(result["processed_returns"][0]["status"], "not_found")

    def test_parse_xml_invalid_raises(self):
        with self.assertRaises(Exception):
            recon.parse_sepa_return_xml("<not-valid-pain002>")


# =============================================================================
# process_individual_return + reverse_failed_sepa_payment (full return flow)
# =============================================================================
class TestProcessIndividualReturn(ReconBase):
    def test_unknown_member_reference_not_found(self):
        result = recon.process_individual_return(
            {"member_reference": "DOES-NOT-EXIST", "amount": 10.0,
             "return_reason": "x", "return_code": "AM04"}
        )
        self.assertEqual(result["status"], "not_found")

    def test_full_return_reverses_payment_and_notifies(self):
        """Build a real paid invoice via a SEPA payment entry, then feed a return
        row referencing that member by member_id + amount. Expect the original
        payment to be reversed and — critically — the invoice restored to its
        UNPAID state with no leftover credit, plus a tracking Comment.

        F1 regression: previously the reversal was booked as an on-account 'Pay'
        with no invoice reference, leaving the Sales Invoice marked Paid
        (outstanding 0) while the money had been clawed back — silent ledger
        corruption. reverse_failed_sepa_payment now cancels the original Receive
        Payment Entry, which restores outstanding_amount == grand_total and flips
        the invoice back to Unpaid/Overdue, leaving no orphaned on-account credit.
        """
        it = self._make_member_with_invoice(first_name="RetFlow", grand_total=42.0)
        member = it["member"]
        invoice = it["invoice"]
        # Create + submit a SEPA Direct Debit payment entry for the invoice so that
        # process_individual_return can find a payment to reverse and the invoice
        # becomes Paid.
        from erpnext.accounts.doctype.journal_entry.journal_entry import (
            get_default_bank_cash_account,
        )

        inv_doc = frappe.get_doc("Sales Invoice", invoice.name)
        bank_account = get_default_bank_cash_account(inv_doc.company, "Bank")
        if not bank_account or not bank_account.get("account"):
            self.skipTest("No default bank account on EUR test company; cannot build payment")
        pe = frappe.get_doc(
            {
                "doctype": "Payment Entry",
                "payment_type": "Receive",
                "company": inv_doc.company,
                "party_type": "Customer",
                "party": it["customer"],
                "posting_date": today(),
                "paid_amount": 42.0,
                "received_amount": 42.0,
                "paid_from": inv_doc.debit_to,
                "paid_to": bank_account["account"],
                "paid_from_account_currency": "EUR",
                "paid_to_account_currency": "EUR",
                "target_exchange_rate": 1,
                "source_exchange_rate": 1,
                "reference_no": "ORIG-REF",
                "reference_date": today(),
                "mode_of_payment": "SEPA Direct Debit",
                "references": [
                    {
                        "reference_doctype": "Sales Invoice",
                        "reference_name": invoice.name,
                        "total_amount": 42.0,
                        "outstanding_amount": 42.0,
                        "allocated_amount": 42.0,
                    }
                ],
            }
        )
        pe.insert()
        pe.submit()

        # Ensure member has the member_id used by the lookup.
        member_id = frappe.db.get_value("Member", member.name, "member_id")
        self.assertTrue(member_id, "member should have a member_id")

        result = recon.process_individual_return(
            {
                "member_reference": member_id,
                "amount": 42.0,
                "return_reason": "Insufficient funds",
                "return_code": "AM04",
            }
        )
        self.assertEqual(result["status"], "processed", msg=result)
        self.assertEqual(result["invoice"], invoice.name)

        # F1 CORE ASSERTIONS: the original Receive PE must be cancelled and the
        # invoice restored to its unpaid state — NOT left marked Paid.
        pe.reload()
        self.assertEqual(pe.docstatus, 2, "original Receive payment entry should be cancelled")

        inv_after = frappe.get_doc("Sales Invoice", invoice.name)
        self.assertIn(
            inv_after.status,
            ["Unpaid", "Overdue"],
            f"returned DD must re-open the invoice, got status={inv_after.status}",
        )
        self.assertEqual(
            float(inv_after.outstanding_amount),
            float(inv_after.grand_total),
            "outstanding must be restored to grand_total after a returned DD",
        )

        # No leftover unallocated on-account credit should remain for the customer:
        # the cancelled PE reverses its own GL, so no stray Pay/credit PE exists.
        leftover_credit = frappe.get_all(
            "Payment Entry",
            filters={
                "party": it["customer"],
                "payment_type": "Pay",
                "docstatus": 1,
                "unallocated_amount": [">", 0],
            },
            fields=["name", "unallocated_amount"],
        )
        self.assertFalse(
            leftover_credit,
            f"no orphaned on-account credit should remain, found: {leftover_credit}",
        )

        # A tracking Comment on the Member should exist.
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Member", "reference_name": member.name,
                     "comment_type": "Info"},
            fields=["name", "content"],
        )
        self.assertTrue(any("SEPA Payment Failed" in (c.get("content") or "") for c in
                            [frappe.get_doc("Comment", c.name) for c in comments]))


# =============================================================================
# create_failed_payment_record / notify_member_of_failed_payment (helpers)
# =============================================================================
class TestFailedPaymentHelpers(ReconBase):
    def test_create_failed_payment_record_creates_comment(self):
        it = self._make_member_with_invoice(first_name="FailRec", grand_total=25.0)
        name = recon.create_failed_payment_record(
            it["member"].name, it["invoice"].name,
            {"amount": 25.0, "return_reason": "Insufficient funds", "return_code": "AM04"},
        )
        self.assertTrue(frappe.db.exists("Comment", name))
        doc = frappe.get_doc("Comment", name)
        self.assertEqual(doc.reference_doctype, "Member")
        self.assertEqual(doc.reference_name, it["member"].name)
        self.assertIn("SEPA Payment Failed", doc.content)

    def test_notify_member_creates_followup_todo(self):
        it = self._make_member_with_invoice(first_name="Notify", grand_total=25.0)
        name = recon.notify_member_of_failed_payment(
            it["member"].name, it["invoice"].name,
            {"amount": 25.0, "return_reason": "Account closed"},
        )
        self.assertTrue(frappe.db.exists("ToDo", name))
        todo = frappe.get_doc("ToDo", name)
        self.assertEqual(todo.reference_type, "Member")
        self.assertEqual(todo.reference_name, it["member"].name)
        self.assertEqual(todo.priority, "High")


# =============================================================================
# correlate_return_transactions + find_original_sepa_batch_for_return
# =============================================================================
class TestCorrelateReturns(ReconBase):
    def test_correlate_returns_success_structure(self):
        result = recon.correlate_return_transactions()
        self.assertTrue(result["success"])
        self.assertIn("correlated_returns", result)
        self.assertEqual(result["total_found"], len(result["correlated_returns"]))

    def test_find_original_batch_for_matching_return(self):
        it = self._make_member_with_invoice(first_name="RetCorr", grand_total=37.0)
        batch = self._make_batch([it], batch_date=add_days(today(), -3))
        # Return txn (withdrawal) matching one batch item amount, after the batch.
        bt = self._make_bank_transaction(
            withdrawal=flt(it["invoice"].grand_total), date=today(),
            description="SEPA DD return reject",
        )
        match = recon.find_original_sepa_batch_for_return(bt)
        self.assertIsNotNone(match)
        self.assertEqual(match["batch_name"], batch.name)
        self.assertEqual(match["confidence"], "high")

    def test_find_original_batch_no_match(self):
        it = self._make_member_with_invoice(first_name="RetNoCorr", grand_total=37.0)
        self._make_batch([it], batch_date=add_days(today(), -3))
        bt = self._make_bank_transaction(
            withdrawal=99999.0, date=today(), description="SEPA return",
        )
        self.assertIsNone(recon.find_original_sepa_batch_for_return(bt))

    def test_correlate_picks_up_matching_return(self):
        it = self._make_member_with_invoice(first_name="CorrHit", grand_total=44.0)
        batch = self._make_batch([it], batch_date=add_days(today(), -2))
        bt = self._make_bank_transaction(
            withdrawal=flt(it["invoice"].grand_total), date=today(),
            description="SEPA DD return failed",
        )
        result = recon.correlate_return_transactions()
        hit = next((r for r in result["correlated_returns"]
                    if r["return_transaction"] == bt.name), None)
        self.assertIsNotNone(hit, "matching return should be correlated")
        self.assertEqual(hit["original_batch"], batch.name)


# =============================================================================
# get_sepa_reconciliation_dashboard (whitelist)
# =============================================================================
class TestDashboard(ReconBase):
    def test_dashboard_structure(self):
        result = recon.get_sepa_reconciliation_dashboard()
        self.assertTrue(result["success"])
        for key in ("recent_batches", "linked_transactions", "pending_reviews", "summary"):
            self.assertIn(key, result)
        self.assertEqual(result["summary"]["total_batches"], len(result["recent_batches"]))

    def test_dashboard_reflects_recent_batch_and_link(self):
        it = self._make_member_with_invoice(first_name="DashHit", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        bt.db_set("custom_sepa_batch", batch.name)
        result = recon.get_sepa_reconciliation_dashboard()
        self.assertIn(batch.name, [b["name"] for b in result["recent_batches"]])
        self.assertIn(bt.name, [t["name"] for t in result["linked_transactions"]])


# =============================================================================
# manual_sepa_reconciliation + create_manual_payment_entry (whitelist)
# =============================================================================
class TestManualReconciliation(ReconBase):
    def test_manual_reconciliation_creates_payment(self):
        it = self._make_member_with_invoice(first_name="ManRec", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        batch_items_json = json.dumps([
            {
                "reconcile": True,
                "member": it["member"].name,
                "invoice": it["invoice"].name,
                "amount": flt(it["invoice"].grand_total),
            }
        ])
        result = recon.manual_sepa_reconciliation(bt.name, batch_items_json)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["total_reconciled"], 1)
        pe_name = result["reconciled_items"][0]["payment_entry"]
        self.assertTrue(frappe.db.exists("Payment Entry", pe_name))
        pe = frappe.get_doc("Payment Entry", pe_name)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.custom_bank_transaction, bt.name)
        bt.reload()
        self.assertEqual(bt.custom_processing_status, "Manually Reconciled")

    def test_manual_reconciliation_skips_unflagged_items(self):
        it = self._make_member_with_invoice(first_name="ManSkip", grand_total=25.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(),
                                         description="SEPA DD")
        batch_items_json = json.dumps([
            {"reconcile": False, "member": it["member"].name,
             "invoice": it["invoice"].name, "amount": 25.0}
        ])
        result = recon.manual_sepa_reconciliation(bt.name, batch_items_json)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_reconciled"], 0)

    def test_manual_reconciliation_bad_transaction_returns_error(self):
        batch_items_json = json.dumps([])
        result = recon.manual_sepa_reconciliation("BT-NONEXISTENT-XYZ", batch_items_json)
        self.assertFalse(result["success"])
        self.assertIn("error", result)

    def test_create_manual_payment_entry_missing_customer_throws(self):
        it = self._make_member_with_invoice(first_name="ManNoCust", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")
        frappe.db.set_value("Member", it["member"].name, "customer", None)
        with self.assertRaises(frappe.ValidationError):
            recon.create_manual_payment_entry(
                bt, {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0}
            )

    def test_create_manual_payment_entry_missing_invoice_throws(self):
        it = self._make_member_with_invoice(first_name="ManNoInv", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")
        with self.assertRaises(frappe.ValidationError):
            recon.create_manual_payment_entry(
                bt, {"member": it["member"].name, "invoice": "SINV-NOPE-XYZ", "amount": 25.0}
            )

    def _make_extra_bank_account(self, company):
        """Create a second non-group Bank-type GL account so the company has more
        than one — which makes get_default_bank_cash_account's 'exactly one'
        fallback return nothing when there is no configured default. Uncommitted;
        rolls back with the test."""
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name"
        )
        acc = frappe.new_doc("Account")
        acc.account_name = f"Extra SEPA Bank {frappe.generate_hash(length=5)}"
        acc.company = company
        acc.account_type = "Bank"
        acc.parent_account = parent
        acc.account_currency = "EUR"
        acc.insert(ignore_permissions=True)
        return acc.name

    def test_create_manual_payment_entry_no_default_bank_account_throws(self):
        """B3 (create_manual_payment_entry, line ~1185): when the invoice's company
        has NO default bank account configured (and not exactly one Bank account so
        the fallback can't guess one), the method throws 'No default bank account
        configured for company ...'. Mirrors the sibling missing-customer /
        missing-invoice throw tests, but exercises the bank-account config gate.

        The default bank account is unset only within the test transaction (with the
        Company document cache cleared so erpnext's get_cached_value re-reads it) and
        restored in a finally block; the extra Bank account and the unset both roll
        back with the test."""
        it = self._make_member_with_invoice(first_name="ManNoBank", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today(), description="SEPA DD")

        original_default = frappe.db.get_value("Company", self.company, "default_bank_account")
        # Guarantee > 1 Bank account so the "single account" fallback can't kick in.
        self._make_extra_bank_account(self.company)
        try:
            frappe.db.set_value("Company", self.company, "default_bank_account", None)
            frappe.clear_document_cache("Company", self.company)
            with self.assertRaises(frappe.ValidationError) as cm:
                recon.create_manual_payment_entry(
                    bt,
                    {"member": it["member"].name, "invoice": it["invoice"].name, "amount": 25.0},
                )
            self.assertIn("No default bank account configured", str(cm.exception))
        finally:
            # Restore the committed default + refresh the cache so sibling tests
            # (which resolve a bank account via the same accessor) are unaffected.
            frappe.db.set_value("Company", self.company, "default_bank_account", original_default)
            frappe.clear_document_cache("Company", self.company)


if __name__ == "__main__":
    unittest.main()
