"""
Real-integration tests for
verenigingen/verenigingen_payments/utils/bank_transaction_reconciliation.py
(previously ~0% coverage).

This module reconciles imported Bank Transactions against SEPA Direct Debit
batches / member invoices and against Mollie bulk settlement payouts. Tests
build REAL Member / Customer / SEPA Mandate / Membership / Sales Invoice /
Direct Debit Batch / Bank Transaction / Payment Entry documents via
SEPATestDataFactory and assert real matching/reconciliation outcomes and DB
side effects. Nothing about the business logic is mocked.

Tests run as Administrator (System Manager), satisfying the @standard_api /
@require_sepa_permission gates AND the MollieConfigurationService role check.

Scope notes / not-covered:

  * match_mollie_settlement / process_mollie_settlement / _create_mollie_payment_entry
    / _create_mollie_fee_entry require a configured Mollie bank-account GL plus a
    live Mollie SettlementsClient (real outbound HTTP to api.mollie.com). The
    early-return branches (no Mollie bank account configured -> ValidationError
    -> None; non-Mollie account; non-Mollie keyword) ARE covered. The
    settlement-fetch / payment-entry-creation branches are NOT exercised because
    they hit an external API boundary that may not be mocked under the
    test-quality-enforcer rules; covering them meaningfully would require a live
    Mollie organization token.

PRODUCT BUGS exposed (xfailed / documented below and in the orchestrator report):

  * parse_pain002_file (line ~1097) is an unimplemented stub returning None.
    process_sepa_return_file(file_type="pain.002") therefore iterates over None
    -> TypeError. See TestProcessSepaReturnFile.test_pain002_stub_crashes.

  * create_reconciliation (line ~488) treats match["type"] == "batch" identically
    to "invoice" and calls create_payment_entry_from_transaction(bank_trans,
    match["reference"], ...) with the *batch name* as the invoice name. The
    payment-entry service then does frappe.db.exists("Sales Invoice", <batch>) ->
    False -> ValidationError -> caught -> transaction marked Unreconciled. A
    highest-confidence (1.0) batch-reference match can therefore NEVER reconcile.
    See TestMatchTransactionAndReconcile.test_batch_type_reconciliation_bug.

  * match_by_description (line ~302) MEMBERSHIP branch queries
    frappe.db.get_value("Sales Invoice", {"membership": <ref>, ...}) but Sales
    Invoice has NO "membership" field -> OperationalError (1054 Unknown column)
    whenever a MEMBERSHIP-pattern description references an existing Membership.
    See TestMatchByDescription.test_membership_pattern_crashes.

  * _is_mollie_payment_processed / _create_mollie_payment_entry read/write
    Payment Entry.custom_mollie_payment_id, but no Frappe field (DocField or
    Custom Field) is wired to that name (only a stale orphan DB column exists).
    Doc writes to it are silently dropped, so the DB-based duplicate guard can
    never find a previously-processed payment. See
    TestMolliePaymentTracking.test_db_dedup_field_not_wired.
"""

import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.utils import add_days, flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)


class BTRBase(EnhancedTestCase):
    """Shared helpers for building real reconciliation fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Provision shared infra ONCE before any per-test transaction opens.
        cls._company = get_eur_test_company()
        cls._ensure_default_bank_account(cls._company)
        cls._ensure_modes_of_payment()
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.company = self._company
        # One shared manager per test; instantiating it validates Bank Transaction
        # fields and Mollie config (logs, never throws on missing Mollie accounts).
        self.mgr = PaymentReconciliationManager()

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
            acc.account_name = "Test BTR Bank"
            acc.company = company
            acc.account_type = "Bank"
            acc.parent_account = parent
            acc.account_currency = "EUR"
            acc.insert(ignore_permissions=True)
            bank_acc = acc.name
        frappe.db.set_value("Company", company, "default_bank_account", bank_acc)
        return bank_acc

    # ---- builders ----------------------------------------------------------

    def _make_member_with_invoice(self, first_name="BTR", grand_total=25.0, submit=True):
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

    def _make_batch(
        self, items, batch_date=None, status="Submitted", submit=True, row_status="Successful"
    ):
        """Build a Direct Debit Batch from already-built member/invoice dicts.

        Real batch.submit() triggers generate_sepa_xml (needs org SEPA settings),
        so we mark the batch submitted directly in the DB (docstatus=1 + status).

        ``row_status`` sets the per-invoice child-row status. Reconciliation only
        books rows that were actually collected ("Successful"/"Processed"), so the
        default is "Successful"; pass a list to set per-row statuses.
        """
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = batch_date or today()
        batch.batch_description = f"BTR Batch {frappe.generate_hash(length=6)}"
        batch.currency = "EUR"
        batch.batch_type = "FRST"
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
        self, deposit=0.0, withdrawal=0.0, description="", date=None,
        reference_number=None, status=None, bank_account=None, submit=False,
    ):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date or today()
        bt.description = description
        bt.deposit = deposit
        bt.withdrawal = withdrawal
        bt.reference_number = reference_number or frappe.generate_hash(length=10)
        ba = bank_account or frappe.db.get_value(
            "Bank Account", {"is_company_account": 1}, "name"
        ) or frappe.db.get_value("Bank Account", {}, "name")
        if ba:
            bt.bank_account = ba
        bt.insert()
        if status:
            frappe.db.set_value("Bank Transaction", bt.name, "status", status, update_modified=False)
            bt.reload()
        if submit:
            bt.submit()
        return bt

    def _txn_dict(self, bt):
        """Build the lightweight dict the matching strategies operate on
        (mirrors the fields reconcile_bank_transactions selects)."""
        return {
            "name": bt.name,
            "date": bt.date,
            "deposit": flt(bt.deposit),
            "withdrawal": flt(bt.withdrawal),
            "description": bt.description or "",
            "bank_account": bt.bank_account,
            "reference_number": bt.reference_number or "",
        }


# =============================================================================
# Pure conversion / validation helpers
# =============================================================================
class TestSafeDecimal(BTRBase):
    def test_none_returns_zero(self):
        self.assertEqual(self.mgr._safe_decimal(None), Decimal("0"))

    def test_int_and_float(self):
        self.assertEqual(self.mgr._safe_decimal(25), Decimal("25"))
        self.assertEqual(self.mgr._safe_decimal(25.5), Decimal("25.5"))

    def test_decimal_passthrough(self):
        d = Decimal("12.34")
        self.assertIs(self.mgr._safe_decimal(d), d)

    def test_string_with_currency_symbol(self):
        self.assertEqual(self.mgr._safe_decimal("€25.50"), Decimal("25.50"))

    def test_string_with_thousands_text(self):
        # Non-numeric chars are stripped; "1.234,56" loses the comma -> 1.23456
        self.assertEqual(self.mgr._safe_decimal("EUR 100.00"), Decimal("100.00"))

    def test_unparseable_string_returns_zero(self):
        self.assertEqual(self.mgr._safe_decimal("abc"), Decimal("0"))

    def test_empty_string_returns_zero(self):
        self.assertEqual(self.mgr._safe_decimal(""), Decimal("0"))

    def test_unexpected_type_returns_zero(self):
        self.assertEqual(self.mgr._safe_decimal({"a": 1}), Decimal("0"))


class TestValidateTransactionAmount(BTRBase):
    def test_exact_match(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(10, 10)
        self.assertTrue(ok)
        self.assertEqual(kind, "exact_match")
        self.assertEqual(diff, Decimal("0"))

    def test_within_tolerance(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(100.5, 100, tolerance_percent=1.0)
        self.assertTrue(ok)
        self.assertEqual(kind, "within_tolerance")
        self.assertEqual(diff, Decimal("0.5"))

    def test_outside_tolerance(self):
        ok, kind, diff = self.mgr._validate_transaction_amount(200, 100, tolerance_percent=1.0)
        self.assertFalse(ok)
        self.assertEqual(kind, "outside_tolerance")
        self.assertEqual(diff, Decimal("100"))

    def test_zero_tolerance_near_miss(self):
        ok, kind, _ = self.mgr._validate_transaction_amount(100.01, 100, tolerance_percent=0.0)
        self.assertFalse(ok)
        self.assertEqual(kind, "outside_tolerance")


# =============================================================================
# _extract_invoice_reference
# =============================================================================
class TestExtractInvoiceReference(BTRBase):
    def test_metadata_invoice_id_wins(self):
        ref = self.mgr._extract_invoice_reference(
            {"metadata": {"invoice_id": "SI-META-1"}, "description": "Invoice: SI-2024-001"}
        )
        self.assertEqual(ref, "SI-META-1")

    def test_si_pattern_in_description(self):
        self.assertEqual(
            self.mgr._extract_invoice_reference({"description": "paid SI-2024-001 thanks"}),
            "SI-2024-001",
        )

    def test_acc_inv_pattern(self):
        self.assertEqual(
            self.mgr._extract_invoice_reference({"description": "ref ACC-INV-2024-0001"}),
            "ACC-INV-2024-0001",
        )

    def test_invoice_label_pattern(self):
        self.assertEqual(
            self.mgr._extract_invoice_reference({"description": "Invoice: ABC-1234-567"}),
            "ABC-1234-567",
        )

    def test_no_reference_returns_none(self):
        self.assertIsNone(self.mgr._extract_invoice_reference({"description": "groceries"}))

    def test_empty_payment_returns_none(self):
        self.assertIsNone(self.mgr._extract_invoice_reference({}))


# =============================================================================
# match_by_batch_reference
# =============================================================================
class TestMatchByBatchReference(BTRBase):
    def test_exact_batch_reference_match(self):
        it = self._make_member_with_invoice(first_name="BatchRef", grand_total=30.0)
        batch = self._make_batch([it])
        # Description embeds BATCH-<token> where token is a substring of the batch name.
        token = batch.name.replace("BATCH-", "") if batch.name.startswith("BATCH-") else batch.name
        bt = self._make_bank_transaction(
            deposit=batch.total_amount, description=f"Incoming BATCH-{token} collection"
        )
        match = self.mgr.match_by_batch_reference(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "batch")
        self.assertEqual(match["reference"], batch.name)
        self.assertEqual(match["confidence"], 1.0)

    def test_batch_reference_amount_mismatch_returns_none(self):
        it = self._make_member_with_invoice(first_name="BatchRefAmt", grand_total=30.0)
        batch = self._make_batch([it])
        token = batch.name.replace("BATCH-", "") if batch.name.startswith("BATCH-") else batch.name
        bt = self._make_bank_transaction(
            deposit=batch.total_amount + 99, description=f"BATCH-{token}"
        )
        self.assertIsNone(self.mgr.match_by_batch_reference(self._txn_dict(bt)))

    def test_no_batch_pattern_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, description="no pattern here")
        self.assertIsNone(self.mgr.match_by_batch_reference(self._txn_dict(bt)))

    def test_batch_pattern_for_unknown_batch_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, description="BATCH-ZZZNONEXISTENT999")
        self.assertIsNone(self.mgr.match_by_batch_reference(self._txn_dict(bt)))


# =============================================================================
# match_by_amount_and_reference
# =============================================================================
class TestMatchByAmountAndReference(BTRBase):
    def test_single_invoice_match_high_confidence(self):
        it = self._make_member_with_invoice(first_name="AmtRef", grand_total=42.0)
        batch = self._make_batch([it])
        # reference_number == invoice name, amount == batch item amount, within ±7d.
        bt = self._make_bank_transaction(
            deposit=42.0, reference_number=it["invoice"].name, date=today()
        )
        match = self.mgr.match_by_amount_and_reference(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "invoice")
        self.assertEqual(match["reference"], it["invoice"].name)
        self.assertEqual(match["batch"], batch.name)
        self.assertEqual(match["confidence"], 0.95)

    def test_no_reference_returns_none(self):
        it = self._make_member_with_invoice(first_name="AmtNoRef", grand_total=42.0)
        self._make_batch([it])
        bt = self._make_bank_transaction(deposit=42.0, reference_number="")
        # reference_number empty -> early None
        self.assertIsNone(self.mgr.match_by_amount_and_reference(self._txn_dict(bt)))

    def test_draft_batch_not_matched(self):
        it = self._make_member_with_invoice(first_name="AmtDraft", grand_total=42.0)
        self._make_batch([it], submit=False)  # status stays Draft
        bt = self._make_bank_transaction(deposit=42.0, reference_number=it["invoice"].name)
        # Batch not in Submitted/Processed -> no SQL match
        self.assertIsNone(self.mgr.match_by_amount_and_reference(self._txn_dict(bt)))

    def test_out_of_date_window_not_matched(self):
        it = self._make_member_with_invoice(first_name="AmtOld", grand_total=42.0)
        self._make_batch([it], batch_date=add_days(today(), -60))
        bt = self._make_bank_transaction(
            deposit=42.0, reference_number=it["invoice"].name, date=today()
        )
        self.assertIsNone(self.mgr.match_by_amount_and_reference(self._txn_dict(bt)))

    def test_multiple_matches_lower_confidence(self):
        # Two batch items, same amount, both referencing same reference via batch-name LIKE.
        it1 = self._make_member_with_invoice(first_name="AmtMulti1", grand_total=55.0)
        it2 = self._make_member_with_invoice(first_name="AmtMulti2", grand_total=55.0)
        batch = self._make_batch([it1, it2])
        # Use the batch name as the reference so the LIKE branch matches BOTH rows.
        bt = self._make_bank_transaction(
            deposit=55.0, reference_number=batch.name, date=today()
        )
        match = self.mgr.match_by_amount_and_reference(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "multiple")
        self.assertEqual(match["confidence"], 0.7)
        self.assertGreaterEqual(len(match["matches"]), 2)


# =============================================================================
# match_by_description (regex + fuzzy fallback)
# =============================================================================
class TestMatchByDescription(BTRBase):
    def test_invoice_number_pattern(self):
        it = self._make_member_with_invoice(first_name="DescInv", grand_total=25.0)
        bt = self._make_bank_transaction(
            deposit=25.0, description=f"Payment for INVOICE {it['invoice'].name}"
        )
        match = self.mgr.match_by_description(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "invoice")
        self.assertEqual(match["reference"], it["invoice"].name)
        self.assertEqual(match["confidence"], 0.9)

    def test_membership_pattern_crashes(self):
        """Regression (FIXED): the MEMBERSHIP-pattern branch of match_by_description
        no longer queries the nonexistent Sales Invoice `membership` column. It
        resolves the membership's member and finds the related unpaid invoice via
        the Sales Invoice `member` field, so a MEMBERSHIP-pattern description maps
        to the related invoice without crashing."""
        it = self._make_member_with_invoice(first_name="DescMemb", grand_total=25.0)
        bt = self._make_bank_transaction(
            deposit=25.0, description=f"MEMBERSHIP {it['membership'].name}"
        )
        match = self.mgr.match_by_description(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["reference"], it["invoice"].name)

    def test_unknown_invoice_falls_through_to_no_match(self):
        bt = self._make_bank_transaction(
            deposit=12345.67, description="INVOICE SINV-DOES-NOT-EXIST-XYZ"
        )
        # Pattern matches but invoice doesn't exist, fuzzy fallback finds nothing.
        self.assertIsNone(self.mgr.match_by_description(self._txn_dict(bt)))

    def test_no_pattern_no_fuzzy_returns_none(self):
        bt = self._make_bank_transaction(deposit=999999.0, description="random text")
        self.assertIsNone(self.mgr.match_by_description(self._txn_dict(bt)))


# =============================================================================
# fuzzy_match_member_name + get_member_unpaid_invoices
# =============================================================================
class TestFuzzyAndMemberInvoices(BTRBase):
    def test_fuzzy_matches_member_name_in_description(self):
        it = self._make_member_with_invoice(first_name="Fuzzylonglastname", grand_total=77.0)
        # Invoice must be Unpaid/Overdue with outstanding == amount and si.member set.
        frappe.db.set_value(
            "Sales Invoice", it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 77.0}, update_modified=False,
        )
        full_name = it["member"].full_name
        match = self.mgr.fuzzy_match_member_name(full_name.upper(), 77.0)
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "invoice")
        self.assertEqual(match["reference"], it["invoice"].name)
        # confidence is score * 0.9, score == 1.0 for exact name
        self.assertLessEqual(match["confidence"], 0.9)

    def test_fuzzy_no_match_for_unrelated_description(self):
        it = self._make_member_with_invoice(first_name="UniqueXyzzy", grand_total=88.0)
        frappe.db.set_value(
            "Sales Invoice", it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 88.0}, update_modified=False,
        )
        self.assertIsNone(self.mgr.fuzzy_match_member_name("ZZZZZ COMPLETELY DIFFERENT", 88.0))

    def test_get_member_unpaid_invoices_returns_match(self):
        it = self._make_member_with_invoice(first_name="UnpaidLook", grand_total=63.0)
        frappe.db.set_value(
            "Sales Invoice", it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 63.0}, update_modified=False,
        )
        result = self.mgr.get_member_unpaid_invoices(it["member"].name, 63.0)
        self.assertIn(it["invoice"].name, result)

    def test_get_member_unpaid_invoices_amount_mismatch_empty(self):
        it = self._make_member_with_invoice(first_name="UnpaidNo", grand_total=63.0)
        frappe.db.set_value(
            "Sales Invoice", it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 63.0}, update_modified=False,
        )
        self.assertEqual(self.mgr.get_member_unpaid_invoices(it["member"].name, 999.0), [])


# =============================================================================
# match_transaction (best-match selection) + create_reconciliation
# =============================================================================
class TestMatchTransactionAndReconcile(BTRBase):
    def test_match_transaction_invoice_match_reconciles(self):
        """End-to-end happy path via the amount+reference (invoice) strategy:
        no BATCH- token in the description, so the highest-confidence match is the
        0.95 invoice match, which reconciles to a real Payment Entry."""
        it = self._make_member_with_invoice(first_name="MatchTxn", grand_total=30.0)
        self._make_batch([it])
        bt = self._make_bank_transaction(
            deposit=30.0, description="SEPA collection",
            reference_number=it["invoice"].name, date=today(),
        )
        result = self.mgr.match_transaction(self._txn_dict(bt))
        self.assertTrue(result)
        bt.reload()
        self.assertEqual(bt.status, "Reconciled")
        # A submitted payment entry referencing the invoice should now exist.
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_name": it["invoice"].name, "reference_doctype": "Sales Invoice"},
            fields=["parent"],
        )
        self.assertTrue(refs, "payment entry should reference the invoice")

    def test_batch_type_reconciliation_bug(self):
        """Regression (FIXED): create_reconciliation now branches on type 'batch'
        and reconciles each invoice in the Direct Debit Batch (via
        create_payment_entries_from_batch) instead of passing the batch name to the
        invoice-only payment service. A perfect (confidence 1.0) batch-reference
        match therefore reconciles. (Former bug: it treated 'batch' like 'invoice'
        and passed the batch name as an invoice name, marking the txn Unreconciled.)
        """
        it = self._make_member_with_invoice(first_name="BatchBug", grand_total=30.0)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=batch.total_amount, date=today())
        match = {
            "type": "batch",
            "reference": batch.name,
            "confidence": 1.0,
            "match_reason": "exact batch ref",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertTrue(ok)
        bt.reload()
        self.assertIn(bt.status, ("Reconciled", "Settled"))

    def test_match_transaction_no_match_returns_false(self):
        bt = self._make_bank_transaction(
            deposit=123456.0, description="totally unmatched", reference_number="NOPE"
        )
        self.assertFalse(self.mgr.match_transaction(self._txn_dict(bt)))

    def test_create_reconciliation_invoice_creates_payment_entry(self):
        it = self._make_member_with_invoice(first_name="ReconInv", grand_total=40.0)
        bt = self._make_bank_transaction(
            deposit=40.0, reference_number="REF-RECON", date=today()
        )
        match = {
            "type": "invoice",
            "reference": it["invoice"].name,
            "confidence": 0.95,
            "match_reason": "test invoice match",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertTrue(ok)
        bt.reload()
        self.assertEqual(bt.status, "Reconciled")
        # Assert via Payment Entry Reference on the invoice (the service links the
        # PE to the invoice; it does NOT populate a custom_bank_transaction field
        # from this code path).
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_name": it["invoice"].name, "reference_doctype": "Sales Invoice"},
            fields=["parent", "allocated_amount"],
        )
        self.assertTrue(refs, "a payment entry referencing the invoice should exist")
        self.assertEqual(flt(refs[0]["allocated_amount"]), 40.0)

    def test_create_reconciliation_multiple_flags_pending(self):
        it = self._make_member_with_invoice(first_name="ReconMulti", grand_total=25.0)
        bt = self._make_bank_transaction(deposit=25.0, date=today())
        match = {
            "type": "multiple",
            "matches": [{"invoice": it["invoice"].name}, {"invoice": "X"}],
            "confidence": 0.7,
            "match_reason": "ambiguous",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertFalse(ok)
        bt.reload()
        self.assertEqual(bt.status, "Pending")

    def test_create_reconciliation_bad_invoice_marks_unreconciled(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        match = {
            "type": "invoice",
            "reference": "SINV-DOES-NOT-EXIST-XYZ",
            "confidence": 0.95,
            "match_reason": "bad ref",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertFalse(ok)
        bt.reload()
        self.assertEqual(bt.status, "Unreconciled")


# =============================================================================
# _mark_transaction_unreconciled
# =============================================================================
class TestMarkUnreconciled(BTRBase):
    def test_marks_status_unreconciled_with_comment(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today())
        self.mgr._mark_transaction_unreconciled({"name": bt.name}, "because reasons")
        bt.reload()
        self.assertEqual(bt.status, "Unreconciled")
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Bank Transaction", "reference_name": bt.name},
            fields=["content"],
        )
        self.assertTrue(any("because reasons" in (c.get("content") or "") for c in comments))


# =============================================================================
# _batch_fetch_invoice_data
# =============================================================================
class TestBatchFetchInvoiceData(BTRBase):
    def test_empty_input_returns_empty(self):
        self.assertEqual(self.mgr._batch_fetch_invoice_data([]), {})

    def test_all_none_returns_empty(self):
        self.assertEqual(self.mgr._batch_fetch_invoice_data([None, None]), {})

    def test_fetches_existing_invoices(self):
        it = self._make_member_with_invoice(first_name="BatchFetch", grand_total=51.0)
        out = self.mgr._batch_fetch_invoice_data([it["invoice"].name, None, "SINV-NOPE"])
        self.assertIn(it["invoice"].name, out)
        self.assertEqual(flt(out[it["invoice"].name].grand_total), 51.0)
        self.assertNotIn("SINV-NOPE", out)


# =============================================================================
# Mollie payment processed tracking
# =============================================================================
class TestMolliePaymentTracking(BTRBase):
    def test_unprocessed_payment_is_false(self):
        pid = f"tr_{frappe.generate_hash(length=10)}"
        self.assertFalse(self.mgr._is_mollie_payment_processed(pid))

    def test_mark_then_is_processed_in_memory(self):
        pid = f"tr_{frappe.generate_hash(length=10)}"
        self.mgr._mark_mollie_payment_processed(pid)
        self.assertTrue(self.mgr._is_mollie_payment_processed(pid))

    def test_db_dedup_field_not_wired(self):
        """Regression (FIXED): custom_mollie_payment_id is now registered as a
        Custom Field on Payment Entry (via the app's custom_field fixture), so doc
        writes to it persist and _is_mollie_payment_processed can detect a
        previously-processed payment from the DB. A submitted PE carrying the id
        makes a fresh manager report it processed."""
        it = self._make_member_with_invoice(first_name="MollieProc", grand_total=25.0)
        pid = f"tr_{frappe.generate_hash(length=10)}"
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        inv = frappe.get_doc("Sales Invoice", it["invoice"].name)
        pe = get_payment_entry(dt="Sales Invoice", dn=inv.name, party_amount=25.0)
        pe.reference_no = pid
        pe.reference_date = today()
        pe.mode_of_payment = "Mollie"
        pe.custom_mollie_payment_id = pid
        pe.insert()
        pe.submit()
        fresh = PaymentReconciliationManager()
        self.assertTrue(fresh._is_mollie_payment_processed(pid))


# =============================================================================
# _get_payment_processing_fees_account
# =============================================================================
class TestFeesAccount(BTRBase):
    def _make_fees_pattern_account(self):
        """Factory helper: create an Account whose name matches a fee pattern."""
        company = self.company
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": "Expense"}, "name"
        ) or frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": "Asset"}, "name"
        )
        acc = frappe.new_doc("Account")
        acc.account_name = f"Payment Processing Fees {frappe.generate_hash(length=5)}"
        acc.company = company
        acc.parent_account = parent
        acc.account_currency = "EUR"
        acc.insert(ignore_permissions=True)
        return acc.name

    def test_resolves_pattern_named_account(self):
        # With no Mollie fees account configured, the method searches for an
        # account whose name matches known fee patterns. Create one and assert it
        # is selected (the pattern-search branch).
        #
        # Determinism: get_fees_account_optional() (an env/config accessor) short-
        # circuits the pattern branch when a site, e.g. veg11, already has a Mollie
        # fees account configured. Patch that config boundary to None so the
        # pattern-search branch is always reached, regardless of site state.
        self._make_fees_pattern_account()
        with patch.object(self.mgr.config, "get_fees_account_optional", return_value=None):
            resolved = self.mgr._get_payment_processing_fees_account()
        self.assertTrue(frappe.db.exists("Account", resolved))
        self.assertIn("Payment Processing Fees", frappe.db.get_value("Account", resolved, "account_name"))

    def test_throws_when_no_account_available(self):
        # No fees account configured, no pattern-named account, and this site has
        # no account_type=="Expense" leaf account -> the method throws.
        #
        # Determinism: patch the config accessor (env/config boundary) so the
        # configured-fees-account short-circuit never fires, regardless of site.
        if frappe.db.count("Account", {"account_type": "Expense", "is_group": 0}):
            self.skipTest("Site has Expense-typed accounts; throw branch not reachable")
        if frappe.db.get_value(
            "Account", {"account_name": ["like", "%Payment Processing Fees%"]}, "name"
        ):
            self.skipTest("A pattern-named fees account already exists on this site")
        with patch.object(self.mgr.config, "get_fees_account_optional", return_value=None):
            with self.assertRaises(frappe.ValidationError):
                self.mgr._get_payment_processing_fees_account()


# =============================================================================
# match_mollie_settlement (early-return branches only; no live Mollie API)
# =============================================================================
class TestMatchMollieSettlementEarlyReturns(BTRBase):
    def test_returns_none_when_no_mollie_bank_account_configured(self):
        # Test site has no mollie_bank_account -> get_bank_account_gl throws
        # ValidationError -> match_mollie_settlement returns None.
        bt = self._make_bank_transaction(
            deposit=100.0, description="mollie settlement payout", date=today()
        )
        self.assertIsNone(self.mgr.match_mollie_settlement(self._txn_dict(bt)))

    def test_returns_none_for_non_mollie_keyword_when_account_set(self):
        # Configure a Mollie bank account that matches the txn's account, but use
        # a description WITHOUT mollie keywords -> still None (keyword branch).
        bank_acc = frappe.db.get_value("Company", self.company, "default_bank_account")
        self.mgr.config.clear_cache()
        frappe.db.set_value("Mollie Settings", "Mollie Settings", "mollie_bank_account", bank_acc)
        self.mgr.config.clear_cache()
        try:
            bt = self._make_bank_transaction(
                deposit=100.0, description="ordinary deposit no keyword",
                date=today(), bank_account=None,
            )
            txn = self._txn_dict(bt)
            txn["bank_account"] = bank_acc  # force account equality
            self.assertIsNone(self.mgr.match_mollie_settlement(txn))
        finally:
            frappe.db.set_value("Mollie Settings", "Mollie Settings", "mollie_bank_account", None)
            self.mgr.config.clear_cache()

    def test_returns_none_for_account_mismatch(self):
        bt = self._make_bank_transaction(
            deposit=100.0, description="mollie settlement", date=today()
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = "SOME-OTHER-GL-ACCOUNT"
        self.assertIsNone(self.mgr.match_mollie_settlement(txn))


# =============================================================================
# reconcile_bank_transactions (whitelist) summary structure
# =============================================================================
class TestReconcileBankTransactions(BTRBase):
    def test_returns_summary_structure(self):
        result = self.mgr.reconcile_bank_transactions()
        for key in ("total_transactions", "matched", "unmatched"):
            self.assertIn(key, result)
        self.assertEqual(
            result["unmatched"], result["total_transactions"] - result["matched"]
        )

    def test_filters_by_bank_account_unknown_returns_zero(self):
        result = self.mgr.reconcile_bank_transactions(bank_account="NO-SUCH-ACCOUNT-XYZ")
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["matched"], 0)

    def test_module_level_reconcile_acquires_lock(self):
        # The module-level function wraps the manager with an advisory lock.
        result = btr.reconcile_bank_transactions(bank_account="NO-SUCH-ACCOUNT-XYZ")
        self.assertIsNotNone(result)
        self.assertEqual(result["total_transactions"], 0)


# =============================================================================
# get_reconciliation_summary (whitelist)
# =============================================================================
class TestReconciliationSummary(BTRBase):
    def test_summary_structure_and_rate(self):
        result = btr.get_reconciliation_summary()
        for key in ("total_transactions", "reconciled", "pending", "unmatched", "reconciliation_rate"):
            self.assertIn(key, result)
        if result["total_transactions"] == 0:
            self.assertEqual(result["reconciliation_rate"], 0)
        else:
            self.assertGreaterEqual(result["reconciliation_rate"], 0)

    def test_summary_counts_reconciled_transaction(self):
        # Side effect: a Reconciled transaction must exist for this date range.
        self._make_bank_transaction(deposit=10.0, date=today(), status="Reconciled")
        result = btr.get_reconciliation_summary(from_date=today(), to_date=today())
        self.assertGreaterEqual(result["reconciled"], 1)
        self.assertGreaterEqual(result["total_transactions"], 1)
        self.assertGreater(result["reconciliation_rate"], 0)


# =============================================================================
# Module-level SEPA return handlers
# =============================================================================
class TestSepaReturnHandlers(BTRBase):
    def test_mark_payment_successful_adds_comment(self):
        it = self._make_member_with_invoice(first_name="MarkSuccess", grand_total=25.0)
        frappe.db.set_value(
            "Sales Invoice", it["invoice"].name, "status", "Unpaid", update_modified=False
        )
        btr.mark_payment_successful(f"E2E-{it['invoice'].name}")
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Sales Invoice", "reference_name": it["invoice"].name},
            fields=["content"],
        )
        self.assertTrue(
            any("SEPA payment accepted" in (c.get("content") or "") for c in comments)
        )

    def test_mark_payment_successful_bad_e2e_noop(self):
        # No "E2E-" prefix -> regex doesn't match -> returns without error.
        self.assertIsNone(btr.mark_payment_successful("GARBAGE-ID"))

    def test_handle_payment_rejection_bad_e2e_noop(self):
        # Malformed end-to-end id returns early (no retry scheduled, no crash).
        self.assertIsNone(btr.handle_payment_rejection("NO-PREFIX", "AM04", "reason"))


# =============================================================================
# create_payment_entries_from_batch — F2 (skip failed rows), F3 (idempotency),
# S2 (conditional Reconciled)
# =============================================================================
class TestBatchReconciliationGuards(BTRBase):
    def _submitted_pe_count_for(self, invoice_name):
        return frappe.db.count(
            "Payment Entry Reference",
            {"reference_doctype": "Sales Invoice", "reference_name": invoice_name, "docstatus": 1},
        )

    def test_failed_row_is_not_booked(self):
        """F2: a bank-rejected (status='Failed') batch row must NOT produce a
        Payment Entry — booking it would overstate cash and mark an unpaid invoice
        as paid."""
        ok_it = self._make_member_with_invoice(first_name="GuardOK", grand_total=30.0)
        failed_it = self._make_member_with_invoice(first_name="GuardFail", grand_total=20.0)
        batch = self._make_batch(
            [ok_it, failed_it], row_status=["Successful", "Failed"]
        )
        bt = self._make_bank_transaction(deposit=30.0, date=today())

        created = self.mgr.create_payment_entries_from_batch(bt, batch.name)

        # Only the collected row is booked.
        self.assertEqual(len(created), 1)
        self.assertEqual(self._submitted_pe_count_for(ok_it["invoice"].name), 1)
        self.assertEqual(
            self._submitted_pe_count_for(failed_it["invoice"].name),
            0,
            "a Failed batch row must not be booked",
        )
        # The Failed invoice stays unpaid.
        failed_inv = frappe.get_doc("Sales Invoice", failed_it["invoice"].name)
        self.assertIn(failed_inv.status, ["Unpaid", "Overdue"])

    def test_pending_row_is_not_booked(self):
        """F2: a not-yet-collected (status='Pending') row is also skipped."""
        it = self._make_member_with_invoice(first_name="GuardPend", grand_total=15.0)
        batch = self._make_batch([it], row_status="Pending")
        bt = self._make_bank_transaction(deposit=15.0, date=today())

        created = self.mgr.create_payment_entries_from_batch(bt, batch.name)

        self.assertEqual(created, [])
        self.assertEqual(self._submitted_pe_count_for(it["invoice"].name), 0)

    def test_rerun_does_not_duplicate_payment_entries(self):
        """F3: re-running batch reconciliation must not create a second Payment
        Entry for an already-booked invoice (idempotency)."""
        it = self._make_member_with_invoice(first_name="GuardDup", grand_total=33.0)
        batch = self._make_batch([it], row_status="Successful")
        bt = self._make_bank_transaction(deposit=33.0, date=today())

        first = self.mgr.create_payment_entries_from_batch(bt, batch.name)
        self.assertEqual(len(first), 1)

        second = self.mgr.create_payment_entries_from_batch(bt, batch.name)
        self.assertEqual(second, [], "re-run must not create duplicate PEs")
        self.assertEqual(
            self._submitted_pe_count_for(it["invoice"].name),
            1,
            "exactly one submitted PE should reference the invoice after a re-run",
        )

    def test_partial_collection_leaves_transaction_unreconciled(self):
        """S2: when failed rows mean the booked total is short of the deposit, the
        bank transaction is left Unreconciled (not falsely Reconciled) so an
        operator sees the discrepancy."""
        ok_it = self._make_member_with_invoice(first_name="GuardPart1", grand_total=30.0)
        failed_it = self._make_member_with_invoice(first_name="GuardPart2", grand_total=20.0)
        batch = self._make_batch([ok_it, failed_it], row_status=["Successful", "Failed"])
        # Deposit reflects the FULL intended batch (50) but only 30 was collected.
        bt = self._make_bank_transaction(deposit=50.0, date=today())
        match = {
            "type": "batch",
            "reference": batch.name,
            "confidence": 1.0,
            "match_reason": "exact batch ref",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertFalse(ok, "partial collection must not report success")
        bt.reload()
        self.assertEqual(
            bt.status, "Unreconciled", "txn must be left Unreconciled on partial collection"
        )

    def test_full_collection_reconciles(self):
        """S2 happy path: when the booked total matches the deposit, the
        transaction is marked Reconciled."""
        it = self._make_member_with_invoice(first_name="GuardFull", grand_total=44.0)
        batch = self._make_batch([it], row_status="Successful")
        bt = self._make_bank_transaction(deposit=44.0, date=today())
        match = {
            "type": "batch",
            "reference": batch.name,
            "confidence": 1.0,
            "match_reason": "exact batch ref",
        }
        ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertTrue(ok)
        bt.reload()
        self.assertIn(bt.status, ("Reconciled", "Settled"))


# =============================================================================
# process_sepa_return_file (whitelist) + parse_pain002_file stub bug
# =============================================================================
class TestProcessSepaReturnFile(BTRBase):
    def test_unsupported_file_type_throws(self):
        with self.assertRaises(frappe.ValidationError):
            btr.process_sepa_return_file("ignored", file_type="mt940")

    def test_pain002_stub_crashes(self):
        """Regression (FIXED): parse_pain002_file now performs a real (minimal,
        namespace-agnostic) parse of the pain.002 transaction-status blocks and
        returns a list (empty for a document with no TxInfAndSts), so
        process_sepa_return_file iterates safely and returns a structured result
        dict with 'processed'."""
        result = btr.process_sepa_return_file("<Document></Document>", file_type="pain.002")
        self.assertIn("processed", result)

    def test_parse_pain002_namespaced_rjct_and_acsp(self):
        """F6: a realistic NAMESPACED pain.002 with one RJCT (carrying a
        StsRsnInf/Rsn/Cd reason code) and one ACSP block must parse into the
        correct status + reason mapping. The RJCT reason code must come from
        StsRsnInf/Rsn/Cd, NOT from an unrelated <Cd> elsewhere in the block."""
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
  <CstmrPmtStsRpt>
    <OrgnlPmtInfAndSts>
      <TxInfAndSts>
        <OrgnlEndToEndId>E2E-INV-001</OrgnlEndToEndId>
        <TxSts>RJCT</TxSts>
        <StsRsnInf>
          <Rsn><Cd>AM04</Cd></Rsn>
          <AddtlInf>Insufficient funds</AddtlInf>
        </StsRsnInf>
        <OrgnlTxRef>
          <PmtTpInf><SvcLvl><Cd>SEPA</Cd></SvcLvl></PmtTpInf>
        </OrgnlTxRef>
      </TxInfAndSts>
      <TxInfAndSts>
        <OrgnlEndToEndId>E2E-INV-002</OrgnlEndToEndId>
        <TxSts>ACSP</TxSts>
      </TxInfAndSts>
    </OrgnlPmtInfAndSts>
  </CstmrPmtStsRpt>
</Document>"""
        rows = btr.parse_pain002_file(xml)
        self.assertEqual(len(rows), 2)
        by_id = {r["end_to_end_id"]: r for r in rows}

        rjct = by_id["E2E-INV-001"]
        self.assertEqual(rjct["status"], "Rejected")
        self.assertEqual(rjct["raw_status"], "RJCT")
        # Reason code is scoped to StsRsnInf/Rsn/Cd — NOT the SvcLvl/Cd="SEPA".
        self.assertEqual(rjct["reason_code"], "AM04")
        self.assertEqual(rjct["reason_text"], "Insufficient funds")

        acsp = by_id["E2E-INV-002"]
        self.assertEqual(acsp["status"], "Accepted")
        self.assertEqual(acsp["raw_status"], "ACSP")

    def test_parse_pain002_malformed_returns_empty_list(self):
        """F6: malformed XML must return [] (so callers iterate safely) rather
        than raising."""
        self.assertEqual(btr.parse_pain002_file("<Document><TxInfAndSts>"), [])


if __name__ == "__main__":
    unittest.main()
