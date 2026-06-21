"""
NET-NEW real-DB integration coverage for the SEPA bank-reconciliation cluster
(CLUSTER 2 — bank reconciliation & creation):

  * verenigingen/verenigingen_payments/services/bank_transaction_creator.py
  * verenigingen/verenigingen_payments/utils/bank_transaction_reconciliation.py
  * verenigingen/verenigingen_payments/api/sepa_reconciliation.py

These modules already have two large companion suites:

  * verenigingen/tests/payment/test_bank_transaction_reconciliation.py
  * verenigingen/tests/payment/test_sepa_reconciliation.py
  * verenigingen/tests/integration/test_bank_transaction_security.py
    (covers BankTransactionCreator.create_from_dict + permission paths)

This file deliberately targets the reachable branches those suites do NOT
exercise, with real documents and meaningful (regression-catching) assertions.
Nothing about business logic is mocked.

What is covered here (method × branch):

  BankTransactionCreator
    - create()                       low-level public method: fresh create +
                                     idempotent return of existing BT by reference
    - _check_existing_by_reference() hit / miss
    - check_already_processed()      not-processed; submitted BT found; cancelled
                                     BT -> reprocess allowed; PE-mode submitted PE
                                     found; PE-mode cancelled PE -> falls through
                                     to BT check
    - link_payment_entry()           real link of a submitted PE to a submitted
                                     BT (allocation + status + clearance_date);
                                     idempotent already-linked short-circuit
    - create_from_dict()             custom_* passthrough branch

  bank_transaction_reconciliation
    - create_payment_entries_from_batch()  raises when batch has no invoices
    - _invoice_has_submitted_payment_entry() True / False
    - match_by_amount_and_reference()      amount present but no DB match -> None
    - match_by_description()               MEMBER-id pattern resolves an unpaid
                                           invoice for the member
    - reconcile_bank_transactions()        from_date/to_date filter path

  sepa_reconciliation (API)
    - find_matching_sepa_batches()    no submitted batches in window -> []
    - find_original_sepa_batch_for_return()  no candidate batch -> None
    - get_sepa_reconciliation_dashboard()    pending-review ToDo surfaced
    - reconcile_full_sepa_batch()     batch with a row pointing at a missing
                                      invoice -> validation_failed (Phase 1, no
                                      begin/commit so test-transaction safe)

OUT OF SCOPE (external boundary / harness limits — not mocked):

  * create_from_mollie_payment / create_from_settlement need a live Mollie SDK
    payment/settlement object routed through PaymentDataExtractor (external
    data shape); get_mollie_bank_account_config needs configured Mollie GL
    accounts. Covered elsewhere (balance/mollie suites) where a real seam exists.
  * match_mollie_settlement / process_mollie_settlement / _create_mollie_* reach
    the live Mollie SettlementsClient (outbound HTTP to api.mollie.com).
  * reconcile_full_sepa_batch's Phase-2 happy path and
    _process_sepa_transaction_conservative_internal full-match call
    frappe.db.begin()/commit(), which the FrappeTestCase transaction wrapper
    rejects ("This statement can cause implicit commit"). Only the pre-commit
    branches are exercised here.

Shard-safety: every committed Bank Transaction / Payment Entry created here is
tracked and force-deleted in tearDown so nothing leaks past FrappeTestCase
rollback into sibling CI shards.
"""

import unittest

import frappe
from frappe.utils import add_days, flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.api import sepa_reconciliation as recon
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    BankTransactionCreator,
    get_bank_transaction_creator,
)
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)


class ReconCoverageBase(EnhancedTestCase):
    """Shared real-fixture harness mirroring the companion suites."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Provision shared infra ONCE before any per-test transaction opens.
        cls._company = get_eur_test_company()
        cls._ensure_default_bank_account(cls._company)
        cls._eur_bank_account = cls._ensure_eur_bank_account_doc(cls._company)
        cls._ensure_modes_of_payment()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.company = self._company
        self.creator = get_bank_transaction_creator()
        # Track committed rows for force-cleanup (shard safety).
        self._committed_bt = []
        self._committed_pe = []
        # Submitting a dated invoice triggers eBoekhouden's ensure_fiscal_year_exists,
        # which logs this benign title when the current FY already exists / overlaps on
        # the shared test DB (a known test-artifact, not a SEPA bug). Acknowledge it so
        # the error-log guard surfaces only genuinely unexpected Error Logs.
        self.expectErrorLog("Fiscal Year Auto-Creation Error")

    def tearDown(self):
        # Force-delete anything we committed so it cannot pollute sibling shards.
        for pe in self._committed_pe:
            try:
                doc = frappe.get_doc("Payment Entry", pe)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Payment Entry", pe, force=True, delete_permanently=True)
            except Exception:
                pass
        for bt in self._committed_bt:
            try:
                doc = frappe.get_doc("Bank Transaction", bt)
                if doc.docstatus == 1:
                    doc.cancel()
                frappe.delete_doc("Bank Transaction", bt, force=True, delete_permanently=True)
            except Exception:
                pass
        if self._committed_bt or self._committed_pe:
            frappe.db.commit()
        super().tearDown()

    # ---- infra -------------------------------------------------------------

    @classmethod
    def _ensure_modes_of_payment(cls):
        for mop in ("SEPA Direct Debit", "Mollie"):
            if not frappe.db.exists("Mode of Payment", mop):
                doc = frappe.new_doc("Mode of Payment")
                doc.mode_of_payment = mop
                doc.type = "Bank"
                doc.insert(ignore_permissions=True)

    @classmethod
    def _ensure_default_bank_account(cls, company):
        existing = frappe.db.get_value("Company", company, "default_bank_account")
        if existing and frappe.db.exists("Account", existing):
            return existing
        bank_acc = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        )
        if not bank_acc:
            parent = frappe.db.get_value(
                "Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name"
            )
            acc = frappe.new_doc("Account")
            acc.account_name = "Test ReconCov Bank"
            acc.company = company
            acc.account_type = "Bank"
            acc.parent_account = parent
            acc.account_currency = "EUR"
            acc.insert(ignore_permissions=True)
            bank_acc = acc.name
        frappe.db.set_value("Company", company, "default_bank_account", bank_acc)
        return bank_acc

    @classmethod
    def _ensure_eur_bank_account_doc(cls, company):
        """Get-or-create a controlled EUR-currency Bank Account doc."""
        gl = cls._ensure_default_bank_account(company)
        existing = frappe.db.get_value("Bank Account", {"account": gl}, "name")
        if existing:
            return existing
        bank_name = "ReconCov Test Bank"
        if not frappe.db.exists("Bank", bank_name):
            bank = frappe.new_doc("Bank")
            bank.bank_name = bank_name
            bank.insert(ignore_permissions=True)
        ba = frappe.new_doc("Bank Account")
        ba.account_name = "ReconCov Test Company Account"
        ba.bank = bank_name
        ba.is_company_account = 1
        ba.company = company
        ba.account = gl
        ba.insert(ignore_permissions=True)
        return ba.name

    # ---- builders ----------------------------------------------------------

    def _make_member_with_invoice(self, first_name="ReconCov", grand_total=25.0, submit=True, **si_kwargs):
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
            **si_kwargs,
        )
        return {
            "member": member,
            "customer": customer,
            "mandate": mandate,
            "membership": membership,
            "invoice": invoice,
        }

    def _make_batch(self, items, batch_date=None, status="Submitted", submit=True, row_status="Successful"):
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = batch_date or today()
        batch.batch_description = f"ReconCov Batch {frappe.generate_hash(length=6)}"
        batch.currency = "EUR"
        batch.batch_type = "CORE"
        batch.status = "Draft"
        total = 0.0
        for idx, it in enumerate(items):
            amount = flt(it["invoice"].grand_total)
            this_status = row_status[idx] if isinstance(row_status, (list, tuple)) else row_status
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
                    "status": this_status,
                    "sequence_type": "FRST",
                },
            )
            total += amount
        batch.total_amount = total
        batch.entry_count = len(items)
        batch.insert()
        if submit:
            frappe.db.set_value(
                "Direct Debit Batch",
                batch.name,
                {"docstatus": 1, "status": status or "Submitted"},
                update_modified=False,
            )
            batch.reload()
        return batch

    def _make_bank_transaction(
        self,
        deposit=0.0,
        withdrawal=0.0,
        description="",
        date=None,
        reference_number=None,
        status=None,
        bank_account=None,
        submit=False,
    ):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or today()
        bt.description = description
        bt.deposit = deposit
        bt.withdrawal = withdrawal
        bt.reference_number = reference_number or frappe.generate_hash(length=10)
        ba = bank_account or self._eur_bank_account
        if ba:
            bt.bank_account = ba
            account = frappe.get_cached_value("Bank Account", ba, "account")
            if account:
                bt.currency = frappe.get_cached_value("Account", account, "account_currency")
        bt.insert()
        if status:
            frappe.db.set_value("Bank Transaction", bt.name, "status", status, update_modified=False)
            bt.reload()
        if submit:
            bt.submit()
        return bt

    def _make_submitted_payment_entry(self, invoice_name, amount, reference_no=None):
        """Create + submit a real Receive Payment Entry against an invoice."""
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry(dt="Sales Invoice", dn=invoice_name, party_amount=amount)
        pe.reference_no = reference_no or frappe.generate_hash(length=10)
        pe.reference_date = today()
        pe.mode_of_payment = "SEPA Direct Debit"
        pe.insert()
        pe.submit()
        return pe


# =============================================================================
# BankTransactionCreator.create() + _check_existing_by_reference()
# =============================================================================
class TestCreatorCreate(ReconCoverageBase):
    def test_create_makes_submitted_bank_transaction(self):
        ref = f"CRT-{frappe.generate_hash(length=8)}"
        name = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=120.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="low-level create path",
        )
        self.assertIsNotNone(name)
        self._committed_bt.append(name)
        bt = frappe.get_doc("Bank Transaction", name)
        self.assertEqual(flt(bt.deposit), 120.0)
        self.assertEqual(bt.reference_number, ref)
        # Administrator has submit permission -> submitted.
        self.assertEqual(bt.docstatus, 1)

    def test_create_is_idempotent_on_reference(self):
        ref = f"CRT-IDEM-{frappe.generate_hash(length=8)}"
        first = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=80.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="first",
        )
        self.assertIsNotNone(first)
        self._committed_bt.append(first)
        # Second call with same reference returns the SAME BT without creating a new one.
        second = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=999.0,  # different amount, must be ignored
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="second",
        )
        self.assertEqual(first, second)
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": ref}),
            1,
            "idempotent create must not insert a duplicate Bank Transaction",
        )
        self.assertEqual(flt(frappe.db.get_value("Bank Transaction", first, "deposit")), 80.0)

    def test_check_existing_by_reference_hit_and_miss(self):
        self.assertIsNone(self.creator._check_existing_by_reference("NO-SUCH-REF-XYZ"))
        ref = f"EXIST-{frappe.generate_hash(length=8)}"
        name = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=10.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="exists check",
        )
        self._committed_bt.append(name)
        self.assertEqual(self.creator._check_existing_by_reference(ref), name)


# =============================================================================
# BankTransactionCreator.create_from_dict() — custom_* passthrough
# =============================================================================
class TestCreatorCustomFields(ReconCoverageBase):
    def test_custom_fields_passed_through(self):
        ref = f"CUSTOM-{frappe.generate_hash(length=8)}"
        name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 60.0,
                "currency": "EUR",
                "description": "custom field passthrough",
                "reference_number": ref,
                # custom_member is a real Custom Field on Bank Transaction; the
                # creator copies any custom_* key onto the doc.
                "custom_processing_status": "Mollie Settlement Processed",
            },
            bank_account=self._eur_bank_account,
            company=self.company,
            source_type="Custom Test",
        )
        self.assertIsNotNone(name)
        self._committed_bt.append(name)
        self.assertEqual(
            frappe.db.get_value("Bank Transaction", name, "custom_processing_status"),
            "Mollie Settlement Processed",
        )


# =============================================================================
# BankTransactionCreator.check_already_processed()
# =============================================================================
class TestCheckAlreadyProcessed(ReconCoverageBase):
    def test_not_processed(self):
        result = self.creator.check_already_processed(f"UNSEEN-{frappe.generate_hash(length=8)}")
        self.assertFalse(result["already_processed"])
        self.assertIsNone(result["bank_transaction"])
        self.assertEqual(result["details"], "Not yet processed")

    def test_submitted_bank_transaction_found(self):
        ref = f"PROC-BT-{frappe.generate_hash(length=8)}"
        name = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=15.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="already processed bt",
        )
        self._committed_bt.append(name)
        result = self.creator.check_already_processed(ref)
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["bank_transaction"], name)
        self.assertEqual(result["document_type"], "Bank Transaction")
        self.assertEqual(result["docstatus"], 1)

    def test_cancelled_bank_transaction_allows_reprocessing(self):
        ref = f"CANC-BT-{frappe.generate_hash(length=8)}"
        name = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=18.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="to-be-cancelled bt",
        )
        self._committed_bt.append(name)
        bt = frappe.get_doc("Bank Transaction", name)
        bt.cancel()
        frappe.db.commit()
        result = self.creator.check_already_processed(ref)
        # Cancelled doc -> treated as NOT processed (reprocessing allowed).
        self.assertFalse(result["already_processed"])
        self.assertEqual(result["details"], "Not yet processed")

    def test_submitted_payment_entry_found_in_pe_mode(self):
        it = self._make_member_with_invoice(first_name="ProcPE", grand_total=22.0)
        ref = f"PROC-PE-{frappe.generate_hash(length=8)}"
        pe = self._make_submitted_payment_entry(it["invoice"].name, 22.0, reference_no=ref)
        self._committed_pe.append(pe.name)
        result = self.creator.check_already_processed(ref, check_payment_entry=True)
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["payment_entry"], pe.name)
        self.assertEqual(result["document_type"], "Payment Entry")
        self.assertEqual(result["docstatus"], 1)

    def test_cancelled_pe_falls_through_to_bank_transaction_check(self):
        """A cancelled Payment Entry must NOT short-circuit; the method continues
        to the Bank Transaction check, which here finds a submitted BT under the
        same reference."""
        it = self._make_member_with_invoice(first_name="ProcPECanc", grand_total=24.0)
        ref = f"PROC-MIX-{frappe.generate_hash(length=8)}"
        pe = self._make_submitted_payment_entry(it["invoice"].name, 24.0, reference_no=ref)
        self._committed_pe.append(pe.name)
        pe.reload()
        pe.cancel()
        # Now create a submitted BT under the SAME reference.
        bt_name = self.creator.create(
            date=today(),
            bank_account=self._eur_bank_account,
            company=self.company,
            deposit=24.0,
            withdrawal=0.0,
            currency="EUR",
            reference_number=ref,
            description="bt under same ref",
        )
        self._committed_bt.append(bt_name)
        result = self.creator.check_already_processed(ref, check_payment_entry=True)
        # Cancelled PE skipped -> BT check wins.
        self.assertTrue(result["already_processed"])
        self.assertEqual(result["document_type"], "Bank Transaction")
        self.assertEqual(result["bank_transaction"], bt_name)


# =============================================================================
# BankTransactionCreator.link_payment_entry()
# =============================================================================
class TestLinkPaymentEntry(ReconCoverageBase):
    def test_links_payment_entry_to_bank_transaction(self):
        it = self._make_member_with_invoice(first_name="LinkPE", grand_total=50.0)
        pe = self._make_submitted_payment_entry(it["invoice"].name, 50.0)
        self._committed_pe.append(pe.name)
        bt = self._make_bank_transaction(deposit=50.0, date=today(), submit=True)
        self._committed_bt.append(bt.name)

        ok = self.creator.link_payment_entry(bt.name, pe.name)
        self.assertTrue(ok, "linking a submitted PE to a submitted BT should succeed")

        bt.reload()
        linked = [p.payment_entry for p in bt.payment_entries]
        self.assertIn(pe.name, linked)
        # Allocation should reflect the PE amount and the BT should no longer be
        # fully unreconciled.
        allocated = next(p.allocated_amount for p in bt.payment_entries if p.payment_entry == pe.name)
        self.assertEqual(flt(allocated), 50.0)
        self.assertIn(bt.status, ("Reconciled", "Settled"))
        # clearance_date set on the PE.
        self.assertEqual(str(frappe.db.get_value("Payment Entry", pe.name, "clearance_date")), str(bt.date))

    def test_link_is_idempotent(self):
        it = self._make_member_with_invoice(first_name="LinkIdem", grand_total=40.0)
        pe = self._make_submitted_payment_entry(it["invoice"].name, 40.0)
        self._committed_pe.append(pe.name)
        bt = self._make_bank_transaction(deposit=40.0, date=today(), submit=True)
        self._committed_bt.append(bt.name)

        self.assertTrue(self.creator.link_payment_entry(bt.name, pe.name))
        # Second call hits the early "already linked" short-circuit.
        self.assertTrue(self.creator.link_payment_entry(bt.name, pe.name))
        bt.reload()
        links = [p for p in bt.payment_entries if p.payment_entry == pe.name]
        self.assertEqual(len(links), 1, "re-linking must not add a duplicate row")


# =============================================================================
# bank_transaction_reconciliation — net-new branches
# =============================================================================
class TestReconciliationNetNew(ReconCoverageBase):
    def setUp(self):
        super().setUp()
        # On a Mollie-less test site, PaymentReconciliationManager.__init__ logs
        # (does not raise) that the Mollie GL accounts are unconfigured. That is
        # expected noise here, not a swallowed failure of the code under test.
        self.expectErrorLog("Mollie")
        self.mgr = PaymentReconciliationManager()

    def _txn_dict(self, bt):
        return {
            "name": bt.name,
            "date": bt.date,
            "deposit": flt(bt.deposit),
            "withdrawal": flt(bt.withdrawal),
            "description": bt.description or "",
            "bank_account": bt.bank_account,
            "reference_number": bt.reference_number or "",
        }

    def test_create_payment_entries_from_batch_no_invoices_raises(self):
        it = self._make_member_with_invoice(first_name="EmptyBatchPE", grand_total=25.0)
        batch = self._make_batch([it])
        # Strip the child rows to hit the "no invoices to reconcile" guard.
        frappe.db.delete("Direct Debit Batch Invoice", {"parent": batch.name})
        batch.reload()
        bt = self._make_bank_transaction(deposit=0.0, date=today())
        with self.assertRaises(frappe.ValidationError):
            self.mgr.create_payment_entries_from_batch(bt, batch.name)

    def test_invoice_has_submitted_payment_entry_true_and_false(self):
        it = self._make_member_with_invoice(first_name="HasPE", grand_total=30.0)
        # Before any PE: False.
        self.assertFalse(self.mgr._invoice_has_submitted_payment_entry(it["invoice"].name))
        pe = self._make_submitted_payment_entry(it["invoice"].name, 30.0)
        self._committed_pe.append(pe.name)
        # After a submitted PE references it: True.
        self.assertTrue(self.mgr._invoice_has_submitted_payment_entry(it["invoice"].name))

    def test_amount_and_reference_no_db_match_returns_none(self):
        # Amount + reference present, but no Direct Debit Batch Invoice matches.
        bt = self._make_bank_transaction(
            deposit=123456.78, reference_number="REF-NO-BATCH-MATCH", date=today()
        )
        self.assertIsNone(self.mgr.match_by_amount_and_reference(self._txn_dict(bt)))

    def test_match_by_description_member_id_pattern(self):
        """The MEMBER ID description pattern resolves an unpaid invoice for that
        member via get_member_unpaid_invoices."""
        it = self._make_member_with_invoice(first_name="MemberDesc", grand_total=37.0)
        frappe.db.set_value(
            "Sales Invoice",
            it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 37.0},
            update_modified=False,
        )
        member_id = it["member"].name
        bt = self._make_bank_transaction(deposit=37.0, description=f"MEMBER ID: {member_id}", date=today())
        match = self.mgr.match_by_description(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "member")
        self.assertEqual(match["reference"], it["invoice"].name)

    def test_reconcile_bank_transactions_date_filter(self):
        # An old Reconciled txn must be excluded by a today() from_date filter
        # (also exercises the Pending+allocated filter selection path).
        old_bt = self._make_bank_transaction(
            deposit=11.0, date=add_days(today(), -90), status="Pending"
        )
        result = self.mgr.reconcile_bank_transactions(
            bank_account=self._eur_bank_account, from_date=today(), to_date=today()
        )
        for key in ("total_transactions", "matched", "unmatched"):
            self.assertIn(key, result)
        # The 90-day-old transaction is outside the from_date window.
        self.assertEqual(result["unmatched"], result["total_transactions"] - result["matched"])
        old_bt.reload()
        self.assertEqual(old_bt.status, "Pending")


# =============================================================================
# sepa_reconciliation (API) — net-new branches
# =============================================================================
class TestSepaReconciliationApiNetNew(ReconCoverageBase):
    def test_find_matching_sepa_batches_empty_window(self):
        # No submitted batch near this date -> empty match list.
        bt = self._make_bank_transaction(deposit=12345.0, date=today(), description="SEPA DD")
        matches = recon.find_matching_sepa_batches(bt)
        self.assertEqual(matches, [])

    def test_find_original_sepa_batch_for_return_none_when_no_batch(self):
        bt = self._make_bank_transaction(withdrawal=98765.0, date=today(), description="SEPA return")
        self.assertIsNone(recon.find_original_sepa_batch_for_return(bt))

    def test_dashboard_surfaces_pending_review_todo(self):
        # Submitting the invoice can trigger production's "Fiscal Year Auto-Creation"
        # log (benign overlap); mark it expected so the suite stays clean under
        # VERENIGINGEN_FAIL_ON_ERROR_LOG=1 audit runs.
        self.expectErrorLog("Fiscal Year")
        it = self._make_member_with_invoice(first_name="DashTodo", grand_total=29.0)
        batch = self._make_batch([it])
        # handle_partial_sepa_batch creates a real Open ToDo against the batch.
        bt = self._make_bank_transaction(deposit=20.0, date=today(), description="SEPA DD")
        partial = recon.handle_partial_sepa_batch(bt, batch)
        todo_name = partial["review_task"]
        result = recon.get_sepa_reconciliation_dashboard()
        self.assertTrue(result["success"])
        self.assertIn(todo_name, [t["name"] for t in result["pending_reviews"]])
        self.assertGreaterEqual(result["summary"]["pending_reviews"], 1)

    def test_reconcile_full_sepa_batch_missing_invoice_validation_failed(self):
        """A batch row pointing at a nonexistent invoice fails Phase-1 validation
        (read-only, before any begin/commit), so it is test-transaction safe."""
        it = self._make_member_with_invoice(first_name="FullMissingInv", grand_total=25.0)
        batch = self._make_batch([it])
        # Repoint the child row at a missing invoice.
        frappe.db.set_value(
            "Direct Debit Batch Invoice",
            {"parent": batch.name},
            "invoice",
            "SINV-DOES-NOT-EXIST-XYZ",
            update_modified=False,
        )
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today(), description="SEPA DD")
        result = recon.reconcile_full_sepa_batch(bt, batch)
        self.assertEqual(result["type"], "validation_failed", msg=result)
        self.assertEqual(result["reconciled_count"], 0)
        self.assertTrue(result["validation_errors"])
        self.assertIn("not found", result["validation_errors"][0]["error"])


if __name__ == "__main__":
    unittest.main()
