"""#2643: the broad handlers in bank_transaction_reconciliation.py must not swallow a 1213/1205.

Same class as #681 (sepa_reconciliation.py): a handler that catches ``Exception``, logs, and
carries on (or returns a sentinel) turns a deadlock into "no match" / "Unreconciled", and the
write it makes to record that is issued on a transaction the server has already discarded.
``NON_RESUMABLE_DB_ERRORS`` must reach whoever owns the transaction boundary.

Each test drives a PUBLIC entry point and injects the error at a DB call below every handler
that could swallow it. The escape is asserted by identity (the injected instance reaches the
caller) AND by traceback frame (it passed through the function whose handler is under test).
Every group has an ordinary-error control keeping today's fallback, so the tests cannot be
satisfied by "always re-raise".

Stubs, stated plainly: ``SettlementsClient`` is the Mollie HTTP boundary and is replaced where
a settlement has to be fetched. Nothing else in the module under test is mocked; errors are
injected at ``frappe.db``/``Document`` methods, below the code whose handlers are under test.
"""

import traceback
from unittest.mock import MagicMock, patch

import frappe
from frappe.model.document import Document
from frappe.utils import flt, today

from verenigingen.tests.fixtures.mollie_account_fixtures import provisioned_mollie_settings
from verenigingen.tests.payment.test_bank_transaction_reconciliation import BTRBase
from verenigingen.tests.support.non_resumable_errors import deadlock, lock_wait_timeout
from verenigingen.verenigingen_payments.utils import bank_transaction_reconciliation as btr
from verenigingen.verenigingen_payments.utils.bank_transaction_reconciliation import (
    PaymentReconciliationManager,
)

ERRORS = (
    ("deadlock", deadlock, frappe.QueryDeadlockError),
    ("timeout", lock_wait_timeout, frappe.QueryTimeoutError),
)


class _Inject:
    """A fresh exception instance per raise, all remembered in ``raised``.

    One instance raised twice accumulates the frames of BOTH raises in its traceback, so a
    handler that swallowed the first and a later one that re-raised the second would still
    show the first handler's frame. A fresh instance per raise keeps the frame assertion
    about the raise that actually escaped."""

    def __init__(self, factory):
        self.factory = factory
        self.raised = []

    def make(self):
        error = self.factory()
        self.raised.append(error)
        return error


def _exc(error):
    return error.make() if isinstance(error, _Inject) else error


def _on_get_doc(doctype, error, *, only_call=None):
    """Make loading a `doctype` document from the DB raise `error` (``Document.load_from_db``,
    what ``frappe.get_doc(doctype, name)`` calls); `only_call=n` raises on the n-th such load
    only (1-based) so a later handler's own read can succeed."""
    real = Document.load_from_db
    seen = {"n": 0}

    def load_from_db(doc, *args, **kwargs):
        if doc.doctype == doctype:
            seen["n"] += 1
            if only_call is None or seen["n"] == only_call:
                raise _exc(error)
        return real(doc, *args, **kwargs)

    return patch.object(Document, "load_from_db", load_from_db)


def _on_sql(needle, error, *, only_call=None):
    """Make a ``frappe.db.sql`` statement containing `needle` raise `error` (on the n-th such
    statement only, with `only_call=n`)."""
    real = frappe.db.sql
    seen = {"n": 0}

    def sql(query, *args, **kwargs):
        if isinstance(query, str) and needle in query:
            seen["n"] += 1
            if only_call is None or seen["n"] == only_call:
                raise _exc(error)
        return real(query, *args, **kwargs)

    # Mock justified: fault injection: raises the injected lock error for one matching statement only, every other statement runs for real
    return patch.object(frappe.db, "sql", sql)


def _on_db_method(method, pred, error):
    """Make ``frappe.db.<method>(*args)`` raise `error` when ``pred(args, kwargs)``."""
    real = getattr(frappe.db, method)

    def wrapped(*args, **kwargs):
        if pred(args, kwargs):
            raise _exc(error)
        return real(*args, **kwargs)

    return patch.object(frappe.db, method, wrapped)


def _raiser_of(error):
    def raiser(*args, **kwargs):
        raise _exc(error)

    return raiser


def _frame_names(exc):
    return [f.name for f in traceback.extract_tb(exc.__traceback__)]


class TestNonResumableErrorsEscapeBankReconciliation2643(BTRBase):
    def assert_escapes(self, via, call, error, expected_cls):
        """`error` reaches the caller unchanged and passed through function `via`."""
        # try/except, not assertRaises: unittest strips the traceback from the exception it
        # hands back, and the frames are half of what is asserted here.
        try:
            call()
        except Exception as caught:
            self.assertIsInstance(caught, expected_cls)
            self.assertIs(caught, error.raised[-1], "a different exception reached the caller")
            self.assertIn(via, _frame_names(caught))
        else:
            self.fail(f"{expected_cls.__name__} was swallowed instead of escaping {via}")

    # ---- builders -----------------------------------------------------------------

    def _invoice_match(self, first_name, grand_total=40.0):
        it = self._make_member_with_invoice(first_name=first_name, grand_total=grand_total)
        bt = self._make_bank_transaction(deposit=grand_total, date=today())
        match = {
            "type": "invoice",
            "reference": it["invoice"].name,
            "confidence": 0.95,
            "match_reason": "test",
        }
        return it, bt, match

    def _batch_match(self, first_name, grand_total=40.0):
        it = self._make_member_with_invoice(first_name=first_name, grand_total=grand_total)
        batch = self._make_batch([it])
        bt = self._make_bank_transaction(deposit=flt(batch.total_amount), date=today())
        match = {"type": "batch", "reference": batch.name, "confidence": 1.0, "match_reason": "test"}
        return it, bt, match

    def _mollie_match_dict(self):
        return {
            "type": "mollie_settlement",
            "reference": "stl_2643",
            "confidence": 0.98,
            "match_reason": "test",
            "settlement_data": {"id": "stl_2643", "amount": {"value": "40.00"}},
        }

    def _processing_status_of(self, bt):
        return frappe.db.get_value("Bank Transaction", bt.name, "custom_processing_status")

    def _missing_invoice_match(self):
        return {
            "type": "invoice",
            "reference": "SINV-DOES-NOT-EXIST-XYZ",
            "confidence": 0.95,
            "match_reason": "x",
        }

    # ---- _validate_bank_transaction_fields (constructor) ---------------------------

    def _get_meta_failing(self, error):
        real = frappe.get_meta

        def get_meta(doctype, *args, **kwargs):
            if doctype == "Bank Transaction":
                raise _exc(error)
            return real(doctype, *args, **kwargs)

        return patch.object(frappe, "get_meta", get_meta)

    def test_a_non_resumable_error_reading_the_meta_escapes_the_constructor(self):
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._get_meta_failing(err):
                    self.assert_escapes(
                        "_validate_bank_transaction_fields", PaymentReconciliationManager, err, cls
                    )

    def test_an_ordinary_error_reading_the_meta_is_still_a_validation_error(self):
        self.expectErrorLog("Error validating Bank Transaction fields")
        with self._get_meta_failing(RuntimeError("boom")):
            with self.assertRaises(frappe.ValidationError):
                PaymentReconciliationManager()

    # ---- _record_near_miss (via match_transaction) ---------------------------------

    def test_a_non_resumable_error_recording_a_near_miss_escapes_match_transaction(self):
        it, bt = self._near_miss_fixture("NM2643", 61.0)
        txn = self._txn_dict(bt)
        self.assertLess(self.mgr.match_by_description(txn)["confidence"], self.mgr.match_threshold)
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with _on_sql("`tabComment`", err):
                    self.assert_escapes(
                        "_record_near_miss", lambda: self.mgr.match_transaction(txn), err, cls
                    )

    def test_an_ordinary_error_recording_a_near_miss_keeps_its_fallback(self):
        it, bt = self._near_miss_fixture("NM2643c", 61.0)
        self.expectErrorLog("Bank Transaction Comment")
        with _on_sql("`tabComment`", RuntimeError("boom")):
            self.assertFalse(self.mgr.match_transaction(self._txn_dict(bt)))

    # ---- match_mollie_settlement ---------------------------------------------------

    def _mollie_txn(self, accounts):
        bt = self._make_bank_transaction(
            deposit=100.0, description="mollie settlement payout", date=today(), bank_account=None
        )
        txn = self._txn_dict(bt)
        txn["bank_account"] = accounts["bank_account_doc"]
        return txn

    def test_a_non_resumable_error_fetching_settlements_escapes_match_mollie_settlement(self):
        for label, factory, cls in ERRORS:
            with self.subTest(label), provisioned_mollie_settings() as accounts:
                txn = self._mollie_txn(accounts)
                err = _Inject(factory)
                with patch.object(btr, "SettlementsClient", side_effect=_raiser_of(err)):
                    self.assert_escapes(
                        "match_mollie_settlement", lambda: self.mgr.match_mollie_settlement(txn), err, cls
                    )

    def test_an_ordinary_error_fetching_settlements_keeps_its_fallback_of_none(self):
        self.expectErrorLog("Mollie Settlement Matching")
        with provisioned_mollie_settings() as accounts:
            txn = self._mollie_txn(accounts)
            with patch.object(btr, "SettlementsClient", side_effect=RuntimeError("boom")):
                self.assertIsNone(self.mgr.match_mollie_settlement(txn))

    # ---- create_reconciliation: the inner handlers + the outer one -----------------

    def _reconcile_call(self, bt, match):
        return lambda: self.mgr.create_reconciliation(self._txn_dict(bt), match)

    def test_a_non_resumable_error_in_the_batch_branch_escapes_create_reconciliation(self):
        _, bt, match = self._batch_match("B2643")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with _on_get_doc("Direct Debit Batch", err):
                    self.assert_escapes("create_reconciliation", self._reconcile_call(bt, match), err, cls)

    def test_an_ordinary_error_in_the_batch_branch_still_marks_unreconciled(self):
        _, bt, match = self._batch_match("B2643c")
        self.expectErrorLog("SEPA Batch Reconciliation")
        with _on_get_doc("Direct Debit Batch", RuntimeError("boom")):
            self.assertFalse(self._reconcile_call(bt, match)())
        self.assertEqual(self._processing_status_of(bt), "Reconciliation Failed")

    def _outstanding_lookup(self, error):
        return _on_db_method(
            "get_value", lambda a, k: a[:1] == ("Sales Invoice",) and "outstanding_amount" in a, error
        )

    def test_a_non_resumable_error_in_the_invoice_branch_escapes_create_reconciliation(self):
        _, bt, match = self._invoice_match("I2643")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._outstanding_lookup(err):
                    self.assert_escapes("create_reconciliation", self._reconcile_call(bt, match), err, cls)

    def test_an_ordinary_error_in_the_invoice_branch_still_marks_unreconciled(self):
        _, bt, match = self._invoice_match("I2643c")
        self.expectErrorLog("Payment Entry Error")
        with self._outstanding_lookup(RuntimeError("boom")):
            self.assertFalse(self._reconcile_call(bt, match)())
        self.assertEqual(self._processing_status_of(bt), "Reconciliation Failed")

    def test_a_non_resumable_error_reading_the_bank_transaction_escapes_the_outer_handler(self):
        """Only the FIRST read of the Bank Transaction fails, so it is the outer handler's
        own frame that is under test: were it to swallow, its fallback read would succeed."""
        _, bt, match = self._invoice_match("O2643")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with _on_get_doc("Bank Transaction", err, only_call=1):
                    self.assert_escapes("create_reconciliation", self._reconcile_call(bt, match), err, cls)

    def test_an_ordinary_error_reading_the_bank_transaction_is_still_marked_unreconciled(self):
        _, bt, match = self._invoice_match("O2643c")
        self.expectErrorLog("Payment Reconciliation")
        with _on_get_doc("Bank Transaction", RuntimeError("boom"), only_call=1):
            self.assertFalse(self._reconcile_call(bt, match)())
        self.assertEqual(self._processing_status_of(bt), "Reconciliation Failed")

    # ---- _mark_transaction_unreconciled --------------------------------------------

    def test_a_non_resumable_error_marking_unreconciled_escapes(self):
        """A refused invoice (ordinary ValidationError) sends create_reconciliation to
        _mark_transaction_unreconciled; the SECOND Bank Transaction read, made there, fails."""
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        match = self._missing_invoice_match()
        self.expectErrorLog("Payment Entry Validation")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with _on_get_doc("Bank Transaction", err, only_call=2):
                    self.assert_escapes(
                        "_mark_transaction_unreconciled", self._reconcile_call(bt, match), err, cls
                    )

    def test_an_ordinary_error_marking_unreconciled_keeps_its_fallback(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        match = self._missing_invoice_match()
        self.expectErrorLog("Payment Entry Validation", "Transaction Status Update")
        with _on_get_doc("Bank Transaction", RuntimeError("boom"), only_call=2):
            self.assertFalse(self._reconcile_call(bt, match)())

    # ---- the Mollie settlement branch ----------------------------------------------

    def _settlement_fails_ordinarily(self):
        """A real, ordinary failure inside process_mollie_settlement: the Mollie client
        cannot be built. Posts nothing, so the settlement has no posted accounting."""
        return patch.object(btr, "SettlementsClient", side_effect=RuntimeError("mollie down"))

    def _drive_settlement(self, bt):
        return lambda: self.mgr.create_reconciliation(self._txn_dict(bt), self._mollie_match_dict())

    def test_a_non_resumable_error_inside_process_mollie_settlement_escapes_create_reconciliation(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with _on_sql("`tabPayment Entry`", err, only_call=1):  # _reject_leftover_draft_entries
                    self.assert_escapes("create_reconciliation", self._drive_settlement(bt), err, cls)

    def test_an_ordinary_error_inside_process_mollie_settlement_is_still_recorded_retryable(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog("Mollie Settlement Reconciliation", "Error processing Mollie settlement")
        with self._settlement_fails_ordinarily():
            self.assertFalse(self._drive_settlement(bt)())
        # posted nothing -> left in the pool, NOT marked failed
        self.assertNotEqual(self._processing_status_of(bt), "Reconciliation Failed")

    def _posted_accounting_lookup(self, error):
        return _on_db_method(
            "exists",
            lambda a, k: a[:1] == ("Payment Entry",)
            and "custom_mollie_settlement_id" in (a[1] if len(a) > 1 else {}),
            error,
        )

    def test_a_non_resumable_error_checking_for_posted_accounting_escapes(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog("Mollie Settlement Reconciliation", "Error processing Mollie settlement")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._settlement_fails_ordinarily(), self._posted_accounting_lookup(err):
                    self.assert_escapes(
                        "_settlement_has_posted_accounting", self._drive_settlement(bt), err, cls
                    )

    def test_an_ordinary_error_checking_for_posted_accounting_still_assumes_it_posted(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog(
            "Mollie Settlement Reconciliation",
            "Error processing Mollie settlement",
            "Transaction Status Update",
        )
        with self._settlement_fails_ordinarily(), self._posted_accounting_lookup(RuntimeError("boom")):
            self.assertFalse(self._drive_settlement(bt)())
        self.assertEqual(self._processing_status_of(bt), "Reconciliation Failed")

    def _retry_comment_count(self, error):
        return _on_db_method("count", lambda a, k: a[:1] == ("Comment",), error)

    def test_a_non_resumable_error_commenting_a_retryable_failure_escapes(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog("Mollie Settlement Reconciliation", "Error processing Mollie settlement")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._settlement_fails_ordinarily(), self._retry_comment_count(err):
                    self.assert_escapes("_comment_transaction_failure", self._drive_settlement(bt), err, cls)

    def test_an_ordinary_error_commenting_a_retryable_failure_keeps_its_fallback(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog(
            "Mollie Settlement Reconciliation",
            "Error processing Mollie settlement",
            "Transaction Status Update",
        )
        with self._settlement_fails_ordinarily(), self._retry_comment_count(RuntimeError("boom")):
            self.assertFalse(self._drive_settlement(bt)())

    def _unmatched_settlement(self):
        """The real process_mollie_settlement over one payment that names no invoice: it books
        nothing, returns ``fully_reconciled=False`` and so takes create_reconciliation down
        the partial-settlement path (retry comment + processing status)."""
        client = MagicMock()
        client.get_payments_for_settlement.return_value = [
            {"id": "tr_2643u", "description": "no reference here", "amount": {"value": "40.00"}}
        ]
        return patch.object(btr, "SettlementsClient", return_value=client)

    def _failing_status_write(self, error):
        real = Document.db_set

        def db_set(doc, *args, **kwargs):
            if doc.doctype == "Bank Transaction" and args and args[0] == "custom_processing_status":
                raise _exc(error)
            return real(doc, *args, **kwargs)

        return patch.object(Document, "db_set", db_set)

    def test_a_non_resumable_error_setting_the_processing_status_escapes(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._unmatched_settlement(), self._failing_status_write(err):
                    self.assert_escapes("_set_processing_status", self._drive_settlement(bt), err, cls)

    def test_an_ordinary_error_setting_the_processing_status_keeps_its_fallback(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog("Bank Transaction Processing Status")
        with self._unmatched_settlement(), self._failing_status_write(RuntimeError("boom")):
            self.assertFalse(self._drive_settlement(bt)())

    def _failing_comment(self, error):
        real = Document.add_comment

        def add_comment(doc, *args, **kwargs):
            if doc.doctype == "Bank Transaction":
                raise _exc(error)
            return real(doc, *args, **kwargs)

        return patch.object(Document, "add_comment", add_comment)

    def test_a_non_resumable_error_adding_a_comment_escapes(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._unmatched_settlement(), self._failing_comment(err):
                    self.assert_escapes("_add_comment_without_failing", self._drive_settlement(bt), err, cls)

    def test_an_ordinary_error_adding_a_comment_keeps_the_flow_going(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        self.expectErrorLog("Bank Transaction Comment", "Transaction Status Update")
        with self._unmatched_settlement(), self._failing_comment(RuntimeError("boom")):
            # a failed comment must not change the settlement's fate: still the partial path
            self.assertFalse(self._drive_settlement(bt)())
        self.assertEqual(self._processing_status_of(bt), "Partial - Manual Review Required")

    # ---- process_mollie_settlement: batch fetch + per-payment handler --------------

    def _client_returning(self, payments):
        client = MagicMock()
        client.get_payments_for_settlement.return_value = payments
        return patch.object(btr, "SettlementsClient", return_value=client)

    def _process_settlement_call(self, bt):
        return lambda: self.mgr.process_mollie_settlement(
            frappe.get_doc("Bank Transaction", bt.name),
            "stl_2643",
            {"id": "stl_2643", "amount": {"value": "40.00"}},
        )

    def test_a_non_resumable_error_batch_fetching_invoices_escapes_process_mollie_settlement(self):
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        payments = [
            {"id": "tr_2643", "metadata": {"invoice_id": "SINV-2643-NOPE"}, "amount": {"value": "40.00"}}
        ]
        self.expectErrorLog("Error processing Mollie settlement")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._client_returning(payments), _on_sql("`tabSales Invoice`", err):
                    self.assert_escapes("_batch_fetch_invoice_data", self._process_settlement_call(bt), err, cls)

    def test_an_ordinary_error_batch_fetching_invoices_keeps_its_empty_fallback(self):
        self.expectErrorLog("Invoice Batch Fetch")
        with _on_sql("`tabSales Invoice`", RuntimeError("boom")):
            self.assertEqual(self.mgr._batch_fetch_invoice_data(["SINV-2643-NOPE"]), {})

    def _one_payment(self, first_name, payment_id):
        it = self._make_member_with_invoice(first_name=first_name, grand_total=40.0)
        bt = self._make_bank_transaction(deposit=40.0, date=today())
        payments = [
            {
                "id": payment_id,
                "metadata": {"invoice_id": it["invoice"].name},
                "amount": {"value": f"{flt(it['invoice'].grand_total):.2f}"},
            }
        ]
        return bt, payments

    def test_a_non_resumable_error_on_one_payment_escapes_process_mollie_settlement(self):
        bt, payments = self._one_payment("P2643", "tr_2643p")
        self.expectErrorLog("Error processing Mollie settlement")
        for label, factory, cls in ERRORS:
            with self.subTest(label):
                err = _Inject(factory)
                with self._client_returning(payments), _on_get_doc("Sales Invoice", err):
                    self.assert_escapes("process_mollie_settlement", self._process_settlement_call(bt), err, cls)

    def test_an_ordinary_error_on_one_payment_is_still_recorded_and_the_loop_goes_on(self):
        bt, payments = self._one_payment("P2643c", "tr_2643q")
        self.expectErrorLog("Mollie Payment Processing")
        with self._client_returning(payments), _on_get_doc("Sales Invoice", RuntimeError("boom")):
            result = self._process_settlement_call(bt)()
        self.assertEqual([d["status"] for d in result["details"]], ["error"])

