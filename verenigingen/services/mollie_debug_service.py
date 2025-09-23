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
            client = self.mollie_client._get_mollie_client()
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
                        "next_payment_date": str(getattr(sub, "next_payment_date", None))
                        if getattr(sub, "next_payment_date", None)
                        else None,
                        "canceled_at": str(getattr(sub, "canceled_at", None))
                        if getattr(sub, "canceled_at", None)
                        else None,
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
                        "signature_date": str(getattr(mandate, "signature_date", None))
                        if getattr(mandate, "signature_date", None)
                        else None,
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
            client = self.mollie_client._get_mollie_client()
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
                "next_payment_date": str(getattr(subscription, "next_payment_date", None))
                if getattr(subscription, "next_payment_date", None)
                else None,
                "canceled_at": str(getattr(subscription, "canceled_at", None))
                if getattr(subscription, "canceled_at", None)
                else None,
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
            client = self.mollie_client._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
            mandate = customer_obj.mandates.get(mandate_id)

            result["mandate_found"] = True
            result["mandate_data"] = {
                "id": mandate.id,
                "status": mandate.status,
                "method": mandate.method,
                "created_at": str(mandate.created_at),
                "mandate_reference": getattr(mandate, "mandate_reference", None),
                "signature_date": str(getattr(mandate, "signature_date", None))
                if getattr(mandate, "signature_date", None)
                else None,
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
            client = self.mollie_client._get_mollie_client()
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
        """Admin function to revoke any mandate"""
        if not customer_id or not mandate_id:
            raise ValueError(_("Customer ID and Mandate ID are required"))

        if not reason:
            raise ValueError(_("Revocation reason is required"))

        try:
            # Use direct Mollie API call to avoid retry/circuit breaker issues
            client = self.mollie_client._get_mollie_client()
            customer_obj = client.customers.get(customer_id)
            revoked_mandate = customer_obj.mandates.delete(mandate_id)

            # Log admin action
            frappe.logger().info(
                f"ADMIN REVOCATION: User {frappe.session.user} revoked mandate {mandate_id} for customer {customer_id}. Reason: {reason}"
            )

            return {
                "status": "success",
                "message": _("Mandate revoked successfully"),
                "mandate_id": mandate_id,
                "customer_id": customer_id,
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
            client = self.mollie_client._get_mollie_client()
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
            client = self.mollie_client._get_mollie_client()
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
            client = self.mollie_client._get_mollie_client()
            payment = client.payments.get(payment_id)

            result["payment_found"] = True
            result["payment_data"] = {
                "id": payment.id,
                "status": payment.status,
                "amount": f"{payment.amount['value']} {payment.amount['currency']}"
                if payment.amount
                else "Unknown",
                "description": payment.description,
                "method": getattr(payment, "method", None),
                "created_at": str(payment.created_at),
                "authorized_at": str(getattr(payment, "authorized_at", None))
                if getattr(payment, "authorized_at", None)
                else None,
                "paid_at": str(getattr(payment, "paid_at", None))
                if getattr(payment, "paid_at", None)
                else None,
                "canceled_at": str(getattr(payment, "canceled_at", None))
                if getattr(payment, "canceled_at", None)
                else None,
                "expired_at": str(getattr(payment, "expired_at", None))
                if getattr(payment, "expired_at", None)
                else None,
                "failed_at": str(getattr(payment, "failed_at", None))
                if getattr(payment, "failed_at", None)
                else None,
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
                            "amount": f"{refund.amount['value']} {refund.amount['currency']}"
                            if refund.amount
                            else "Unknown",
                            "description": getattr(refund, "description", None),
                            "created_at": str(refund.created_at),
                            "settled_at": str(getattr(refund, "settled_at", None))
                            if getattr(refund, "settled_at", None)
                            else None,
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
                            "amount": f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                            if chargeback.amount
                            else "Unknown",
                            "created_at": str(chargeback.created_at),
                            "reason": getattr(chargeback, "reason", None),
                            "reversed_at": str(getattr(chargeback, "reversed_at", None))
                            if getattr(chargeback, "reversed_at", None)
                            else None,
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
            client = self.mollie_client._get_mollie_client()

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
                        "amount": f"{payment.amount['value']} {payment.amount['currency']}"
                        if payment.amount
                        else "Unknown",
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
            client = self.mollie_client._get_mollie_client()

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
                "amount": f"{refund.amount['value']} {refund.amount['currency']}"
                if refund.amount
                else "Unknown",
                "description": getattr(refund, "description", None),
                "created_at": str(refund.created_at),
                "settled_at": str(getattr(refund, "settled_at", None))
                if getattr(refund, "settled_at", None)
                else None,
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
            client = self.mollie_client._get_mollie_client()

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
                                    "amount": f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                                    if chargeback.amount
                                    else "Unknown",
                                    "created_at": str(chargeback.created_at),
                                    "reason": getattr(chargeback, "reason", None),
                                    "reversed_at": str(getattr(chargeback, "reversed_at", None))
                                    if getattr(chargeback, "reversed_at", None)
                                    else None,
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
                                "amount": f"{chargeback.amount['value']} {chargeback.amount['currency']}"
                                if chargeback.amount
                                else "Unknown",
                                "created_at": str(chargeback.created_at),
                                "reason": getattr(chargeback, "reason", None),
                                "reversed_at": str(getattr(chargeback, "reversed_at", None))
                                if getattr(chargeback, "reversed_at", None)
                                else None,
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
            client = self.mollie_client._get_mollie_client()
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
            client = self.mollie_client._get_mollie_client()

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
            client = self.mollie_client._get_mollie_client()

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
