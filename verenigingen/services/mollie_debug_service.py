"""
Mollie Debug Service
Unified service layer for all Mollie API debugging operations
"""

import frappe
from frappe import _

from verenigingen.integrations.mollie.core.client import MollieClient
from verenigingen.utils.security.api_security_framework import OperationType


class MollieDebugService:
    """Centralized service for Mollie API debugging operations"""

    def __init__(self):
        self.mollie_client = MollieClient()

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

            result["subscription_data"] = {
                "id": subscription.id,
                "customer_id": subscription.customer_id,
                "status": subscription.status,
                "amount": amount_str,
                "interval": subscription.interval,
                "description": subscription.description,
                "created_at": str(subscription.created_at),
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
                "mandate_id": getattr(subscription, "mandateId", None),
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
            # Use direct Mollie API call to avoid retry/circuit breaker issues
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            cancelled_subscription = customer_obj.subscriptions.delete(subscription_id)

            # Log admin action
            frappe.logger().info(
                f"ADMIN CANCELLATION: User {frappe.session.user} cancelled subscription {subscription_id} for customer {customer_id}. Reason: {reason}"
            )

            return {
                "status": "success",
                "message": _("Subscription cancelled successfully"),
                "subscription_id": subscription_id,
                "customer_id": customer_id,
                "cancelled_by": frappe.session.user,
                "reason": reason,
                "timestamp": frappe.utils.now(),
            }

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
                frappe.logger().info(
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
                            frappe.logger().info(
                                f"ADMIN MANDATE REVOCATION: Cancelled subscription {sub.id} "
                                f"before revoking mandate {mandate_id} for customer {customer_id}"
                            )
                        except Exception as sub_error:
                            # Log but don't fail if subscription is already cancelled
                            frappe.logger().warning(
                                f"Could not cancel subscription {sub.id} during mandate revocation: {str(sub_error)}"
                            )
            except Exception as list_error:
                frappe.logger().warning(
                    f"Could not list subscriptions during mandate revocation for customer {customer_id}: {str(list_error)}"
                )

            # STEP 2: Revoke the mandate
            revoked_mandate = customer_obj.mandates.delete(mandate_id)

            # Log admin action
            frappe.logger().info(
                f"ADMIN REVOCATION: User {frappe.session.user} revoked mandate {mandate_id} "
                f"for customer {customer_id}. Cancelled {len(cancelled_subscriptions)} subscriptions. "
                f"Reason: {reason}"
            )

            return {
                "status": "success",
                "message": _("Mandate revoked and {0} subscription(s) cancelled successfully").format(
                    len(cancelled_subscriptions)
                ),
                "mandate_id": mandate_id,
                "customer_id": customer_id,
                "cancelled_subscriptions": cancelled_subscriptions,
                "revoked_by": frappe.session.user,
                "reason": reason,
                "timestamp": frappe.utils.now(),
            }

        except Exception as api_error:
            error_message = str(api_error)
            if "no longer available" in error_message or "Gone" in error_message:
                frappe.logger().info(
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
            subscriptions = customer_obj.subscriptions.list()
            mandates = customer_obj.mandates.list()

            # Log the impending deletion with full details
            frappe.logger().warning(
                f"CUSTOMER DELETION INITIATED: User {frappe.session.user} is deleting customer {customer_id}"
            )
            frappe.logger().warning(f"Customer details: {customer_details}")
            frappe.logger().warning(
                f"Will cascade delete {len(subscriptions)} subscriptions and {len(mandates)} mandates"
            )
            frappe.logger().warning(f"Reason: {reason}")

            # Perform the deletion
            deleted_customer = client.customers.delete(customer_id)

            # Log successful deletion
            frappe.logger().warning(
                f"CUSTOMER DELETION COMPLETED: Customer {customer_id} successfully deleted by {frappe.session.user}"
            )

            return {
                "status": "success",
                "message": _("Customer deleted successfully (including all subscriptions and mandates)"),
                "customer_id": customer_id,
                "deleted_by": frappe.session.user,
                "reason": reason,
                "timestamp": frappe.utils.now(),
                "customer_details": customer_details,
                "cascaded_deletions": {
                    "subscriptions_deleted": len(subscriptions),
                    "mandates_deleted": len(mandates),
                },
            }

        except Exception as api_error:
            error_message = str(api_error)
            if "not found" in error_message.lower() or "does not exist" in error_message.lower():
                frappe.logger().info(
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
        # Validate limit
        try:
            limit = int(limit)
            if limit < 1 or limit > 250:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

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
        try:
            limit = int(limit)
            if limit < 1 or limit > 250:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

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
        try:
            limit = int(limit)
            if limit < 1 or limit > 250:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

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

            # Log admin action
            frappe.logger().info(
                f"ADMIN PAYMENT CANCELLATION: User {frappe.session.user} cancelled payment {payment_id}. Reason: {reason}"
            )

            return {
                "status": "success",
                "message": _("Payment cancelled successfully"),
                "payment_id": payment_id,
                "previous_status": payment.status,
                "cancelled_by": frappe.session.user,
                "reason": reason,
                "timestamp": frappe.utils.now(),
            }

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
                frappe.logger().info(
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
        try:
            limit = int(limit)
            if limit < 1 or limit > 100:
                limit = 20
        except (ValueError, TypeError):
            limit = 20

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
            frappe.log_error(f"Mollie search customers error: {str(e)}")

        return result

    def test_webhook_processing(self, payment_id):
        """
        Test webhook processing for a specific payment ID.

        Calls the unified webhook handler directly to simulate webhook delivery.
        Now supports both donation and membership dues payments.
        """
        if not payment_id:
            raise ValueError(_("Payment ID is required"))

        from verenigingen.integrations.mollie.api.unified_payment_api import handle_payment_webhook

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
            from verenigingen.integrations.mollie.services.payment_type_router import get_payment_router

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
            frappe.log_error(f"Webhook test processing error: {str(e)}")

        return result

    def _format_mollie_amount(self, amount_obj):
        """
        Format Mollie amount object to human-readable string.

        Args:
            amount_obj: Mollie amount object (dict or other)

        Returns:
            str: Formatted amount string (e.g., "EUR 25.00")
        """
        try:
            if not amount_obj:
                return "Unknown"
            if isinstance(amount_obj, dict):
                return f"{amount_obj.get('currency', 'EUR')} {amount_obj.get('value', '0')}"
            return str(amount_obj)
        except Exception:
            return "Error parsing amount"

    def _sanitize_error_message(self, error_msg: str) -> str:
        """
        Sanitize error messages to prevent information disclosure.

        Args:
            error_msg: Raw error message

        Returns:
            str: Sanitized error message safe for client display
        """
        error_lower = error_msg.lower()

        # Check for API key exposure
        if "test_" in error_msg or "live_" in error_msg:
            return "API authentication error - check configuration"

        # Check for internal system information
        if any(keyword in error_lower for keyword in ["internal", "traceback", "file", "line"]):
            return "Internal system error - contact administrator"

        # Check for database information
        if any(keyword in error_lower for keyword in ["database", "sql", "query"]):
            return "Data access error - contact administrator"

        return error_msg

    def create_subscription(
        self,
        customer_id: str,
        amount: float,
        interval: str,
        description: str,
        mandate_id: str = None,
        start_date: str = None,
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

        # Validate amount
        try:
            amount_float = float(amount)
        except (ValueError, TypeError):
            raise ValueError(_("Invalid amount format - must be a number"))

        if amount_float <= 0:
            raise ValueError(_("Amount must be positive"))

        # Add reasonable maximum for test subscriptions (€1,000)
        if amount_float > 1000.00:
            raise ValueError(_("Test subscription amount cannot exceed €1,000"))

        # Validate interval format
        valid_intervals = ["1 month", "2 months", "3 months", "6 months", "12 months"]
        if interval not in valid_intervals:
            raise ValueError(_("Invalid interval - must be one of: {0}").format(", ".join(valid_intervals)))

        result = {
            "customer_id": customer_id,
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "status": "pending",
            "error": None,
        }

        try:
            # Get the raw Mollie client
            client = self.mollie_client.sdk_client

            # Build subscription data
            # Note: webhookUrl intentionally omitted to use Mollie dashboard webhook settings
            # This ensures webhooks go to the correct environment (production/test)
            subscription_data = {
                "amount": {"value": f"{amount_float:.2f}", "currency": "EUR"},
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
            if start_date:
                subscription_data["startDate"] = start_date

            # Create subscription
            customer = client.customers.get(customer_id)
            subscription = customer.subscriptions.create(subscription_data)

            result["status"] = "success"
            result["subscription_id"] = subscription.id
            result["subscription_status"] = subscription.status
            result["amount"] = self._format_mollie_amount(subscription.amount)
            result["interval"] = subscription.interval
            result["description"] = subscription.description
            result["webhook_url"] = getattr(subscription, "webhookUrl", "Using dashboard webhook")

            # Add optional fields if present
            if hasattr(subscription, "start_date") and subscription.start_date:
                result["start_date"] = str(subscription.start_date)
            if hasattr(subscription, "next_payment_date") and subscription.next_payment_date:
                result["next_payment_date"] = str(subscription.next_payment_date)

            # Enhanced audit logging
            frappe.logger().info(
                f"DEBUG SUBSCRIPTION CREATION: User {frappe.session.user} "
                f"created subscription {subscription.id} for customer {customer_id} "
                f"(amount: €{amount_float:.2f}, interval: {interval}, description: {description}, "
                f"mandate: {mandate_id or 'auto'}, start: {start_date or 'immediate'})"
            )

        except Exception as e:
            # Sanitize error message before returning to client
            sanitized_error = self._sanitize_error_message(str(e))
            result["error"] = sanitized_error
            result["status"] = "error"

            # Log full error internally with user context
            frappe.log_error(
                f"Mollie subscription creation error for user {frappe.session.user}, "
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
                amount_str = self._format_mollie_amount(sub.amount)

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
            # Sanitize error message
            sanitized_error = self._sanitize_error_message(str(e))
            result["error"] = sanitized_error
            frappe.log_error(f"Mollie list subscriptions error for customer {customer_id}: {str(e)}")

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
            from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor

            dues_processor = DuesPaymentProcessor()

            # Get all payments for customer
            client = self.mollie_client.sdk_client
            customer_obj = client.customers.get(customer_id)
            payments = customer_obj.payments.list(limit=limit)

            result["total_found"] = len(payments)

            for payment in payments:
                # Check if already processed
                idempotency_check = dues_processor.check_payment_already_processed(payment.id)

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
            frappe.log_error(f"Error retrieving customer payments for {customer_id}: {str(e)}")

        return result

    def batch_process_dues_payments(self, payment_ids: list, customer_id: str = None):
        """
        Process multiple membership dues payments in batch.

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
            from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor

            dues_processor = DuesPaymentProcessor()

            for payment_id in payment_ids:
                try:
                    payment_result = dues_processor.process_dues_payment(payment_id)
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
                    frappe.log_error(f"Error processing payment {payment_id}: {e}")

            frappe.logger().info(
                f"✅ Batch processing complete: {result['processed']} processed, "
                f"{result['skipped']} skipped, {result['errors']} errors"
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Batch processing error: {e}")

        return result

    def create_test_payment(self, amount: float, description: str, customer_id: str = None):
        """
        Create a test payment with customizable description.

        Args:
            amount: Payment amount in EUR
            description: Custom payment description
            customer_id: Optional customer ID to link payment to

        Returns:
            Dict containing:
                - status: "success" or "error"
                - payment_id: Created payment ID (if successful)
                - checkout_url: URL to complete payment
                - error: Error message (if failed)
        """
        # Validate amount
        try:
            amount_float = float(amount)
        except (ValueError, TypeError):
            raise ValueError(_("Invalid amount format - must be a number"))

        if amount_float <= 0:
            raise ValueError(_("Amount must be positive"))

        # Add reasonable maximum for test payments (€1,000)
        if amount_float > 1000.00:
            raise ValueError(_("Test payment amount cannot exceed €1,000"))

        if not description or len(description.strip()) < 3:
            raise ValueError(_("Description must be at least 3 characters"))

        result = {
            "test_mode": self.mollie_client.is_test_mode(),
            "timestamp": frappe.utils.now(),
            "status": "pending",
            "error": None,
        }

        try:
            # Get site URL for redirect
            site_url = frappe.utils.get_url()
            redirect_url = f"{site_url}/mollie_payments_debug"

            # Get webhook URL using MollieClient method
            webhook_url = self.mollie_client.get_webhook_url()

            # Build payment data (amount as dict, not Money object)
            payment_data = {
                "amount": {"value": f"{amount_float:.2f}", "currency": "EUR"},
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

            # Create payment using MollieClient
            payment = self.mollie_client.create_payment(payment_data)

            result["status"] = "success"
            result["payment_id"] = payment.id
            result["payment_status"] = payment.status
            result["amount"] = self._format_mollie_amount(payment.amount)
            result["description"] = payment.description
            result["checkout_url"] = payment.checkout_url
            result["customer_id"] = customer_id

            # Enhanced audit logging
            frappe.logger().info(
                f"DEBUG PAYMENT CREATION: User {frappe.session.user} "
                f"created payment {payment.id} "
                f"(amount: €{amount_float:.2f}, description: {description}, "
                f"customer: {customer_id or 'none'})"
            )

        except Exception as e:
            # Sanitize error message before returning to client
            sanitized_error = self._sanitize_error_message(str(e))
            result["error"] = sanitized_error
            result["status"] = "error"

            # Log full error internally with user context
            frappe.log_error(f"Mollie test payment creation error for user {frappe.session.user}: {str(e)}")

        return result

    def sync_membership_end_dates_from_mollie(self, dry_run: bool = True):
        """
        Sync membership end dates from Mollie subscription cancellation dates
        for terminated/banned members.

        This function:
        1. Finds all members with status in ('Terminated', 'Banned', 'Suspended')
        2. For each member with a mollie_customer_id:
           a. Queries Mollie for customer data
           b. Retrieves subscription information
           c. Uses the subscription cancellation date
           d. Updates the Membership.cancellation_date field

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
                    "status": ["in", ["Terminated", "Banned", "Suspended"]],
                    "mollie_customer_id": ["!=", ""],
                },
                fields=["name", "full_name", "status", "mollie_customer_id", "mollie_subscription_id"],
            )

            result["total_checked"] = len(members)
            frappe.logger().info(
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
                    # Get customer data from Mollie
                    client = self.mollie_client.sdk_client
                    customer_obj = client.customers.get(member.mollie_customer_id)

                    # Get subscriptions
                    subscriptions = customer_obj.subscriptions.list()

                    # Find the most recent canceled subscription
                    latest_canceled_at = None
                    for sub in subscriptions:
                        if hasattr(sub, "canceled_at") and sub.canceled_at:
                            # Compare datetime objects
                            if latest_canceled_at is None or sub.canceled_at > latest_canceled_at:
                                latest_canceled_at = sub.canceled_at
                                member_result["subscription_id"] = sub.id

                    if latest_canceled_at:
                        # Convert to date string for Frappe
                        from datetime import datetime

                        if isinstance(latest_canceled_at, str):
                            # Parse ISO string
                            canceled_date = datetime.fromisoformat(
                                latest_canceled_at.replace("Z", "+00:00")
                            ).date()
                        else:
                            # Already datetime object
                            canceled_date = latest_canceled_at.date()

                        member_result["canceled_at"] = str(canceled_date)

                        # Get current membership cancellation date
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

                            # Check if update is needed
                            if not current_cancellation_date or str(current_cancellation_date) != str(
                                canceled_date
                            ):
                                member_result["needs_update"] = True
                                result["updates_needed"] += 1

                                # Apply update if not dry run
                                if not dry_run:
                                    # Use db_set for audit-trailed update without document validation
                                    # This is appropriate for syncing external data (Mollie) to submitted docs
                                    frappe.db.set_value(
                                        "Membership",
                                        membership[0].name,
                                        "cancellation_date",
                                        canceled_date,
                                        update_modified=False,  # Don't change modified timestamp
                                    )
                                    frappe.db.commit()  # Commit immediately for safety
                                    member_result["updated"] = True
                                    result["updates_applied"] += 1

                                    frappe.logger().info(
                                        f"Updated membership {membership[0].name} cancellation_date "
                                        f"from {current_cancellation_date} to {canceled_date} "
                                        f"for member {member.name}"
                                    )
                        else:
                            member_result["error"] = "No submitted membership found"

                except Exception as member_error:
                    member_result["error"] = str(member_error)
                    frappe.log_error(
                        f"Error processing member {member.name} for Mollie sync: {str(member_error)}"
                    )

                result["members"].append(member_result)

            # Summary logging
            if dry_run:
                frappe.logger().info(
                    f"Mollie sync DRY RUN complete: {result['total_checked']} members checked, "
                    f"{result['updates_needed']} would be updated"
                )
            else:
                frappe.logger().info(
                    f"Mollie sync complete: {result['total_checked']} members checked, "
                    f"{result['updates_applied']} updated"
                )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Mollie membership end date sync error: {str(e)}")

        return result

    def bulk_retrieve_all_member_payments(
        self, days_back: int = 30, max_payments: int = 5000, payment_status_filter: str = None
    ):
        """
        Bulk retrieve payments for all members with Mollie customer IDs.

        Uses global payments endpoint with pagination for optimal performance.
        Makes 1 API call per 250 payments instead of 1 per member (N+1 problem).

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
        }

        try:
            # Find all active members with Mollie customer IDs
            members = frappe.get_all(
                "Member",
                filters={"mollie_customer_id": ["!=", ""], "status": "Active"},
                fields=["name", "full_name", "mollie_customer_id", "email"],
            )

            result["total_members"] = len(members)

            # Build customer ID lookup map for fast filtering
            customer_id_to_member = {m.mollie_customer_id: m for m in members}

            frappe.logger().info(
                f"Bulk payment retrieval: Found {len(members)} active members with Mollie IDs. "
                f"Using global payments endpoint with pagination."
            )

            # Calculate date range
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days_back)
            start_date_str = start_date.strftime("%Y-%m-%d")

            # Get raw Mollie client
            client = self.mollie_client.sdk_client

            # Initialize member results dict
            member_results = {}
            for member in members:
                member_results[member.mollie_customer_id] = {
                    "member": member.name,
                    "full_name": member.full_name,
                    "customer_id": member.mollie_customer_id,
                    "payments": [],
                    "payment_count": 0,
                    "unprocessed_count": 0,
                    "error": None,
                }

            # Fetch ALL payments using global endpoint with pagination
            has_next = True
            from_id = None
            limit = 250
            total_fetched = 0

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

                    frappe.logger().info(
                        f"Fetched batch of {len(batch_payments)} payments (API call #{result['api_calls_made']})"
                    )

                    # Process each payment
                    for payment in batch_payments:
                        total_fetched += 1

                        # Extract customer ID
                        customer_id = getattr(payment, "customer_id", None)

                        # Skip if payment doesn't belong to any of our members
                        if not customer_id or customer_id not in customer_id_to_member:
                            continue

                        # Parse payment date
                        if hasattr(payment, "created_at") and payment.created_at:
                            payment_date_str = payment.created_at[:10]  # YYYY-MM-DD

                            # Skip if outside date range
                            if payment_date_str < start_date_str:
                                continue

                            # Filter by status if specified
                            if payment_status_filter and payment_status_filter != "all":
                                if payment.status != payment_status_filter:
                                    continue

                            # Check if already processed
                            payment_entry_exists = frappe.db.exists(
                                "Payment Entry", {"reference_no": payment.id, "docstatus": ["in", [0, 1]]}
                            )

                            bank_transaction_exists = frappe.db.exists(
                                "Bank Transaction", {"mollie_payment_id": payment.id}
                            )

                            is_processed = bool(payment_entry_exists or bank_transaction_exists)

                            # Build payment info
                            payment_info = {
                                "payment_id": payment.id,
                                "status": payment.status,
                                "amount": (
                                    f"{payment.amount['value']} {payment.amount['currency']}"
                                    if payment.amount
                                    else "Unknown"
                                ),
                                "description": getattr(payment, "description", ""),
                                "created_at": str(payment.created_at),
                                "paid_at": (
                                    str(getattr(payment, "paid_at", None))
                                    if getattr(payment, "paid_at", None)
                                    else None
                                ),
                                "is_processed": is_processed,
                                "payment_entry": payment_entry_exists if is_processed else None,
                                "bank_transaction": bank_transaction_exists if is_processed else None,
                            }

                            # Add to member's payment list
                            member_result = member_results[customer_id]
                            member_result["payments"].append(payment_info)
                            member_result["payment_count"] += 1
                            result["total_payments"] += 1

                            if not is_processed:
                                member_result["unprocessed_count"] += 1
                                result["unprocessed_payments"] += 1

                    # Check pagination
                    has_next = len(batch_payments) == limit
                    if has_next and batch_payments:
                        from_id = batch_payments[-1].id
                    else:
                        has_next = False

                except Exception as batch_error:
                    frappe.log_error(f"Error fetching payment batch: {str(batch_error)}")
                    break

            # Convert member_results dict to list
            for customer_id, member_result in member_results.items():
                if member_result["payment_count"] > 0 or member_result["error"]:
                    result["members"].append(member_result)
                    result["members_checked"] += 1

            frappe.logger().info(
                f"Bulk retrieval complete: {result['api_calls_made']} API calls made, "
                f"{total_fetched} total payments fetched, {result['total_payments']} matched to members, "
                f"{result['unprocessed_payments']} unprocessed"
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Bulk payment retrieval error: {str(e)}")

        return result

    def bulk_process_member_payments(
        self, payment_ids: list, docstatus: int = 0, create_bank_transactions: bool = True
    ):
        """
        Bulk process selected payments to create Payment Entries and/or Bank Transactions.

        Args:
            payment_ids: List of Mollie payment IDs to process
            docstatus: 0 for Draft, 1 for Submitted (default: 0)
            create_bank_transactions: Whether to create Bank Transactions (default: True)

        Returns:
            Dict with processing results
        """
        result = {
            "total_requested": len(payment_ids),
            "processed": 0,
            "skipped": 0,
            "errors": 0,
            "results": [],
            "timestamp": frappe.utils.now(),
            "docstatus": docstatus,
            "create_bank_transactions": create_bank_transactions,
        }

        try:
            from verenigingen.integrations.mollie.services.dues_payment_processor import DuesPaymentProcessor

            dues_processor = DuesPaymentProcessor()

            for payment_id in payment_ids:
                # Wrap each payment in explicit transaction for atomic operations
                try:
                    frappe.db.begin()  # Start transaction

                    # Process the payment
                    payment_result = dues_processor.process_dues_payment(payment_id)

                    # If successful and docstatus is specified, update the documents
                    if payment_result.get("status") == "success":
                        if docstatus == 1 and payment_result.get("payment_entry"):
                            # Submit the payment entry with proper permission check
                            try:
                                pe_doc = frappe.get_doc("Payment Entry", payment_result["payment_entry"])
                                if pe_doc.docstatus == 0:
                                    # Verify user has submit permission
                                    if not frappe.has_permission("Payment Entry", "submit", pe_doc):
                                        raise frappe.PermissionError(
                                            f"User {frappe.session.user} does not have permission "
                                            f"to submit Payment Entry {pe_doc.name}"
                                        )
                                    pe_doc.submit()
                                    payment_result["payment_entry_submitted"] = True
                            except Exception as submit_error:
                                payment_result["submit_error"] = str(submit_error)
                                frappe.db.rollback()  # Rollback on submission error
                                result["errors"] += 1
                                result["results"].append(payment_result)
                                continue

                        frappe.db.commit()  # Commit successful transaction
                        result["processed"] += 1
                    elif payment_result.get("status") in ["skipped", "already_processed"]:
                        frappe.db.rollback()  # No changes made, rollback
                        result["skipped"] += 1
                    else:
                        frappe.db.rollback()  # Failed processing, rollback
                        result["errors"] += 1

                    result["results"].append(payment_result)

                except Exception as e:
                    frappe.db.rollback()  # Ensure rollback on exception
                    result["errors"] += 1
                    result["results"].append({"payment_id": payment_id, "status": "error", "error": str(e)})
                    frappe.log_error(f"Error processing payment {payment_id}: {e}")

            frappe.logger().info(
                f"Bulk processing complete: {result['processed']} processed, "
                f"{result['skipped']} skipped, {result['errors']} errors"
            )

        except Exception as e:
            result["error"] = str(e)
            frappe.log_error(f"Bulk processing error: {e}")

        return result
