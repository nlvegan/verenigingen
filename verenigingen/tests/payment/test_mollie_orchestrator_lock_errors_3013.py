"""#3013: the Mollie orchestrator's broad handlers must not turn a 1213/1205 into a normal return.

Every ``except Exception`` in ``MolliePaymentOrchestrator`` that sits after a write (a Customer, Fiscal
Year, Sales Invoice, Payment Entry insert) used to convert a lock error into ``status="error"`` /
``None`` / a warning line. After a 1213 the server has rolled the WHOLE transaction back, so the caller
(a bulk run, a recovery run, a webhook) carried on, and counted as done, work that no longer existed.
``PaymentEntryCreationService`` additionally re-threw the lock error as a plain ``ValidationError``.

The lock error is injected at the DRIVER (``Cursor.execute`` raises ``OperationalError(1213/1205)``,
which frappe's dispatch wraps into ``QueryDeadlockError`` / ``QueryTimeoutError``), so it passes through
every real layer between the failing statement and the handler under test (README rule 17).

Probe shortcuts, stated:
* the lock error is injected, not provoked, so the server does not really roll back; the tests pin who
  sees the error, not the database state afterwards;
* ``process_bt_only_payment`` has its write one layer down in ``BankTransactionCreator`` (whose own
  swallow is #2983's), so its handler is driven with the injection on the plain Member read that
  precedes it. The handler is the same ``except Exception`` the later write sits under.

Run:
    PYTHONPATH=<worktree> bench --site test_site_7 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_orchestrator_lock_errors_3013
"""

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.payment.test_mollie_orchestrator_coverage_b2 import OrchestratorBase
from verenigingen.tests.support.mollie_settings import (
    pin_mollie_clearing_account,
    pin_payments_settings,
    pin_verenigingen_settings,
)
from verenigingen.verenigingen_payments.mollie.tests.fixtures.payment_entry_fixtures import (
    ensure_mollie_bank_gl_account,
)

LOCK_CODES_3013 = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))
AMOUNT = 25.0


def lock_error_at_driver_3013(code, fragment, *, startswith=("INSERT", "UPDATE")):
    """``Cursor.execute`` raises OperationalError(code) once, on a statement touching *fragment*.

    Returns (patcher, hits). Calls through for every other statement."""
    hits = []
    cursor_cls = frappe.db._cursor.__class__
    real_execute = cursor_cls.execute

    def execute(cursor, query, *args, **kwargs):
        if (
            not hits
            and isinstance(query, str)
            and query.lstrip().upper().startswith(startswith)
            and fragment in query
        ):
            hits.append(query)
            raise frappe.db.OperationalError(code, "injected at the driver")
        return real_execute(cursor, query, *args, **kwargs)

    # Mock justified: fault injection at the driver; every other statement runs for real
    return patch.object(cursor_cls, "execute", execute), hits


class TestOrchestratorLockErrors3013(OrchestratorBase):
    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
            MolliePaymentOrchestrator,
        )

        self.orch = MolliePaymentOrchestrator()
        clearing = ensure_mollie_bank_gl_account(self.company)
        self.assertTrue(clearing, "fixture problem: no Mollie clearing account")
        pin_verenigingen_settings(self, company=self.company)
        pin_mollie_clearing_account(self, clearing)
        pin_payments_settings(self, dues_income_account=self._get_or_create_income_account(self.company))
        self.member = self._make_member_with_customer(first_name="LockProbe")
        self.invoice = self._make_sales_invoice(self.member.customer, today(), today(), outstanding=AMOUNT)
        # Every handler under test logs before it used to swallow; the log is not what is asserted.
        self.expectErrorLog(
            "Mollie Orphan Invoice Error",
            "Mollie Orphaned Payment Error",
            "Mollie BT-Only Payment Error",
            "Mollie Payment Orchestrator Error",
            "Orphan Customer Creation Error",
            "Orphan Invoice Creation Error",
            "Orphan PE Creation Error",
            "Mollie Customer Creation Error",
            "Mollie Fiscal Year Error",
            "Fiscal Year Auto-Creation Error",
            "Payment Entry Unexpected Error",
        )

    def _orphan_payment_stub(self, customer_id=None):
        return SimpleNamespace(
            id=self.pid,
            status="paid",
            amount={"value": f"{AMOUNT:.2f}", "currency": "EUR"},
            paid_at=f"{today()}T10:05:00+00:00",
            created_at=f"{today()}T10:00:00+00:00",
            description="orphan 3013",
            method="ideal",
            metadata={},
            customer_id=customer_id,
        )

    def _assert_lock_error_reaches_caller(self, call, code, error, fragment, **inject_kwargs):
        inject, hits = lock_error_at_driver_3013(code, fragment, **inject_kwargs)
        outcome = []
        try:
            with inject:
                outcome.append(call())
        except error:
            pass
        self.assertTrue(hits, f"the injection never fired on {fragment}; call returned {outcome}")
        self.assertFalse(outcome, f"{error.__name__} was swallowed; call returned {outcome}")

    def _free_orphan_customer_name(self):
        """The fallback Customer may already exist on the site; step it aside so its INSERT is reached."""
        existing = frappe.db.get_value("Customer", {"customer_name": "Orphaned Mollie Payments"}, "name")
        if existing:
            frappe.db.set_value(
                "Customer", existing, "customer_name", f"Orphaned Mollie Payments {self.pid}"
            )

    # -- orphan flow, writes in the orchestrator's own frames --------------------------------------

    def test_a_lock_error_on_the_orphan_customer_insert_reaches_the_caller(self):
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                self._free_orphan_customer_name()
                self._assert_lock_error_reaches_caller(
                    self.orch._get_or_create_orphan_customer, code, error, "`tabCustomer`"
                )

    def test_a_lock_error_on_the_orphan_invoice_insert_reaches_the_caller(self):
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                self._assert_lock_error_reaches_caller(
                    lambda: self.orch.process_orphaned_payment_with_invoice(
                        self.pid, self._orphan_payment_stub()
                    ),
                    code,
                    error,
                    "`tabSales Invoice`",
                )

    def test_a_lock_error_on_the_orphan_payment_entry_insert_reaches_the_caller(self):
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                self._assert_lock_error_reaches_caller(
                    lambda: self.orch.process_orphaned_payment_with_invoice(
                        self.pid, self._orphan_payment_stub()
                    ),
                    code,
                    error,
                    "`tabPayment Entry`",
                )

    def test_a_lock_error_on_the_mollie_customer_insert_reaches_the_caller(self):
        self.orch.mollie_client = SimpleNamespace(
            sdk_client=SimpleNamespace(
                customers=SimpleNamespace(get=lambda cid: SimpleNamespace(name="Lock Probe", email=None))
            )
        )
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                # Mollie's id grammar is enforced before the insert (cst_ + 14 chars), and a fresh
                # payment id per code: the first iteration must not leave a Bank Transaction behind.
                cust_id = f"cst_{frappe.generate_hash(length=14)}"
                self.pid = f"tr_{frappe.generate_hash(length=20)}"
                self._assert_lock_error_reaches_caller(
                    lambda: self.orch.process_orphaned_payment(
                        self.pid, self._orphan_payment_stub(customer_id=cust_id)
                    ),
                    code,
                    error,
                    "`tabCustomer`",
                )

    # -- PaymentEntryCreationService re-threw the lock error as a ValidationError ----------------

    def test_the_payment_entry_service_does_not_rethrow_a_lock_error_as_something_else(self):
        from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config
        from verenigingen.verenigingen_payments.services.payment import payment_entry_service

        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                self._assert_lock_error_reaches_caller(
                    lambda: payment_entry_service.create_payment_entry_from_invoice(
                        invoice_name=self.invoice.name,
                        amount=Decimal(str(AMOUNT)),
                        posting_date=today(),
                        reference_no=self.pid,
                        reference_date=today(),
                        mode_of_payment="Mollie",
                        bank_account=get_mollie_config().get_clearing_account(),
                    ),
                    code,
                    error,
                    "`tabPayment Entry`",
                )

    # -- the main entry: fiscal-year write inside the recovery-mode invoice creation ---------------

    def test_process_payment_raises_a_lock_error_from_the_fiscal_year_insert(self):
        """``create_missing_invoice=True`` is the admin recovery run: a 1213 on the Fiscal Year insert
        passes ``ensure_fiscal_year_exists``, ``_create_invoice_if_safe`` and ``process_payment``."""
        frappe.db.set_value("Member", self.member.name, "mollie_customer_id", f"cst_{self.pid[-10:]}")
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                # A fresh payment id and no 1951 Fiscal Year each time: an earlier iteration must
                # neither leave a Bank Transaction (already_processed) nor a Fiscal Year behind.
                self.pid = f"tr_{frappe.generate_hash(length=20)}"
                frappe.db.delete("Fiscal Year", {"year": "1951"})
                payment = SimpleNamespace(
                    id=self.pid,
                    status="paid",
                    description="contributie",
                    customer_id=f"cst_{self.pid[-10:]}",
                    subscription_id=None,
                    amount={"value": f"{AMOUNT:.2f}", "currency": "EUR"},
                    paid_at="1951-03-15T12:00:00+00:00",
                    details=None,
                )
                self._assert_lock_error_reaches_caller(
                    lambda: self.orch.process_payment(
                        self.pid, payment=payment, member_name=self.member.name, create_missing_invoice=True
                    ),
                    code,
                    error,
                    "`tabFiscal Year`",
                )

    # -- control: an ordinary failure still degrades as before ------------------------------------

    def test_control_an_ordinary_error_on_the_orphan_invoice_insert_keeps_the_error_result(self):
        inject, hits = lock_error_at_driver_3013(1064, "`tabSales Invoice`")
        with inject:
            result = self.orch.process_orphaned_payment_with_invoice(self.pid, self._orphan_payment_stub())
        self.assertTrue(hits)
        self.assertEqual(result.status, "error")
        self.assertEqual(result.error, "Failed to create orphan invoice")

    # -- bt-only: handler driven from the read that precedes the (swallowed-below) write -----------

    def test_process_bt_only_payment_raises_a_lock_error(self):
        for code, error in LOCK_CODES_3013:
            with self.subTest(code=code):
                self._assert_lock_error_reaches_caller(
                    lambda: self.orch.process_bt_only_payment(
                        self.pid, payment=self._orphan_payment_stub(), member_name=self.member.name
                    ),
                    code,
                    error,
                    "`tabMember`",
                    startswith=("SELECT",),
                )
