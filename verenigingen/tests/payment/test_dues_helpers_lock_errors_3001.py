"""#3001: the invoice/item helpers behind ``_get_or_create_historical_invoice`` must not swallow 1213/1205.

Reached only from the recovery run (``MolliePaymentOrchestrator.process_payment(create_missing_invoice=True)``)
and ``batch_process_customer_payments(create_payment_entry=True)``, never from ``process_dues_payment``.
Ruling: no retry inside ``_create_simple_invoice`` (a retry of the invoice alone runs in a transaction the
server already rolled back, the #2983 finding); the writing helpers re-raise ``NON_RESUMABLE_DB_ERRORS``.

Probe shortcut, stated: the lock error is injected at ``Cursor.execute`` (a real deadlock needs a second
connection), so the server does not actually roll back; the tests pin who sees the error, not the DB state
after it. ``_eur_invoices_3001`` pins the new Sales Invoice to EUR: this site's default price list is INR
and ``_create_simple_invoice`` sets no currency, so without it validation fails before the INSERT.
"""

from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import frappe

from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.mollie.tests.test_dues_payment_processor_creation_unit import (
    DuesCreationTestBase,
    FakeMolliePayment,
)

LOCK_CODES = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))


class TestDuesHelpersLockErrors3001(DuesCreationTestBase):
    def setUp(self):
        super().setUp()
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.MollieClient"
        ):
            self.processor = DuesPaymentProcessor()
        self.expectErrorLog(
            "Historical Invoice Creation Error",
            "Sales Invoice Creation Error",
            "Mollie Payment Orchestrator Error",
            "Operation Error",
        )
        self.member = self._member_with_customer()
        # The historical-invoice path stops at "no membership type" without a default (this site has none).
        self.membership_type = self.create_test_membership_type(amount=22.5)
        frappe.db.set_single_value(
            "Verenigingen Settings", "default_membership_type", self.membership_type.name
        )
        self.price_list = self._ensure_selling_price_list("EUR")
        frappe.db.set_value("Customer", self.member.customer, "default_price_list", self.price_list)

    @contextmanager
    def _eur_invoices_3001(self):
        real_new_doc = frappe.new_doc

        def new_doc(doctype, *args, **kwargs):
            doc = real_new_doc(doctype, *args, **kwargs)
            if doctype == "Sales Invoice":
                doc.currency = "EUR"
                doc.conversion_rate = 1.0
                doc.selling_price_list = self.price_list
            return doc

        # Mock justified: fixture shim for this site's INR default price list; every other call passes through
        with patch.object(frappe, "new_doc", new_doc):
            yield

    def _inject_lock_error_3001(self, code, fragment, *, startswith=("INSERT", "UPDATE")):
        """``Cursor.execute`` raises OperationalError(code) on a matching statement. Returns (patcher, hits)."""
        hits = []
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if (
                isinstance(query, str)
                and query.lstrip().upper().startswith(startswith)
                and fragment in query
            ):
                hits.append(query)
                raise frappe.db.OperationalError(code, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute), hits

    def _simple_invoice_3001(self):
        member = frappe.get_doc("Member", self.member.name)
        return self.processor._create_simple_invoice(
            member, "Probe Type", date(2025, 1, 1), date(2025, 12, 31), 22.5, date(2025, 1, 5)
        )

    def _payment_3001(self):
        return FakeMolliePayment(
            id=f"tr_3001_{frappe.generate_hash()[:8]}", status="paid", value="22.50", customer_id="cst_3001"
        )

    # -- _create_simple_invoice -------------------------------------------------------------------

    def test_simple_invoice_raises_a_lock_error_after_exactly_one_attempt(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._inject_lock_error_3001(code, "`tabSales Invoice`", startswith=("INSERT",))
                with self._eur_invoices_3001(), inject, self.assertRaises(error):
                    self._simple_invoice_3001()
                self.assertEqual(len(hits), 1, "no in-place retry: the server rolled the unit back")

    def test_control_simple_invoice_still_returns_none_on_an_ordinary_error(self):
        inject, hits = self._inject_lock_error_3001(1064, "`tabSales Invoice`", startswith=("INSERT",))
        with self._eur_invoices_3001(), inject:
            self.assertIsNone(self._simple_invoice_3001())
        self.assertEqual(len(hits), 1, "an ordinary error is not retried either")

    def test_control_simple_invoice_creates_the_invoice_when_nothing_fails(self):
        with self._eur_invoices_3001():
            name = self._simple_invoice_3001()
        self.assertTrue(name and frappe.db.exists("Sales Invoice", name), "the shim fixture must reach a real insert")

    # -- _get_or_create_dues_item -----------------------------------------------------------------

    def test_dues_item_raises_a_lock_error_instead_of_a_generic_item_name(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                name = f"Membership Dues - Probe{frappe.generate_hash()[:6]}"
                inject, hits = self._inject_lock_error_3001(code, "`tabItem`", startswith=("INSERT",))
                with inject, self.assertRaises(error):
                    self.processor._get_or_create_dues_item(name, self.company, self.income_account)
                self.assertTrue(hits)

    def test_control_dues_item_still_falls_back_on_an_ordinary_error(self):
        name = f"Membership Dues - Probe{frappe.generate_hash()[:6]}"
        inject, hits = self._inject_lock_error_3001(1064, "`tabItem`", startswith=("INSERT",))
        with inject:
            out = self.processor._get_or_create_dues_item(name, self.company, self.income_account)
        self.assertTrue(hits)
        self.assertNotEqual(out, name, "the old fallback to another item name is kept for ordinary errors")

    # -- _get_or_create_historical_invoice ---------------------------------------------------------

    def test_historical_invoice_raises_a_lock_error_from_its_reads(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                inject, hits = self._inject_lock_error_3001(code, "`tabSales Invoice`", startswith=("SELECT",))
                with inject, self.assertRaises(error):
                    self.processor._get_or_create_historical_invoice(self.member.name, date(2025, 1, 5), 22.5)
                self.assertTrue(hits, "the injection must have fired")

    def test_control_historical_invoice_still_returns_none_on_an_ordinary_error(self):
        inject, hits = self._inject_lock_error_3001(1064, "`tabSales Invoice`", startswith=("SELECT",))
        with inject:
            out = self.processor._get_or_create_historical_invoice(self.member.name, date(2025, 1, 5), 22.5)
        self.assertTrue(hits)
        self.assertIsNone(out)

    def test_historical_invoice_raises_a_lock_error_from_the_invoice_insert(self):
        """The full chain, not the reads: Sales Invoice INSERT -> _create_simple_invoice -> historical."""
        inject, hits = self._inject_lock_error_3001(1213, "`tabSales Invoice`", startswith=("INSERT",))
        with self._eur_invoices_3001(), inject, self.assertRaises(frappe.QueryDeadlockError):
            self.processor._get_or_create_historical_invoice(self.member.name, date(2025, 1, 5), 22.5)
        self.assertEqual(len(hits), 1)

    # -- the harm: no unallocated Payment Entry after a deadlock -----------------------------------

    def test_a_deadlock_creating_the_invoice_books_no_unallocated_payment_entry(self):
        payment = self._payment_3001()
        inject, hits = self._inject_lock_error_3001(1213, "`tabSales Invoice`", startswith=("INSERT",))
        with self._eur_invoices_3001(), inject, self.assertRaises(frappe.QueryDeadlockError):
            self.processor._create_payment_entry_for_dues(self.member.name, payment)
        self.assertTrue(hits)
        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": payment.id}))

    def test_control_an_ordinary_invoice_error_keeps_the_unallocated_payment_entry(self):
        payment = self._payment_3001()
        inject, hits = self._inject_lock_error_3001(1064, "`tabSales Invoice`", startswith=("INSERT",))
        with self._eur_invoices_3001(), inject:
            pe = self.processor._create_payment_entry_for_dues(self.member.name, payment)
        self.assertTrue(hits)
        self.assertTrue(pe, "the old behaviour (unallocated PE on an ordinary invoice failure) is kept")

    # -- the recovery run (the only live path) -----------------------------------------------------

    def _recovery_3001(self, payment):
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            MolliePaymentOrchestrator,
        )

        orchestrator = MolliePaymentOrchestrator()
        orchestrator.dues_processor = self.processor
        return orchestrator.process_payment(
            payment.id, payment=payment, member_name=self.member.name, create_missing_invoice=True
        )

    def test_a_deadlocked_recovery_run_reports_a_failure_and_a_rerun_books_once(self):
        payment = self._payment_3001()
        inject, hits = self._inject_lock_error_3001(1213, "`tabSales Invoice`", startswith=("INSERT",))
        with self._eur_invoices_3001(), inject:
            failed = self._recovery_3001(payment)
        self.assertTrue(hits, "the injection must have fired on the invoice insert")
        self.assertEqual(failed.status, "error", failed.to_dict())
        self.assertEqual(failed.exception_type, "QueryDeadlockError")
        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": payment.id}))

        with self._eur_invoices_3001():
            rerun = self._recovery_3001(payment)
        self.assertEqual(rerun.status, "success", rerun.to_dict())
        with self._eur_invoices_3001():
            again = self._recovery_3001(payment)
        self.assertNotEqual(again.status, "error", again.to_dict())
        self.assertEqual(
            frappe.db.count("Payment Entry", {"reference_no": payment.id}),
            1,
            "a re-run must not book the payment twice",
        )
