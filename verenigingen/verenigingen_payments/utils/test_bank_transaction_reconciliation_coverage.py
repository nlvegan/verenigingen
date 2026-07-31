"""
Supplemental real-integration coverage for
verenigingen/verenigingen_payments/utils/bank_transaction_reconciliation.py.

The sibling suite (verenigingen/tests/payment/test_bank_transaction_reconciliation.py)
covers the SEPA matching/reconciliation paths and the pain.002 parser. This module
targets the parts that suite explicitly left uncovered:

  * the Mollie *settlement* reconciliation pipeline
    (match_mollie_settlement live branch, process_mollie_settlement,
    _create_mollie_payment_entry, _create_mollie_fee_entry, and the
    create_reconciliation "mollie_settlement" branch); and
  * a handful of small module helpers / branches
    (resolve_invoice_from_reference, the MEMBER-ID description branch, the
    single-bound date filters, and the process_sepa_return_file accept/reject loop).

The Mollie SettlementsClient is the ONLY thing substituted, and only by swapping
the module-level class name for a hand-rolled stub that returns canned API
payloads (the same `_StubSettlementsClient` boundary pattern used in
test_bulk_transaction_importer_sweep.py). Everything downstream of that HTTP
boundary — invoice matching, Payment Entry creation, fee Journal Entries, amount
validation, duplicate tracking — runs for real against documents built by
SEPATestDataFactory. No business logic is mocked.

PRODUCT BUGS found + fixed here (all in the Mollie settlement pipeline, which
required a live Mollie SettlementsClient and so was never exercised by tests):

  1. _create_mollie_payment_entry set `paid_from = clearing_account`. For a
     "Receive" Payment Entry the party/receivable account IS `paid_from`, so this
     corrupted the party account and ERPNext rejected every settlement payment
     with "... is associated with Debtors, but Party Account is <clearing>". The
     clearing account is the destination, so it must be `paid_to`.
     See TestCreateMolliePaymentEntry.

  2. _create_mollie_fee_entry built a Journal Entry without the mandatory
     `company` field -> "Company is mandatory" whenever settlement fees are booked.
     Fixed by deriving the company from the clearing account's GL account.

  3. _create_mollie_fee_entry also omitted a `cost_center` on the P&L fees row,
     which ERPNext requires (it is NOT auto-filled from the company default during
     JE validation) -> "Cost Center is required for 'Profit and Loss' account ...".
     Fixed by stamping erpnext.get_default_cost_center(company) on each row.
     See TestCreateMollieFeeEntry.test_full_path_creates_balanced_journal_entry.

DEAD CODE flagged (not seeded): _get_payment_processing_fees_account's final
fallback queries Account with filters={"account_type": "Expense", ...}, but
"Expense" is not a valid ERPNext account_type (the options are "Expense Account",
"Direct Expense", "Indirect Expense", ...). That query can never match, so the
fallback always falls through to the frappe.throw. Lines ~1124-1138 are effectively
unreachable; left uncovered and reported rather than seeded.
"""

import contextlib
import unittest
from decimal import Decimal

import frappe
from frappe.utils import flt, today

from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr


class _StubSettlementsClient:
    """HTTP/SDK boundary stand-in for the Mollie SettlementsClient.

    Only the two read methods the reconciliation code calls are implemented; both
    return canned, test-supplied payloads so the extraction / matching / PE-booking
    / fee logic downstream runs for real.
    """

    settlements = []
    payments = []

    def get_settlements_by_date_range(self, _date_from, _date_to):
        return list(type(self).settlements)

    def get_payments_for_settlement(self, _settlement_id):
        return list(type(self).payments)


class MollieBase(BTRBase):
    """Adds Mollie-settlement fixtures (clearing/fees accounts, client stub)."""

    @contextlib.contextmanager
    def _stub_client(self, settlements=None, payments=None):
        """Swap the module-level SettlementsClient for the canned-payload stub."""
        _StubSettlementsClient.settlements = settlements or []
        _StubSettlementsClient.payments = payments or []
        original = btr.SettlementsClient
        btr.SettlementsClient = _StubSettlementsClient
        try:
            yield
        finally:
            btr.SettlementsClient = original

    def _make_gl_account(self, name_prefix, root_type="Asset", account_type=None):
        """Create a leaf GL Account on the EUR test company."""
        company = self.company
        parent = frappe.db.get_value(
            "Account", {"company": company, "is_group": 1, "root_type": root_type}, "name"
        )
        acc = frappe.new_doc("Account")
        acc.account_name = f"{name_prefix} {frappe.generate_hash(length=5)}"
        acc.company = company
        acc.parent_account = parent
        acc.account_currency = "EUR"
        if account_type:
            acc.account_type = account_type
        acc.insert(ignore_permissions=True)
        return acc.name

    def _ensure_company_cost_center(self):
        """Ensure the EUR test company has a default cost center.

        ERPNext Journal Entry validation requires a cost center for P&L (Expense)
        accounts and auto-fills it from the company default. Real deployments set
        this; the fresh CI test company may not, so guarantee it here.
        """
        company = self.company
        existing = frappe.db.get_value("Company", company, "cost_center")
        if existing and frappe.db.exists("Cost Center", existing):
            return existing
        cc = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        if cc:
            frappe.db.set_value("Company", company, "cost_center", cc)
            # erpnext.get_default_cost_center reads the cached Company value; drop the
            # stale cache so the just-written default is visible this request.
            frappe.clear_document_cache("Company", company)
        return cc

    @contextlib.contextmanager
    def _mollie_settings(self, clearing_account=None, fees_account=None, bank_account=None):
        """Temporarily set Mollie Settings GL fields (and restore + clear cache)."""
        keys = {
            "mollie_clearing_account": clearing_account,
            "payment_processing_fees_account": fees_account,
            "mollie_bank_account": bank_account,
        }
        original = {k: frappe.db.get_value("Mollie Settings", "Mollie Settings", k) for k in keys}
        for k, v in keys.items():
            if v is not None:
                frappe.db.set_value("Mollie Settings", "Mollie Settings", k, v)
        self.mgr.config.clear_cache()
        try:
            yield
        finally:
            for k, v in original.items():
                frappe.db.set_value("Mollie Settings", "Mollie Settings", k, v)
            self.mgr.config.clear_cache()

    def _mollie_payment(self, payment_id=None, value="25.00", invoice_id=None, description=None):
        p = {
            "id": payment_id or f"tr_{frappe.generate_hash(length=10)}",
            "amount": {"value": value, "currency": "EUR"},
        }
        if invoice_id is not None:
            p["metadata"] = {"invoice_id": invoice_id}
        if description is not None:
            p["description"] = description
        return p


# =============================================================================
# match_mollie_settlement — live (stubbed) settlement-fetch branch (383-417)
# =============================================================================
class TestMatchMollieSettlementLive(MollieBase):
    def test_amount_match_returns_settlement_match(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=123.45,
            description="Mollie settlement payout",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = bank_gl  # force account equality with the configured Mollie account
        settlement = {"id": "stl_TESTMATCH", "amount": {"value": "123.45", "currency": "EUR"}}
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                match = self.mgr.match_mollie_settlement(txn)
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "mollie_settlement")
        self.assertEqual(match["reference"], "stl_TESTMATCH")
        self.assertEqual(match["confidence"], 0.98)
        self.assertEqual(match["settlement_data"], settlement)

    def test_within_tolerance_lower_confidence(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=1000.00, description="mollie payout", date=today(), bank_account=self._eur_bank_account
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = bank_gl
        # 0.5 off 1000 is within the 0.1% tolerance window (1.0) -> within_tolerance.
        settlement = {"id": "stl_TOL", "amount": {"value": "1000.50", "currency": "EUR"}}
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                match = self.mgr.match_mollie_settlement(txn)
        self.assertIsNotNone(match)
        self.assertEqual(match["confidence"], 0.92)

    def test_no_settlement_amount_match_returns_none(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=50.00, description="mollie settlement", date=today(), bank_account=self._eur_bank_account
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = bank_gl
        settlement = {"id": "stl_NOPE", "amount": {"value": "9999.00", "currency": "EUR"}}
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[settlement]):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))

    def test_zero_deposit_returns_none(self):
        bank_gl = frappe.db.get_value("Company", self.company, "default_bank_account")
        bt = self._make_bank_transaction(
            deposit=0.0,
            withdrawal=5.0,
            description="mollie",
            date=today(),
            bank_account=self._eur_bank_account,
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = bank_gl
        with self._mollie_settings(bank_account=bank_gl):
            with self._stub_client(settlements=[{"id": "x", "amount": {"value": "5.00"}}]):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))


# =============================================================================
# process_mollie_settlement — the full payment breakdown pipeline (817-979)
# =============================================================================
class TestProcessMollieSettlement(MollieBase):
    def test_success_invoice_match_books_payment_entry(self):
        it = self._make_member_with_invoice(first_name="MollieSettleOK", grand_total=25.0)
        invoice_name = it["invoice"].name
        bt = self._make_bank_transaction(deposit=25.0, date=today(), bank_account=self._eur_bank_account)
        payment = self._mollie_payment(value="25.00", invoice_id=invoice_name)
        settlement_data = {"id": "stl_OK", "amount": {"value": "25.00", "currency": "EUR"}}
        with self._stub_client(payments=[payment]):
            result = self.mgr.process_mollie_settlement(bt, "stl_OK", settlement_data)
        self.assertEqual(result["type"], "mollie_settlement")
        self.assertEqual(result["total_payments"], 1)
        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["details"][0]["status"], "success")
        # A real submitted Payment Entry now references the invoice.
        refs = frappe.get_all(
            "Payment Entry Reference",
            filters={"reference_doctype": "Sales Invoice", "reference_name": invoice_name},
            fields=["parent"],
        )
        self.assertTrue(refs, "Mollie settlement should book a Payment Entry for the invoice")

    def test_mixed_payments_classify_each_outcome(self):
        ok = self._make_member_with_invoice(first_name="MollieMixOK", grand_total=40.0)
        mismatch = self._make_member_with_invoice(first_name="MollieMixBad", grand_total=40.0)
        dup_pid = f"tr_{frappe.generate_hash(length=10)}"
        # Pre-mark one payment id processed so the duplicate branch fires.
        self.mgr._mark_mollie_payment_processed(dup_pid)

        payments = [
            {"amount": {"value": "1.00"}},  # missing id -> error
            self._mollie_payment(
                payment_id=dup_pid, value="5.00", invoice_id=ok["invoice"].name
            ),  # duplicate
            self._mollie_payment(value="40.00", invoice_id=ok["invoice"].name),  # success
            self._mollie_payment(value="5.00", description="Invoice: SINV-NOPE-XYZ-9"),  # invoice_not_found
            self._mollie_payment(value="999.00", invoice_id=mismatch["invoice"].name),  # amount_mismatch
            self._mollie_payment(value="3.00", description="grocery store purchase"),  # no_invoice_match
        ]
        # Settlement value == successful reconciled total (40) so the fee branch is skipped.
        settlement_data = {"id": "stl_MIX", "amount": {"value": "40.00", "currency": "EUR"}}
        with self._stub_client(payments=payments):
            bt = self._make_bank_transaction(deposit=40.0, date=today(), bank_account=self._eur_bank_account)
            result = self.mgr.process_mollie_settlement(bt, "stl_MIX", settlement_data)

        statuses = [d["status"] for d in result["details"]]
        self.assertEqual(result["total_payments"], 6)
        self.assertEqual(result["processed_count"], 1)
        self.assertIn("error", statuses)  # missing id
        self.assertIn("duplicate", statuses)
        self.assertIn("success", statuses)
        self.assertIn("invoice_not_found", statuses)
        self.assertIn("amount_mismatch", statuses)
        self.assertIn("no_invoice_match", statuses)
        self.assertEqual(result["total_reconciled"], "40.00")

    def test_empty_settlement_returns_zero_counts(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        settlement_data = {"id": "stl_EMPTY", "amount": {"value": "0.00"}}
        with self._stub_client(payments=[]):
            result = self.mgr.process_mollie_settlement(bt, "stl_EMPTY", settlement_data)
        self.assertEqual(result["total_payments"], 0)
        self.assertEqual(result["processed_count"], 0)

    def test_client_error_propagates(self):
        class _BoomClient:
            def get_payments_for_settlement(self, _sid):
                raise RuntimeError("mollie api down")

        original = btr.SettlementsClient
        btr.SettlementsClient = _BoomClient
        try:
            bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
            with self.assertRaises(RuntimeError):
                self.mgr.process_mollie_settlement(
                    bt, "stl_BOOM", {"id": "stl_BOOM", "amount": {"value": "0"}}
                )
        finally:
            btr.SettlementsClient = original


# =============================================================================
# create_reconciliation — the "mollie_settlement" match branch (586-616)
# =============================================================================
class TestCreateReconciliationMollieBranch(MollieBase):
    def test_mollie_settlement_branch_reconciles(self):
        it = self._make_member_with_invoice(first_name="MollieRecon", grand_total=30.0)
        bt = self._make_bank_transaction(deposit=30.0, date=today(), bank_account=self._eur_bank_account)
        settlement_data = {"id": "stl_RECON", "amount": {"value": "30.00", "currency": "EUR"}}
        match = {
            "type": "mollie_settlement",
            "reference": "stl_RECON",
            "confidence": 0.98,
            "match_reason": "Mollie settlement exact match",
            "settlement_data": settlement_data,
        }
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)
        self.assertTrue(ok)
        bt.reload()
        self.assertEqual(bt.status, "Reconciled")


# =============================================================================
# create_reconciliation "mollie_settlement" branch under PRODUCTION validation
# =============================================================================
class TestCreateReconciliationMollieBranchProduction(MollieBase):
    """The Mollie branch with ``frappe.flags.in_import`` False, as production runs it.

    ``EnhancedTestCase.setUp`` sets ``in_import = True`` (to bypass user-creation
    throttling). ``BaseDocument._validate_selects()`` early-returns on that flag, so
    the sibling class above never checks that the value the branch writes to
    ``custom_processing_status`` is one of the Custom Field's Select options. In
    production the flag is False and an out-of-options value raises on ``save()`` --
    AFTER ``process_mollie_settlement`` has already inserted and SUBMITTED the
    Payment Entries and the fee Journal Entry, which are not rolled back.
    """

    def _bt_comments(self, bank_transaction_name):
        return [
            (c.get("content") or "")
            for c in frappe.get_all(
                "Comment",
                filters={
                    "reference_doctype": "Bank Transaction",
                    "reference_name": bank_transaction_name,
                },
                fields=["content"],
            )
        ]

    def _match(self, settlement_id, amount="30.00"):
        return {
            "type": "mollie_settlement",
            "reference": settlement_id,
            "confidence": 0.98,
            "match_reason": "Mollie settlement exact match",
            "settlement_data": {"id": settlement_id, "amount": {"value": amount, "currency": "EUR"}},
        }

    @contextlib.contextmanager
    def _boom_client(self, message="mollie api down"):
        """Mollie API outage: the settlement fetch fails, so NOTHING is posted."""

        class _BoomClient:
            def get_payments_for_settlement(self, _sid):
                raise RuntimeError(message)

        original = btr.SettlementsClient
        btr.SettlementsClient = _BoomClient
        try:
            yield
        finally:
            btr.SettlementsClient = original

    @contextlib.contextmanager
    def _select_option_not_deployed(self):
        """Reproduce a deploy whose fixtures have not been synced yet: the
        "Mollie Settlement Processed" Select option is absent, so the branch's
        ``save()`` raises -- AFTER ``process_mollie_settlement`` has submitted the
        Payment Entries. This is the exact production incident 4db12397 fixed."""
        field = "Bank Transaction-custom_processing_status"
        original = frappe.db.get_value("Custom Field", field, "options")
        stripped = "\n".join(
            line for line in (original or "").split("\n") if line != "Mollie Settlement Processed"
        )
        frappe.db.set_value("Custom Field", field, "options", stripped, update_modified=False)
        frappe.clear_cache(doctype="Bank Transaction")
        try:
            yield
        finally:
            frappe.db.set_value("Custom Field", field, "options", original, update_modified=False)
            frappe.clear_cache(doctype="Bank Transaction")

    @contextlib.contextmanager
    def _capture_error_logs(self):
        """Collect the Error Log rows written inside the block."""
        marker = frappe.utils.now_datetime()
        before = {
            r.name for r in frappe.get_all("Error Log", filters={"creation": [">=", marker]}, fields=["name"])
        }
        rows = []
        yield rows
        rows.extend(
            r
            for r in frappe.get_all(
                "Error Log",
                filters={"creation": [">=", marker]},
                fields=["name", "method", "error"],
            )
            if r.name not in before
        )

    def test_settlement_reconciles_and_persists_processing_status(self):
        """The happy path must actually reconcile -- and actually book the accounting.

        Every per-payment failure inside ``process_mollie_settlement`` is swallowed
        into the result's ``details`` and the branch still returns True, so status
        assertions alone stay green in a world where ZERO Payment Entries were booked.
        """
        it = self._make_member_with_invoice(first_name="MollieProd", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_PROD")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            # Only the reconciliation call runs with production validation; the
            # fixtures above create Users, which throttle when in_import is False.
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        bt.reload()
        self.assertTrue(
            ok,
            "Mollie settlement reconciliation returned False. Bank Transaction "
            f"status={bt.status!r} custom_processing_status="
            f"{bt.custom_processing_status!r}; comments={self._bt_comments(bt.name)}",
        )
        self.assertEqual(bt.status, "Reconciled")
        self.assertEqual(bt.custom_processing_status, "Mollie Settlement Processed")

        # The deploy-critical artifact: the option must exist on the DEPLOYED Custom
        # Field, not merely in the working copy of fixtures/custom_field.json. On a
        # long-lived site the doc keeps validating against whatever was last synced,
        # so reverting the fixture would otherwise leave this suite green.
        self.assertIn(
            "Mollie Settlement Processed",
            frappe.db.get_value("Custom Field", "Bank Transaction-custom_processing_status", "options"),
        )

        # The accounting really happened.
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            f"no SUBMITTED Payment Entry for Mollie payment {payment['id']}",
        )
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", it["invoice"].name, "outstanding_amount")),
            0.0,
            "the settlement's Payment Entry did not clear the invoice",
        )
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any("Processed 1/1 payments" in c for c in comments),
            f"settlement summary does not report every payment as processed; comments={comments}",
        )

    def test_failure_error_log_keeps_the_traceback(self):
        """``frappe.utils.error.log_error`` takes ``title`` FIRST and, when a second
        argument is given, uses it AS the traceback -- ``frappe.get_traceback()`` is
        never called. ``log_error(f"...{e}", "Some Title")`` therefore writes an Error
        Log row whose stack trace is the literal title string, and swaps the two the
        moment the exception text contains a newline. The stack is the only thing that
        says WHERE a swallowed failure came from."""
        self.expectErrorLog("mollie api down")
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        with self._capture_error_logs() as rows:
            with self._boom_client():
                with self.production_validation():
                    self.mgr.create_reconciliation(self._txn_dict(bt), self._match("stl_TRACE"))

        handler_rows = [r for r in rows if "Mollie Settlement Reconciliation" in f"{r.method}\n{r.error}"]
        self.assertTrue(
            handler_rows,
            f"the Mollie branch handler logged nothing; rows={[r.method for r in rows]}",
        )
        for row in handler_rows:
            # "most recent call last" matches both the plain and the with_context
            # ("Traceback with variables ...") header frappe.get_traceback emits.
            self.assertIn(
                "most recent call last",
                row.error or "",
                f"Error Log row {row.method!r} carries no stack frame -- its 'error' field is "
                f"{row.error!r}, i.e. log_error's title/message arguments were used as the traceback",
            )
            self.assertIn("bank_transaction_reconciliation.py", row.error or "")
            self.assertIn("mollie api down", row.error or "")

    def test_transient_failure_before_posting_stays_retryable(self):
        """A Mollie API outage fails BEFORE anything is posted.

        ``reconcile_bank_transactions`` only ever selects ``{"status": "Pending"}``
        and nothing anywhere moves a Bank Transaction back out of "Unreconciled", so
        marking it Unreconciled removes the deposit from auto-reconciliation forever.
        For a failure that posted no accounting the next run would simply have
        succeeded, so the status must be left alone and only the reason recorded."""
        self.expectErrorLog("mollie api down")
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        with self._boom_client():
            with self.production_validation():
                ok = self.mgr.create_reconciliation(self._txn_dict(bt), self._match("stl_RETRY"))

        self.assertFalse(ok)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"custom_mollie_settlement_id": "stl_RETRY"}),
            "staging error: this must be the nothing-was-posted case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Pending",
            "a settlement that failed before posting anything must stay in the "
            "'Pending' auto-reconciliation pool; nothing ever moves an 'Unreconciled' "
            "transaction back, so marking it here makes a transient outage permanent",
        )
        comments = self._bt_comments(bt.name)
        self.assertTrue(
            any("mollie api down" in c for c in comments),
            f"no Comment records why the settlement failed; comments={comments}",
        )

    def test_failure_after_posting_marks_unreconciled_without_success_comment(self):
        """The settlement HAS posted (and submitted) its Payment Entries and then the
        save() fails because the Select option is not deployed. The transaction must
        NOT stay retryable -- a re-run cannot re-post the payments (the dedup guard
        skips them) but WOULD re-book the fee Journal Entry -- and the success
        comments must not be persisted next to the failure."""
        self.expectErrorLog("custom_processing_status", "Mollie Settlement Reconciliation")
        it = self._make_member_with_invoice(first_name="MollieAfterPost", grand_total=30.0)
        bt = self._make_bank_transaction(
            deposit=30.0, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_AFTERPOST")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._stub_client(payments=[payment]):
            with self._select_option_not_deployed():
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        self.assertFalse(ok)
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            "staging error: nothing was posted, so this is not the after-posting case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Unreconciled",
            "a settlement whose accounting was already posted must be taken out of the "
            "retry pool and put in front of an operator",
        )
        comments = self._bt_comments(bt.name)
        self.assertFalse(
            any("Auto-reconciled" in c for c in comments),
            "add_comment() inserts immediately and is not rolled back by the failing "
            f"save(), so an 'Auto-reconciled' comment ends up directly above "
            f"'Reconciliation failed'; comments={comments}",
        )

    def test_fee_entry_failure_after_posting_marks_unreconciled(self):
        """The other after-posting shape: ``process_mollie_settlement`` itself raises
        (the fee Journal Entry cannot be booked) AFTER submitting the Payment Entries,
        so it never returns and its result is never bound. Retryability must be decided
        on whether accounting was posted, not on whether that call returned."""
        self.expectErrorLog("stl_FEEBOOM", "Mollie Settlement Reconciliation")
        self._ensure_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing FeeBoom", root_type="Asset", account_type="Bank")
        it = self._make_member_with_invoice(first_name="MollieFeeBoom", grand_total=30.0)
        # Mollie kept 1.50 in fees, so the settlement payout is 28.50 -> the fee
        # Journal Entry branch fires, and its fees account does not exist.
        bt = self._make_bank_transaction(
            deposit=28.50, date=today(), bank_account=self._eur_bank_account, status="Pending"
        )
        match = self._match("stl_FEEBOOM", amount="28.50")
        payment = self._mollie_payment(value="30.00", invoice_id=it["invoice"].name)
        with self._mollie_settings(
            clearing_account=clearing, fees_account="Mollie Fees Account That Does Not Exist"
        ):
            with self._stub_client(payments=[payment]):
                with self.production_validation():
                    ok = self.mgr.create_reconciliation(self._txn_dict(bt), match)

        self.assertFalse(ok)
        self.assertTrue(
            frappe.db.exists("Payment Entry", {"custom_mollie_payment_id": payment["id"], "docstatus": 1}),
            "staging error: nothing was posted, so this is not the after-posting case",
        )
        bt.reload()
        self.assertEqual(
            bt.status,
            "Unreconciled",
            "the Payment Entries were already submitted, so this settlement must not "
            "go back into the auto-reconciliation pool",
        )


# =============================================================================
# _create_mollie_payment_entry — direct (1021-1052)
# =============================================================================
class TestCreateMolliePaymentEntry(MollieBase):
    def test_creates_payment_entry_with_mollie_fields(self):
        it = self._make_member_with_invoice(first_name="MolliePE", grand_total=22.0)
        bt = self._make_bank_transaction(deposit=22.0, date=today(), bank_account=self._eur_bank_account)
        pid = f"tr_{frappe.generate_hash(length=10)}"
        payment = self._mollie_payment(payment_id=pid, value="22.00")
        settlement_data = {"id": "stl_PE"}
        pe = self.mgr._create_mollie_payment_entry(bt, it["invoice"].name, payment, settlement_data)
        self.assertTrue(frappe.db.exists("Payment Entry", pe.name))
        self.assertEqual(pe.mode_of_payment, "Mollie")
        self.assertEqual(pe.reference_no, pid)
        self.assertEqual(pe.custom_mollie_payment_id, pid)
        self.assertEqual(pe.custom_mollie_settlement_id, "stl_PE")
        self.assertEqual(pe.custom_bank_transaction, bt.name)

    def test_uses_clearing_account_when_configured(self):
        it = self._make_member_with_invoice(first_name="MolliePEClr", grand_total=18.0)
        clearing = self._make_gl_account("Mollie Clearing", root_type="Asset", account_type="Bank")
        bt = self._make_bank_transaction(deposit=18.0, date=today(), bank_account=self._eur_bank_account)
        payment = self._mollie_payment(value="18.00")
        with self._mollie_settings(clearing_account=clearing):
            pe = self.mgr._create_mollie_payment_entry(bt, it["invoice"].name, payment, {"id": "stl_C"})
        # For a Receive PE the clearing account is the destination (paid_to); paid_from
        # stays the invoice's receivable (party) account.
        self.assertEqual(pe.paid_to, clearing)


# =============================================================================
# _create_mollie_fee_entry — direct (1057-1100) + the company bug
# =============================================================================
class TestCreateMollieFeeEntry(MollieBase):
    def test_tiny_fee_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        self.assertIsNone(self.mgr._create_mollie_fee_entry(bt, Decimal("0.005"), {"id": "stl_T"}))

    def test_no_clearing_account_returns_none(self):
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=""):
            self.assertIsNone(self.mgr._create_mollie_fee_entry(bt, Decimal("1.50"), {"id": "stl_N"}))

    def test_full_path_creates_balanced_journal_entry(self):
        """Regression for the missing-company bug: a positive Mollie fee must book a
        balanced, submitted Journal Entry (clearing debited, fees credited)."""
        self._ensure_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing JE", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees JE", root_type="Expense")
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            je = self.mgr._create_mollie_fee_entry(bt, Decimal("2.50"), {"id": "stl_FEE"})
        self.assertIsNotNone(je)
        self.assertTrue(frappe.db.exists("Journal Entry", je.name))
        self.assertEqual(je.docstatus, 1)
        self.assertEqual(je.total_debit, je.total_credit)
        rows = {r.account: r for r in je.accounts}
        self.assertGreater(rows[clearing].debit_in_account_currency, 0)
        self.assertGreater(rows[fees].credit_in_account_currency, 0)

    def test_negative_fee_inverts_entry(self):
        self._ensure_company_cost_center()
        clearing = self._make_gl_account("Mollie Clearing Neg", root_type="Asset", account_type="Bank")
        fees = self._make_gl_account("Payment Processing Fees Neg", root_type="Expense")
        bt = self._make_bank_transaction(deposit=10.0, date=today(), bank_account=self._eur_bank_account)
        with self._mollie_settings(clearing_account=clearing, fees_account=fees):
            je = self.mgr._create_mollie_fee_entry(bt, Decimal("-1.75"), {"id": "stl_NEG"})
        self.assertIsNotNone(je)
        rows = {r.account: r for r in je.accounts}
        # Negative fee -> clearing credited, fees debited (the inverse of the positive case).
        self.assertGreater(rows[clearing].credit_in_account_currency, 0)
        self.assertGreater(rows[fees].debit_in_account_currency, 0)


# =============================================================================
# resolve_invoice_from_reference (module helper, 1346-1359)
# =============================================================================
class TestResolveInvoiceFromReference(MollieBase):
    def test_direct_invoice_name_match(self):
        it = self._make_member_with_invoice(first_name="ResolveDirect", grand_total=15.0)
        self.assertEqual(btr.resolve_invoice_from_reference(it["invoice"].name), it["invoice"].name)

    def test_embedded_pattern_match(self):
        it = self._make_member_with_invoice(first_name="ResolveEmbed", grand_total=15.0)
        name = it["invoice"].name
        self.assertEqual(btr.resolve_invoice_from_reference(f"payment ref {name} received"), name)

    def test_empty_reference_returns_none(self):
        self.assertIsNone(btr.resolve_invoice_from_reference(""))
        self.assertIsNone(btr.resolve_invoice_from_reference(None))

    def test_unknown_reference_returns_none(self):
        self.assertIsNone(btr.resolve_invoice_from_reference("SINV-0000000-DOES-NOT-EXIST"))


# =============================================================================
# match_by_description — MEMBER ID branch (333-342)
# =============================================================================
class TestMatchByDescriptionMemberBranch(MollieBase):
    def test_member_id_pattern_resolves_unpaid_invoice(self):
        it = self._make_member_with_invoice(first_name="DescMemberId", grand_total=27.0)
        frappe.db.set_value(
            "Sales Invoice",
            it["invoice"].name,
            {"status": "Unpaid", "outstanding_amount": 27.0},
            update_modified=False,
        )
        bt = self._make_bank_transaction(deposit=27.0, description=f"MEMBER ID: {it['member'].name}")
        match = self.mgr.match_by_description(self._txn_dict(bt))
        self.assertIsNotNone(match)
        self.assertEqual(match["type"], "member")
        self.assertEqual(match["reference"], it["invoice"].name)
        self.assertEqual(match["confidence"], 0.8)


# =============================================================================
# Single-bound date filters (124-128, 1408, 1410)
# =============================================================================
class TestDateFilterBranches(MollieBase):
    def test_reconcile_from_date_only(self):
        result = self.mgr.reconcile_bank_transactions(from_date=today())
        self.assertIn("total_transactions", result)

    def test_reconcile_to_date_only(self):
        result = self.mgr.reconcile_bank_transactions(to_date=today())
        self.assertIn("total_transactions", result)

    def test_summary_from_date_only(self):
        result = btr.get_reconciliation_summary(from_date=today())
        self.assertIn("total_transactions", result)

    def test_summary_to_date_only(self):
        result = btr.get_reconciliation_summary(to_date=today())
        self.assertIn("total_transactions", result)


# =============================================================================
# process_sepa_return_file — accept/reject dispatch loop (1223-1233)
# =============================================================================
class TestProcessSepaReturnFileLoop(MollieBase):
    def test_accepted_status_marks_payment(self):
        it = self._make_member_with_invoice(first_name="SepaAccept", grand_total=25.0)
        frappe.db.set_value("Sales Invoice", it["invoice"].name, "status", "Unpaid", update_modified=False)
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.002.001.03">
  <CstmrPmtStsRpt>
    <OrgnlPmtInfAndSts>
      <TxInfAndSts>
        <OrgnlEndToEndId>E2E-{it['invoice'].name}</OrgnlEndToEndId>
        <TxSts>ACSP</TxSts>
      </TxInfAndSts>
    </OrgnlPmtInfAndSts>
  </CstmrPmtStsRpt>
</Document>"""
        result = btr.process_sepa_return_file(xml, file_type="pain.002")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["processed"], 1)
        comments = frappe.get_all(
            "Comment",
            filters={"reference_doctype": "Sales Invoice", "reference_name": it["invoice"].name},
            fields=["content"],
        )
        self.assertTrue(any("SEPA payment accepted" in (c.get("content") or "") for c in comments))


if __name__ == "__main__":
    unittest.main()
