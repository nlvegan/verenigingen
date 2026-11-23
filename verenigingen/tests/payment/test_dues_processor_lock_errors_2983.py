"""#2983: ``process_dues_payment``'s broad handler must not turn a 1213/1205 into an error dict.

``batch_process_customer_payments`` wraps ``process_dues_payment`` in ``execute_with_deadlock_retry``,
but the method catches every ``Exception`` and returns ``{"status": "error"}``, so the retry saw a
normal return and never retried. The lock error is injected at the DRIVER (``Cursor.execute``
raises ``OperationalError(1213/1205)``, which frappe's dispatch wraps into
``QueryDeadlockError`` / ``QueryTimeoutError``), so it passes through every real layer: the Member
save, the Bank Account insert, the Sales Invoice read, the Bank Transaction -> Payment Entry link.

Probe shortcut, stated: the lock error is injected, not provoked (a real deadlock needs a second
connection), so the server does not actually roll the transaction back; the test pins the
control flow (who sees the error), not the database state after it.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.retry_utilities import DEADLOCK_MAX_RETRIES
from verenigingen.utils.validation.iban_validator import generate_test_iban
from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import DuesPaymentProcessor
from verenigingen.verenigingen_payments.mollie.tests.test_dues_payment_processor_creation_unit import (
    DuesCreationTestBase,
    FakeMolliePayment,
    _FakeMollieClient,
    _make_eur_invoice,
)

LOCK_CODES = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))
ALL_ATTEMPTS = DEADLOCK_MAX_RETRIES + 1


class _AttemptCountingProcessor(DuesPaymentProcessor):
    """The real processor; records each ``process_dues_payment`` call (one per retry attempt)."""

    def __init__(self):
        super().__init__()
        self.attempts = []

    def process_dues_payment(self, payment_id, *args, **kwargs):
        self.attempts.append(payment_id)
        return super().process_dues_payment(payment_id, *args, **kwargs)


class TestDuesProcessorLockErrors2983(DuesCreationTestBase):
    def setUp(self):
        super().setUp()
        with patch(
            "verenigingen.verenigingen_payments.mollie.services.dues_payment_processor.MollieClient"
        ):
            self.processor = _AttemptCountingProcessor()
        # Every handler under test writes an Error Log row; none of them is the thing asserted.
        self.expectErrorLog(
            "Mollie Bank Data Save Failed",
            "Bank Account Creation Failed",
            "Dues Payment Processing Error",
            "Sales Invoice Fetch Error",
            "Mollie dues: Bank Transaction not linked",
            "Bank Transaction Creation Error",
            "Payment Router Error",
        )
        self.member = self._member_with_customer()
        self.customer_id = f"cst_2983_{frappe.generate_hash()[:8]}"
        frappe.db.set_value("Member", self.member.name, "mollie_customer_id", self.customer_id)
        self.iban = generate_test_iban("RABO", str(frappe.generate_hash(length=10)).translate(
            {ord(c): "7" for c in "abcdef"}
        ))

    def _paid_dues_payment_2983(self, ref=None):
        return FakeMolliePayment(
            id=ref or f"tr_2983_{frappe.generate_hash()[:8]}",
            status="paid",
            description="contributie",
            customer_id=self.customer_id,
            value="22.50",
            details={"consumerName": "Lock Err", "consumerAccount": self.iban},
        )

    def _processor_for(self, payment):
        self.processor.mollie_client = _FakeMollieClient(payment=payment, customer_payments=[payment])
        return self.processor

    def _driver_raising(self, code, fragment, *, times=None, startswith=("INSERT", "UPDATE")):
        """``Cursor.execute`` raises OperationalError(code) on a write touching *fragment*.

        ``times`` bounds the injections (None = every time). Returns (patcher, hits).
        """
        hits = []
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if (
                isinstance(query, str)
                and query.lstrip().upper().startswith(startswith)
                and all(f in query for f in ((fragment,) if isinstance(fragment, str) else fragment))
                and (times is None or len(hits) < times)
            ):
                hits.append(query)
                raise frappe.db.OperationalError(code, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute), hits

    # -- the defect: the retry around process_dues_payment never saw the error ----------------

    def test_a_deadlock_on_the_bank_account_insert_is_retried(self):
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1213, "`tabBank Account`", times=1)
        with inject:
            result = proc.batch_process_customer_payments(self.customer_id)
        self.assertEqual(len(hits), 1, "the injection must have fired on the Bank Account insert")
        self.assertEqual(len(proc.attempts), 2, "the deadlock must make execute_with_deadlock_retry run it again")
        self.assertEqual(result["results"][0]["status"], "success", result)

    def test_a_persistent_deadlock_exhausts_the_retries_and_names_the_deadlock(self):
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1213, "`tabBank Account`")
        with inject:
            result = proc.batch_process_customer_payments(self.customer_id)
        self.assertEqual(len(proc.attempts), ALL_ATTEMPTS)
        self.assertEqual(result["errors"], 1)
        self.assertIn("1213", result["results"][0]["error"])

    def test_process_dues_payment_raises_the_lock_error_on_the_bank_account_insert(self):
        for code, error in LOCK_CODES:
            with self.subTest(code=code):
                proc = self._processor_for(self._paid_dues_payment_2983())
                inject, hits = self._driver_raising(code, "`tabBank Account`")
                with inject, self.assertRaises(error):
                    proc.process_dues_payment(f"tr_2983_{frappe.generate_hash()[:8]}", self._paid_dues_payment_2983())
                self.assertTrue(hits)

    def test_control_a_lock_timeout_is_not_retried(self):
        """1205 is not a deadlock: ``execute_with_deadlock_retry`` raises it at once (one attempt)."""
        proc = self._processor_for(self._paid_dues_payment_2983())
        inject, hits = self._driver_raising(1205, "`tabBank Account`")
        with inject:
            result = proc.batch_process_customer_payments(self.customer_id)
        self.assertEqual(len(proc.attempts), 1)
        self.assertEqual(result["errors"], 1)

    # -- the Bank Transaction write itself (rule 17) -----------------------------------------------

    def test_a_deadlock_on_the_bank_transaction_insert_or_submit_is_raised_not_reported(self):
        """1213 on the first INSERT / first UPDATE of the Bank Transaction, ONCE: the creator used to
        retry in place, and the retry succeeded, reporting a booking inside a discarded transaction."""
        for verb, writes in (("insert", ("INSERT",)), ("update", ("UPDATE",))):
            with self.subTest(write=verb):
                payment = self._paid_dues_payment_2983()
                proc = self._processor_for(payment)
                inject, hits = self._driver_raising(
                    1213, "`tabBank Transaction`", times=1, startswith=writes
                )
                with inject, self.assertRaises(frappe.QueryDeadlockError):
                    proc.process_dues_payment(payment.id, payment, creation_mode="Bank Transaction")
                self.assertEqual(len(hits), 1, "the injection must have fired")

    def test_control_a_lock_timeout_on_the_bank_transaction_write_is_an_error_result(self):
        """1205 is not raised by the creator (it keeps its generic handler): error dict, as on develop."""
        for verb, writes in (("insert", ("INSERT",)), ("update", ("UPDATE",))):
            with self.subTest(write=verb):
                payment = self._paid_dues_payment_2983()
                proc = self._processor_for(payment)
                inject, hits = self._driver_raising(1205, "`tabBank Transaction`", startswith=writes)
                with inject:
                    result = proc.process_dues_payment(payment.id, payment, creation_mode="Bank Transaction")
                self.assertTrue(hits)
                self.assertEqual(result["status"], "error", result)

    # -- other swallowing layers inside the same try (rule 17) ---------------------------------

    def test_a_deadlock_on_the_sales_invoice_read_after_booking_is_not_reported_as_success(self):
        """The ``Sales Invoice Fetch Error`` handler sits INSIDE the outer try: a 1213 there
        (after the Bank Transaction was written) was logged and the call returned success."""
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(
            1213, ("`tabSales Invoice`", "`status`", "posting_date"), startswith=("SELECT",)
        )
        with inject, self.assertRaises(frappe.QueryDeadlockError):
            proc.process_dues_payment(payment.id, payment, creation_mode="Bank Transaction")
        self.assertTrue(hits)

    def test_a_deadlock_linking_the_bank_transaction_to_the_payment_entry_is_raised(self):
        member = self.member
        invoice = _make_eur_invoice(
            self.company,
            member.customer,
            self.income_account,
            22.5,
            selling_price_list=self._ensure_selling_price_list("EUR"),
        )
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1213, "`tabBank Transaction Payments`")
        with inject, self.assertRaises(frappe.QueryDeadlockError):
            proc.process_dues_payment(
                payment.id, payment, creation_mode="Bank Transaction", invoice_name=invoice.name
            )
        self.assertTrue(hits)

    # -- the opposite harm: the webhook path ------------------------------------------------------
    # The webhook reaches process_dues_payment through PaymentTypeRouter.route_payment, which has no
    # deadlock retry and whose own broad handler turns anything into an error dict. If that error
    # PROPAGATED, the webhook's ``except Exception as classification_error`` would fall through to
    # the DONATION processor. So the router must keep answering with an error dict, and a redelivery
    # (Mollie retries a 5xx) must then book exactly once.

    def _router_for(self, proc):
        from verenigingen.verenigingen_payments.mollie.services.payment_type_router import PaymentTypeRouter

        with patch(
            "verenigingen.verenigingen_payments.mollie.services.payment_type_router.PaymentTypeRouter.__init__",
            lambda router: None,
        ):
            router = PaymentTypeRouter()
        from verenigingen.verenigingen_payments.mollie.domain.payment_classification import PaymentClassifier

        router.classifier = PaymentClassifier()
        router.dues_processor = proc
        return router

    def test_the_router_still_answers_a_deadlock_with_an_error_dict_and_a_redelivery_books_once(self):
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        router = self._router_for(proc)
        inject, hits = self._driver_raising(1213, "`tabBank Account`")
        with inject:
            failed = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertTrue(hits)
        self.assertEqual(failed["status"], "error", failed)
        self.assertEqual(failed["processor"], "none", "an error dict, not a fall-through to another processor")

        first = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertEqual(first["status"], "success", first)
        again = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertEqual(again["status"], "already_processed", again)
        self.assertEqual(again["bank_transaction"], first["bank_transaction"])
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": payment.id}),
            1,
            "a redelivery must not book the payment twice",
        )

    # -- the opposite harm: a 1205 AFTER the payment is fully booked keeps the booking's success ---

    SI_LIST = ("`tabSales Invoice`", "`status`", "posting_date")

    def _matched_invoice_covering(self, payment):
        """An open dues invoice the matcher pairs with the payment (exact amount, paid_at in coverage)."""
        return _make_eur_invoice(
            self.company,
            self.member.customer,
            self.income_account,
            22.5,
            coverage_start="2025-01-01",
            coverage_end="2025-12-31",
            selling_price_list=self._ensure_selling_price_list("EUR"),
        )

    def _booked_counts(self, payment_id):
        return (
            frappe.db.count("Bank Transaction", {"reference_number": payment_id}),
            frappe.db.count("Payment Entry", {"reference_no": payment_id}),
        )

    def test_a_lock_timeout_on_the_post_booking_invoice_list_keeps_the_success(self):
        payment = self._paid_dues_payment_2983()
        invoice = self._matched_invoice_covering(payment)
        router = self._router_for(self._processor_for(payment))
        inject, hits = self._driver_raising(1205, self.SI_LIST, startswith=("SELECT",))
        with inject:
            result = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertTrue(hits)
        self.assertEqual(result["matched_invoice"], invoice.name, "the fixture must reach the PE path")
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(self._booked_counts(payment.id), (1, 1))

    def test_a_deadlock_on_the_post_booking_invoice_list_answers_error_and_a_redelivery_books_once(self):
        payment = self._paid_dues_payment_2983()
        invoice = self._matched_invoice_covering(payment)
        router = self._router_for(self._processor_for(payment))
        inject, hits = self._driver_raising(1213, self.SI_LIST, startswith=("SELECT",))
        with inject:
            failed = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertTrue(hits)
        self.assertEqual(failed["status"], "error", failed)
        self.assertEqual(failed["processor"], "none")
        again = router.route_payment(payment.id, payment, alert_staff=True)
        self.assertEqual(again["status"], "already_processed", again)
        self.assertEqual(self._booked_counts(payment.id), (1, 1), "redelivery must not book twice")

    def test_a_lock_timeout_linking_the_bank_transaction_keeps_the_booking(self):
        payment = self._paid_dues_payment_2983()
        invoice = self._matched_invoice_covering(payment)
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1205, "`tabBank Transaction Payments`")
        with inject:
            result = proc.process_dues_payment(payment.id, payment, creation_mode="Bank Transaction")
        self.assertTrue(hits)
        self.assertEqual(result["status"], "success", result)
        self.assertFalse(result["reconciled"])
        self.assertEqual(self._booked_counts(payment.id), (1, 1))

    # -- the opposite harm: ordinary errors keep the error-dict contract ----------------------

    def test_an_ordinary_error_on_the_sales_invoice_read_still_leaves_the_booking_a_success(self):
        """The Sales Invoice list is informational: an ordinary failure there must not fail the booking."""
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(
            1064, ("`tabSales Invoice`", "`status`", "posting_date"), startswith=("SELECT",)
        )
        with inject:
            result = proc.process_dues_payment(payment.id, payment, creation_mode="Bank Transaction")
        self.assertTrue(hits, "the injection must have fired on the Sales Invoice list")
        self.assertEqual(result["status"], "success", result)
        self.assertTrue(result["bank_transaction"])

    def test_an_ordinary_error_linking_the_bank_transaction_still_reports_not_linked(self):
        invoice = _make_eur_invoice(
            self.company,
            self.member.customer,
            self.income_account,
            22.5,
            selling_price_list=self._ensure_selling_price_list("EUR"),
        )
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1064, "`tabBank Transaction Payments`")
        with inject:
            result = proc.process_dues_payment(
                payment.id, payment, creation_mode="Bank Transaction", invoice_name=invoice.name
            )
        self.assertTrue(hits, "the injection must have fired on the link write")
        self.assertEqual(result["status"], "success", result)
        self.assertTrue(result["payment_entry"], "the Payment Entry stays booked")
        self.assertFalse(result["reconciled"])

    def test_an_ordinary_driver_error_still_returns_the_error_dict(self):
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1064, "`tabBank Account`")
        with inject:
            result = proc.batch_process_customer_payments(self.customer_id)
        self.assertTrue(hits)
        self.assertEqual(len(proc.attempts), 1, "an ordinary error is not retried")
        self.assertEqual(result["results"][0]["status"], "error")

    def test_an_ordinary_error_in_process_dues_payment_returns_not_raises(self):
        payment = self._paid_dues_payment_2983()
        proc = self._processor_for(payment)
        inject, hits = self._driver_raising(1064, "`tabBank Account`")
        with inject:
            result = proc.process_dues_payment(payment.id, payment)
        self.assertTrue(hits)
        self.assertEqual(result["status"], "error")
