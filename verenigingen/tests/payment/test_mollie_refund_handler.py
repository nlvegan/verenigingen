"""
Tests for the Mollie RefundHandler.

Covers ``verenigingen_payments/mollie/services/handlers/refund_handler.py``:
- _fetch_refunds: success, API error (returns None), client wiring
- _process_single_refund: status filter (only 'refunded'), idempotency skip
  when a refund Payment Entry already exists
- process_refunds: full orchestration over a list (none / multiple / error)
- _create_refund_entry: original-donation-not-found error branch (real DB)
- process_payment_refunds module wrapper

The Mollie SDK client is the only external boundary and is supplied as a test
double (constructor injection). All DB lookups (Payment Entry idempotency,
Donation lookup) run for real.

Run with:
    bench --site test_site_3 run-tests --app verenigingen \\
        --module verenigingen.tests.payment.test_mollie_refund_handler
"""

from datetime import datetime
from types import SimpleNamespace

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.handlers.refund_handler import (
    RefundHandler,
    process_payment_refunds,
)


def _refund(refund_id, status="refunded", value="10.00", created_at=None):
    """Build a Mollie-like refund object."""
    return SimpleNamespace(
        id=refund_id,
        status=status,
        amount={"value": value, "currency": "EUR"},
        created_at=created_at,
    )


class _FakeRefundCollection:
    """Mimics mollie.payment_refunds.with_parent_id(pid).list()."""

    def __init__(self, refunds=None, raise_on_list=False):
        self._refunds = refunds or []
        self._raise = raise_on_list
        self.parent_ids = []

    def with_parent_id(self, payment_id):
        self.parent_ids.append(payment_id)
        return self

    def list(self):
        if self._raise:
            raise RuntimeError("Mollie API down")
        return self._refunds


class _FakeSDK:
    def __init__(self, refunds=None, raise_on_list=False):
        self.payment_refunds = _FakeRefundCollection(refunds, raise_on_list)


class TestFetchRefunds(EnhancedTestCase):
    def test_fetch_success_returns_list(self):
        sdk = _FakeSDK(refunds=[_refund("re_1"), _refund("re_2")])
        handler = RefundHandler(mollie_client=sdk)
        refunds = handler._fetch_refunds("tr_abc")
        self.assertEqual(len(refunds), 2)
        self.assertEqual(sdk.payment_refunds.parent_ids, ["tr_abc"])

    def test_fetch_error_returns_none(self):
        sdk = _FakeSDK(raise_on_list=True)
        handler = RefundHandler(mollie_client=sdk)
        self.assertIsNone(handler._fetch_refunds("tr_err"))

    def test_fetch_empty_returns_empty_list(self):
        sdk = _FakeSDK(refunds=[])
        handler = RefundHandler(mollie_client=sdk)
        self.assertEqual(handler._fetch_refunds("tr_none"), [])


class TestProcessSingleRefund(EnhancedTestCase):
    def test_skips_non_refunded_status(self):
        handler = RefundHandler(mollie_client=_FakeSDK())
        result = handler._process_single_refund("tr_x", _refund("re_pending", status="pending"))
        self.assertIsNone(result)

    def test_idempotency_skip_when_pe_exists(self):
        # Create a real submitted refund Payment Entry with the refund id as
        # reference_no and payment_type 'Pay' to trigger the idempotency skip.
        refund_id = f"re_{frappe.generate_hash(length=10)}"
        self._make_refund_pe(refund_id)

        handler = RefundHandler(mollie_client=_FakeSDK())
        result = handler._process_single_refund("tr_x", _refund(refund_id, status="refunded"))
        self.assertIsNone(result, "Existing refund PE should make processing idempotent (skip)")

    def _make_refund_pe(self, refund_id):
        """Persist a minimal submitted 'Pay' Payment Entry as an existing refund."""
        company = frappe.get_single("Verenigingen Settings").company
        receivable = frappe.get_value("Company", company, "default_receivable_account")
        # Need a 'paid_from' bank/cash account for a Pay entry; reuse any bank acct.
        bank = frappe.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
        ) or frappe.get_value(
            "Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
        )
        if not (receivable and bank):
            self.skipTest("No suitable accounts on site to build a refund Payment Entry")

        # Need a party (Customer) for the receivable side.
        customer = frappe.get_value("Customer", {}, "name")
        if not customer:
            cust = frappe.new_doc("Customer")
            cust.customer_name = f"Refund Test Cust {frappe.generate_hash(length=5)}"
            cust.customer_type = "Individual"
            cust.insert(ignore_permissions=True)
            customer = cust.name

        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Pay"
        pe.party_type = "Customer"
        pe.party = customer
        pe.company = company
        pe.paid_from = bank
        pe.paid_to = receivable
        pe.paid_amount = 10.0
        pe.received_amount = 10.0
        pe.reference_no = refund_id
        pe.reference_date = frappe.utils.getdate()
        pe.posting_date = frappe.utils.getdate()
        try:
            pe.insert(ignore_permissions=True)
            pe.submit()
        except Exception as e:
            self.skipTest(f"Could not build refund Payment Entry fixture: {e}")
        return pe.name


class TestProcessRefundsOrchestration(EnhancedTestCase):
    def test_no_refunds(self):
        handler = RefundHandler(mollie_client=_FakeSDK(refunds=[]))
        result = handler.process_refunds("tr_norefund")
        self.assertEqual(result, {"refunds_processed": []})

    def test_fetch_error_returns_empty(self):
        handler = RefundHandler(mollie_client=_FakeSDK(raise_on_list=True))
        # _fetch_refunds returns None on error -> process_refunds returns the
        # short-circuit empty result.
        result = handler.process_refunds("tr_err")
        self.assertEqual(result, {"refunds_processed": []})

    def test_non_refunded_filtered_out(self):
        # A 'pending' refund is filtered by _process_single_refund (returns None)
        # so processed list stays empty while total_refunds reflects the fetch.
        handler = RefundHandler(mollie_client=_FakeSDK(refunds=[_refund("re_p", status="pending")]))
        result = handler.process_refunds("tr_pending")
        self.assertEqual(result["total_refunds"], 1)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(result["refunds_processed"], [])

    def test_refunded_without_donation_reports_failed(self):
        # A 'refunded' refund whose payment has no matching Donation should be
        # reported as failed (not silently dropped).
        refund_id = f"re_{frappe.generate_hash(length=8)}"
        payment_id = f"tr_{frappe.generate_hash(length=8)}"  # no Donation has this
        handler = RefundHandler(
            mollie_client=_FakeSDK(refunds=[_refund(refund_id, status="refunded", created_at=datetime(2025, 5, 1))])
        )
        result = handler.process_refunds(payment_id)
        self.assertEqual(result["total_refunds"], 1)
        self.assertEqual(result["processed_count"], 0)
        self.assertEqual(len(result["refunds_processed"]), 1)
        entry = result["refunds_processed"][0]
        self.assertEqual(entry["refund_id"], refund_id)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("not found", entry["error"])


class TestCreateRefundEntryNoDonation(EnhancedTestCase):
    def test_create_refund_entry_no_donation(self):
        handler = RefundHandler(mollie_client=_FakeSDK())
        payment_id = f"tr_{frappe.generate_hash(length=8)}"
        result = handler._create_refund_entry(
            payment_id, _refund("re_no_donation", status="refunded", created_at=datetime(2025, 1, 2))
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["refund_id"], "re_no_donation")
        self.assertIn(payment_id, result["error"])


class TestRefundLoggingDoesNotPolluteErrorLog(EnhancedTestCase):
    """The happy-path "Refund Debug" breadcrumbs were downgraded from
    frappe.log_error (which writes Error Log rows) to frappe.logger().debug, so
    running this handler in production no longer emits bogus Error Log rows. Only
    genuine failures (the except branches) still write to Error Log."""

    def test_happy_path_writes_no_error_log(self):
        # A successful fetch with a non-'refunded' refund exercises the Start
        # Processing, Fetch Success, and Refund Details breadcrumbs (all former
        # Error Log writers) without hitting any except branch.
        handler = RefundHandler(mollie_client=_FakeSDK(refunds=[_refund("re_p", status="pending")]))
        with self.assertNoErrorLog():
            result = handler.process_refunds(f"tr_{frappe.generate_hash(length=8)}")
        self.assertEqual(result["total_refunds"], 1)

    def test_no_refunds_writes_no_error_log(self):
        handler = RefundHandler(mollie_client=_FakeSDK(refunds=[]))
        with self.assertNoErrorLog():
            handler.process_refunds(f"tr_{frappe.generate_hash(length=8)}")

    def test_fetch_failure_still_logs_error(self):
        # The genuine error sink in the _fetch_refunds except branch must remain:
        # a Mollie API failure should still produce an Error Log row. (frappe.log_error
        # here stores the title in `error` and the message in `method`.)
        self.expectErrorLog("Mollie Refund Fetch Failed")  # intentional sink; tolerate in tearDown
        handler = RefundHandler(mollie_client=_FakeSDK(raise_on_list=True))
        payment_id = f"tr_{frappe.generate_hash(length=8)}"
        marker = frappe.utils.now_datetime()
        self.assertIsNone(handler._fetch_refunds(payment_id))
        rows = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", marker], "error": "Mollie Refund Fetch Failed"},
            fields=["method"],
        )
        self.assertTrue(
            any(payment_id in (r.method or "") for r in rows),
            "Genuine fetch failure should still write a 'Mollie Refund Fetch Failed' Error Log",
        )


class TestModuleWrapper(EnhancedTestCase):
    def test_process_payment_refunds_wrapper_runs(self):
        # The standalone wrapper builds its own RefundHandler (no injected
        # client) -> _get_mollie_client constructs a real MollieClient whose SDK
        # call fails on the test site, so _fetch_refunds returns None and the
        # wrapper returns the empty short-circuit. We assert the contract shape
        # rather than a live result.
        result = process_payment_refunds(f"tr_{frappe.generate_hash(length=8)}")
        self.assertIn("refunds_processed", result)
        self.assertIsInstance(result["refunds_processed"], list)
