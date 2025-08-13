"""
Payment Gateway Abstraction Layer
Provides a unified interface for different payment methods (Mollie, SEPA, etc.)
"""

from abc import ABC, abstractmethod

import frappe
from frappe import _
from frappe.utils import getdate


class PaymentGateway(ABC):
    """Abstract base class for payment gateways"""

    @abstractmethod
    def process_payment(self, donation, form_data):
        """Process payment for a donation"""

    @abstractmethod
    def handle_webhook(self, payload):
        """Handle payment gateway webhook"""

    @abstractmethod
    def get_payment_status(self, payment_id):
        """Get payment status from gateway"""


class BankTransferGateway(PaymentGateway):
    """Handler for bank transfer payments"""

    def process_payment(self, donation, form_data):
        """Generate bank transfer instructions"""
        settings = frappe.get_single("Verenigingen Settings")
        company = frappe.get_doc("Company", settings.donation_company)

        # Generate unique payment reference
        payment_reference = f"DON-{donation.name}-{donation.creation.strftime('%Y%m%d')}"

        # Update donation with payment reference
        donation.db_set("payment_id", payment_reference)

        return {
            "status": "awaiting_transfer",
            "payment_reference": payment_reference,
            "bank_details": {
                "account_holder": company.company_name,
                "iban": getattr(settings, "company_iban", ""),
                "bic": getattr(settings, "company_bic", ""),
                "reference": payment_reference,
                "amount": donation.amount,
            },
            "instructions": _("Please transfer the exact amount and include the reference number"),
            "expected_days": 1,
        }

    def handle_webhook(self, payload):
        """Bank transfers don't have webhooks - manual reconciliation"""
        return {"status": "not_applicable"}

    def get_payment_status(self, payment_id):
        """Check if bank transfer has been received"""
        # This would typically integrate with bank API or manual reconciliation
        return {"status": "pending", "message": "Manual verification required"}


class MollieGateway(PaymentGateway):
    """
    Complete Mollie payment gateway implementation

    Provides full Mollie payment processing functionality including:
    - Payment creation with Mollie API
    - Real-time payment status checking
    - Webhook handling for payment updates
    - Multi-currency and multi-configuration support
    - Error handling and recovery

    This implementation matches the functionality from the Frappe Payments PR
    while integrating with the verenigingen payment gateway architecture.
    """

    def __init__(self, gateway_name="Default"):
        """
        Initialize Mollie gateway with configuration

        Args:
            gateway_name (str): Name of Mollie Settings configuration to use
        """
        self.gateway_name = gateway_name
        self.settings = self._get_mollie_settings()
        self.client = self._get_mollie_client()

    def process_payment(self, donation, form_data):
        """
        Create Mollie payment and return checkout information

        Args:
            donation: Donation document to process payment for
            form_data (dict): Form data containing payment details

        Returns:
            dict: Payment processing result with status and redirect information
        """
        try:
            # Validate currency support
            currency = getattr(donation, "currency", "EUR")
            self.settings.validate_transaction_currency(currency)

            # Prepare payment data
            payment_data = {
                "amount": {"currency": currency, "value": f"{float(donation.amount):.2f}"},
                "description": f"Donation {donation.name}",
                "redirectUrl": self._get_redirect_url(donation),
                "webhookUrl": self.settings.get_webhook_url(),
                "metadata": {
                    "donation_id": donation.name,
                    "reference_doctype": donation.doctype,
                    "reference_docname": donation.name,
                },
            }

            # Add billing address if email available
            email = self._get_email_from_form_or_doc(donation, form_data)
            if email:
                payment_data["billingAddress"] = {"email": email}

            # Create payment with Mollie
            payment = self.client.payments.create(payment_data)

            # Update donation with payment details
            donation.db_set("payment_id", payment.id)
            if hasattr(donation, "payment_status"):
                donation.db_set("payment_status", "Open")

            # Log payment creation
            frappe.logger().info(f"Created Mollie payment {payment.id} for donation {donation.name}")

            return {
                "status": "redirect_required",
                "payment_url": payment.checkout_url,
                "payment_id": payment.id,
                "expires_at": payment.expires_at.isoformat() if payment.expires_at else None,
                "message": _("Redirecting to Mollie for payment..."),
            }

        except Exception as e:
            frappe.log_error(
                f"Mollie payment creation failed for {donation.name}: {str(e)}", "Mollie Payment Error"
            )
            return {
                "status": "error",
                "message": _("Payment setup failed. Please try again or contact support."),
            }

    def handle_webhook(self, payload):
        """
        Handle Mollie webhook notifications for payment status updates

        Args:
            payload (dict): Webhook payload from Mollie

        Returns:
            dict: Processing result
        """
        try:
            payment_id = payload.get("id")
            if not payment_id:
                return {"status": "ignored", "reason": "No payment ID in payload"}

            # Get payment from Mollie
            payment = self.client.payments.get(payment_id)

            # Find the related document
            reference_doctype = payment.metadata.get("reference_doctype")
            reference_docname = payment.metadata.get("reference_docname")

            if not (reference_doctype and reference_docname):
                return {"status": "ignored", "reason": "No reference document in metadata"}

            # Update document based on payment status
            doc = frappe.get_doc(reference_doctype, reference_docname)

            if payment.is_paid():
                # Payment successful
                doc.db_set("paid", 1)
                if hasattr(doc, "payment_status"):
                    doc.db_set("payment_status", "Completed")

                # Create payment entry if method exists
                if hasattr(doc, "create_payment_entry"):
                    doc.create_payment_entry()

                # Call custom payment completion hook if exists
                if hasattr(doc, "on_payment_authorized"):
                    doc.on_payment_authorized("Completed")

                frappe.logger().info(f"Payment {payment_id} completed for {reference_docname}")
                return {"status": "processed", "payment_status": "completed"}

            elif payment.is_canceled() or payment.is_expired() or payment.is_failed():
                # Payment failed/cancelled
                if hasattr(doc, "payment_status"):
                    doc.db_set("payment_status", "Cancelled")

                frappe.logger().info(f"Payment {payment_id} failed/cancelled for {reference_docname}")
                return {"status": "processed", "payment_status": "failed"}

            else:
                # Payment still pending
                if hasattr(doc, "payment_status"):
                    doc.db_set("payment_status", "Pending")

                return {"status": "processed", "payment_status": "pending"}

        except Exception as e:
            frappe.log_error(f"Mollie webhook processing failed: {str(e)}", "Mollie Webhook Error")
            return {"status": "error", "message": str(e)}

    def get_payment_status(self, payment_id):
        """
        Get current payment status from Mollie API

        Args:
            payment_id (str): Mollie payment ID

        Returns:
            dict: Payment status information
        """
        try:
            payment = self.client.payments.get(payment_id)

            if payment.is_paid():
                return {
                    "status": "Completed",
                    "payment_url": None,
                    "message": "Payment completed successfully",
                }
            elif payment.is_pending():
                return {
                    "status": "Pending",
                    "payment_url": payment.checkout_url,
                    "message": "Payment is being processed",
                }
            elif payment.is_open():
                return {
                    "status": "Open",
                    "payment_url": payment.checkout_url,
                    "message": "Payment is waiting for completion",
                }
            else:
                return {
                    "status": "Cancelled",
                    "payment_url": None,
                    "message": "Payment was cancelled or expired",
                }

        except Exception as e:
            frappe.log_error(
                f"Error checking Mollie payment status {payment_id}: {str(e)}", "Mollie Status Check"
            )
            return {"status": "Error", "message": f"Could not check payment status: {str(e)}"}

    def create_new_payment_for_cancelled(self, donation, form_data):
        """
        Create new payment if previous one was cancelled/expired

        Args:
            donation: Donation document
            form_data (dict): Form data

        Returns:
            dict: New payment result
        """
        try:
            # Clear old payment ID
            donation.db_set("payment_id", "")
            if hasattr(donation, "payment_status"):
                donation.db_set("payment_status", "")

            # Create new payment
            return self.process_payment(donation, form_data)

        except Exception as e:
            frappe.log_error(f"Error creating new Mollie payment: {str(e)}", "Mollie Payment Recreation")
            return {"status": "error", "message": _("Could not create new payment. Please try again.")}

    def _get_mollie_settings(self):
        """Get Mollie settings configuration"""
        try:
            from verenigingen.verenigingen_payments.doctype.mollie_settings.mollie_settings import (
                get_mollie_settings,
            )

            return get_mollie_settings(self.gateway_name)
        except Exception as e:
            frappe.throw(_("Mollie gateway '{0}' not configured: {1}").format(self.gateway_name, str(e)))

    def _get_mollie_client(self):
        """Get configured Mollie API client"""
        return self.settings.get_mollie_client()

    def _get_redirect_url(self, donation):
        """Get redirect URL after payment"""
        return self.settings.get_redirect_url(donation.doctype, donation.name)

    def _get_email_from_form_or_doc(self, donation, form_data):
        """Extract email from form data or document"""
        # Try form data first
        email = form_data.get("donor_email") or form_data.get("email")

        # Fall back to document fields
        if not email:
            for field in ["donor_email", "email", "contact_email"]:
                if hasattr(donation, field):
                    email = getattr(donation, field)
                    if email:
                        break

        return email

    def create_subscription(self, member, subscription_data):
        """
        Create Mollie subscription for recurring membership dues

        Args:
            member: Member document
            subscription_data (dict): Subscription configuration

        Returns:
            dict: Subscription creation result
        """
        try:
            if not self.settings.enable_subscriptions:
                return {
                    "status": "error",
                    "message": _("Subscriptions are not enabled for this Mollie gateway"),
                }

            # Prepare customer data
            customer_data = {
                "name": f"{member.first_name} {member.last_name}".strip(),
                "email": member.email,
                "metadata": {
                    "member_id": member.name,
                    "member_number": getattr(member, "member_id", ""),
                    "reference_doctype": "Member",
                    "reference_docname": member.name,
                },
            }

            # Prepare subscription data
            interval_mapping = {
                "1 month": "1 month",
                "3 months": "3 months",
                "6 months": "6 months",
                "1 year": "1 year",
            }

            mollie_subscription_data = {
                "amount": {
                    "currency": subscription_data.get("currency", "EUR"),
                    "value": f"{float(subscription_data['amount']):.2f}",
                },
                "interval": interval_mapping.get(subscription_data.get("interval", "1 month"), "1 month"),
                "description": subscription_data.get(
                    "description", f"Membership dues for {member.first_name} {member.last_name}"
                ),
                "webhookUrl": self.settings.get_subscription_webhook_url(),
                "metadata": {
                    "member_id": member.name,
                    "subscription_type": "membership_dues",
                    "reference_doctype": "Member",
                    "reference_docname": member.name,
                },
            }

            # Add start date if provided
            if subscription_data.get("start_date"):
                mollie_subscription_data["startDate"] = subscription_data["start_date"]

            # Create subscription via Mollie Settings
            result = self.settings.create_subscription(customer_data, mollie_subscription_data)

            # Update member with subscription details
            member.db_set("mollie_customer_id", result["customer_id"])
            member.db_set("mollie_subscription_id", result["subscription_id"])
            member.db_set("subscription_status", result["status"])
            member.db_set("next_payment_date", result.get("next_payment_date"))

            frappe.logger().info(
                f"Created Mollie subscription {result['subscription_id']} for member {member.name}"
            )

            return {
                "status": "success",
                "customer_id": result["customer_id"],
                "subscription_id": result["subscription_id"],
                "subscription_status": result["status"],
                "next_payment_date": result.get("next_payment_date"),
                "message": _("Subscription created successfully"),
            }

        except Exception as e:
            frappe.log_error(
                f"Mollie subscription creation failed for {member.name}: {str(e)}",
                "Mollie Subscription Error",
            )
            return {
                "status": "error",
                "message": _("Subscription creation failed. Please try again or contact support."),
            }

    def get_subscription_status(self, customer_id, subscription_id):
        """
        Get current subscription status from Mollie

        Args:
            customer_id (str): Mollie customer ID
            subscription_id (str): Mollie subscription ID

        Returns:
            dict: Subscription status information
        """
        try:
            subscription = self.settings.get_subscription(customer_id, subscription_id)

            if subscription:
                return {
                    "status": "success",
                    "subscription": subscription,
                    "message": _("Subscription status retrieved successfully"),
                }
            else:
                return {"status": "error", "message": _("Could not retrieve subscription status")}

        except Exception as e:
            frappe.log_error(
                f"Error getting Mollie subscription status: {str(e)}", "Mollie Subscription Status"
            )
            return {"status": "error", "message": f"Error retrieving subscription status: {str(e)}"}

    def cancel_subscription(self, member):
        """
        Cancel Mollie subscription for member

        Args:
            member: Member document with subscription details

        Returns:
            dict: Cancellation result
        """
        try:
            customer_id = getattr(member, "mollie_customer_id", None)
            subscription_id = getattr(member, "mollie_subscription_id", None)

            if not (customer_id and subscription_id):
                return {"status": "error", "message": _("No active subscription found for this member")}

            success = self.settings.cancel_subscription(customer_id, subscription_id)

            if success:
                # Update member subscription status
                member.db_set("subscription_status", "cancelled")
                member.db_set("subscription_cancelled_date", frappe.utils.today())

                return {"status": "success", "message": _("Subscription cancelled successfully")}
            else:
                return {"status": "error", "message": _("Failed to cancel subscription")}

        except Exception as e:
            frappe.log_error(
                f"Error cancelling Mollie subscription for {member.name}: {str(e)}",
                "Mollie Subscription Cancel",
            )
            return {"status": "error", "message": f"Error cancelling subscription: {str(e)}"}


class SEPAGateway(PaymentGateway):
    """Handler for SEPA Direct Debit"""

    def process_payment(self, donation, form_data):
        """Set up SEPA direct debit mandate"""
        iban = form_data.get("donor_iban", "").replace(" ", "").upper()

        if not iban:
            return {"status": "error", "message": "IBAN is required for SEPA payments"}

        # Validate IBAN format with comprehensive validation
        from verenigingen.utils.validation.iban_validator import validate_iban

        validation_result = validate_iban(iban)
        if not validation_result["valid"]:
            return {"status": "error", "message": validation_result["message"]}

        # Create or update SEPA mandate
        mandate = self._create_sepa_mandate(donation, iban, form_data)

        if mandate:
            # Update donation with SEPA details
            donation.db_set("sepa_mandate", mandate.name)
            donation.db_set("payment_method", "SEPA Direct Debit")

            return {
                "status": "mandate_created",
                "mandate_id": mandate.name,
                "collection_date": self._calculate_collection_date(donation),
                "message": _("SEPA mandate created successfully"),
            }
        else:
            return {"status": "error", "message": "Failed to create SEPA mandate"}

    def handle_webhook(self, payload):
        """SEPA doesn't use webhooks - batch processing"""
        return {"status": "not_applicable"}

    def get_payment_status(self, payment_id):
        """Check SEPA collection status"""
        # This would check with bank or SEPA processing system
        return {"status": "pending", "message": "SEPA collection pending"}

    def _validate_iban(self, iban):
        """Comprehensive IBAN validation with mod-97 checksum"""
        from verenigingen.utils.validation.iban_validator import validate_iban

        result = validate_iban(iban)
        return result["valid"]

    def _create_sepa_mandate(self, donation, iban, form_data):
        """Create SEPA mandate record"""
        try:
            # Get donor information
            donor = frappe.get_doc("Donor", donation.donor)

            # Validate and format IBAN
            from verenigingen.utils.validation.iban_validator import derive_bic_from_iban, validate_iban

            validation_result = validate_iban(iban)
            formatted_iban = validation_result.get("formatted", iban) if validation_result["valid"] else iban
            bic = derive_bic_from_iban(iban)

            # Create mandate
            mandate = frappe.new_doc("SEPA Mandate")
            mandate.update(
                {
                    "customer": getattr(donor, "customer", None),
                    "iban": formatted_iban,
                    "bic": bic,
                    "account_holder_name": form_data.get("donor_name", donor.donor_name),
                    "mandate_type": "RCUR" if donation.donation_status == "Recurring" else "OOFF",
                    "status": "Active",
                    "mandate_reference": "MAND-{donation.name}",
                    "signature_date": getdate(),
                    "reference_doctype": "Donation",
                    "reference_name": donation.name,
                }
            )

            mandate.insert(ignore_permissions=True)
            return mandate

        except Exception as e:
            frappe.log_error(f"SEPA mandate creation failed: {str(e)}", "SEPA Gateway Error")
            return None

    def _calculate_collection_date(self, donation):
        """Calculate SEPA collection date (usually T+2 for first collection)"""
        return frappe.utils.add_to_date(getdate(), days=2)


class CashGateway(PaymentGateway):
    """Handler for cash payments"""

    def process_payment(self, donation, form_data):
        """Handle cash payment registration"""
        settings = frappe.get_single("Verenigingen Settings")

        return {
            "status": "cash_pending",
            "reference": "CASH-{donation.name}",
            "instructions": _("Please bring cash to our office or pay at events"),
            "contact_email": getattr(settings, "member_contact_email", ""),
            "office_hours": _("Monday-Friday 9:00-17:00"),
        }

    def handle_webhook(self, payload):
        """Cash payments don't have webhooks"""
        return {"status": "not_applicable"}

    def get_payment_status(self, payment_id):
        """Cash payments are manually verified"""
        return {"status": "pending", "message": "Manual verification required"}


class PaymentGatewayFactory:
    """Factory class to get appropriate payment gateway"""

    _gateways = {
        "Bank Transfer": BankTransferGateway,
        "Mollie": MollieGateway,
        "SEPA Direct Debit": SEPAGateway,
        "Cash": CashGateway,
    }

    @classmethod
    def get_gateway(cls, payment_method, gateway_name="Default"):
        """
        Get payment gateway instance for given method

        Args:
            payment_method (str): Payment method name
            gateway_name (str): Gateway configuration name (for Mollie)

        Returns:
            PaymentGateway: Configured gateway instance
        """
        gateway_class = cls._gateways.get(payment_method)
        if gateway_class:
            # For Mollie, pass the gateway_name parameter
            if payment_method == "Mollie":
                return gateway_class(gateway_name)
            else:
                return gateway_class()
        else:
            raise ValueError(f"Unsupported payment method: {payment_method}")

    @classmethod
    def get_supported_methods(cls):
        """Get list of supported payment methods"""
        return list(cls._gateways.keys())


# Webhook endpoints
@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Handle Mollie webhook notifications"""
    try:
        payload = frappe.request.get_data(as_text=True)
        data = frappe.parse_json(payload) if payload else {}

        gateway = PaymentGatewayFactory.get_gateway("Mollie")
        result = gateway.handle_webhook(data)

        return {"status": "success", "result": result}

    except Exception as e:
        frappe.log_error(f"Mollie webhook error: {str(e)}", "Payment Gateway Webhook")
        return {"status": "error", "message": str(e)}


@frappe.whitelist(allow_guest=True)
def mollie_subscription_webhook():
    """
    Handle Mollie subscription webhook notifications

    Processes subscription payments by:
    1. Finding the member with the subscription
    2. Processing any new payments (creating Payment Entry for unpaid invoices)
    3. Updating member subscription status
    """
    try:
        payload = frappe.request.get_data(as_text=True)
        data = frappe.parse_json(payload) if payload else {}

        # Extract subscription information
        subscription_id = data.get("id")
        if not subscription_id:
            return {"status": "ignored", "reason": "No subscription ID in payload"}

        # Check if this is a payment notification
        payment_id = data.get("payment", {}).get("id") if data.get("payment") else None

        # Find member with this subscription
        members = frappe.get_all(
            "Member",
            filters={"mollie_subscription_id": subscription_id},
            fields=["name", "mollie_customer_id", "customer"],
        )

        if not members:
            frappe.log_error(
                f"No member found for subscription {subscription_id}", "Mollie Subscription Webhook"
            )
            return {"status": "ignored", "reason": "No member found for subscription"}

        member_name = members[0]["name"]
        customer_id = members[0]["mollie_customer_id"]
        member_customer = members[0]["customer"]

        result = {
            "status": "processed",
            "member": member_name,
            "subscription_id": subscription_id,
            "actions": [],
        }

        # Get subscription status from Mollie
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Process payment if this webhook includes a payment
        if payment_id:
            try:
                payment_result = _process_subscription_payment(
                    gateway, member_name, member_customer, payment_id, subscription_id
                )
                result["payment_processed"] = payment_result
                result["actions"].append("payment_processed")

                frappe.logger().info(f"Processed subscription payment {payment_id} for member {member_name}")
            except Exception as e:
                frappe.log_error(
                    f"Failed to process subscription payment {payment_id} for member {member_name}: {str(e)}",
                    "Mollie Subscription Payment Processing",
                )
                result["payment_error"] = str(e)

        # Update subscription status
        status_result = gateway.get_subscription_status(customer_id, subscription_id)

        if status_result["status"] == "success":
            subscription = status_result["subscription"]

            # Update member subscription status
            member = frappe.get_doc("Member", member_name)
            member.db_set("subscription_status", subscription["status"])

            if subscription.get("next_payment_date"):
                member.db_set("next_payment_date", subscription["next_payment_date"])

            if subscription["status"] == "canceled" and subscription.get("canceled_at"):
                member.db_set("subscription_cancelled_date", subscription["canceled_at"])

            result["subscription_status"] = subscription["status"]
            result["actions"].append("status_updated")

            frappe.logger().info(
                f"Updated subscription status for member {member_name}: {subscription['status']}"
            )

        else:
            frappe.log_error(
                f"Failed to get subscription status: {status_result['message']}",
                "Mollie Subscription Webhook",
            )
            result["subscription_error"] = status_result["message"]

        return result

    except Exception as e:
        frappe.log_error(f"Mollie subscription webhook error: {str(e)}", "Mollie Subscription Webhook")
        return {"status": "error", "message": str(e)}


def _process_subscription_payment(gateway, member_name, member_customer, payment_id, subscription_id):
    """
    Process a subscription payment by creating Payment Entry for unpaid invoices

    Args:
        gateway: MollieGateway instance
        member_name (str): Member document name
        member_customer (str): Customer name linked to member
        payment_id (str): Mollie payment ID
        subscription_id (str): Mollie subscription ID

    Returns:
        dict: Payment processing result
    """
    try:
        # Get payment details from Mollie
        payment = gateway.client.payments.get(payment_id)

        if not payment.is_paid():
            return {
                "status": "ignored",
                "reason": f"Payment {payment_id} is not paid (status: {payment.status})",
            }

        # Find the most recent unpaid Sales Invoice for this member
        unpaid_invoices = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": member_customer,
                "docstatus": 1,
                "status": ["in", ["Unpaid", "Overdue", "Partly Paid"]],
            },
            fields=["name", "grand_total", "currency", "posting_date"],
            order_by="posting_date desc",
            limit=1,
        )

        if not unpaid_invoices:
            frappe.logger().warning(
                f"No unpaid invoices found for member {member_name} (customer: {member_customer}) "
                f"when processing subscription payment {payment_id}"
            )
            return {"status": "no_invoice", "reason": "No unpaid invoices found for this member"}

        invoice = unpaid_invoices[0]

        # Verify payment amount matches invoice (with some tolerance for currency precision)
        payment_amount = float(payment.amount["value"])
        invoice_amount = float(invoice["grand_total"])

        if abs(payment_amount - invoice_amount) > 0.01:  # 1 cent tolerance
            frappe.logger().warning(
                f"Payment amount mismatch: Mollie payment {payment_id} is {payment_amount} "
                f"but invoice {invoice['name']} is {invoice_amount}"
            )
            # Continue anyway - partial payments are handled by ERPNext

        # Create Payment Entry to mark invoice as paid
        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = member_customer
        payment_entry.posting_date = frappe.utils.today()
        payment_entry.paid_amount = payment_amount
        payment_entry.received_amount = payment_amount
        payment_entry.reference_no = payment_id
        payment_entry.reference_date = frappe.utils.today()
        payment_entry.mode_of_payment = "Mollie"

        # Set currency
        payment_entry.paid_from_account_currency = invoice["currency"]
        payment_entry.paid_to_account_currency = invoice["currency"]

        # Get default accounts (this should be configured in Mollie Settings or Company)
        company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value(
            "Global Defaults", "default_company"
        )

        # Get appropriate accounts for Mollie payments
        paid_to_account = frappe.db.get_value("Company", company, "default_cash_account")
        if not paid_to_account:
            # Fallback to first cash account
            paid_to_account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
            )

        if not paid_to_account:
            frappe.throw(
                f"No cash account found for company {company}. Please configure Mollie payment accounts."
            )

        payment_entry.paid_to = paid_to_account

        # Link to the invoice
        payment_entry.append(
            "references",
            {
                "reference_doctype": "Sales Invoice",
                "reference_name": invoice["name"],
                "allocated_amount": min(payment_amount, invoice_amount),
            },
        )

        # Add notes about subscription payment
        payment_entry.remarks = (
            f"Automatic payment via Mollie subscription {subscription_id}. Payment ID: {payment_id}"
        )

        # Set accounts - ERPNext will auto-populate based on party
        payment_entry.set_missing_values()

        # Submit the payment entry
        payment_entry.insert()
        payment_entry.submit()

        frappe.logger().info(
            f"Created Payment Entry {payment_entry.name} for Mollie subscription payment {payment_id} "
            f"against invoice {invoice['name']} for member {member_name}"
        )

        return {
            "status": "success",
            "payment_entry": payment_entry.name,
            "invoice": invoice["name"],
            "amount": payment_amount,
            "payment_id": payment_id,
        }

    except Exception as e:
        frappe.log_error(
            f"Error processing subscription payment {payment_id} for member {member_name}: {str(e)}",
            "Mollie Subscription Payment Processing",
        )
        raise e


@frappe.whitelist()
def process_donation_payment(donation_id, payment_method, form_data):
    """Process payment for a donation using appropriate gateway"""
    try:
        donation = frappe.get_doc("Donation", donation_id)
        gateway = PaymentGatewayFactory.get_gateway(payment_method)

        result = gateway.process_payment(donation, form_data)

        return {"success": True, "payment_result": result}

    except Exception as e:
        frappe.log_error(f"Payment processing error: {str(e)}", "Payment Gateway Processing")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_payment_status(donation_id):
    """Get payment status for a donation"""
    try:
        donation = frappe.get_doc("Donation", donation_id)

        if donation.paid:
            return {"status": "paid", "payment_date": donation.modified}

        if donation.payment_method and donation.payment_id:
            gateway = PaymentGatewayFactory.get_gateway(donation.payment_method)
            return gateway.get_payment_status(donation.payment_id)

        return {"status": "pending", "message": "Payment not yet initiated"}

    except Exception as e:
        frappe.log_error(f"Payment status check error: {str(e)}", "Payment Gateway Status")
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def create_member_subscription(member_id, amount, interval="1 month", description=None):
    """Create Mollie subscription for a member"""
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions"))

    try:
        member = frappe.get_doc("Member", member_id)

        # Prepare subscription data
        subscription_data = {
            "amount": amount,
            "interval": interval,
            "currency": "EUR",
            "description": description or f"Membership dues for {member.first_name} {member.last_name}",
        }

        # Create subscription
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        result = gateway.create_subscription(member, subscription_data)

        if result["status"] == "success":
            # Update member payment method
            member.db_set("payment_method", "Mollie")

        return result

    except Exception as e:
        frappe.log_error(
            f"Error creating subscription for member {member_id}: {str(e)}", "Member Subscription"
        )
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def cancel_member_subscription(member_id):
    """Cancel Mollie subscription for a member"""
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions"))

    try:
        member = frappe.get_doc("Member", member_id)
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        result = gateway.cancel_subscription(member)

        return result

    except Exception as e:
        frappe.log_error(
            f"Error cancelling subscription for member {member_id}: {str(e)}", "Member Subscription Cancel"
        )
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def get_member_subscription_status(member_id):
    """Get subscription status for a member"""
    try:
        member = frappe.get_doc("Member", member_id)

        customer_id = getattr(member, "mollie_customer_id", None)
        subscription_id = getattr(member, "mollie_subscription_id", None)

        if not (customer_id and subscription_id):
            return {"status": "no_subscription", "message": "No active subscription found"}

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        result = gateway.get_subscription_status(customer_id, subscription_id)

        return result

    except Exception as e:
        frappe.log_error(
            f"Error getting subscription status for member {member_id}: {str(e)}",
            "Member Subscription Status",
        )
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def manual_payment_confirmation(donation_id, payment_reference, notes=None):
    """Manually confirm payment (for bank transfers, cash, etc.)"""
    if not frappe.has_permission("Donation", "write"):
        frappe.throw(_("Insufficient permissions"))

    try:
        donation = frappe.get_doc("Donation", donation_id)
        donation.paid = 1
        donation.payment_id = payment_reference

        if notes:
            donation.add_comment("Comment", "Manual payment confirmation: {notes}")

        # Create payment entry if automation is enabled
        if hasattr(donation, "create_payment_entry"):
            donation.create_payment_entry()

        donation.save()

        return {"success": True, "message": "Payment confirmed successfully"}

    except Exception as e:
        frappe.log_error(f"Manual payment confirmation error: {str(e)}", "Payment Confirmation")
        return {"success": False, "message": str(e)}
