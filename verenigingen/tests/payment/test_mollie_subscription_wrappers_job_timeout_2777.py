"""#2777: a job timeout must leave the Mollie subscription-payment readers and the
recurring-donation sweep unchanged, not as a MolliePaymentError / a swallowed summary error.

Only the SDK boundary (`MollieClient._get_mollie_client`), `time.sleep` and the sweep's
subscription source are stubbed; MollieClient, its retry policy and the sweep are real.
The sweep tests set the DonationProcessor and the webhook-retry-window check by stub (a
probe shortcut): they stand in for the booking call that is running when RQ's timeout fires.

Run:
    PYTHONPATH=<worktree> scripts/testing/run_without_credentials.sh test_site_1 \\
        verenigingen.tests.payment.test_mollie_subscription_wrappers_job_timeout_2777
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from rq.timeouts import JobTimeoutException

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient

_SLEEP = "verenigingen.verenigingen_payments.core.resilience.retry_policy.time.sleep"
_SWEEP_2777 = "verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge_sweep"


class TestClientWrappersKeepJobTimeout2777(EnhancedTestCase):
    def _sdk_timing_out_on_customer_get_2777(self):
        sdk = MagicMock()
        sdk.customers.get.side_effect = JobTimeoutException()
        return sdk

    def _client_over_2777(self, sdk):
        patches = (
            patch.object(MollieClient, "_get_api_key", return_value="test_dummy"),
            patch.object(MollieClient, "_get_mollie_client", return_value=sdk),
            patch(_SLEEP),
        )
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return MollieClient()

    def test_list_subscription_payments_reraises_a_job_timeout(self):
        sdk = self._sdk_timing_out_on_customer_get_2777()
        client = self._client_over_2777(sdk)
        with patch("frappe.log_error") as log_error:
            with self.assertRaises(JobTimeoutException):
                client.list_subscription_payments("cst_x", "sub_x")
        self.assertEqual(sdk.customers.get.call_count, 1, "a timeout is not retried")
        log_error.assert_not_called()

    def test_get_next_payments_page_reraises_a_job_timeout(self):
        page = MagicMock()
        page.get_next.side_effect = JobTimeoutException()
        client = self._client_over_2777(MagicMock())
        with patch("frappe.log_error") as log_error:
            with self.assertRaises(JobTimeoutException):
                client.get_next_payments_page(page)
        self.assertEqual(page.get_next.call_count, 1, "a timeout is not retried")
        log_error.assert_not_called()

    def test_a_non_timeout_failure_is_still_wrapped_as_a_payment_error(self):
        """Control: the wrappers keep converting ordinary exhausted failures."""
        from verenigingen.verenigingen_payments.mollie.exceptions import MolliePaymentError

        sdk = MagicMock()
        sdk.customers.get.side_effect = ValueError("boom")
        client = self._client_over_2777(sdk)
        self.expectErrorLog("Mollie Client")
        with self.assertRaises(MolliePaymentError):
            client.list_subscription_payments("cst_x", "sub_x")


class TestSweepKeepsJobTimeout2777(EnhancedTestCase):
    def _origin_2777(self, tag):
        return SimpleNamespace(
            name=f"DON-{tag}", mollie_customer_id=f"cst_{tag}", mollie_subscription_id=f"sub_{tag}"
        )

    def test_sweep_stops_on_a_timeout_listing_the_first_subscription(self):
        origins = [self._origin_2777("a"), self._origin_2777("b")]
        client = MagicMock()
        client.list_subscription_payments.side_effect = JobTimeoutException()
        with patch(f"{_SWEEP_2777}.MollieClient", return_value=client), patch(
            f"{_SWEEP_2777}._active_donation_subscriptions", return_value=origins
        ), patch(f"{_SWEEP_2777}.DonationProcessor"):
            with self.assertRaises(JobTimeoutException):
                from verenigingen.verenigingen_payments.mollie.services.recurring_donation_charge_sweep import (
                    sweep_recurring_donation_charges,
                )

                sweep_recurring_donation_charges()
        self.assertEqual(client.list_subscription_payments.call_count, 1, "the walk went on past the timeout")

    def test_sweep_stops_on_a_timeout_while_booking_a_charge(self):
        from verenigingen.verenigingen_payments.mollie.services import recurring_donation_charge_sweep as sweep

        payment_id = f"tr_{frappe.generate_hash(length=8)}"
        payment = {"id": payment_id, "status": "paid"}
        processor = MagicMock()
        processor.process_donation_payment.side_effect = JobTimeoutException()
        summary = {"charges_not_paid": 0, "errors": [], "charges_booked": 0}
        with patch(f"{_SWEEP_2777}._is_within_webhook_retry_window", return_value=False):
            with self.assertRaises(JobTimeoutException):
                sweep._sweep_one_payment(payment, processor, summary)
        self.assertEqual(summary["errors"], [])

    def test_sweep_still_records_an_ordinary_booking_failure(self):
        """Control: a non-timeout failure is still swept past and recorded."""
        from verenigingen.verenigingen_payments.mollie.services import recurring_donation_charge_sweep as sweep

        payment_id = f"tr_{frappe.generate_hash(length=8)}"
        processor = MagicMock()
        processor.process_donation_payment.side_effect = ValueError("boom")
        summary = {"charges_not_paid": 0, "errors": [], "charges_booked": 0}
        with patch(f"{_SWEEP_2777}._is_within_webhook_retry_window", return_value=False):
            sweep._sweep_one_payment({"id": payment_id, "status": "paid"}, processor, summary)
        self.assertEqual(len(summary["errors"]), 1)
