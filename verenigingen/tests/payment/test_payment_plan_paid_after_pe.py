# Copyright (c) 2026, Verenigingen
"""PaymentPlan.process_payment() marks Paid only after the PE succeeds -- #1288.

Before this fix, process_payment() saved the installment as Paid (and, on a
partial payment, rewrote its amount/notes) BEFORE calling
create_payment_entry(), and create_payment_entry() swallowed its own
exceptions (log_error, no re-raise, no signal to the caller). Any PE failure
therefore left the installment permanently Paid with no Payment Entry and no
retry -- the only trace was an Error Log row.

Most of this file forces a PE failure by patching create_payment_entry()
itself, to isolate the ORDERING/atomicity half of the fix (decision 1) from
PE-creation correctness (covered separately by
test_payment_plan_create_payment_entry.py). That patch replaces the whole
method, so it cannot discriminate the SECOND half of the fix -- that
create_payment_entry() itself no longer swallows its own exceptions
(decision 2): a mocked-out method has no swallow to remove either way.
TestCreatePaymentEntryPropagatesFailure below forces a REAL failure inside
the unmocked method body instead, specifically to red/green that half.

Asserts:

1. process_payment() itself: the installment mutation (status/payment_date/
   payment_reference/amount/notes) does not land, and the exception
   propagates to the caller.
2. create_payment_entry() itself: a real failure inside its own body (an
   unconfigured company) propagates out rather than being logged and
   swallowed.
3. The webhook finalizer (finalize_payment_plan_installment): the failure
   becomes an "error" result (which the Mollie and Pay.nl webhook handlers
   both turn into an HTTP 500 so the gateway retries), the installment stays
   payable, and the Payment Plan Payment intent is NOT marked Paid, so a
   redelivered webhook can retry.
4. That retry is idempotent once the underlying cause is gone: it creates
   exactly one Payment Entry and marks the installment Paid exactly once --
   not a second PE and not a double-applied payment.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.singleton_backup import singleton_backup
from verenigingen.tests.support.invoice_payments import member_with_customer
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.doctype.payment_plan.payment_plan import PaymentPlan
from verenigingen.verenigingen_payments.services.payment_plan_finalization import (
    finalize_payment_plan_installment,
)

_PE_FAILURE_MESSAGE = "Simulated Payment Entry failure (#1288 test)"


class TestProcessPaymentAtomicity(VereningingenTestCase):
    """process_payment() itself: no partial state when the PE fails."""

    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Atomic"
        m.last_name = "Member"
        m.email = f"atomic-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _create_plan(self, member_name, total_amount=120.0, installments=3):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = total_amount
        p.number_of_installments = installments
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def test_pe_failure_leaves_installment_untouched_and_raises(self):
        original = self.plan.installments[0].as_dict()
        installment_amount = original["amount"]

        with patch.object(PaymentPlan, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)):
            with self.assertRaises(RuntimeError) as cm:
                self.plan.process_payment(
                    installment_number=1,
                    payment_amount=installment_amount,
                    payment_reference="ATOMIC-REF-1",
                    payment_date=today(),
                )
        self.assertEqual(str(cm.exception), _PE_FAILURE_MESSAGE)

        # Re-fetch from the DB (not the in-memory doc, which the savepoint
        # rollback does not touch) -- the mutation must not have landed.
        reloaded = frappe.get_doc("Payment Plan", self.plan.name)
        first = reloaded.installments[0]
        self.assertEqual(first.status, "Pending", "installment must NOT be Paid when the PE fails")
        self.assertEqual(first.amount, installment_amount, "partial-payment amount rewrite must roll back too")
        self.assertFalse(first.payment_reference)
        self.assertIsNone(first.payment_date)

    def test_pe_failure_on_partial_payment_also_rolls_back(self):
        """The partial-payment branch mutates amount/notes before the PE call --
        those mutations must roll back together with the Paid mutation, not
        independently."""
        installment_amount = self.plan.installments[0].amount
        partial_amount = installment_amount / 2

        with patch.object(PaymentPlan, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)):
            with self.assertRaises(RuntimeError):
                self.plan.process_payment(
                    installment_number=1,
                    payment_amount=partial_amount,
                    payment_reference="ATOMIC-PARTIAL-1",
                )

        reloaded = frappe.get_doc("Payment Plan", self.plan.name)
        first = reloaded.installments[0]
        self.assertEqual(first.status, "Pending")
        self.assertEqual(first.amount, installment_amount, "the reduced/partial amount must not persist")
        self.assertFalse(first.notes)


class TestFinalizationAtomicity(VereningingenTestCase):
    """The webhook-facing finalizer sees the failure and leaves a retryable state."""

    def setUp(self):
        super().setUp()
        self.member = self._create_member()
        self.plan = self._create_plan(self.member.name)

    def _create_member(self):
        m = frappe.new_doc("Member")
        m.first_name = "Fin"
        m.last_name = "Atomic"
        m.email = f"fin-atomic-{frappe.generate_hash(length=6)}@example.com"
        m.member_since = today()
        m.save(ignore_permissions=True)
        self.track_doc("Member", m.name)
        return m

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = 120.0
        p.number_of_installments = 3
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def _create_intent(self, installment_number=1, amount=40.0, payment_id="ref_1"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": self.plan.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": self.member.name,
                "gateway": "Mollie",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Payment Plan Payment", intent.name)
        # Commit the fixture (member/plan/intent) so it represents data from
        # an already-completed prior request. finalize_payment_plan_installment's
        # own except branch does a FULL frappe.db.rollback() (by design, matching
        # its "one request = one transaction" model) -- without this commit that
        # rollback reverts past this test's own uncommitted setUp data too (a
        # known harness hazard: see enhanced_test_factory.py's "transaction-wide
        # frappe.db.rollback() that wipes THIS test's uncommitted setUp data").
        # Named `_create_*` so scripts/testing/scan_order_dependence.py's COMMIT
        # exemption applies (a fixture-builder commit, not a leak).
        frappe.db.commit()
        return intent

    def test_pe_failure_returns_error_and_leaves_installment_and_intent_payable(self):
        intent = self._create_intent(payment_id="ref_pe_fail")
        self.expectErrorLog("Payment Plan Payment Webhook")

        with patch.object(PaymentPlan, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)):
            result = finalize_payment_plan_installment(intent.name, payment_reference="ref_pe_fail", status="paid")

        self.assertEqual(result["status"], "error")

        intent.reload()
        self.assertNotEqual(intent.status, "Paid", "a redelivered webhook must be able to retry this intent")
        self.assertFalse(intent.paid)

        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Pending")

    def test_redelivered_webhook_after_transient_failure_is_idempotent(self):
        """First delivery hits a PE failure (patched); the redelivered webhook,
        once the cause is gone, must finalize exactly once -- not double-process
        the now-still-Pending installment."""
        intent = self._create_intent(payment_id="ref_retry")
        self.expectErrorLog("Payment Plan Payment Webhook")

        with patch.object(PaymentPlan, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)):
            first = finalize_payment_plan_installment(intent.name, payment_reference="ref_retry", status="paid")
        self.assertEqual(first["status"], "error")

        # Real retry: create_payment_entry() runs for real this time (the
        # member's Customer was auto-created by Member.after_insert, and
        # test_site_1's Verenigingen Settings.company already resolves to a
        # usable EUR company -- see TestRetryCreatesExactlyOnePaymentEntry,
        # which asserts that resolution explicitly rather than relying on it
        # ambiently). The point here is the finalizer's own idempotency, not
        # PE correctness, which test_payment_plan_create_payment_entry.py and
        # TestRetryCreatesExactlyOnePaymentEntry below cover directly.
        second = finalize_payment_plan_installment(intent.name, payment_reference="ref_retry", status="paid")
        self.assertEqual(second["status"], "success")

        intent.reload()
        self.assertEqual(intent.status, "Paid")
        self.assertTrue(intent.paid)

        plan = frappe.get_doc("Payment Plan", self.plan.name)
        self.assertEqual(plan.installments[0].status, "Paid")

        # A third (duplicate) delivery must be a no-op, not a second attempt.
        third = finalize_payment_plan_installment(intent.name, payment_reference="ref_retry", status="paid")
        self.assertEqual(third["status"], "skipped")


class TestRetryCreatesExactlyOnePaymentEntry(EnhancedTestCase):
    """A redelivered webhook, once the transient PE failure is gone, must create
    exactly one real Payment Entry -- not a second one alongside a stray first
    attempt from before the fix."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.company = get_eur_test_company()

    def _plan(self, member_name):
        plan = frappe.new_doc("Payment Plan")
        plan.member = member_name
        plan.plan_type = "Equal Installments"
        plan.total_amount = 90.0
        plan.number_of_installments = 3
        plan.frequency = "Monthly"
        plan.start_date = today()
        plan.status = "Active"
        plan.reason = "test"
        plan.payment_method = "Bank Transfer"
        plan.save()
        self.track_doc("Payment Plan", plan.name)
        return plan

    def _create_intent(self, plan, member_name, installment_number=1, amount=30.0, payment_id="ref_1"):
        intent = frappe.get_doc(
            {
                "doctype": "Payment Plan Payment",
                "payment_plan": plan.name,
                "installment_number": installment_number,
                "amount": amount,
                "currency": "EUR",
                "member": member_name,
                "gateway": "Mollie",
                "status": "Pending",
                "payment_id": payment_id,
            }
        ).insert()
        self.track_doc("Payment Plan Payment", intent.name)
        # Commit: finalize_payment_plan_installment's except branch does a FULL
        # frappe.db.rollback() by design (one request = one transaction). Without
        # committing the fixture first, that rollback would revert this test's own
        # uncommitted setUp data too -- see the identical note in
        # TestFinalizationAtomicity._create_intent above. Named `_create_*` so
        # scan_order_dependence.py's COMMIT exemption applies.
        frappe.db.commit()
        return intent

    def _create_eur_default_company_if_needed(self, company):
        """Idempotently make `company` the resolvable default (Verenigingen
        Settings.company), durably -- NOT via singleton_backup, because the
        same full-rollback this test deliberately provokes (see
        _create_intent above) would undo an uncommitted restore-on-exit just
        as it would any other uncommitted write, leaving the setting wrong
        for the real retry that follows. Mirrors the same idempotent,
        committed-once-if-needed shape as tests/setup/ensure_default_company().
        A no-op (no mutation, nothing to commit) when already correct, which
        is expected on this app's own test sites (#1288 self-review: do not
        silently depend on ambient site config -- assert/ensure it instead).
        """
        if frappe.db.get_single_value("Verenigingen Settings", "company") == company:
            return
        frappe.db.set_single_value("Verenigingen Settings", "company", company)
        frappe.db.commit()

    def test_retry_creates_exactly_one_payment_entry(self):
        member = member_with_customer(self, "PPRetry")
        plan = self._plan(member.name)
        self._create_eur_default_company_if_needed(self.company)

        # Intent creation commits (see _create_intent) -- durable, so it survives
        # the FULL rollback the first (failing) finalize call below issues.
        intent = self._create_intent(plan, member.name, payment_id="PPRETRY-REF-1")

        with patch.object(PaymentPlan, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)):
            self.expectErrorLog("Payment Plan Payment Webhook")
            first = finalize_payment_plan_installment(
                intent.name, payment_reference="PPRETRY-REF-1", status="paid"
            )
        self.assertEqual(first["status"], "error")

        # No PE from the failed attempt.
        self.assertEqual(
            frappe.get_all(
                "Payment Entry",
                filters={"party": member.customer, "reference_no": "PPRETRY-REF-1"},
            ),
            [],
        )

        with self.assertNoErrorLog():
            second = finalize_payment_plan_installment(
                intent.name, payment_reference="PPRETRY-REF-1", status="paid"
            )
        self.assertEqual(second["status"], "success")

        payment_entries = frappe.get_all(
            "Payment Entry",
            filters={"party": member.customer, "reference_no": "PPRETRY-REF-1"},
            fields=["name"],
        )
        self.assertEqual(len(payment_entries), 1, "the retry must create exactly one Payment Entry")
        pe = frappe.get_doc("Payment Entry", payment_entries[0].name)
        self.factory.track_document("Payment Entry", pe.name, priority=6)
        self.assertEqual(pe.docstatus, 1)

        plan.reload()
        self.assertEqual(plan.installments[0].status, "Paid")

        intent.reload()
        self.assertEqual(intent.status, "Paid")

        # A duplicate delivery after success must not create a second PE.
        third = finalize_payment_plan_installment(intent.name, payment_reference="PPRETRY-REF-1", status="paid")
        self.assertEqual(third["status"], "skipped")
        self.assertEqual(
            len(
                frappe.get_all(
                    "Payment Entry",
                    filters={"party": member.customer, "reference_no": "PPRETRY-REF-1"},
                )
            ),
            1,
        )


class TestCreatePaymentEntryPropagatesFailure(VereningingenTestCase):
    """create_payment_entry() itself no longer swallows -- #1288 decision (2).

    Every other class in this file patches create_payment_entry() away
    entirely to isolate ordering/atomicity, which cannot discriminate THIS
    half of the fix: a mocked-out method has no swallow to remove either way.
    This class forces a REAL failure inside the unmocked method body -- a
    Company with no Chart of Accounts, so default_receivable_account and
    default_cash_account are both unset, the exact failure mode #1288 names
    -- and asserts the exception actually propagates out of process_payment()
    instead of being logged and swallowed. Against the pre-fix body, this
    same failure is caught inside create_payment_entry(), logged, and
    discarded: process_payment() returns normally with the installment
    already saved as Paid.
    """

    def setUp(self):
        super().setUp()
        self.broken_company = self._create_broken_company()

    def _create_broken_company(self):
        """A company with no Chart of Accounts (cheap to insert, nothing to
        clean up -- same pattern test_harness_production_fidelity.py uses),
        so it never gets default_receivable_account/default_cash_account."""
        frappe.local.flags.ignore_chart_of_accounts = True
        try:
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": f"1288 Broken Co {frappe.generate_hash(length=6)}",
                    "abbr": frappe.generate_hash(length=5).upper(),
                    "default_currency": "EUR",
                    "country": "Netherlands",
                }
            ).insert()
        finally:
            frappe.local.flags.ignore_chart_of_accounts = False
        self.track_doc("Company", company.name)
        return company

    def _create_plan(self, member_name):
        p = frappe.new_doc("Payment Plan")
        p.member = member_name
        p.plan_type = "Equal Installments"
        p.total_amount = 120.0
        p.number_of_installments = 3
        p.frequency = "Monthly"
        p.start_date = today()
        p.status = "Active"
        p.reason = "test"
        p.payment_method = "Bank Transfer"
        p.save(ignore_permissions=True)
        self.track_doc("Payment Plan", p.name)
        return p

    def test_pe_failure_propagates_instead_of_being_swallowed(self):
        member = member_with_customer(self, "SwallowGuard")
        plan = self._create_plan(member.name)
        installment_amount = plan.installments[0].amount

        # process_payment() calls straight through to the real,
        # unmocked create_payment_entry(); no full-transaction rollback is
        # involved here (that only happens inside finalize_payment_plan_
        # installment, exercised elsewhere in this file), so a plain
        # singleton_backup with its usual restore-on-exit is safe.
        with singleton_backup("Verenigingen Settings"):
            settings = frappe.get_single("Verenigingen Settings")
            settings.company = self.broken_company.name
            settings.save()

            with self.assertNoErrorLog():
                # The real failure mode: paid_from/paid_to resolve to None (the
                # broken company has neither account configured), so ERPNext's
                # own set_exchange_rate() cannot resolve a currency and PE.save()
                # raises "Source Exchange Rate is mandatory" -- a ValidationError,
                # not MandatoryError (matches the #1200 comment in
                # create_payment_entry describing this exact failure shape).
                with self.assertRaises(frappe.ValidationError):
                    plan.process_payment(
                        installment_number=1,
                        payment_amount=installment_amount,
                        payment_reference="SWALLOW-GUARD-1",
                        payment_date=today(),
                    )

        reloaded = frappe.get_doc("Payment Plan", plan.name)
        first = reloaded.installments[0]
        self.assertEqual(
            first.status,
            "Pending",
            "create_payment_entry()'s failure must reach process_payment() (which "
            "then rolls back the Paid mutation), not be swallowed inside it",
        )
