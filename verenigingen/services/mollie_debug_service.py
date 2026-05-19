"""
Mollie Debug Service
Unified service layer for all Mollie API debugging operations
"""

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.error_handling import sanitize_error_for_audit
from verenigingen.utils.security.api_security_framework import OperationType
from verenigingen.verenigingen_payments.core.compliance.audit_trail import (
    AuditEventType,
    AuditSeverity,
    get_audit_trail,
)
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    create_error_response,
    create_success_response,
    format_mollie_amount,
    format_mollie_response_amount,
    validate_mollie_amount,
)
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


class MollieDebugService(StatelessService):
    """Centralized service for Mollie API debugging operations.

    Inherits from StatelessService for consistent logging, metrics, and error handling.
    """

    def __init__(self):
        super().__init__(service_name="MollieDebugService")
        self.mollie_client = MollieClient()
        self.audit_trail = get_audit_trail()
        self._config = None  # Lazy-loaded configuration service

    @property
    def config(self):
        """Lazy-load configuration service."""
        if self._config is None:
            self._config = get_mollie_config()
        return self._config

    @property
    def test_mode(self):
        """Get test mode from configuration service."""
        return self.config.is_test_mode()

    @staticmethod
    def _sanitize_limit(limit, max_val=250, default=20):
        """Sanitize pagination limit to safe range."""
        try:
            limit = int(limit)
            if limit < 1 or limit > max_val:
                return default
        except (ValueError, TypeError):
            return default
        return limit

    def debug_customer(self, customer_id):
        """Debug a Mollie customer with detailed information"""
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        result = {
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customer_found": False,
            "subscriptions": [],
            "mandates": [],
            "database_records": {"members": [], "donors": []},
            "error": None,
        }

        try:
            # Get customer data using working MollieClient method
            customer = self.mollie_client.get_customer(customer_id)
            result["customer_found"] = True
            result["customer_data"] = {
                "id": customer.id,
                "name": customer.name,
                "email": customer.email,
                "created_at": str(customer.created_at),
                "mode": customer.mode,
            }

            # Get subscriptions using raw mollie client
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            subscriptions = customer_obj.subscriptions.list()

            for sub in subscriptions:
                # Handle amount safely with comprehensive error handling
                amount_str = "Unknown"
                try:
                    if hasattr(sub, "amount") and sub.amount:
                        if isinstance(sub.amount, dict):
                            amount_str = f"{sub.amount.get('value', '0')} {sub.amount.get('currency', 'EUR')}"
                        else:
                            amount_str = str(sub.amount)
                except Exception:
                    amount_str = "Error parsing amount"

                result["subscriptions"].append(
                    {
                        "id": sub.id,
                        "status": sub.status,
                        "amount": amount_str,
                        "interval": sub.interval,
                        "description": sub.description,
                        "created_at": str(sub.created_at),
                        "next_payment_date": (
                            str(getattr(sub, "next_payment_date", None))
                            if getattr(sub, "next_payment_date", None)
                            else None
                        ),
                        "canceled_at": (
                            str(getattr(sub, "canceled_at", None))
                            if getattr(sub, "canceled_at", None)
                            else None
                        ),
                        "mandate_id": getattr(sub, "mandateId", None),
                    }
                )

            # Get mandates
            mandates = customer_obj.mandates.list()
            for mandate in mandates:
                result["mandates"].append(
                    {
                        "id": mandate.id,
                        "status": mandate.status,
                        "method": mandate.method,
                        "created_at": str(mandate.created_at),
                        "mandate_reference": getattr(mandate, "mandate_reference", None),
                        "signature_date": (
                            str(getattr(mandate, "signature_date", None))
                            if getattr(mandate, "signature_date", None)
                            else None
                        ),
                    }
                )

        except Exception as api_error:
            result["error"] = str(api_error)

        # Check database records
        members = frappe.get_all(
            "Member",
            filters={"mollie_customer_id": customer_id},
            fields=["name", "full_name", "mollie_subscription_id", "subscription_status", "payment_method"],
        )
        result["database_records"]["members"] = members

        donors = frappe.get_all(
            "Donor", filters={"mollie_customer_id": customer_id}, fields=["name", "donor_name", "member"]
        )
        result["database_records"]["donors"] = donors

        return result

    def debug_subscription(self, subscription_id, customer_id=None):
        """Debug a specific subscription"""
        if not subscription_id:
            raise ValueError(_("Subscription ID is required"))

        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        result = {
            "subscription_id": subscription_id,
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "subscription_found": False,
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            subscription = customer_obj.subscriptions.get(subscription_id)

            result["subscription_found"] = True

            # Handle amount safely
            amount_str = "Unknown"
            try:
                if hasattr(subscription, "amount") and subscription.amount:
                    if isinstance(subscription.amount, dict):
                        amount_str = f"{subscription.amount.get('value', '0')} {subscription.amount.get('currency', 'EUR')}"
                    else:
                        amount_str = str(subscription.amount)
            except Exception:
                amount_str = "Error parsing amount"

            # Safely extract times - Mollie SDK may throw on None values
            try:
                times_value = getattr(subscription, "times", None)
            except (TypeError, ValueError):
                times_value = None  # Unlimited subscription

            result["subscription_data"] = {
                "id": subscription.id,
                "customer_id": subscription.customer_id,
                "status": subscription.status,
                "amount": amount_str,
                "interval": subscription.interval,
                "times": times_value,  # Number of payments (None = unlimited)
                "description": subscription.description,
                "created_at": str(subscription.created_at),
                "start_date": (
                    str(getattr(subscription, "start_date", None) or getattr(subscription, "startDate", None))
                    if (getattr(subscription, "start_date", None) or getattr(subscription, "startDate", None))
                    else None
                ),
                "next_payment_date": (
                    str(getattr(subscription, "next_payment_date", None))
                    if getattr(subscription, "next_payment_date", None)
                    else None
                ),
                "canceled_at": (
                    str(getattr(subscription, "canceled_at", None))
                    if getattr(subscription, "canceled_at", None)
                    else None
                ),
                # Try both snake_case (SDK) and camelCase (API) attribute names
                "mandate_id": getattr(subscription, "mandate_id", None)
                or getattr(subscription, "mandateId", None),
                "webhook_url": getattr(subscription, "webhook_url", None)
                or getattr(subscription, "webhookUrl", None),
                "metadata": getattr(subscription, "metadata", {}),
            }

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def debug_mandate(self, mandate_id, customer_id=None):
        """Debug a specific mandate"""
        if not mandate_id:
            raise ValueError(_("Mandate ID is required"))

        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        result = {
            "mandate_id": mandate_id,
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "mandate_found": False,
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            mandate = customer_obj.mandates.get(mandate_id)

            result["mandate_found"] = True
            result["mandate_data"] = {
                "id": mandate.id,
                "status": mandate.status,
                "method": mandate.method,
                "created_at": str(mandate.created_at),
                "mandate_reference": getattr(mandate, "mandate_reference", None),
                "signature_date": (
                    str(getattr(mandate, "signature_date", None))
                    if getattr(mandate, "signature_date", None)
                    else None
                ),
                "consumer_name": getattr(mandate, "consumer_name", None),
                "consumer_account": getattr(mandate, "consumer_account", None),
            }

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def admin_cancel_subscription(self, customer_id, subscription_id, reason="Administrative cancellation"):
        """Admin function to cancel any subscription"""
        if not customer_id or not subscription_id:
            raise ValueError(_("Customer ID and Subscription ID are required"))

        if not reason:
            raise ValueError(_("Cancellation reason is required"))

        try:
            # Route through the standardised MollieClient wrapper rather than
            # the raw SDK, so this admin path cannot drift from the contract.
            # cancel_subscription raises MolliePaymentError on failure; the
            # except block below inspects its message for "already cancelled".
            self.mollie_client.cancel_subscription(customer_id, subscription_id)

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.WARNING,
                f"Admin cancelled subscription {subscription_id} for customer {customer_id}",
                details={
                    "action": "subscription_cancellation",
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "reason": reason,
                    "cancelled_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription_id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"ADMIN CANCELLATION: User {frappe.session.user} cancelled subscription {subscription_id} for customer {customer_id}. Reason: {reason}"
            )

            return create_success_response(
                "Subscription cancelled successfully",
                {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "cancelled_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            # Handle various "already cancelled" scenarios
            if any(
                phrase in error_message.lower()
                for phrase in [
                    "not found",
                    "does not exist",
                    "has been cancelled",
                    "already cancelled",
                    "cannot be cancelled",
                ]
            ):
                self.logger.info(
                    f"ADMIN CANCELLATION ATTEMPT: User {frappe.session.user} attempted to cancel already-cancelled subscription {subscription_id} for customer {customer_id}. Reason: {reason}"
                )

                return {
                    "status": "warning",
                    "message": _("Subscription is already cancelled or cannot be cancelled"),
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": error_message,
                }
            else:
                raise api_error

    def update_subscription_webhook(
        self, customer_id, subscription_id, webhook_url, reason="Webhook URL update"
    ):
        """
        Update the webhook URL for a subscription via Mollie PATCH API.

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID
            webhook_url: New webhook URL to set
            reason: Reason for the update (for audit trail)

        Returns:
            Dict with success/error status
        """
        if not customer_id or not subscription_id:
            raise ValueError(_("Customer ID and Subscription ID are required"))

        if not webhook_url:
            raise ValueError(_("Webhook URL is required"))

        # Validate webhook URL format
        if not webhook_url.startswith("https://"):
            raise ValueError(_("Webhook URL must use HTTPS"))

        try:
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)

            # Get current subscription to verify it exists and capture old webhook
            current_subscription = customer_obj.subscriptions.get(subscription_id)
            old_webhook_url = getattr(current_subscription, "webhookUrl", None)

            # Update the subscription with new webhook URL
            updated_subscription = customer_obj.subscriptions.update(
                subscription_id, {"webhookUrl": webhook_url}
            )

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.INFO,
                f"Updated webhook URL for subscription {subscription_id}",
                details={
                    "action": "subscription_webhook_update",
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_webhook_url": old_webhook_url,
                    "new_webhook_url": webhook_url,
                    "reason": reason,
                    "updated_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription_id,
            )

            self.logger.info(
                f"WEBHOOK UPDATE: User {frappe.session.user} updated webhook URL for subscription "
                f"{subscription_id} (customer {customer_id}). Old: {old_webhook_url}, New: {webhook_url}"
            )

            return create_success_response(
                "Webhook URL updated successfully",
                {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_webhook_url": old_webhook_url,
                    "new_webhook_url": webhook_url,
                    "updated_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            self.logger.error(
                f"WEBHOOK UPDATE FAILED: User {frappe.session.user} failed to update webhook URL for "
                f"subscription {subscription_id} (customer {customer_id}): {error_message}"
            )
            raise api_error

    def update_subscription_mandate(
        self, customer_id, subscription_id, new_mandate_id, reason="Bank account update"
    ):
        """
        Update the mandate (bank account) for a subscription via Mollie PATCH API.

        Args:
            customer_id: Mollie customer ID (cst_xxx)
            subscription_id: Mollie subscription ID (sub_xxx)
            new_mandate_id: Mollie mandate ID to switch to (mdt_xxx)
            reason: Reason for the update (for audit trail)

        Returns:
            Dict with success/error status (via create_success_response)
        """
        if not customer_id or not subscription_id:
            raise ValueError(_("Customer ID and Subscription ID are required"))

        if not new_mandate_id:
            raise ValueError(_("New Mandate ID is required"))

        try:
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)

            # Verify subscription exists and capture old mandate ID
            current_subscription = customer_obj.subscriptions.get(subscription_id)
            old_mandate_id = getattr(current_subscription, "mandateId", None)

            # PATCH the subscription with the new mandate
            customer_obj.subscriptions.update(subscription_id, {"mandateId": new_mandate_id})

            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.INFO,
                f"Updated mandate for subscription {subscription_id}",
                details={
                    "action": "subscription_mandate_update",
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_mandate_id": old_mandate_id,
                    "new_mandate_id": new_mandate_id,
                    "reason": reason,
                    "updated_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription_id,
            )

            self.logger.info(
                f"MANDATE UPDATE: User {frappe.session.user} updated mandate for subscription "
                f"{subscription_id} (customer {customer_id}). Old: {old_mandate_id}, New: {new_mandate_id}"
            )

            return create_success_response(
                "Subscription mandate updated successfully",
                {
                    "subscription_id": subscription_id,
                    "customer_id": customer_id,
                    "old_mandate_id": old_mandate_id,
                    "new_mandate_id": new_mandate_id,
                    "updated_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            self.logger.error(
                f"MANDATE UPDATE FAILED: User {frappe.session.user} failed to update mandate for "
                f"subscription {subscription_id} (customer {customer_id}): {error_message}"
            )
            raise api_error

    def admin_revoke_mandate(self, customer_id, mandate_id, reason="Administrative revocation"):
        """
        Admin function to revoke a mandate and cancel all associated subscriptions.

        This function performs a two-step process:
        1. Cancel all active subscriptions for the customer
        2. Revoke the mandate

        This prevents subscriptions from going into 'pending' state waiting for a new mandate.
        """
        if not customer_id or not mandate_id:
            raise ValueError(_("Customer ID and Mandate ID are required"))

        if not reason:
            raise ValueError(_("Revocation reason is required"))

        cancelled_subscriptions = []

        try:
            # Use direct Mollie API call
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)

            # STEP 1: Cancel all active subscriptions first to prevent pending state
            try:
                subscriptions = customer_obj.subscriptions.list()
                for sub in subscriptions:
                    if sub.status in ["active", "pending"]:
                        try:
                            customer_obj.subscriptions.delete(sub.id)
                            cancelled_subscriptions.append(sub.id)
                            self.logger.info(
                                f"ADMIN MANDATE REVOCATION: Cancelled subscription {sub.id} "
                                f"before revoking mandate {mandate_id} for customer {customer_id}"
                            )
                        except Exception as sub_error:
                            # Log but don't fail if subscription is already cancelled
                            self.logger.warning(
                                f"Could not cancel subscription {sub.id} during mandate revocation: {str(sub_error)}"
                            )
            except Exception as list_error:
                self.logger.warning(
                    f"Could not list subscriptions during mandate revocation for customer {customer_id}: {str(list_error)}"
                )

            # STEP 2: Revoke the mandate
            revoked_mandate = customer_obj.mandates.delete(mandate_id)

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.CONFIGURATION_CHANGED,
                AuditSeverity.WARNING,
                f"Admin revoked mandate {mandate_id} for customer {customer_id}",
                details={
                    "action": "mandate_revocation",
                    "mandate_id": mandate_id,
                    "customer_id": customer_id,
                    "cancelled_subscriptions": cancelled_subscriptions,
                    "subscriptions_cancelled_count": len(cancelled_subscriptions),
                    "reason": reason,
                    "revoked_by": frappe.session.user,
                },
                entity_type="Mollie Mandate",
                entity_id=mandate_id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"ADMIN REVOCATION: User {frappe.session.user} revoked mandate {mandate_id} "
                f"for customer {customer_id}. Cancelled {len(cancelled_subscriptions)} subscriptions. "
                f"Reason: {reason}"
            )

            return create_success_response(
                _("Mandate revoked and {0} subscription(s) cancelled successfully").format(
                    len(cancelled_subscriptions)
                ),
                {
                    "mandate_id": mandate_id,
                    "customer_id": customer_id,
                    "cancelled_subscriptions": cancelled_subscriptions,
                    "revoked_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            if "no longer available" in error_message or "Gone" in error_message:
                self.logger.info(
                    f"ADMIN REVOCATION ATTEMPT: User {frappe.session.user} attempted to revoke already-revoked mandate {mandate_id} for customer {customer_id}. Reason: {reason}"
                )

                return {
                    "status": "warning",
                    "message": _("Mandate was already revoked or is no longer available"),
                    "mandate_id": mandate_id,
                    "customer_id": customer_id,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": error_message,
                }
            else:
                raise api_error

    @staticmethod
    def _validate_mandate_params(
        customer_id, consumer_name, consumer_account, consumer_bic, signature_date, mandate_reference
    ):
        """Validate SEPA mandate parameters. Returns normalized signature_date."""
        from verenigingen.utils.validation.iban_validator import validate_iban
        from verenigingen.verenigingen_payments.utils.sepa_input_validation import SEPAInputValidator

        if not customer_id:
            raise ValueError(_("Customer ID is required"))
        if not consumer_name:
            raise ValueError(_("Consumer name is required"))
        if not consumer_account:
            raise ValueError(_("IBAN is required"))
        if len(consumer_name) > 70:
            raise ValueError(_("Consumer name must not exceed 70 characters"))
        if mandate_reference and len(mandate_reference) > 35:
            raise ValueError(_("Mandate reference must not exceed 35 characters"))

        iban_validation = validate_iban(consumer_account)
        if not iban_validation.get("valid"):
            raise ValueError(_("Invalid IBAN: {0}").format(iban_validation.get("message")))

        if consumer_bic:
            bic_validation = SEPAInputValidator.validate_bic(consumer_bic)
            if not bic_validation.get("valid"):
                raise ValueError(_("Invalid BIC: {0}").format(", ".join(bic_validation.get("errors", []))))

        if signature_date:
            try:
                from frappe.utils import getdate

                parsed_date = getdate(signature_date)
                if parsed_date > getdate():
                    raise ValueError(_("Signature date cannot be in the future"))
                return str(parsed_date)
            except ValueError:
                raise
            except Exception:
                raise ValueError(_("Invalid signature date format - use YYYY-MM-DD"))

        return signature_date

    def create_mandate(
        self,
        customer_id,
        consumer_name,
        consumer_account,
        consumer_bic=None,
        signature_date=None,
        mandate_reference=None,
    ):
        """
        Create a new SEPA Direct Debit mandate for a customer.

        Args:
            customer_id: Mollie customer ID (cst_xxx)
            consumer_name: Account holder name (max 70 chars per SEPA specs)
            consumer_account: IBAN number
            consumer_bic: BIC code (optional)
            signature_date: Date mandate was signed in YYYY-MM-DD format (optional)
            mandate_reference: Custom mandate reference (optional, max 35 chars, must be unique)

        Returns:
            dict with created mandate details
        """
        signature_date = self._validate_mandate_params(
            customer_id, consumer_name, consumer_account, consumer_bic, signature_date, mandate_reference
        )

        try:
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)

            # Build mandate data with cleaned values
            cleaned_iban = consumer_account.replace(" ", "").upper()
            mandate_data = {
                "method": "directdebit",
                "consumerName": consumer_name,
                "consumerAccount": cleaned_iban,
            }

            if consumer_bic:
                mandate_data["consumerBic"] = consumer_bic.replace(" ", "").upper()
            if signature_date:
                mandate_data["signatureDate"] = signature_date
            if mandate_reference:
                mandate_data["mandateReference"] = mandate_reference

            # Create the mandate
            mandate = customer_obj.mandates.create(mandate_data)

            # Build response with mandate details
            mandate_response = {
                "id": mandate.id,
                "status": mandate.status,
                "method": mandate.method,
                "signatureDate": str(mandate.signature_date) if mandate.signature_date else None,
                "mandateReference": mandate.mandate_reference
                if hasattr(mandate, "mandate_reference")
                else None,
                "createdAt": str(mandate.created_at),
            }

            # Add consumer details if available
            if hasattr(mandate, "details") and mandate.details:
                mandate_response["details"] = {
                    "consumerName": mandate.details.get("consumerName"),
                    "consumerAccount": mandate.details.get("consumerAccount"),
                    "consumerBic": mandate.details.get("consumerBic"),
                }

            # Structured audit trail logging (mask IBAN for security, preserve country code)
            if len(cleaned_iban) >= 6:
                # Show country code (2 chars) + masked middle + last 4 digits
                masked_iban = f"{cleaned_iban[:2]}{'*' * (len(cleaned_iban) - 6)}{cleaned_iban[-4:]}"
            else:
                masked_iban = "*" * len(cleaned_iban)
            self.audit_trail.log_event(
                AuditEventType.PAYMENT_CREATED,
                AuditSeverity.INFO,
                f"Created SEPA mandate {mandate.id} for customer {customer_id}",
                details={
                    "action": "mandate_creation",
                    "mandate_id": mandate.id,
                    "customer_id": customer_id,
                    "iban_masked": masked_iban,
                    "mandate_status": mandate.status,
                    "created_by": frappe.session.user,
                },
                entity_type="Mollie Mandate",
                entity_id=mandate.id,
            )

            self.logger.info(
                f"MANDATE CREATED: User {frappe.session.user} created mandate {mandate.id} "
                f"for customer {customer_id}. IBAN: {masked_iban}"
            )

            return create_success_response(
                "Mandate created successfully",
                {
                    "customer_id": customer_id,
                    "test_mode": self.test_mode,
                    "mandate": mandate_response,
                    "created_by": frappe.session.user,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            sanitized_error = self._sanitize_error_message(str(api_error))
            self.logger.error(
                f"MANDATE CREATION FAILED: User {frappe.session.user} failed to create mandate "
                f"for customer {customer_id}. Error: {sanitized_error}"
            )

            return create_error_response(
                sanitized_error,
                {
                    "customer_id": customer_id,
                    "test_mode": self.test_mode,
                    "timestamp": frappe.utils.now(),
                },
            )

    def admin_delete_customer(self, customer_id, reason="Administrative deletion", confirmation_text=None):
        """Admin function to delete entire customer (DANGEROUS - cascades to all subscriptions/mandates)"""
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        if not reason:
            raise ValueError(_("Deletion reason is required"))

        # Require explicit confirmation text
        if confirmation_text != "DELETE CUSTOMER":
            raise ValueError(_("Confirmation text must be exactly: DELETE CUSTOMER"))

        try:
            # Get customer details first for logging
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            customer_details = {
                "id": customer_obj.id,
                "name": customer_obj.name,
                "email": customer_obj.email,
                "created_at": str(customer_obj.created_at),
                "mode": customer_obj.mode,
            }

            # Get counts of what will be deleted
            subscriptions = list(customer_obj.subscriptions.list())
            mandates = list(customer_obj.mandates.list())
            subscription_count = len(subscriptions)
            mandate_count = len(mandates)

            # Log the impending deletion with full details
            self.logger.warning(
                f"CUSTOMER DELETION INITIATED: User {frappe.session.user} is deleting customer {customer_id}"
            )
            self.logger.warning(f"Customer details: {customer_details}")
            self.logger.warning(
                f"Will cascade delete {subscription_count} subscriptions and {mandate_count} mandates"
            )
            self.logger.warning(f"Reason: {reason}")

            # Perform the deletion
            deleted_customer = client.customers.delete(customer_id)

            # Structured audit trail logging (CRITICAL severity for customer deletion)
            self.audit_trail.log_event(
                AuditEventType.DATA_DELETION,
                AuditSeverity.CRITICAL,
                f"Admin deleted Mollie customer {customer_id} ({customer_details.get('name', 'N/A')})",
                details={
                    "action": "customer_deletion",
                    "customer_id": customer_id,
                    "customer_name": customer_details.get("name"),
                    "customer_email": customer_details.get("email"),
                    "subscriptions_deleted": subscription_count,
                    "mandates_deleted": mandate_count,
                    "reason": reason,
                    "deleted_by": frappe.session.user,
                },
                entity_type="Mollie Customer",
                entity_id=customer_id,
            )

            # Log successful deletion
            self.logger.warning(
                f"CUSTOMER DELETION COMPLETED: Customer {customer_id} successfully deleted by {frappe.session.user}"
            )

            return create_success_response(
                "Customer deleted successfully (including all subscriptions and mandates)",
                {
                    "customer_id": customer_id,
                    "deleted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "customer_details": customer_details,
                    "cascaded_deletions": {
                        "subscriptions_deleted": subscription_count,
                        "mandates_deleted": mandate_count,
                    },
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            if "not found" in error_message.lower() or "does not exist" in error_message.lower():
                self.logger.info(
                    f"CUSTOMER DELETION ATTEMPT: User {frappe.session.user} attempted to delete non-existent customer {customer_id}. Reason: {reason}"
                )

                return {
                    "status": "warning",
                    "message": _("Customer not found or already deleted"),
                    "customer_id": customer_id,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": error_message,
                }
            else:
                raise api_error

    def list_customers(self, limit=20):
        """List Mollie customers for easy ID lookup"""
        limit = self._sanitize_limit(limit)

        result = {
            "limit": limit,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customers": [],
            "error": None,
        }

        try:
            # Use direct Mollie API call to avoid retry decorators
            client = self.mollie_client.sdk_client
            customers = client.customers.list(limit=limit)

            for customer in customers:
                result["customers"].append(
                    {
                        "id": customer.id,
                        "name": customer.name,
                        "email": customer.email,
                        "created_at": str(customer.created_at),
                        "mode": customer.mode,
                    }
                )

            return result

        except Exception as api_error:
            result["error"] = str(api_error)
            return result

    def debug_payment(self, payment_id):
        """Debug a specific payment with comprehensive details"""
        if not payment_id:
            raise ValueError(_("Payment ID is required"))

        result = {
            "payment_id": payment_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "payment_found": False,
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client
            payment = client.payments.get(payment_id)

            result["payment_found"] = True
            result["payment_data"] = {
                "id": payment.id,
                "status": payment.status,
                "amount": (
                    f"{payment.amount['value']} {payment.amount['currency']}" if payment.amount else "Unknown"
                ),
                "description": payment.description,
                "method": getattr(payment, "method", None),
                "created_at": str(payment.created_at),
                "authorized_at": (
                    str(getattr(payment, "authorized_at", None))
                    if getattr(payment, "authorized_at", None)
                    else None
                ),
                "paid_at": (
                    str(getattr(payment, "paid_at", None)) if getattr(payment, "paid_at", None) else None
                ),
                "canceled_at": (
                    str(getattr(payment, "canceled_at", None))
                    if getattr(payment, "canceled_at", None)
                    else None
                ),
                "expired_at": (
                    str(getattr(payment, "expired_at", None))
                    if getattr(payment, "expired_at", None)
                    else None
                ),
                "failed_at": (
                    str(getattr(payment, "failed_at", None)) if getattr(payment, "failed_at", None) else None
                ),
                "customer_id": getattr(payment, "customer_id", None),
                "subscription_id": getattr(payment, "subscription_id", None),
                "mandate_id": getattr(payment, "mandate_id", None),
                "profile_id": getattr(payment, "profile_id", None),
                "sequence_type": getattr(payment, "sequence_type", None),
                "webhook_url": getattr(payment, "webhook_url", None),
                "redirect_url": getattr(payment, "redirect_url", None),
                "settlement_id": getattr(payment, "settlement_id", None),
                "metadata": getattr(payment, "metadata", {}),
                "details": getattr(payment, "details", {}),
                "failure_reason": getattr(payment, "failure_reason", None),
            }

            # Get refunds if any
            try:
                refunds = payment.refunds.list()
                result["refunds"] = []
                for refund in refunds:
                    result["refunds"].append(
                        {
                            "id": refund.id,
                            "status": refund.status,
                            "amount": (
                                f"{refund.amount['value']} {refund.amount['currency']}"
                                if refund.amount
                                else "Unknown"
                            ),
                            "description": getattr(refund, "description", None),
                            "created_at": str(refund.created_at),
                            "settled_at": (
                                str(getattr(refund, "settled_at", None))
                                if getattr(refund, "settled_at", None)
                                else None
                            ),
                        }
                    )
            except Exception:
                result["refunds"] = []

            # Get chargebacks if any
            try:
                chargebacks = payment.chargebacks.list()
                result["chargebacks"] = []
                for chargeback in chargebacks:
                    result["chargebacks"].append(
                        {
                            "id": chargeback.id,
                            "amount": (
                                f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                                if chargeback.amount
                                else "Unknown"
                            ),
                            "created_at": str(chargeback.created_at),
                            "reason": getattr(chargeback, "reason", None),
                            "reversed_at": (
                                str(getattr(chargeback, "reversed_at", None))
                                if getattr(chargeback, "reversed_at", None)
                                else None
                            ),
                        }
                    )
            except Exception:
                result["chargebacks"] = []

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def list_payments(self, customer_id=None, limit=20, status_filter=None):
        """List payments with optional filtering"""
        limit = self._sanitize_limit(limit)

        result = {
            "limit": limit,
            "customer_id": customer_id,
            "status_filter": status_filter,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "payments": [],
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client

            if customer_id:
                # Get payments via customer (Mollie API doesn't support customerId filter on payments.list)
                customer_obj = client.customers.get(customer_id)
                payments = customer_obj.payments.list(limit=limit)

                # Apply status filter after getting payments
                if status_filter:
                    payments = [p for p in payments if p.status == status_filter]
            else:
                # List all payments with status filter
                params = {"limit": limit}
                if status_filter:
                    params["status"] = status_filter
                payments = client.payments.list(**params)

            for payment in payments:
                result["payments"].append(
                    {
                        "id": payment.id,
                        "status": payment.status,
                        "amount": (
                            f"{payment.amount['value']} {payment.amount['currency']}"
                            if payment.amount
                            else "Unknown"
                        ),
                        "description": payment.description,
                        "method": getattr(payment, "method", None),
                        "created_at": str(payment.created_at),
                        "customer_id": getattr(payment, "customer_id", None),
                        "subscription_id": getattr(payment, "subscription_id", None),
                        "sequence_type": getattr(payment, "sequence_type", None),
                    }
                )

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def debug_refund(self, refund_id, payment_id=None):
        """Debug a specific refund"""
        if not refund_id:
            raise ValueError(_("Refund ID is required"))

        result = {
            "refund_id": refund_id,
            "payment_id": payment_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "refund_found": False,
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client

            if payment_id:
                # Get refund via payment
                payment = client.payments.get(payment_id)
                refund = payment.refunds.get(refund_id)
            else:
                # Direct refund lookup (if supported)
                refund = client.refunds.get(refund_id)

            result["refund_found"] = True
            result["refund_data"] = {
                "id": refund.id,
                "payment_id": refund.payment_id,
                "status": refund.status,
                "amount": (
                    f"{refund.amount['value']} {refund.amount['currency']}" if refund.amount else "Unknown"
                ),
                "description": getattr(refund, "description", None),
                "created_at": str(refund.created_at),
                "settled_at": (
                    str(getattr(refund, "settled_at", None)) if getattr(refund, "settled_at", None) else None
                ),
                "metadata": getattr(refund, "metadata", {}),
                "settlement_id": getattr(refund, "settlement_id", None),
            }

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def list_chargebacks(self, customer_id=None, limit=20):
        """List chargebacks for debugging disputed transactions"""
        limit = self._sanitize_limit(limit)

        result = {
            "limit": limit,
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "chargebacks": [],
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client

            # Get chargebacks - Note: Mollie API may require getting via payments
            if customer_id:
                # Get customer payments first, then their chargebacks
                payments = client.payments.list(customerId=customer_id, limit=100)
                for payment in payments:
                    try:
                        chargebacks = payment.chargebacks.list()
                        for chargeback in chargebacks:
                            result["chargebacks"].append(
                                {
                                    "id": chargeback.id,
                                    "payment_id": payment.id,
                                    "amount": (
                                        f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                                        if chargeback.amount
                                        else "Unknown"
                                    ),
                                    "created_at": str(chargeback.created_at),
                                    "reason": getattr(chargeback, "reason", None),
                                    "reversed_at": (
                                        str(getattr(chargeback, "reversed_at", None))
                                        if getattr(chargeback, "reversed_at", None)
                                        else None
                                    ),
                                    "settlement_id": getattr(chargeback, "settlement_id", None),
                                }
                            )
                    except Exception:
                        continue
            else:
                # Try direct chargeback listing (if available)
                try:
                    chargebacks = client.chargebacks.list(limit=limit)
                    for chargeback in chargebacks:
                        result["chargebacks"].append(
                            {
                                "id": chargeback.id,
                                "payment_id": getattr(chargeback, "payment_id", None),
                                "amount": (
                                    f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                                    if chargeback.amount
                                    else "Unknown"
                                ),
                                "created_at": str(chargeback.created_at),
                                "reason": getattr(chargeback, "reason", None),
                                "reversed_at": (
                                    str(getattr(chargeback, "reversed_at", None))
                                    if getattr(chargeback, "reversed_at", None)
                                    else None
                                ),
                                "settlement_id": getattr(chargeback, "settlement_id", None),
                            }
                        )
                except Exception:
                    result["error"] = "Direct chargeback listing not available - try specifying a customer_id"

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def debug_webhook_delivery(self, payment_id):
        """Debug webhook delivery status for a payment"""
        if not payment_id:
            raise ValueError(_("Payment ID is required"))

        result = {
            "payment_id": payment_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "webhook_info": {},
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client
            payment = client.payments.get(payment_id)

            result["webhook_info"] = {
                "payment_id": payment.id,
                "webhook_url": getattr(payment, "webhook_url", None),
                "status": payment.status,
                "created_at": str(payment.created_at),
                "status_changes": [],
            }

            # Add status change timeline based on available timestamps
            status_changes = []
            if getattr(payment, "created_at", None):
                status_changes.append({"status": "created", "timestamp": str(payment.created_at)})
            if getattr(payment, "authorized_at", None):
                status_changes.append({"status": "authorized", "timestamp": str(payment.authorized_at)})
            if getattr(payment, "paid_at", None):
                status_changes.append({"status": "paid", "timestamp": str(payment.paid_at)})
            if getattr(payment, "canceled_at", None):
                status_changes.append({"status": "canceled", "timestamp": str(payment.canceled_at)})
            if getattr(payment, "expired_at", None):
                status_changes.append({"status": "expired", "timestamp": str(payment.expired_at)})
            if getattr(payment, "failed_at", None):
                status_changes.append({"status": "failed", "timestamp": str(payment.failed_at)})

            result["webhook_info"]["status_changes"] = status_changes

            # Note: Webhook delivery details are not directly available via Mollie API
            # This would typically require checking your own webhook logs
            result["webhook_info"][
                "note"
            ] = "Webhook delivery logs should be checked in your application's webhook endpoint logs"

        except Exception as api_error:
            result["error"] = str(api_error)

        return result

    def admin_cancel_payment(self, payment_id, reason="Administrative cancellation"):
        """Admin function to cancel any payment (if cancellable)"""
        if not payment_id:
            raise ValueError(_("Payment ID is required"))

        if not reason:
            raise ValueError(_("Cancellation reason is required"))

        result = {
            "payment_id": payment_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "error": None,
        }

        try:
            # Use direct Mollie API call to avoid retry/circuit breaker issues
            client = self.mollie_client.sdk_client

            # First check if payment exists and is cancellable
            payment = client.payments.get(payment_id)

            # Check if payment can be cancelled (only pending payments can typically be cancelled)
            if payment.status not in ["open", "pending", "authorized"]:
                return {
                    "status": "warning",
                    "message": _("Payment cannot be cancelled - status is '{0}'").format(payment.status),
                    "payment_id": payment_id,
                    "current_status": payment.status,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": f"Payment status '{payment.status}' does not allow cancellation",
                }

            # Check isCancelable first
            if not getattr(payment, "isCancelable", False):
                return {
                    "status": "warning",
                    "message": _("Payment is not cancelable according to Mollie API"),
                    "payment_id": payment_id,
                    "current_status": payment.status,
                    "is_cancelable": False,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                }

            # Use direct HTTP DELETE since Python SDK doesn't support cancellation
            import requests

            api_key = client.api_key
            url = f"https://api.mollie.com/v2/payments/{payment_id}"
            headers = {"Authorization": f"Bearer {api_key}"}

            response = requests.delete(url, headers=headers, timeout=30)

            if response.status_code == 204:
                # Success - payment cancelled
                pass
            elif response.status_code == 422:
                error_data = response.json()
                return {
                    "status": "warning",
                    "message": _("Payment cannot be cancelled: {0}").format(
                        error_data.get("detail", "Unknown reason")
                    ),
                    "payment_id": payment_id,
                    "current_status": payment.status,
                    "mollie_error": error_data,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                }
            else:
                response.raise_for_status()

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.PAYMENT_UPDATED,
                AuditSeverity.WARNING,
                f"Admin cancelled payment {payment_id}",
                details={
                    "action": "payment_cancellation",
                    "payment_id": payment_id,
                    "previous_status": payment.status,
                    "reason": reason,
                    "cancelled_by": frappe.session.user,
                },
                entity_type="Mollie Payment",
                entity_id=payment_id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"ADMIN PAYMENT CANCELLATION: User {frappe.session.user} cancelled payment {payment_id}. Reason: {reason}"
            )

            return create_success_response(
                "Payment cancelled successfully",
                {
                    "payment_id": payment_id,
                    "previous_status": payment.status,
                    "cancelled_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as api_error:
            error_message = str(api_error)
            # Handle various "cannot cancel" scenarios
            if any(
                phrase in error_message.lower()
                for phrase in [
                    "not found",
                    "does not exist",
                    "cannot be cancelled",
                    "already cancelled",
                    "already paid",
                    "already failed",
                ]
            ):
                self.logger.info(
                    f"ADMIN PAYMENT CANCELLATION ATTEMPT: User {frappe.session.user} attempted to cancel uncancellable payment {payment_id}. Reason: {reason}"
                )

                return {
                    "status": "warning",
                    "message": _("Payment cannot be cancelled or does not exist"),
                    "payment_id": payment_id,
                    "attempted_by": frappe.session.user,
                    "reason": reason,
                    "timestamp": frappe.utils.now(),
                    "error_detail": error_message,
                }
            else:
                raise api_error

    def search_customers_by_name(self, search_term, limit=20):
        """Search Mollie customers by name/email"""
        limit = self._sanitize_limit(limit, max_val=100)

        result = {
            "search_term": search_term,
            "limit": limit,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customers": [],
            "total_found": 0,
            "error": None,
        }

        if not search_term or len(search_term.strip()) < 2:
            result["error"] = "Search term must be at least 2 characters"
            return result

        try:
            client = self.mollie_client.sdk_client

            # Get more customers to search through (Mollie API doesn't support server-side search)
            all_customers = client.customers.list(limit=250)
            search_lower = search_term.lower().strip()

            matching_customers = []
            for customer in all_customers:
                # Search in name and email
                name_match = customer.name and search_lower in customer.name.lower()
                email_match = customer.email and search_lower in customer.email.lower()

                if name_match or email_match:
                    matching_customers.append(
                        {
                            "id": customer.id,
                            "name": customer.name or "N/A",
                            "email": customer.email or "N/A",
                            "created_at": str(customer.created_at),
                            "locale": getattr(customer, "locale", "N/A"),
                            "mode": getattr(customer, "mode", "N/A"),
                        }
                    )

                    if len(matching_customers) >= limit:
                        break

            result["customers"] = matching_customers
            result["total_found"] = len(matching_customers)

        except Exception as e:
            result["error"] = str(e)
            self.logger.error(f"Mollie search customers error: {str(e)}")

        return result

    def test_webhook_processing(self, payment_id):
        """
        Test webhook processing for a specific payment ID.

        Calls the unified webhook handler directly to simulate webhook delivery.
        Now supports both donation and membership dues payments.
        """
        if not payment_id:
            raise ValueError(_("Payment ID is required"))

        from verenigingen.verenigingen_payments.mollie.api.unified_payment_api import handle_payment_webhook

        result = {
            "payment_id": payment_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "webhook_called": False,
            "webhook_result": None,
            "error": None,
            "status": "pending",
        }

        try:
            # First, classify the payment to show what type it is
            from verenigingen.verenigingen_payments.mollie.services.payment_type_router import (
                get_payment_router,
            )

            router = get_payment_router()
            payment = router.fetch_payment(payment_id)
            classification = router.classify_payment(payment)

            result["payment_type"] = classification["payment_type"]
            result["classification_confidence"] = classification["confidence"]
            result["classification_method"] = classification["matched_by"]

            # Call the unified webhook handler
            webhook_result = handle_payment_webhook(payment_id=payment_id)

            result["webhook_called"] = True
            result["webhook_result"] = webhook_result
            result["status"] = "success"
            result["message"] = (
                f"Webhook processed successfully for payment {payment_id} "
                f"(type: {classification['payment_type']})"
            )

            # Extract useful info from result if available
            if isinstance(webhook_result, dict):
                result["http_status"] = frappe.local.response.get("http_status_code", 200)
                result["webhook_status"] = webhook_result.get("status", "unknown")

        except Exception as e:
            result["error"] = str(e)
            result["status"] = "error"
            result["message"] = f"Webhook processing failed: {str(e)}"
            result["http_status"] = frappe.local.response.get("http_status_code", 500)
            self.logger.error(f"Webhook test processing error: {str(e)}")

        return result

    def _sanitize_error_message(self, error_msg: str) -> str:
        """
        Sanitize error messages to prevent information disclosure.

        Uses centralized sanitize_error_for_audit utility with keyword filtering
        enabled to catch API keys, internal system info, and database details.

        Args:
            error_msg: Raw error message

        Returns:
            str: Sanitized error message safe for client display
        """
        return (
            sanitize_error_for_audit(
                error_msg,
                max_length=500,
                remove_stack_trace=True,
                redact_pii=True,
                filter_sensitive_keywords=True,
                fallback_message="Internal error - contact administrator",
            )
            or error_msg
        )

    def create_subscription(
        self,
        customer_id: str,
        amount: float,
        interval: str,
        description: str,
        mandate_id: str = None,
        start_date: str = None,
        times: int = None,
    ):
        """
        Create a new Mollie subscription for testing purposes.

        Args:
            customer_id: Mollie customer ID (e.g., "cst_xxxxxxxxxx")
            amount: Subscription amount in EUR
            interval: Payment interval (e.g., "1 month", "3 months")
            description: Human-readable subscription description
            mandate_id: Optional specific mandate ID to use
            start_date: Optional start date (YYYY-MM-DD format)
            times: Optional number of payments (1 = single payment, None = unlimited)

        Returns:
            Dict containing subscription details including:
                - status: "success" or "error"
                - subscription_id: Created subscription ID (if successful)
                - error: Error message (if failed)

        Raises:
            ValueError: If validation fails for any input parameter

        Note:
            This operation is restricted to Verenigingen Administrator role
            and creates comprehensive audit trail entries.
        """
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        # Validate amount using centralized helper
        amount_float = validate_mollie_amount(amount, min_amount=0.01)

        # Add reasonable maximum for test subscriptions (€1,000)
        if amount_float > 1000.00:
            raise ValueError(_("Test subscription amount cannot exceed €1,000"))

        # Validate interval format
        valid_intervals = ["1 month", "2 months", "3 months", "6 months", "12 months"]
        if interval not in valid_intervals:
            raise ValueError(_("Invalid interval - must be one of: {0}").format(", ".join(valid_intervals)))

        try:
            # Build subscription data
            # Note: webhookUrl intentionally omitted to use Mollie dashboard webhook settings
            # This ensures webhooks go to the correct environment (production/test)
            subscription_data = {
                "amount": format_mollie_amount(amount_float),
                "interval": interval,
                "description": description,
                "metadata": {
                    "created_via": "debug_page",
                    "created_by": frappe.session.user,
                    "created_at": frappe.utils.now(),
                },
            }

            # Add optional parameters
            if mandate_id:
                subscription_data["mandateId"] = mandate_id

            # Add times parameter for limited-payment subscriptions (e.g., times=1 for single payment)
            if times is not None and times > 0:
                subscription_data["times"] = times

            # Handle start date - use configured scheduled months if not explicitly provided
            if start_date:
                subscription_data["startDate"] = start_date
            else:
                # For quarterly/yearly subscriptions, calculate optimal start date
                if interval in ["3 months", "6 months", "12 months"]:
                    mollie_settings = frappe.get_single("Mollie Settings")
                    calculated_start = mollie_settings.get_next_payment_date_for_scheduled_months(
                        min_months_ahead=2
                    )
                    if calculated_start:
                        subscription_data["startDate"] = calculated_start
                        self.logger.info(
                            f"Auto-calculated subscription start date: {calculated_start} "
                            f"(interval: {interval}, configured months: {mollie_settings.quarterly_yearly_payment_months})"
                        )

            # Create the subscription through the standardised MollieClient
            # wrapper rather than reaching the raw SDK directly.
            subscription = self.mollie_client.create_subscription(customer_id, subscription_data)

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.PAYMENT_CREATED,
                AuditSeverity.INFO,
                f"Created subscription {subscription.id} for customer {customer_id}",
                details={
                    "action": "subscription_creation",
                    "subscription_id": subscription.id,
                    "customer_id": customer_id,
                    "amount": amount_float,
                    "interval": interval,
                    "description": description,
                    "mandate_id": mandate_id,
                    "start_date": start_date or subscription_data.get("startDate"),
                    "times": times,
                    "created_by": frappe.session.user,
                },
                entity_type="Mollie Subscription",
                entity_id=subscription.id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"DEBUG SUBSCRIPTION CREATION: User {frappe.session.user} "
                f"created subscription {subscription.id} for customer {customer_id} "
                f"(amount: €{amount_float:.2f}, interval: {interval}, description: {description}, "
                f"mandate: {mandate_id or 'auto'}, start: {start_date or 'immediate'}, "
                f"times: {times or 'unlimited'})"
            )

            return create_success_response(
                "Subscription created successfully",
                {
                    "customer_id": customer_id,
                    "test_mode": self.test_mode,
                    "subscription_id": subscription.id,
                    "subscription_status": subscription.status,
                    "amount": format_mollie_response_amount(subscription.amount),
                    "interval": subscription.interval,
                    "description": subscription.description,
                    "webhook_url": getattr(subscription, "webhook_url", None)
                    or getattr(subscription, "webhookUrl", None),
                    "start_date": str(subscription.start_date)
                    if hasattr(subscription, "start_date") and subscription.start_date
                    else None,
                    "next_payment_date": str(subscription.next_payment_date)
                    if hasattr(subscription, "next_payment_date") and subscription.next_payment_date
                    else None,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as e:
            # Sanitize error message before returning to client
            sanitized_error = self._sanitize_error_message(str(e))

            # Log full error internally with user context
            self.logger.error(
                f"Mollie subscription creation error for user {frappe.session.user}, "
                f"customer {customer_id}: {str(e)}"
            )

            return create_error_response(
                sanitized_error,
                {
                    "customer_id": customer_id,
                    "test_mode": self.test_mode,
                    "timestamp": frappe.utils.now(),
                },
            )

    @staticmethod
    def _validate_subscription_params(customer_id, amount, interval_count, interval_unit, times):
        """Validate and normalize subscription creation parameters.

        Returns:
            Tuple of (amount_float, interval_count_int, mollie_interval).

        Raises:
            ValueError: If any parameter is invalid.
        """
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        try:
            amount_float = float(amount)
        except (ValueError, TypeError):
            raise ValueError(_("Invalid amount format - must be a number"))
        if amount_float <= 0:
            raise ValueError(_("Amount must be positive"))
        if amount_float > 1000.00:
            raise ValueError(_("Test subscription amount cannot exceed €1,000"))

        try:
            interval_count_int = int(interval_count)
        except (ValueError, TypeError):
            raise ValueError(_("Invalid interval count - must be a number"))
        if interval_unit not in ["weeks", "months"]:
            raise ValueError(_("Interval unit must be 'weeks' or 'months'"))
        if interval_unit == "months" and not (1 <= interval_count_int <= 12):
            raise ValueError(_("For months, interval count must be between 1 and 12"))
        if interval_unit == "weeks" and not (1 <= interval_count_int <= 52):
            raise ValueError(_("For weeks, interval count must be between 1 and 52"))

        mollie_interval = (
            f"{interval_count_int} {interval_unit[:-1] if interval_count_int == 1 else interval_unit}"
        )

        if times is not None:
            try:
                times_int = int(times)
                if times_int < 1:
                    raise ValueError(_("Times must be at least 1"))
                if times_int > 999:
                    raise ValueError(_("Times cannot exceed 999 payments"))
            except (ValueError, TypeError):
                raise ValueError(_("Invalid times format - must be a number"))

        return amount_float, interval_count_int, mollie_interval

    def _resolve_subscription_start_date(self, start_date, mollie_interval):
        """Resolve start date: use explicit value, or auto-calculate for quarterly/yearly."""
        if start_date:
            return start_date

        if mollie_interval in ["3 months", "6 months", "12 months"]:
            mollie_settings = frappe.get_single("Mollie Settings")
            calculated_start = mollie_settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
            if calculated_start:
                self.logger.info(
                    f"Auto-calculated subscription start date: {calculated_start} "
                    f"(interval: {mollie_interval}, configured months: "
                    f"{mollie_settings.quarterly_yearly_payment_months})"
                )
                return calculated_start

        return None

    def create_scheduled_subscription(
        self,
        customer_id: str,
        amount: float,
        interval_count: int,
        interval_unit: str,
        description: str,
        times: int = None,
        start_date: str = None,
        mandate_id: str = None,
    ):
        """
        Create a new Mollie subscription with flexible scheduling options.

        Args:
            customer_id: Mollie customer ID (e.g., "cst_xxxxxxxxxx")
            amount: Subscription amount in EUR
            interval_count: Number of weeks/months between payments (1-12 for months, 1-52 for weeks)
            interval_unit: "weeks" or "months"
            description: Human-readable subscription description
            times: Optional number of payments before subscription ends (None = indefinite)
            start_date: Optional start date (YYYY-MM-DD format). If None and interval is quarterly/yearly,
                       will use configured scheduled months
            mandate_id: Optional specific mandate ID to use

        Returns:
            Dict containing subscription details including:
                - status: "success" or "error"
                - subscription_id: Created subscription ID (if successful)
                - error: Error message (if failed)

        Raises:
            ValueError: If validation fails for any input parameter
        """
        amount_float, interval_count_int, mollie_interval = self._validate_subscription_params(
            customer_id, amount, interval_count, interval_unit, times
        )

        result = {
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "status": "pending",
            "error": None,
        }

        try:
            subscription_data = {
                "amount": format_mollie_amount(amount_float),
                "interval": mollie_interval,
                "description": description,
                "metadata": {
                    "created_via": "debug_page_scheduled",
                    "created_by": frappe.session.user,
                    "created_at": frappe.utils.now(),
                    "interval_count": interval_count_int,
                    "interval_unit": interval_unit,
                },
            }

            if mandate_id:
                subscription_data["mandateId"] = mandate_id
            if times is not None:
                subscription_data["times"] = int(times)

            resolved_start = self._resolve_subscription_start_date(start_date, mollie_interval)
            if resolved_start:
                subscription_data["startDate"] = resolved_start

            # Create the subscription through the standardised MollieClient
            # wrapper rather than reaching the raw SDK directly.
            subscription = self.mollie_client.create_subscription(customer_id, subscription_data)

            result["status"] = "success"
            result["subscription_id"] = subscription.id
            result["subscription_status"] = subscription.status
            result["amount"] = format_mollie_response_amount(subscription.amount)
            result["interval"] = subscription.interval
            result["description"] = subscription.description
            result["webhook_url"] = getattr(subscription, "webhook_url", None) or getattr(
                subscription, "webhookUrl", None
            )

            if hasattr(subscription, "start_date") and subscription.start_date:
                result["start_date"] = str(subscription.start_date)
            if hasattr(subscription, "next_payment_date") and subscription.next_payment_date:
                result["next_payment_date"] = str(subscription.next_payment_date)
            if hasattr(subscription, "times") and subscription.times:
                result["times"] = subscription.times

            self.logger.info(
                f"DEBUG SUBSCRIPTION CREATION: User {frappe.session.user} "
                f"created subscription {subscription.id} for customer {customer_id} "
                f"(amount: €{amount_float:.2f}, interval: {mollie_interval}, "
                f"times: {times or 'indefinite'}, start: {start_date or 'auto-calculated'})"
            )

        except Exception as e:
            sanitized_error = self._sanitize_error_message(str(e))
            result["error"] = sanitized_error
            result["status"] = "error"
            self.logger.error(
                f"Mollie scheduled subscription creation error for user {frappe.session.user}, "
                f"customer {customer_id}: {str(e)}"
            )

        return result

    def list_subscriptions(self, customer_id: str, limit: int = 50, active_only: bool = True):
        """
        List subscriptions for a specific customer with optional status filtering.

        Args:
            customer_id: Mollie customer ID (required)
            limit: Maximum number of subscriptions to return (1-250, default 50)
            active_only: If True, only return active subscriptions (default True)

        Returns:
            Dict containing:
                - subscriptions: List of subscription details
                - total_found: Number of subscriptions returned
                - customer_id: Customer ID queried
                - error: Error message if failed

        Raises:
            ValueError: If customer_id is empty or limit is out of range

        Note:
            Filtering by active_only happens client-side after fetching from Mollie API,
            as the Mollie subscriptions.list() endpoint doesn't support status filtering.
        """
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        # Validate and sanitize limit
        try:
            limit = int(limit)
            if not 1 <= limit <= 250:
                limit = 50
        except (ValueError, TypeError):
            limit = 50

        result = {
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customer_id": customer_id,
            "active_only": active_only,
            "limit": limit,
            "subscriptions": [],
            "total_found": 0,
            "error": None,
        }

        try:
            client = self.mollie_client.sdk_client

            # List subscriptions for specific customer
            customer = client.customers.get(customer_id)
            subscriptions = customer.subscriptions.list(limit=limit)

            # Process and filter subscriptions
            for sub in subscriptions:
                # Filter by status if active_only
                if active_only and sub.status != "active":
                    continue

                # Use helper method for consistent amount formatting
                amount_str = format_mollie_response_amount(sub.amount)

                result["subscriptions"].append(
                    {
                        "id": sub.id,
                        "customer_id": (
                            getattr(sub, "_links", {}).get("customer", {}).get("href", "").split("/")[-1]
                            if hasattr(sub, "_links")
                            else customer_id
                        ),
                        "status": sub.status,
                        "amount": amount_str,
                        "interval": sub.interval,
                        "description": sub.description,
                        "created_at": str(sub.created_at),
                        "next_payment_date": (
                            str(getattr(sub, "next_payment_date", None))
                            if getattr(sub, "next_payment_date", None)
                            else None
                        ),
                        "canceled_at": (
                            str(getattr(sub, "canceled_at", None))
                            if getattr(sub, "canceled_at", None)
                            else None
                        ),
                    }
                )

                # Respect limit
                if len(result["subscriptions"]) >= limit:
                    break

            result["total_found"] = len(result["subscriptions"])

        except Exception as e:
            error_msg = str(e)

            # Provide helpful context for "customer not found" errors
            if "No customer exists" in error_msg:
                current_mode = "test" if self.mollie_client.is_test_mode() else "live"
                sanitized_error = (
                    f"Customer {customer_id} not found in {current_mode} mode. "
                    f"This may indicate: 1) Customer ID from different Mollie account, "
                    f"2) Customer deleted in Mollie dashboard, or 3) Wrong API credentials configured."
                )
            else:
                sanitized_error = self._sanitize_error_message(error_msg)

            result["error"] = sanitized_error
            self.logger.error(
                f"Mollie list subscriptions error for customer {customer_id}: {error_msg}. "
                f"Mode: {self.mollie_client.is_test_mode()}"
                "Mollie Customer Error",
            )

        return result

    def retrieve_customer_payments_for_processing(self, customer_id: str, limit: int = 250):
        """
        Retrieve all payment transactions for a customer with processing status.

        This method fetches all payments and checks which ones have already been
        processed (have Payment Entry records) to support two-stage processing.

        Args:
            customer_id: Mollie customer ID
            limit: Maximum number of payments to retrieve (1-250)

        Returns:
            Dict containing:
                - customer_id: Customer ID queried
                - payments: List of payment details with processing status
                - total_found: Total payments retrieved
                - unprocessed_count: Number of payments not yet processed
                - processed_count: Number already processed
        """
        if not customer_id:
            raise ValueError(_("Customer ID is required"))

        # Validate limit
        try:
            limit = int(limit)
            if not 1 <= limit <= 250:
                limit = 250
        except (ValueError, TypeError):
            limit = 250

        result = {
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "customer_id": customer_id,
            "limit": limit,
            "payments": [],
            "total_found": 0,
            "unprocessed_count": 0,
            "processed_count": 0,
            "error": None,
        }

        try:
            # Import dues processor
            from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
                DuesPaymentProcessor,
            )

            dues_processor = DuesPaymentProcessor()

            # Get all payments for customer
            client = self.mollie_client.sdk_client

            # First verify customer exists and log mode info
            try:
                customer_obj = client.customers.get(customer_id)
                result["customer_name"] = getattr(customer_obj, "name", None)
                result["customer_email"] = getattr(customer_obj, "email", None)
                self.logger.info(
                    f"Retrieved customer {customer_id} in {'test' if result['test_mode'] else 'live'} mode"
                )
            except Exception as customer_error:
                error_msg = str(customer_error)
                if "No customer exists" in error_msg or "404" in error_msg:
                    mode = "test" if self.mollie_client.is_test_mode() else "live"
                    result["error"] = (
                        f"Customer {customer_id} not found in {mode} mode. "
                        f"Check if customer exists in the correct Mollie environment."
                    )
                else:
                    result["error"] = self._sanitize_error_message(error_msg)
                self.logger.error(f"Customer lookup failed for {customer_id}: {error_msg}")
                return result

            payments_iter = customer_obj.payments.list(limit=limit)

            # Convert to list to avoid iterator issues with len() and multiple iterations
            payments = list(payments_iter)
            result["total_found"] = len(payments)

            self.logger.info(f"Found {len(payments)} payments for customer {customer_id}")

            # Get bank transaction creator for idempotency checks
            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            bank_tx_creator = get_bank_transaction_creator()

            for payment in payments:
                # Check if already processed using centralized service
                idempotency_check = bank_tx_creator.check_already_processed(
                    payment.id, check_payment_entry=True  # Check both Payment Entry and Bank Transaction
                )

                # Identify payment type
                payment_type = dues_processor.identify_payment_type(payment)

                # Find associated member if it's a dues payment
                member_name = None
                if payment_type == "dues":
                    member_name = dues_processor.find_member_for_payment(payment)

                payment_info = {
                    "id": payment.id,
                    "status": payment.status,
                    "amount": (
                        f"{payment.amount['value']} {payment.amount['currency']}"
                        if payment.amount
                        else "Unknown"
                    ),
                    "description": getattr(payment, "description", ""),
                    "created_at": str(payment.created_at),
                    "paid_at": (
                        str(getattr(payment, "paid_at", None)) if getattr(payment, "paid_at", None) else None
                    ),
                    "subscription_id": getattr(payment, "subscription_id", None),
                    "payment_type": payment_type,
                    "member": member_name,
                    "already_processed": idempotency_check["already_processed"],
                    "payment_entry": idempotency_check.get("payment_entry"),
                    "processable": payment.status == "paid"
                    and payment_type == "dues"
                    and not idempotency_check["already_processed"],
                }

                result["payments"].append(payment_info)

                if idempotency_check["already_processed"]:
                    result["processed_count"] += 1
                else:
                    result["unprocessed_count"] += 1

        except Exception as e:
            sanitized_error = self._sanitize_error_message(str(e))
            result["error"] = sanitized_error
            self.logger.error(f"Error retrieving customer payments for {customer_id}: {str(e)}")

        return result

    def batch_process_dues_payments(self, payment_ids: list, customer_id: str = None):
        """
        Process multiple membership dues payments in batch with intelligent invoice matching.

        Args:
            payment_ids: List of Mollie payment IDs to process
            customer_id: Optional customer ID for context

        Returns:
            Dict with batch processing results
        """
        if not payment_ids:
            raise ValueError(_("No payment IDs provided"))

        result = {
            "customer_id": customer_id,
            "total_requested": len(payment_ids),
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "timestamp": frappe.utils.now(),
        }

        try:
            from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import (
                BulkPaymentChecker,
            )
            from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
                DuesPaymentProcessor,
            )

            dues_processor = DuesPaymentProcessor()
            invoice_checker = BulkPaymentChecker()

            for payment_id in payment_ids:
                try:
                    # Fetch payment from Mollie to check for invoice matching
                    payment = dues_processor.mollie_client.sdk_client.payments.get(payment_id)

                    # Find member for this payment
                    member_name = dues_processor.find_member_for_payment(payment)

                    # Check for matching unpaid invoice
                    invoice_name = None
                    if member_name and payment.status == "paid":
                        matching_invoice = invoice_checker.check_invoice_match_for_payment(
                            sdk_payment=payment, member_name=member_name
                        )
                        if matching_invoice and isinstance(matching_invoice, dict):
                            invoice_name = matching_invoice.get("invoice_name")
                            self.logger.info(
                                f"Found matching invoice {invoice_name} for payment {payment_id}"
                            )

                    # Process with invoice_name if found (enables PE creation + reconciliation)
                    payment_result = dues_processor.process_dues_payment(
                        payment_id, payment=payment, invoice_name=invoice_name
                    )
                    result["results"].append(payment_result)

                    if payment_result["status"] == "success":
                        result["processed"] += 1
                    elif payment_result["status"] in ["skipped", "already_processed"]:
                        result["skipped"] += 1
                    elif payment_result["status"] == "error":
                        result["errors"] += 1

                except Exception as e:
                    result["errors"] += 1
                    result["results"].append({"payment_id": payment_id, "status": "error", "error": str(e)})
                    self.logger.error(f"Error processing payment {payment_id}: {e}")

            self.logger.info(
                f"✅ Batch processing complete: {result['processed']} processed, "
                f"{result['skipped']} skipped, {result['errors']} errors"
            )

        except Exception as e:
            result["error"] = str(e)
            self.logger.error(f"Batch processing error: {e}")

        return result

    def create_test_payment(
        self, amount: float, description: str, customer_id: str = None, due_date: str = None
    ):
        """
        Create a test payment with customizable description.

        Args:
            amount: Payment amount in EUR
            description: Custom payment description
            customer_id: Optional customer ID to link payment to
            due_date: Optional due date for bank transfer payments (YYYY-MM-DD format).
                      Must be between tomorrow and 100 days from now.
                      Only applicable for bank transfer payment method.

        Returns:
            Dict containing:
                - status: "success" or "error"
                - payment_id: Created payment ID (if successful)
                - checkout_url: URL to complete payment
                - due_date: The due date if provided (for bank transfer payments)
                - error: Error message (if failed)
        """
        from datetime import datetime, timedelta

        # Validate amount using centralized helper
        amount_float = validate_mollie_amount(amount, min_amount=0.01)

        # Add reasonable maximum for test payments (€1,000)
        if amount_float > 1000.00:
            raise ValueError(_("Test payment amount cannot exceed €1,000"))

        if not description or len(description.strip()) < 3:
            raise ValueError(_("Description must be at least 3 characters"))

        # Validate due date if provided
        validated_due_date = None
        if due_date:
            try:
                due_date_obj = datetime.strptime(due_date, "%Y-%m-%d").date()
                tomorrow = (datetime.now() + timedelta(days=1)).date()
                max_date = (datetime.now() + timedelta(days=100)).date()

                if due_date_obj < tomorrow:
                    raise ValueError(_("Due date must be at least tomorrow"))
                if due_date_obj > max_date:
                    raise ValueError(_("Due date cannot be more than 100 days from now"))

                validated_due_date = due_date
            except ValueError as e:
                if "strptime" in str(e.__class__):
                    raise ValueError(_("Invalid due date format. Use YYYY-MM-DD"))
                raise

        try:
            # Get site URL for redirect
            site_url = frappe.utils.get_url()
            redirect_url = f"{site_url}/mollie_payments_debug"

            # Get webhook URL using MollieClient method
            webhook_url = self.mollie_client.get_webhook_url()

            # Build payment data (amount as dict, not Money object)
            payment_data = {
                "amount": format_mollie_amount(amount_float),
                "description": description[:255],  # Mollie has 255 char limit
                "redirectUrl": redirect_url,
                "webhookUrl": webhook_url,
                "metadata": {
                    "created_via": "debug_page",
                    "created_by": frappe.session.user,
                    "created_at": frappe.utils.now(),
                },
            }

            # Add customer if provided
            if customer_id:
                payment_data["customerId"] = customer_id

            # Add due date if provided (only applicable for bank transfer payments)
            if validated_due_date:
                payment_data["dueDate"] = validated_due_date

            # Create payment using MollieClient
            payment = self.mollie_client.create_payment(payment_data)

            # Structured audit trail logging
            self.audit_trail.log_event(
                AuditEventType.PAYMENT_CREATED,
                AuditSeverity.INFO,
                f"Created test payment {payment.id}",
                details={
                    "action": "test_payment_creation",
                    "payment_id": payment.id,
                    "amount": amount_float,
                    "description": description[:100],  # Truncate for audit log
                    "customer_id": customer_id,
                    "due_date": validated_due_date,
                    "created_by": frappe.session.user,
                },
                entity_type="Mollie Payment",
                entity_id=payment.id,
            )

            # Also keep standard logger for operational visibility
            self.logger.info(
                f"DEBUG PAYMENT CREATION: User {frappe.session.user} "
                f"created payment {payment.id} "
                f"(amount: €{amount_float:.2f}, description: {description}, "
                f"customer: {customer_id or 'none'}, due_date: {validated_due_date or 'none'})"
            )

            return create_success_response(
                "Test payment created successfully",
                {
                    "test_mode": self.test_mode,
                    "payment_id": payment.id,
                    "payment_status": payment.status,
                    "amount": format_mollie_response_amount(payment.amount),
                    "description": payment.description,
                    "checkout_url": payment.checkout_url,
                    "customer_id": customer_id,
                    "due_date": validated_due_date,
                    "timestamp": frappe.utils.now(),
                },
            )

        except Exception as e:
            # Sanitize error message before returning to client
            sanitized_error = self._sanitize_error_message(str(e))

            # Log full error internally with user context
            self.logger.error(f"Mollie test payment creation error for user {frappe.session.user}: {str(e)}")

            return create_error_response(
                sanitized_error,
                {
                    "test_mode": self.test_mode,
                    "timestamp": frappe.utils.now(),
                },
            )

    def sync_membership_end_dates_from_mollie(self, dry_run: bool = True):
        """
        Sync membership end dates from Mollie subscription cancellation dates
        for terminated/banned/suspended members.

        This function:
        1. Finds all members with status in ('Quit', 'Banned', 'Suspended')
        2. For each member with a mollie_customer_id:
           a. Queries Mollie for customer data
           b. Retrieves subscription information
           c. Uses the subscription cancellation date
           d. Updates the Member.member_end_date field (always)
           e. Also updates Membership.cancellation_date field (if Membership record exists)

        This is particularly useful for imported terminated members who may lack
        Membership records but still need their end date populated from Mollie.

        Args:
            dry_run: If True, only report what would be updated without making changes

        Returns:
            Dict containing:
                - total_checked: Number of members checked
                - updates_needed: Number of members needing updates
                - updates_applied: Number of updates actually applied (0 if dry_run)
                - members: List of member details with update info
                - error: Error message if failed
        """
        result = {
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "dry_run": dry_run,
            "total_checked": 0,
            "updates_needed": 0,
            "updates_applied": 0,
            "members": [],
            "error": None,
        }

        try:
            # Find all terminated/banned/suspended members with Mollie customer IDs
            members = frappe.get_all(
                "Member",
                filters={
                    "status": ["in", ["Quit", "Banned", "Suspended"]],
                    "mollie_customer_id": ["!=", ""],
                },
                fields=["name", "full_name", "status", "mollie_customer_id", "mollie_subscription_id"],
            )

            result["total_checked"] = len(members)
            self.logger.info(
                f"Mollie membership end date sync: Found {len(members)} terminated/banned/suspended members "
                f"with Mollie customer IDs (dry_run={dry_run})"
            )

            for member in members:
                member_result = {
                    "member": member.name,
                    "full_name": member.full_name,
                    "status": member.status,
                    "customer_id": member.mollie_customer_id,
                    "subscription_id": member.mollie_subscription_id,
                    "canceled_at": None,
                    "current_cancellation_date": None,
                    "needs_update": False,
                    "updated": False,
                    "error": None,
                }

                try:
                    self._sync_single_member_end_date(member, member_result, result, dry_run)
                except Exception as member_error:
                    member_result["error"] = str(member_error)
                    self.logger.error(
                        f"Error processing member {member.name} for Mollie sync: {str(member_error)}"
                    )

                result["members"].append(member_result)

            # Summary logging
            if dry_run:
                self.logger.info(
                    f"Mollie sync DRY RUN complete: {result['total_checked']} members checked, "
                    f"{result['updates_needed']} would be updated"
                )
            else:
                self.logger.info(
                    f"Mollie sync complete: {result['total_checked']} members checked, "
                    f"{result['updates_applied']} updated"
                )

        except Exception as e:
            result["error"] = str(e)
            self.logger.error(f"Mollie membership end date sync error: {str(e)}")

        return result

    def _fetch_mollie_cancellation_date(self, customer_id, member_result):
        """Fetch the latest subscription cancellation date from Mollie.

        Returns canceled date object or None. Marks member_result as skipped on 410.
        """
        from datetime import datetime

        client = self.mollie_client.sdk_client

        try:
            customer_obj = client.customers.get(customer_id)
        except Exception as api_error:
            error_msg = str(api_error)
            if "no longer available" in error_msg.lower() or "410" in error_msg:
                member_result["error"] = "Customer deleted in Mollie (410 Gone)"
                member_result["skipped"] = True
                return None
            raise

        subscriptions = customer_obj.subscriptions.list()
        latest_canceled_at = None
        for sub in subscriptions:
            if hasattr(sub, "canceled_at") and sub.canceled_at:
                if latest_canceled_at is None or sub.canceled_at > latest_canceled_at:
                    latest_canceled_at = sub.canceled_at
                    member_result["subscription_id"] = sub.id

        if not latest_canceled_at:
            return None

        if isinstance(latest_canceled_at, str):
            return datetime.fromisoformat(latest_canceled_at.replace("Z", "+00:00")).date()
        return latest_canceled_at.date()

    def _sync_single_member_end_date(self, member, member_result, result, dry_run):
        """Sync end date for a single member from Mollie subscription cancellation.

        Mutates member_result and result dicts in place.
        """
        canceled_date = self._fetch_mollie_cancellation_date(member.mollie_customer_id, member_result)
        if not canceled_date:
            return

        member_result["canceled_at"] = str(canceled_date)

        # Update Member.member_end_date if needed
        member_doc = frappe.get_doc("Member", member.name)
        current_member_end_date = member_doc.get("member_end_date")
        member_result["current_member_end_date"] = (
            str(current_member_end_date) if current_member_end_date else None
        )

        if not current_member_end_date or str(current_member_end_date) != str(canceled_date):
            member_result["needs_update"] = True
            result["updates_needed"] += 1

            if not dry_run:
                frappe.db.set_value(
                    "Member", member.name, "member_end_date", canceled_date, update_modified=False
                )
                frappe.db.commit()
                member_result["updated"] = True
                result["updates_applied"] += 1
                self.logger.info(
                    f"Updated member {member.name} member_end_date "
                    f"from {current_member_end_date} to {canceled_date} "
                    f"based on Mollie subscription cancellation"
                )

        # Attach sales invoices
        sales_invoices = frappe.get_all(
            "Sales Invoice",
            filters={"member": member.name, "docstatus": 1},
            fields=["name", "posting_date", "grand_total", "status"],
            order_by="posting_date desc",
            limit=5,
        )
        member_result["sales_invoices"] = [
            {
                "name": inv.name,
                "date": str(inv.posting_date),
                "amount": float(inv.grand_total),
                "status": inv.status,
            }
            for inv in sales_invoices
        ]
        member_result["invoice_count"] = len(sales_invoices)

        # Update Membership.cancellation_date if record exists
        membership = frappe.get_all(
            "Membership",
            filters={"member": member.name, "docstatus": 1},
            fields=["name", "cancellation_date"],
            order_by="creation desc",
            limit=1,
        )

        if membership:
            current_cancellation_date = membership[0].get("cancellation_date")
            member_result["current_cancellation_date"] = (
                str(current_cancellation_date) if current_cancellation_date else None
            )
            member_result["membership"] = membership[0].name

            if not current_cancellation_date or str(current_cancellation_date) != str(canceled_date):
                if not dry_run:
                    frappe.db.set_value(
                        "Membership",
                        membership[0].name,
                        "cancellation_date",
                        canceled_date,
                        update_modified=False,
                    )
                    frappe.db.commit()
                    self.logger.info(
                        f"Updated membership {membership[0].name} cancellation_date "
                        f"from {current_cancellation_date} to {canceled_date} "
                        f"for member {member.name}"
                    )
        else:
            member_result["membership_note"] = "No submitted membership found (member end date still updated)"

    def _process_retrieved_payment(
        self,
        payment,
        matcher,
        bank_tx_creator,
        invoice_checker,
        seen_payment_ids,
        start_date_str,
        payment_status_filter,
        consecutive_old_payments,
        member_results,
        result,
    ):
        """Process a single payment during bulk retrieval. Returns True to stop pagination."""
        # Deduplicate
        if payment.id in seen_payment_ids:
            result["total_filtered_by_duplicate"] += 1
            self.logger.warning(
                f"Duplicate payment ID from Mollie API: {payment.id}. "
                f"This indicates the API returned the same payment multiple times."
            )
            return False
        seen_payment_ids.add(payment.id)

        # Match to member
        member_info = matcher.find_member_for_payment(payment)
        if not member_info:
            result["total_filtered_by_member"] += 1
            return False

        # Date filtering with early termination
        if not (hasattr(payment, "created_at") and payment.created_at):
            return False

        payment_date_str = payment.created_at[:10]
        if payment_date_str < start_date_str:
            result["total_filtered_by_date"] += 1
            consecutive_old_payments += 1
            result["_consecutive_old"] = consecutive_old_payments
            if consecutive_old_payments >= 50:
                self.logger.info(
                    f"Early termination: {consecutive_old_payments} consecutive "
                    f"payments older than {start_date_str}. Stopping pagination."
                )
                result["early_termination"] = True
                return True
            return False

        consecutive_old_payments = 0
        result["_consecutive_old"] = consecutive_old_payments

        # Status filter
        if payment_status_filter and payment_status_filter != "all":
            if payment.status != payment_status_filter:
                return False

        # Idempotency check
        idempotency_check = bank_tx_creator.check_already_processed(payment.id, check_payment_entry=True)
        is_processed = idempotency_check["already_processed"]

        # Invoice matching for unprocessed paid payments
        matching_invoice, processing_mode = self._check_invoice_for_retrieval(
            payment, is_processed, member_info, invoice_checker
        )

        # Build payment info and accumulate
        payment_info = self._build_retrieved_payment_info(
            payment, is_processed, idempotency_check, matching_invoice, processing_mode
        )

        member_name = member_info["name"]
        if member_name not in member_results:
            member_results[member_name] = {
                "member": member_name,
                "full_name": member_info.get("full_name", member_name),
                "customer_id": member_info.get("mollie_customer_id"),
                "member_status": member_info.get("status"),
                "payments": [],
                "payment_count": 0,
                "unprocessed_count": 0,
                "error": None,
            }

        member_result = member_results[member_name]
        member_result["payments"].append(payment_info)
        member_result["payment_count"] += 1
        result["total_payments"] += 1
        result["total_payments_after_filtering"] += 1

        if not is_processed:
            member_result["unprocessed_count"] += 1
            result["unprocessed_payments"] += 1

        return False

    def _check_invoice_for_retrieval(self, payment, is_processed, member_info, invoice_checker):
        """Check for matching invoice during bulk payment retrieval."""
        if payment.status == "paid" and not is_processed and member_info and payment.amount:
            try:
                matching_invoice = invoice_checker.check_invoice_match_for_payment(
                    sdk_payment=payment, member_name=member_info["name"]
                )
                processing_mode = "bt_pe_reconcile" if matching_invoice else "bt_only"
                return matching_invoice, processing_mode
            except Exception as e:
                self.logger.warning(f"Could not check for matching invoice: {e}")
                return None, "bt_only"
        return None, None

    @staticmethod
    def _build_retrieved_payment_info(
        payment, is_processed, idempotency_check, matching_invoice, processing_mode
    ):
        """Build payment info dict for bulk retrieval results."""
        return {
            "payment_id": payment.id,
            "status": payment.status,
            "amount": (
                f"{payment.amount['value']} {payment.amount['currency']}" if payment.amount else "Unknown"
            ),
            "description": getattr(payment, "description", ""),
            "created_at": str(payment.created_at),
            "paid_at": (
                str(getattr(payment, "paid_at", None)) if getattr(payment, "paid_at", None) else None
            ),
            "is_processed": is_processed,
            "payment_entry": idempotency_check.get("payment_entry") if is_processed else None,
            "bank_transaction": idempotency_check.get("bank_transaction") if is_processed else None,
            "matching_invoice": matching_invoice,
            "processing_mode": processing_mode,
        }

    def bulk_retrieve_all_member_payments(
        self, days_back: int = 30, max_payments: int = 5000, payment_status_filter: str = None
    ):
        """
        Bulk retrieve payments for all members with Mollie customer IDs.

        Uses global payments endpoint with pagination for optimal performance.
        Makes 1 API call per 250 payments instead of 1 per member (N+1 problem).

        Matches payments to ALL members (regardless of status) for complete
        bookkeeping/audit trail. Uses centralized MemberPaymentMatcher for
        consistent matching with global_payments mode.

        Args:
            days_back: Number of days back to check (default: 30)
            max_payments: Maximum total payments to retrieve (default: 5000)
            payment_status_filter: Optional filter ('paid', 'pending', 'all')

        Returns:
            Dict containing:
                - total_members: Number of members with Mollie IDs
                - members_checked: Number successfully checked
                - total_payments: Total payments found
                - unprocessed_payments: Payments not yet processed
                - members: List of member details with payments
                - api_calls_made: Number of API calls to Mollie
        """
        from datetime import datetime, timedelta

        from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
            get_member_payment_matcher,
        )

        result = {
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "days_back": days_back,
            "max_payments": max_payments,
            "total_members": 0,
            "members_checked": 0,
            "total_payments": 0,
            "unprocessed_payments": 0,
            "members": [],
            "api_calls_made": 0,
            "error": None,
            # Filtering statistics
            "total_payments_found": 0,  # Raw count from Mollie API before filtering
            "total_payments_after_filtering": 0,  # After deduplication
            "total_filtered_by_duplicate": 0,
            "total_filtered_by_date": 0,  # Payments outside date range
            "total_filtered_by_member": 0,  # Payments without matching member (renamed for clarity)
            "early_termination": False,  # True if stopped due to old payments
        }

        try:
            # Use centralized matcher for consistent member matching
            matcher = get_member_payment_matcher()
            members = matcher.get_all_members_with_mollie_id()

            result["total_members"] = len(members)

            self.logger.info(
                f"Bulk payment retrieval: Found {len(members)} members with Mollie IDs "
                f"(all statuses). Using global payments endpoint with pagination."
            )

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            start_date_str = start_date.strftime("%Y-%m-%d")

            # Get raw Mollie client
            client = self.mollie_client.sdk_client

            # Initialize member results dict keyed by member name (not customer_id)
            # This handles cases where member is found via description parsing
            member_results = {}

            # Get bank transaction creator for idempotency checks (outside loop for efficiency)
            from verenigingen.verenigingen_payments.mollie.services.bulk_payment_checker import (
                BulkPaymentChecker,
            )
            from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
                get_bank_transaction_creator,
            )

            bank_tx_creator = get_bank_transaction_creator()
            invoice_checker = BulkPaymentChecker()  # Reuse for all payments

            # Fetch ALL payments using global endpoint with pagination
            has_next = True
            from_id = None
            limit = 250
            total_fetched = 0
            seen_payment_ids = set()  # Track payment IDs to detect duplicates
            consecutive_old_payments = 0  # Track consecutive out-of-range payments for early termination

            while has_next and total_fetched < max_payments:
                try:
                    # Build parameters for global payments endpoint
                    params = {"limit": limit}
                    if from_id:
                        params["from"] = from_id

                    # Fetch payments batch
                    payment_list = client.payments.list(**params)
                    batch_payments = list(payment_list)
                    result["api_calls_made"] += 1

                    self.logger.info(
                        f"Fetched batch of {len(batch_payments)} payments (API call #{result['api_calls_made']})"
                    )

                    # Process each payment
                    for payment in batch_payments:
                        total_fetched += 1
                        result["total_payments_found"] += 1

                        stop = self._process_retrieved_payment(
                            payment,
                            matcher,
                            bank_tx_creator,
                            invoice_checker,
                            seen_payment_ids,
                            start_date_str,
                            payment_status_filter,
                            consecutive_old_payments,
                            member_results,
                            result,
                        )
                        # Update consecutive_old_payments from result dict
                        consecutive_old_payments = result.get("_consecutive_old", consecutive_old_payments)
                        if stop:
                            has_next = False
                            break

                    # Check pagination
                    has_next = len(batch_payments) == limit
                    if has_next and batch_payments:
                        from_id = batch_payments[-1].id
                    else:
                        has_next = False

                except Exception as batch_error:
                    self.logger.error(f"Error fetching payment batch: {str(batch_error)}")
                    break

            # Convert member_results dict to list
            for member_name, member_result in member_results.items():
                if member_result["payment_count"] > 0 or member_result["error"]:
                    result["members"].append(member_result)
                    result["members_checked"] += 1

            self.logger.info(
                f"Bulk retrieval complete: {result['api_calls_made']} API calls made, "
                f"{total_fetched} total payments fetched, {result['total_payments']} matched to members, "
                f"{result['unprocessed_payments']} unprocessed"
            )

        except Exception as e:
            result["error"] = str(e)
            self.logger.error(f"Bulk payment retrieval error: {str(e)}")

        result.pop("_consecutive_old", None)
        return result

    @staticmethod
    def _resolve_payment_mode(payment_modes, payment_id):
        """Resolve processing mode and invoice name from payment_modes dict."""
        payment_mode_info = payment_modes.get(payment_id, {})
        matching_invoice = None
        processing_mode = None
        if isinstance(payment_mode_info, dict):
            matching_invoice = payment_mode_info.get("matching_invoice")
            processing_mode = payment_mode_info.get("mode")

        invoice_name = None
        if matching_invoice:
            if isinstance(matching_invoice, dict):
                invoice_name = matching_invoice.get("invoice_name")
            else:
                invoice_name = matching_invoice

        return processing_mode, invoice_name

    @staticmethod
    def _route_to_orchestrator(orchestrator, payment_id, processing_mode, invoice_name):
        """Route a payment to the appropriate orchestrator method."""
        if processing_mode in ("bt_only_orphaned", "bt_only_anonymous"):
            return orchestrator.process_orphaned_payment(payment_id=payment_id, allow_anonymous=True)
        elif processing_mode == "bt_only":
            return orchestrator.process_bt_only_payment(payment_id=payment_id)
        else:
            return orchestrator.process_payment(
                payment_id=payment_id, invoice_name=invoice_name, create_missing_invoice=False
            )

    def _submit_processed_documents(self, processing_result, payment_id, payment_result):
        """Submit bank transaction and payment entry if they exist and are in draft."""
        try:
            if processing_result.bank_transaction:
                bt_doc = frappe.get_doc("Bank Transaction", processing_result.bank_transaction)
                if bt_doc.docstatus == 0 and frappe.has_permission("Bank Transaction", "submit", bt_doc):
                    bt_doc.submit()
                    payment_result["bank_transaction_submitted"] = True

            if processing_result.payment_entry:
                pe_doc = frappe.get_doc("Payment Entry", processing_result.payment_entry)
                if pe_doc.docstatus == 0 and frappe.has_permission("Payment Entry", "submit", pe_doc):
                    pe_doc.submit()
                    payment_result["payment_entry_submitted"] = True
        except Exception as submit_error:
            payment_result["submit_error"] = str(submit_error)
            self.logger.error(f"Submission error for {payment_id}: {submit_error}")

    def _process_single_bulk_payment(self, orchestrator, payment_id, payment_modes, docstatus):
        """Process a single payment through the orchestrator and optionally submit."""
        processing_mode, invoice_name = self._resolve_payment_mode(payment_modes, payment_id)
        processing_result = self._route_to_orchestrator(
            orchestrator, payment_id, processing_mode, invoice_name
        )

        payment_result = {
            "payment_id": payment_id,
            "status": processing_result.status,
            "bank_transaction": processing_result.bank_transaction,
            "payment_entry": processing_result.payment_entry,
            "member": processing_result.member,
            "sales_invoice": processing_result.sales_invoice,
            "actions_taken": processing_result.actions_taken,
            "reconciled": processing_result.reconciled,
        }

        if processing_result.error:
            payment_result["error"] = processing_result.error
        if processing_result.skipped_reason:
            payment_result["skipped_reason"] = processing_result.skipped_reason

        if processing_result.status == "success" and docstatus == 1:
            self._submit_processed_documents(processing_result, payment_id, payment_result)

        return payment_result

    def bulk_process_member_payments(self, payment_ids: list, docstatus: int = 0, payment_modes: dict = None):
        """
        Bulk process selected payments using the MolliePaymentOrchestrator.

        Uses the consolidated orchestrator for consistent processing flow.
        The orchestrator handles invoice matching, BT creation, PE creation, and BT-PE linking.

        Args:
            payment_ids: List of Mollie payment IDs to process
            docstatus: 0 for Draft, 1 for Submitted (default: 0)
            payment_modes: Dict mapping payment_id to {mode, matching_invoice}
                          (Legacy parameter - matching_invoice still used if provided)

        Returns:
            Dict with processing results
        """
        import random
        import time

        # Default to empty dict if not provided
        if payment_modes is None:
            payment_modes = {}

        # Auto-batch large requests to prevent deadlocks and timeouts
        SAFE_BATCH_SIZE = 250

        result = {
            "total_requested": len(payment_ids),
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "timestamp": frappe.utils.now(),
            "docstatus": docstatus,
            "orchestrator_mode": True,  # Indicates using new consolidated orchestrator
            "batches_processed": 0,
            "total_batches": 0,
        }

        # If request is larger than safe batch size, split into batches
        if len(payment_ids) > SAFE_BATCH_SIZE:
            total_batches = (len(payment_ids) + SAFE_BATCH_SIZE - 1) // SAFE_BATCH_SIZE
            result["total_batches"] = total_batches
            result["batch_size"] = SAFE_BATCH_SIZE

            self.logger.info(
                f"Auto-splitting {len(payment_ids)} payments into {total_batches} batches "
                f"of {SAFE_BATCH_SIZE} to prevent deadlocks"
            )

            # Process in batches with delays
            for batch_num in range(total_batches):
                start_idx = batch_num * SAFE_BATCH_SIZE
                end_idx = min(start_idx + SAFE_BATCH_SIZE, len(payment_ids))
                batch_payment_ids = payment_ids[start_idx:end_idx]

                # Extract payment_modes for this batch
                batch_payment_modes = {
                    pid: payment_modes.get(pid) for pid in batch_payment_ids if pid in payment_modes
                }

                self.logger.info(
                    f"Processing batch {batch_num + 1}/{total_batches}: "
                    f"payments {start_idx + 1}-{end_idx} of {len(payment_ids)}"
                )

                # Recursively call this function with smaller batch
                batch_result = self.bulk_process_member_payments(
                    batch_payment_ids, docstatus, batch_payment_modes
                )

                # Aggregate results
                result["processed"] += batch_result["processed"]
                result["skipped"] += batch_result["skipped"]
                result["errors"] += batch_result["errors"]
                result["results"].extend(batch_result.get("results", []))
                result["batches_processed"] += 1

                # Add random delay between batches to reduce contention (0.5-2 seconds)
                if batch_num < total_batches - 1:
                    delay = random.uniform(0.5, 2.0)
                    self.logger.info(
                        f"Batch {batch_num + 1} complete. Waiting {delay:.2f}s before next batch..."
                    )
                    time.sleep(delay)

            result["message"] = f"Completed {total_batches} batches successfully"
            return result

        # Single batch processing using orchestrator
        result["batches_processed"] = 1
        result["total_batches"] = 1

        try:
            from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
                get_payment_orchestrator,
            )

            orchestrator = get_payment_orchestrator()

            for payment_id in payment_ids:
                payment_result = self._process_single_bulk_payment(
                    orchestrator, payment_id, payment_modes, docstatus
                )

                # Update counters
                status = payment_result["status"]
                if status == "success":
                    result["processed"] += 1
                elif status in ["skipped", "already_processed"]:
                    result["skipped"] += 1
                else:
                    result["errors"] += 1

                result["results"].append(payment_result)

            self.logger.info(
                f"Bulk processing complete: {result['processed']} processed, "
                f"{result['skipped']} skipped, {result['errors']} errors"
            )

        except Exception as e:
            result["error"] = str(e)
            self.logger.error(f"Bulk processing error: {e}")

        return result

    def process_payment_batch_background(
        self, batch_num: int, payment_ids: list, docstatus: int, payment_modes: dict, job_id: str
    ):
        """
        Background job handler for processing a batch of payments.

        This function is called by Frappe's background job queue to process
        a chunk of payments asynchronously.

        Args:
            batch_num: Batch number (for logging/tracking)
            payment_ids: List of payment IDs for this batch
            docstatus: 0 for Draft, 1 for Submitted
            payment_modes: Dict mapping payment_id to {mode, matching_invoice}
            job_id: Unique job identifier for tracking

        Returns:
            Dict with batch processing results
        """
        self.logger.info(
            f"Background job {job_id}: Processing batch {batch_num} with {len(payment_ids)} payments"
        )

        try:
            # Process the batch using existing method
            result = self.bulk_process_member_payments(payment_ids, docstatus, payment_modes)

            # Add batch metadata
            result["batch_num"] = batch_num
            result["job_id"] = job_id

            self.logger.info(
                f"Background job {job_id}: Batch {batch_num} complete - "
                f"{result['processed']} processed, {result['skipped']} skipped, {result['errors']} errors"
            )

            return result

        except Exception as e:
            error_msg = f"Background job {job_id}: Batch {batch_num} failed - {str(e)}"
            self.logger.error(error_msg)
            return {
                "batch_num": batch_num,
                "job_id": job_id,
                "error": str(e),
                "total_requested": len(payment_ids),
                "processed": 0,
                "skipped": 0,
                "errors": len(payment_ids),
            }
