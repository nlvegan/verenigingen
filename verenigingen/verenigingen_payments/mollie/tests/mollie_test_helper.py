"""
Mollie Test Helper

Provides utilities for creating real test payments in Mollie's test API
for integration testing of refund and chargeback functionality.
"""

import time
from typing import Any, Dict, Optional

import frappe

from verenigingen.verenigingen_payments.mollie.utils.amount_helpers import extract_amount_float


class MollieTestHelper:
    """
    Helper class for integration testing with real Mollie test API.

    This class creates real test payments via Mollie's test API,
    allowing us to test refunds and chargebacks with actual webhook
    processing instead of relying on mocks.
    """

    def __init__(self):
        """Initialize with Mollie test API credentials."""
        self.mollie_settings = frappe.get_single("Mollie Settings")

        # Verify we're using test API key
        if not self.is_test_mode():
            raise RuntimeError(
                "MollieTestHelper requires test API key. " "Current key does not start with 'test_'"
            )

        self.client = self.mollie_settings.get_mollie_client()
        self._created_payments = []  # Track for cleanup

    def is_test_mode(self) -> bool:
        """Check if using test API key."""
        api_key = self.mollie_settings.get_api_key()
        return api_key and api_key.startswith("test_")

    def create_test_payment(
        self,
        amount: float,
        description: str = "Test Payment",
        redirect_url: Optional[str] = None,
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a real test payment via Mollie API.

        Args:
            amount: Payment amount in EUR
            description: Payment description
            redirect_url: Optional redirect URL (uses default if not provided)
            webhook_url: Optional webhook URL (uses default if not provided)

        Returns:
            Dict with payment details including payment_id and checkout_url
        """
        try:
            # Use defaults from settings if not provided
            if not redirect_url:
                site_url = frappe.utils.get_url()
                redirect_url = f"{site_url}/mollie-payment-return"

            if not webhook_url:
                site_url = frappe.utils.get_url()
                webhook_url = f"{site_url}/api/method/verenigingen.verenigingen_payments.mollie.api.unified_payment_api.handle_mollie_webhook"

            # Create payment via Mollie API
            payment_data = {
                "amount": {"currency": "EUR", "value": f"{amount:.2f}"},
                "description": description,
                "redirectUrl": redirect_url,
                "webhookUrl": webhook_url,
                "metadata": {"test_payment": True, "created_by": "MollieTestHelper"},
            }

            payment = self.client.payments.create(payment_data)

            # Track for cleanup
            self._created_payments.append(payment.id)

            # Extract checkout URL for simulation
            checkout_url = (
                payment.get_checkout_url()
                if hasattr(payment, "get_checkout_url")
                else payment._links.get("checkout", {}).get("href")
            )

            return {
                "payment_id": payment.id,
                "status": payment.status,
                "amount": amount,
                "checkout_url": checkout_url,
                "payment_object": payment,  # Keep reference for advanced operations
            }

        except Exception as e:
            frappe.log_error(f"Failed to create test payment: {e}", "Mollie Test Helper")
            raise

    def mark_payment_as_paid(self, payment_id: str) -> Dict[str, Any]:
        """
        Mark a test payment as paid using Mollie's test mode features.

        In test mode, you can force a payment to 'paid' status by accessing
        the checkout URL and following test mode instructions.

        Args:
            payment_id: Mollie payment ID

        Returns:
            Updated payment details
        """
        try:
            # Get current payment
            payment = self.client.payments.get(payment_id)

            # In test mode, payment includes a changePaymentState URL
            # We need to check if this payment has been marked as paid
            # by checking its status

            # For automated testing, we'll provide the checkout URL
            # The test needs to manually mark it as paid or use selenium
            checkout_url = (
                payment._links.get("checkout", {}).get("href") if hasattr(payment, "_links") else None
            )

            return {
                "payment_id": payment.id,
                "status": payment.status,
                "checkout_url": checkout_url,
                "message": "Visit checkout_url to mark payment as paid in test mode",
            }

        except Exception as e:
            frappe.log_error(f"Failed to mark payment as paid: {e}", "Mollie Test Helper")
            raise

    def create_refund(
        self, payment_id: str, amount: Optional[float] = None, description: str = "Test Refund"
    ) -> Dict[str, Any]:
        """
        Create a refund for a test payment.

        Args:
            payment_id: Mollie payment ID
            amount: Refund amount (None = full refund)
            description: Refund description

        Returns:
            Refund details
        """
        try:
            # Get payment
            payment = self.client.payments.get(payment_id)

            # Build refund data
            refund_data = {"description": description}

            if amount is not None:
                refund_data["amount"] = {"currency": "EUR", "value": f"{amount:.2f}"}

            # Create refund
            refund = payment.refunds.create(refund_data)

            return {
                "refund_id": refund.id,
                "payment_id": payment_id,
                "amount": extract_amount_float(refund.amount) or amount,
                "status": refund.status,
            }

        except Exception as e:
            frappe.log_error(f"Failed to create refund: {e}", "Mollie Test Helper")
            raise

    def wait_for_webhook(self, payment_id: str, timeout: int = 30, check_interval: int = 2) -> bool:
        """
        Wait for webhook to be processed.

        Args:
            payment_id: Payment ID to check
            timeout: Maximum time to wait in seconds
            check_interval: Time between checks in seconds

        Returns:
            True if webhook processed, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            # Check if Payment Entry exists for this payment
            pe_exists = frappe.db.exists("Payment Entry", {"reference_no": payment_id, "docstatus": 1})

            if pe_exists:
                return True

            time.sleep(check_interval)

        return False

    def cleanup_test_payments(self):
        """
        Clean up test payments created during testing.

        Note: Mollie doesn't allow deleting payments, but we can
        track which ones were created for reporting purposes.
        """
        if self._created_payments:
            frappe.logger().info(
                f"MollieTestHelper created {len(self._created_payments)} test payments: "
                f"{', '.join(self._created_payments)}"
            )

        # Clear tracking list
        self._created_payments = []

    def get_payment_change_state_url(self, payment_id: str) -> Optional[str]:
        """
        Get the changePaymentState URL for a test payment.

        This URL allows simulating refunds and chargebacks in test mode.

        Args:
            payment_id: Mollie payment ID

        Returns:
            URL string or None if not available
        """
        try:
            payment = self.client.payments.get(payment_id)

            # The changePaymentState URL is available for paid test payments
            if hasattr(payment, "_links") and "changePaymentState" in payment._links:
                return payment._links["changePaymentState"]["href"]

            return None

        except Exception as e:
            frappe.log_error(f"Failed to get changePaymentState URL: {e}", "Mollie Test Helper")
            return None


def get_test_helper() -> MollieTestHelper:
    """
    Get MollieTestHelper instance.

    Returns:
        MollieTestHelper instance

    Raises:
        RuntimeError: If not in test mode
    """
    return MollieTestHelper()


def ensure_mollie_test_credentials() -> bool:
    """Populate this site's Mollie Settings from the test credentials in site config,
    so integration tests can hit Mollie's real test API.

    The credentials live in common_site_config.json under ``mollie_test_secret_key``
    and ``mollie_test_profile_id`` (copied from a configured site; never committed).
    When they are absent — e.g. CI without the key — this returns False and callers
    should skip the live integration tests.

    Returns:
        True if a test key is configured and Mollie Settings is ready; False otherwise.
    """
    secret_key = frappe.conf.get("mollie_test_secret_key")
    profile_id = frappe.conf.get("mollie_test_profile_id")
    if not secret_key or not secret_key.startswith("test_"):
        return False

    settings = frappe.get_single("Mollie Settings")
    settings.test_mode = 1
    settings.enable_subscriptions = 1
    if profile_id:
        settings.profile_id = profile_id
    settings.test_secret_key = secret_key
    # Skip the controller validate(): its webhook-URL domain whitelist rejects the
    # test-site hostname, and we only need the API key set for read/cancel/mandate ops.
    settings.flags.ignore_validate = True
    settings.save(ignore_permissions=True)
    frappe.db.commit()

    # Ensure a freshly built MollieClient reads the new key, not a cached single doc.
    frappe.clear_document_cache("Mollie Settings", "Mollie Settings")
    return True


def ensure_mollie_reversal_accounts() -> None:
    """
    Ensure the master data the unified payment-entry creator needs to build refund/
    chargeback Payment Entries exists for the test company.

    In production these are configured by the operator; the test site ships without
    them, so the creator's bank-account fallback chain (mollie_bank_account ->
    Account named "Mollie" -> company default_bank_account) and the "Mollie Refund"
    mode of payment would otherwise be unresolvable.

    Creates (idempotently):
    - a leaf bank Account named "Mollie" under the company's bank-account group
    - the "Mollie Refund" Mode of Payment
    """
    company = frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")
    if not company:
        return

    # Bank account named "Mollie" (matches the creator's named-account fallback)
    mollie_account = frappe.db.get_value("Account", {"company": company, "account_name": "Mollie"}, "name")
    if not mollie_account:
        bank_group = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        )
        if bank_group:
            frappe.get_doc(
                {
                    "doctype": "Account",
                    "account_name": "Mollie",
                    "parent_account": bank_group,
                    "company": company,
                    "account_type": "Bank",
                    "is_group": 0,
                }
            ).insert(ignore_permissions=True)

    # Mode of Payment used for reversal (Pay) entries
    if not frappe.db.exists("Mode of Payment", "Mollie Refund"):
        frappe.get_doc(
            {"doctype": "Mode of Payment", "mode_of_payment": "Mollie Refund", "type": "Bank"}
        ).insert(ignore_permissions=True)

    frappe.db.commit()
