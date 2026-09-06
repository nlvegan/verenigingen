"""DonationProcessor — unit tests (#872, part B of #345).

DonationProcessor's own logic is a thin translation layer: delegate a
payment_id to UnifiedWebhookWrapperService.process_payment_webhook (the exact
pipeline the Mollie webhook itself uses) and reshape its result into the
{status, message} shape PaymentTypeRouter expects from every processor
branch. The delegate is the correct boundary to stub here -- the booking
pipeline it wraps is covered end-to-end by test_recurring_donation_charge.py
and test_webhook_wrapper_unified_unit.py; this module only has to prove the
wiring and the reshaping.

Because the stubbed collaborator (UnifiedWebhookWrapperService) is a
module-level class, this file is named ``*_unit.py`` (Tier-1), matching
test_webhook_wrapper_unified_unit.py's own rationale.
"""

from unittest.mock import patch

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.mollie.services.donation_processor import DonationProcessor

_WEBHOOK_SERVICE = (
    "verenigingen.verenigingen_payments.mollie.services.webhook_wrapper_service_unified"
    ".UnifiedWebhookWrapperService.process_payment_webhook"
)


class TestDonationProcessor(EnhancedTestCase):
    def test_delegates_payment_id_to_webhook_pipeline(self):
        with patch(_WEBHOOK_SERVICE, return_value={"status": "success", "message": "booked"}) as mocked:
            result = DonationProcessor().process_donation_payment("tr_delegate_test")

        mocked.assert_called_once_with("tr_delegate_test", {})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["message"], "booked")

    def test_error_status_passes_through(self):
        with patch(
            _WEBHOOK_SERVICE,
            return_value={"status": "error", "message": "No donation found for payment tr_x"},
        ):
            result = DonationProcessor().process_donation_payment("tr_x")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["message"], "No donation found for payment tr_x")

    def test_missing_status_defaults_to_error(self):
        # A result dict with no "status" key must not silently read as success.
        with patch(_WEBHOOK_SERVICE, return_value={}):
            result = DonationProcessor().process_donation_payment("tr_y")

        self.assertEqual(result["status"], "error")

    def test_prefetched_payment_is_accepted_but_not_required_by_the_delegate(self):
        # payment is accepted for interface parity with the other processors,
        # but process_payment_webhook always does its own fetch -- so passing
        # one must not change what gets sent downstream.
        with patch(_WEBHOOK_SERVICE, return_value={"status": "success"}) as mocked:
            DonationProcessor().process_donation_payment("tr_z", payment=object())

        mocked.assert_called_once_with("tr_z", {})
