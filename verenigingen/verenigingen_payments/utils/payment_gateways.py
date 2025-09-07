"""
Payment Gateway Abstraction Layer
Provides a unified interface for different payment methods (Mollie, SEPA, etc.)
"""

from abc import ABC, abstractmethod

import frappe
from frappe import _
from frappe.utils import getdate

from verenigingen.utils.member_utils import validate_member_ownership
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


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
        frappe.logger().error("🏗️ MollieGateway.__init__ called")
        self.gateway_name = gateway_name

        frappe.logger().error("🏗️ Getting Mollie settings...")
        try:
            self.settings = self._get_mollie_settings()
            frappe.logger().error("✅ Mollie settings loaded successfully")
        except Exception as e:
            frappe.logger().error(f"❌ Failed to load Mollie settings: {str(e)}")
            raise e

        frappe.logger().error("🏗️ Getting Mollie client...")
        try:
            self.client = self._get_mollie_client()
            frappe.logger().error("✅ Mollie client loaded successfully")
        except Exception as e:
            frappe.logger().error(f"❌ Failed to load Mollie client: {str(e)}")
            raise e

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
            frappe.logger().info(f"🎯 MollieGateway.process_payment() started for {donation.name}")
            frappe.logger().info(f"📋 Donation object type: {type(donation)}")
            frappe.logger().info(f"📋 Donation attributes: {dir(donation)}")
            frappe.logger().info(f"📋 Form data: {form_data}")

            # Debug donation object fields
            for attr in ["amount", "currency", "name", "doctype"]:
                try:
                    value = getattr(donation, attr, "NOT_FOUND")
                    frappe.logger().info(f"📋 donation.{attr}: {value} (type: {type(value)})")
                except Exception as e:
                    frappe.logger().error(f"📋 Error accessing donation.{attr}: {e}")

            # Validate currency support - ensure we have a valid currency
            currency = getattr(donation, "currency", "EUR") or "EUR"
            frappe.logger().info(f"💴 Using currency: {currency}")
            self.settings.validate_transaction_currency(currency)
            frappe.logger().info("✅ Currency validation passed")

            # Prepare payment data with redirect URL
            frappe.logger().info("🌐 Generating redirect and webhook URLs...")
            redirect_url = self.settings.get_redirect_url(donation.doctype, donation.name)
            webhook_url = self.settings.get_webhook_url()
            frappe.logger().info(f"🔗 Redirect URL: {redirect_url}")
            frappe.logger().info(f"🪝 Webhook URL: {webhook_url}")

            # Use custom description if provided (for webhook metadata), otherwise default
            description = form_data.get("description_override", f"Donation {donation.name}")

            payment_data = {
                "amount": {"value": f"{float(donation.amount):.2f}", "currency": currency},
                "description": description,
                "redirectUrl": redirect_url,
                "webhookUrl": webhook_url,
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
                frappe.logger().info(f"📧 Added billing email: {email}")

            # Add sequenceType for subscription setup (per Mollie API requirements)
            if form_data.get("subscription_setup"):
                # For first payment in subscription flow - establishes mandate
                payment_data["sequenceType"] = "first"
                frappe.logger().info("🎯 Added sequenceType: 'first' for subscription setup")

                # Add customerId if available for recurring payments
                if form_data.get("customer_id"):
                    payment_data["customerId"] = form_data.get("customer_id")
                    frappe.logger().info(f"👤 Added customerId: {form_data.get('customer_id')}")
            elif form_data.get("recurring_payment"):
                # For subsequent payments in subscription flow
                payment_data["sequenceType"] = "recurring"
                payment_data["customerId"] = form_data.get("customer_id")  # Required for recurring
                frappe.logger().info("🔄 Added sequenceType: 'recurring' for recurring payment")

            frappe.logger().info(
                f"📋 Payment data prepared: amount={payment_data['amount']}, description='{payment_data['description']}'"
            )

            # Create payment with Mollie
            frappe.logger().info("🚀 Calling Mollie API: client.payments.create()")
            payment = self.client.payments.create(payment_data)
            frappe.logger().info("✅ Mollie API responded successfully")

            # Log payment response structure for debugging
            frappe.logger().info(f"💳 Payment ID: {payment.id}")
            frappe.logger().info(f"📊 Payment status: {payment.status}")
            frappe.logger().info(f"⏰ Expires at: {payment.expires_at}")

            # Extract checkout URL according to Mollie spec
            checkout_url = None
            if hasattr(payment, "checkout_url"):
                checkout_url = payment.checkout_url
                frappe.logger().info(f"🔗 Using payment.checkout_url: {checkout_url}")
            elif hasattr(payment, "_links") and hasattr(payment._links, "checkout"):
                checkout_url = payment._links.checkout.href
                frappe.logger().info(f"🔗 Using payment._links.checkout.href: {checkout_url}")
            else:
                frappe.logger().error("❌ No checkout URL found in Mollie response!")
                frappe.logger().error(f"❌ Payment object attributes: {dir(payment)}")
                raise Exception("No checkout URL found in Mollie payment response")

            # Update donation with payment details (only if it's a real document)
            if hasattr(donation, "db_set") and callable(donation.db_set):
                donation.db_set("payment_id", payment.id)
                if hasattr(donation, "payment_status"):
                    donation.db_set("payment_status", "Open")
                frappe.logger().info("📝 Updated donation with payment details")

            # Log payment creation
            frappe.logger().info(
                f"🎉 Successfully created Mollie payment {payment.id} for donation {donation.name}"
            )

            # Handle timezone-aware expires_at from Mollie API
            from ..utils.timezone_utils import ensure_timezone_naive, parse_mollie_datetime

            # Parse and convert timezone-aware datetime to naive for Frappe compatibility
            expires_at_aware = (
                parse_mollie_datetime(payment.expires_at)
                if isinstance(payment.expires_at, str)
                else payment.expires_at
            )
            expires_at_naive = ensure_timezone_naive(expires_at_aware)

            return {
                "status": "redirect_required",
                "payment_url": checkout_url,
                "payment_id": payment.id,
                "expires_at": (
                    expires_at_naive.isoformat() if expires_at_naive else None
                ),  # Convert to string for JSON serialization
                "message": _("Redirecting to Mollie for payment..."),
            }

        except Exception as e:
            frappe.logger().error(f"💥 Exception in MollieGateway.process_payment: {str(e)}")
            frappe.logger().error(
                f"📋 Payment data that failed: {payment_data if 'payment_data' in locals() else 'Not yet created'}"
            )

            # Enhanced error logging with full traceback
            import traceback

            full_traceback = traceback.format_exc()
            frappe.logger().error(f"🔍 Full Python traceback:\n{full_traceback}")

            # Also log donation object details for debugging
            frappe.logger().error(f"🗃️ Donation object type: {type(donation)}")
            frappe.logger().error(f"🗃️ Donation object attributes: {dir(donation)}")

            frappe.log_error(
                f"Mollie payment creation failed for {donation.name}: {str(e)}\nFull traceback: {full_traceback}",
                "Mollie Payment Error",
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

            return get_mollie_settings()
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

            # Pass consumerAccount separately for mandate creation (not part of subscription data)
            mollie_subscription_data["consumerAccount"] = (
                member.iban.replace(" ", "") if member.iban else None
            )

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
                    "mandate_type": "RCUR" if donation.status == "Recurring" else "OOFF",
                    "status": "Active",
                    "mandate_reference": "MAND-{donation.name}",
                    "signature_date": getdate(),
                    "reference_doctype": "Donation",
                    "reference_name": donation.name,
                }
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            mandate_result = secure_document_operation(
                operation="insert",
                doc=mandate,
                justification=f"Create SEPA mandate for donation {donation.name} - {mandate.mandate_type} mandate for donor {form_data.get('donor_name', donor.donor_name)}",
                required_permissions=["SEPA Mandate:create"],
            )
            if not mandate_result.success:
                frappe.log_error(
                    f"Failed to create SEPA mandate for donation {donation.name}: {'; '.join(mandate_result.errors)}",
                    "SEPA Gateway Error",
                )
                return None
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


def _activate_subscription_after_first_payment(gateway, member_name, member_customer, payment_id):
    """
    Activate subscription after first payment establishes a mandate

    Args:
        gateway: MollieGateway instance
        member_name (str): Member document name
        member_customer (str): Customer name linked to member
        payment_id (str): Mollie payment ID that was just completed

    Returns:
        dict: Subscription activation result
    """
    try:
        # Get member and check if subscription is needed
        member = frappe.get_doc("Member", member_name)

        # Skip if member already has an active subscription
        if member.mollie_subscription_id and member.subscription_status == "Active":
            return {"status": "skipped", "reason": "Member already has active subscription"}

        # Find any Membership Dues Schedule for this member to determine subscription details
        dues_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active", "auto_generate": 1},
            fields=["name", "dues_rate", "billing_frequency", "next_invoice_date"],
            order_by="creation desc",
            limit=1,
        )

        if not dues_schedules:
            return {"status": "skipped", "reason": "No active dues schedule found for subscription"}

        dues_schedule = dues_schedules[0]

        # Convert billing frequency to Mollie interval format
        frequency_map = {
            "Monthly": "1 month",
            "Quarterly": "3 months",
            "Semi-Annual": "6 months",
            "Annual": "12 months",
        }

        interval = frequency_map.get(dues_schedule["billing_frequency"], "1 month")

        # Create subscription data
        subscription_data = {
            "amount": dues_schedule["dues_rate"],
            "currency": "EUR",
            "interval": interval,
            "description": f"Membership dues for {member.first_name} {member.last_name}",
            "startDate": dues_schedule.get("next_invoice_date")
            or frappe.utils.add_months(frappe.utils.today(), 1),
        }

        # Attempt to create subscription now that mandate is established
        result = gateway.create_subscription(member, subscription_data)

        if result["status"] == "success":
            frappe.logger().info(
                f"Successfully activated subscription {result['subscription_id']} for member {member_name}"
            )

            # Update member with subscription details
            member.db_set("mollie_subscription_id", result["subscription_id"])
            member.db_set("subscription_status", "Active")
            member.db_set("next_payment_date", subscription_data["startDate"])

            return {
                "status": "success",
                "subscription_id": result["subscription_id"],
                "customer_id": result.get("customer_id"),
                "next_payment": subscription_data["startDate"],
            }
        else:
            return {
                "status": "failed",
                "reason": result.get("message", "Unknown error creating subscription"),
            }

    except Exception as e:
        frappe.log_error(
            f"Error activating subscription for member {member_name}: {str(e)}",
            "Mollie Subscription Activation",
        )
        return {"status": "error", "message": str(e)}


def retry_failed_subscription_activations():
    """
    Retry subscription activation for members who completed first payments
    but don't have active subscriptions yet

    This can be called from a scheduled job or manually to recover from
    failed subscription creations after successful payments

    Returns:
        dict: Summary of retry results
    """
    try:
        # Find members with completed Mollie payments but no active subscriptions
        # Look for Payment Entries with Mollie mode_of_payment in the last 30 days
        recent_payments = frappe.get_all(
            "Payment Entry",
            filters={
                "mode_of_payment": "Mollie",
                "docstatus": 1,
                "posting_date": [">=", frappe.utils.add_days(frappe.utils.today(), -30)],
            },
            fields=["party", "reference_no", "posting_date"],
            order_by="posting_date desc",
        )

        retry_results = {
            "total_payments_checked": len(recent_payments),
            "members_without_subscriptions": 0,
            "retry_attempts": 0,
            "successful_activations": 0,
            "failed_retries": 0,
            "details": [],
        }

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        for payment_info in recent_payments:
            customer_name = payment_info["party"]
            payment_id = payment_info["reference_no"]

            # Find member for this customer
            members = frappe.get_all(
                "Member",
                filters={"customer": customer_name},
                fields=["name", "mollie_subscription_id", "subscription_status"],
            )

            if not members:
                continue

            member = members[0]

            # Skip if member already has active subscription
            if member["mollie_subscription_id"] and member["subscription_status"] == "Active":
                continue

            retry_results["members_without_subscriptions"] += 1

            # Check if this was a first payment by querying Mollie
            try:
                mollie_payment = gateway.client.payments.get(payment_id)
                if mollie_payment.sequence_type != "first":
                    continue

                # Only retry if the payment was actually completed
                if not mollie_payment.is_paid():
                    continue

                retry_results["retry_attempts"] += 1

                # Attempt subscription activation
                activation_result = _activate_subscription_after_first_payment(
                    gateway, member["name"], customer_name, payment_id
                )

                if activation_result["status"] == "success":
                    retry_results["successful_activations"] += 1
                    retry_results["details"].append(
                        {
                            "member": member["name"],
                            "customer": customer_name,
                            "payment_id": payment_id,
                            "result": "success",
                            "subscription_id": activation_result.get("subscription_id"),
                        }
                    )
                    frappe.logger().info(
                        f"Successfully activated subscription for member {member['name']} on retry"
                    )
                else:
                    retry_results["failed_retries"] += 1
                    retry_results["details"].append(
                        {
                            "member": member["name"],
                            "customer": customer_name,
                            "payment_id": payment_id,
                            "result": "failed",
                            "reason": activation_result.get(
                                "reason", activation_result.get("message", "Unknown error")
                            ),
                        }
                    )

            except Exception as e:
                retry_results["failed_retries"] += 1
                retry_results["details"].append(
                    {
                        "member": member["name"],
                        "customer": customer_name,
                        "payment_id": payment_id,
                        "result": "error",
                        "reason": str(e),
                    }
                )
                frappe.log_error(
                    f"Error during subscription retry for member {member['name']}: {str(e)}",
                    "Mollie Subscription Retry Error",
                )

        frappe.logger().info(
            f"Subscription retry completed: {retry_results['successful_activations']} successful, {retry_results['failed_retries']} failed"
        )
        return retry_results

    except Exception as e:
        frappe.log_error(
            f"Error in subscription retry process: {str(e)}", "Mollie Subscription Retry Process"
        )
        return {"error": str(e)}


def _activate_donation_subscription_after_first_payment(gateway, payment):
    """
    Create Mollie subscription for recurring donation after first payment establishes mandate

    Args:
        gateway: MollieGateway instance
        payment: Mollie payment object from first payment

    Returns:
        dict: Subscription creation result
    """
    try:
        # Get donation and agreement info from payment metadata
        donation_id = payment.metadata.get("donation_id")
        if not donation_id:
            return {"status": "skipped", "reason": "No donation ID in payment metadata"}

        # Get donation and associated agreement
        donation = frappe.get_doc("Donation", donation_id)
        if not donation.donation_agreement:
            return {"status": "skipped", "reason": "No donation agreement found"}

        agreement = frappe.get_doc("Donation Agreement", donation.donation_agreement)

        # Get customer ID from payment
        customer_id = payment.customer_id
        if not customer_id:
            return {"status": "error", "reason": "No customer ID found in payment"}

        # Create subscription data based on agreement
        subscription_data = {
            "amount": {"currency": "EUR", "value": f"{float(agreement.amount):.2f}"},
            "interval": _convert_frequency_to_mollie_interval(agreement.recurring_frequency),
            "description": f"Recurring donation - {donation.donation_type}",
            "startDate": agreement.next_due_date.strftime("%Y-%m-%d") if agreement.next_due_date else None,
            "metadata": {
                "donation_agreement_id": agreement.name,
                "donation_id": donation_id,
                "donor_id": donation.donor,
                "donation_type": donation.donation_type,
                "purpose": donation.donation_purpose_type,
            },
        }

        # Create subscription using Mollie API directly
        customer = gateway.client.customers.get(customer_id)
        subscription = customer.subscriptions.create(data=subscription_data)

        # Update donation agreement with subscription details
        agreement.db_set("mollie_subscription_id", subscription.id)
        agreement.db_set("status", "Active")

        frappe.logger().info(
            f"Successfully created subscription {subscription.id} for donation agreement {agreement.name}"
        )

        return {
            "status": "success",
            "subscription_id": subscription.id,
            "customer_id": customer_id,
            "agreement_id": agreement.name,
            "next_payment": subscription_data.get("startDate"),
        }

    except Exception as e:
        frappe.log_error(
            f"Error creating donation subscription after first payment: {str(e)}",
            "Mollie Donation Subscription Creation",
        )
        return {"status": "error", "message": str(e)}


def _convert_frequency_to_mollie_interval(frequency):
    """Convert Donation Agreement frequency to Mollie interval format"""
    frequency_map = {
        "Monthly": "1 month",
        "Quarterly": "3 months",
        "Semi-Annual": "6 months",
        "Annual": "12 months",
        "1 month": "1 month",  # Direct mapping
        "3 months": "3 months",
        "6 months": "6 months",
        "12 months": "12 months",
    }
    return frequency_map.get(frequency, "1 month")


@frappe.whitelist()
def manual_subscription_retry():
    """
    Manual trigger for subscription activation retry
    Requires appropriate permissions
    """
    return retry_failed_subscription_activations()


# Webhook endpoints
@frappe.whitelist(allow_guest=True)
def mollie_webhook():
    """Handle Mollie webhook notifications with security verification"""

    # EXTENSIVE DEBUG LOGGING - START OF REQUEST
    print("=" * 80)
    print("🚨 MOLLIE WEBHOOK DEBUG: Request received!")
    print(f"🔍 Timestamp: {frappe.utils.now_datetime()}")
    print(f"🔍 Request Method: {frappe.request.method if hasattr(frappe, 'request') else 'Unknown'}")
    print(f"🔍 Session User: {frappe.session.user}")
    print(
        f"🔍 Request Headers: {dict(frappe.request.headers) if hasattr(frappe, 'request') and hasattr(frappe.request, 'headers') else 'No headers available'}"
    )
    print(
        f"🔍 Request Data: {frappe.request.data if hasattr(frappe, 'request') and hasattr(frappe.request, 'data') else 'No data available'}"
    )
    print(
        f"🔍 Request Form: {dict(frappe.request.form) if hasattr(frappe, 'request') and hasattr(frappe.request, 'form') else 'No form data available'}"
    )
    print(
        f"🔍 Request Args: {dict(frappe.request.args) if hasattr(frappe, 'request') and hasattr(frappe.request, 'args') else 'No args available'}"
    )
    print("=" * 80)

    # SECURITY: Verify system user permissions for webhook processing
    if frappe.session.user == "Guest":
        # For webhook calls, create system context
        frappe.set_user("Administrator")

    print(
        f"🔍 Permissions check: Payment Entry create permission = {frappe.has_permission('Payment Entry', 'create')}"
    )

    if not frappe.has_permission("Payment Entry", "create"):
        print("❌ Permission check failed!")
        frappe.throw("Insufficient permissions for payment processing")

    print("✅ Permission check passed!")

    try:
        print("🔍 Importing webhook security utilities...")
        # Import webhook security utilities
        from verenigingen.utils.webhook_security import (
            authenticate_mollie_webhook,
            log_webhook_security_event,
        )

        print("✅ Security utilities imported successfully!")

        # Authenticate webhook and get validated payload
        try:
            print("🔍 Attempting webhook authentication...")
            payload = authenticate_mollie_webhook()
            print(f"✅ Authentication successful! Payload length: {len(payload) if payload else 0}")
            print(f"🔍 Raw payload preview (first 200 chars): {repr(payload[:200]) if payload else 'Empty'}")
            log_webhook_security_event(
                "success", {"event": "donation_webhook_authenticated", "payload_length": len(payload)}
            )
        except Exception as auth_error:
            print(f"❌ Authentication failed: {str(auth_error)}")
            print(f"🔍 Traceback: {frappe.get_traceback()}")
            log_webhook_security_event(
                "failure",
                {
                    "event": "donation_authentication_failed",
                    "error": str(auth_error),
                    "headers": dict(frappe.request.headers),
                },
            )
            return {"status": "error", "message": "Webhook authentication failed", "details": str(auth_error)}

        # Enhanced logging for webhook debugging
        frappe.logger().info("🪝 Mollie webhook received and authenticated")
        frappe.logger().info(f"📊 Payload length: {len(payload) if payload else 0}")

        # Check for empty payload
        if not payload:
            return {"status": "ignored", "reason": "Empty payload received"}

        # Parse payload - handle both JSON and form-encoded data
        try:
            # First try JSON parsing
            data = frappe.parse_json(payload)
            frappe.logger().info("✅ Successfully parsed JSON payload")
        except (ValueError, TypeError) as json_error:
            frappe.logger().info(f"🔄 JSON parsing failed, trying form-encoded parsing: {str(json_error)}")

            # Check if it looks like form-encoded data (key=value format)
            if "=" in payload and not payload.strip().startswith("{"):
                try:
                    # Parse form-encoded data
                    from urllib.parse import parse_qs, unquote_plus

                    # Handle single key=value or multiple key=value&key=value
                    if "&" in payload:
                        # Multiple parameters
                        parsed_data = parse_qs(payload)
                        # Convert lists to single values for simple cases
                        data = {k: (v[0] if len(v) == 1 else v) for k, v in parsed_data.items()}
                    else:
                        # Single parameter like 'id=tr_abc123'
                        key, value = payload.split("=", 1)
                        data = {unquote_plus(key): unquote_plus(value)}

                    frappe.logger().info(f"✅ Successfully parsed form-encoded payload: {data}")

                except Exception as form_error:
                    frappe.logger().error(f"❌ Form-encoded parsing also failed: {str(form_error)}")
                    frappe.log_error(
                        f"Mollie webhook parsing failed: Neither JSON nor form-encoded\nJSON error: {str(json_error)}\nForm error: {str(form_error)}\nFull payload: {repr(payload)}",
                        "Mollie Webhook Parsing Error",
                    )
                    return {"status": "error", "message": "Invalid payload format"}
            else:
                # Check if payload looks truncated (ends with incomplete JSON)
                is_truncated = (
                    payload.endswith("{")
                    or payload.endswith(",")
                    or payload.count("{") > payload.count("}")
                    or payload.count("[") > payload.count("]")
                )

                if is_truncated:
                    frappe.logger().error("⚠️ Payload appears to be truncated - possible size limit issue")
                    error_msg = f"Webhook payload appears truncated: {str(json_error)}"
                else:
                    error_msg = f"Invalid JSON in webhook payload: {str(json_error)}"

                frappe.log_error(
                    f"Mollie webhook JSON parsing failed: {error_msg}\nFull payload: {repr(payload)}",
                    "Mollie Webhook JSON Error",
                )
                return {"status": "error", "message": "Invalid JSON payload"}

        print(f"🔍 Parsed webhook data: {data}")

        # Process webhook with gateway
        print("🔍 Getting Mollie gateway...")
        gateway = PaymentGatewayFactory.get_gateway("Mollie")
        print(f"✅ Gateway obtained: {type(gateway)}")

        print("🔍 Processing webhook with gateway...")
        result = gateway.handle_webhook(data)
        print(f"✅ Webhook processed successfully! Result: {result}")

        frappe.logger().info("✅ Webhook processed successfully")
        print("=" * 80)
        print("🎉 MOLLIE WEBHOOK DEBUG: Request completed successfully!")
        print("=" * 80)
        return {"status": "success", "result": result}

    except Exception as e:
        print("=" * 80)
        print(f"💥 MOLLIE WEBHOOK DEBUG: Exception occurred!")
        print(f"🔍 Exception type: {type(e)}")
        print(f"🔍 Exception message: {str(e)}")
        print(f"🔍 Full traceback: {frappe.get_traceback()}")
        print("=" * 80)

        frappe.logger().error(f"💥 Mollie webhook processing failed: {str(e)}")
        frappe.log_error(
            f"Mollie webhook error: {str(e)}\nPayload: {repr(payload[:1000]) if 'payload' in locals() else 'N/A'}",
            "Payment Gateway Webhook",
        )
        return {"status": "error", "message": str(e)}


@frappe.whitelist()
def mollie_subscription_webhook():
    """
    Handle Mollie subscription webhook notifications with security verification

    Processes subscription payments by:
    1. Verifying webhook signature for security
    2. Finding the member with the subscription
    3. Processing any new payments (creating Payment Entry for unpaid invoices)
    4. Updating member subscription status
    """
    try:
        # Import webhook security utilities
        from verenigingen.utils.webhook_security import (
            authenticate_mollie_webhook,
            log_webhook_security_event,
        )

        # Authenticate webhook and get validated payload
        try:
            payload = authenticate_mollie_webhook()
            log_webhook_security_event(
                "success", {"event": "webhook_authenticated", "payload_length": len(payload)}
            )
        except Exception as auth_error:
            log_webhook_security_event(
                "failure",
                {
                    "event": "authentication_failed",
                    "error": str(auth_error),
                    "headers": dict(frappe.request.headers),
                },
            )
            return {"status": "error", "message": "Webhook authentication failed", "details": str(auth_error)}

        # Enhanced logging for webhook debugging
        frappe.logger().info("🔄 Mollie subscription webhook received and authenticated")
        frappe.logger().info(f"📊 Payload length: {len(payload) if payload else 0}")

        # Parse payload - handle both JSON and form-encoded data
        try:
            # First try JSON parsing
            data = frappe.parse_json(payload)
            frappe.logger().info("✅ Successfully parsed subscription JSON payload")
        except (ValueError, TypeError) as json_error:
            frappe.logger().info(
                f"🔄 Subscription JSON parsing failed, trying form-encoded: {str(json_error)}"
            )

            # Check if it looks like form-encoded data (key=value format)
            if "=" in payload and not payload.strip().startswith("{"):
                try:
                    # Parse form-encoded data
                    from urllib.parse import parse_qs, unquote_plus

                    # Handle single key=value or multiple key=value&key=value
                    if "&" in payload:
                        # Multiple parameters
                        parsed_data = parse_qs(payload)
                        # Convert lists to single values for simple cases
                        data = {k: (v[0] if len(v) == 1 else v) for k, v in parsed_data.items()}
                    else:
                        # Single parameter like 'id=sub_abc123'
                        key, value = payload.split("=", 1)
                        data = {unquote_plus(key): unquote_plus(value)}

                    frappe.logger().info(f"✅ Successfully parsed subscription form-encoded payload: {data}")

                except Exception as form_error:
                    frappe.logger().error(
                        f"❌ Subscription form-encoded parsing also failed: {str(form_error)}"
                    )
                    frappe.log_error(
                        f"Mollie subscription webhook parsing failed: Neither JSON nor form-encoded\nJSON error: {str(json_error)}\nForm error: {str(form_error)}\nFull payload: {repr(payload)}",
                        "Mollie Subscription Webhook Parsing Error",
                    )
                    return {"status": "error", "message": "Invalid payload format"}
            else:
                # Check if payload looks truncated (ends with incomplete JSON)
                is_truncated = (
                    payload.endswith("{")
                    or payload.endswith(",")
                    or payload.count("{") > payload.count("}")
                    or payload.count("[") > payload.count("]")
                )

                if is_truncated:
                    frappe.logger().error(
                        "⚠️ Subscription payload appears to be truncated - possible size limit issue"
                    )
                    error_msg = f"Subscription webhook payload appears truncated: {str(json_error)}"
                else:
                    error_msg = f"Invalid JSON in subscription webhook payload: {str(json_error)}"

                frappe.log_error(
                    f"Mollie subscription webhook JSON parsing failed: {error_msg}\nFull payload: {repr(payload)}",
                    "Mollie Subscription Webhook JSON Error",
                )
                return {"status": "error", "message": "Invalid JSON payload"}

        # Extract subscription information
        subscription_id = data.get("id")
        if not subscription_id:
            return {"status": "ignored", "reason": "No subscription ID in payload"}

        # IDEMPOTENCY: Check if webhook already processed
        payment_id = data.get("payment", {}).get("id") if data.get("payment") else None
        if payment_id and frappe.db.exists("Payment Entry", {"reference_no": payment_id}):
            frappe.logger().info(f"Payment {payment_id} already processed, skipping webhook")
            return {"status": "already_processed", "payment_id": payment_id}

        # Find member by Customer's Mollie subscription ID (correct data location)
        customers_with_subscription = frappe.get_all(
            "Customer",
            filters={"custom_mollie_subscription_id": subscription_id},
            fields=["name", "custom_mollie_customer_id"],
        )

        if not customers_with_subscription:
            frappe.log_error(
                f"No customer found for subscription {subscription_id}", "Mollie Subscription Webhook"
            )
            return {"status": "ignored", "reason": "No customer found for subscription"}

        # Find the member linked to this customer
        customer_name = customers_with_subscription[0]["name"]
        customer_id = customers_with_subscription[0]["custom_mollie_customer_id"]

        members = frappe.get_all("Member", filters={"customer": customer_name}, fields=["name"])

        if not members:
            frappe.log_error(
                f"No member found for customer {customer_name} with subscription {subscription_id}",
                "Mollie Subscription Webhook",
            )
            return {"status": "ignored", "reason": "No member found for customer"}

        member_name = members[0]["name"]
        member_customer = customer_name

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

        # TRANSACTION SAFETY: Wrap payment processing in database transaction
        # Use proper Frappe transaction handling for MariaDB
        frappe.db.begin()
        try:
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

            # Get appropriate Bank account for Mollie electronic payments (not Cash)
            paid_to_account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
            )
            if not paid_to_account:
                # Fallback to default cash account if no bank account found
                paid_to_account = frappe.db.get_value("Company", company, "default_cash_account")
                if not paid_to_account:
                    # Final fallback to first cash account
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

            # Set accounts manually (avoid EmployeePaymentEntry issues)
            # Use the same receivable account as the invoice to avoid validation errors
            invoice_receivable_account = frappe.db.get_value("Sales Invoice", invoice["name"], "debit_to")

            if invoice_receivable_account:
                payment_entry.paid_from = invoice_receivable_account

            # Submit the payment entry
            payment_entry.insert()
            payment_entry.submit()

            frappe.logger().info(
                f"Created Payment Entry {payment_entry.name} for Mollie subscription payment {payment_id} "
                f"against invoice {invoice['name']} for member {member_name}"
            )

            # Commit transaction
            frappe.db.commit()

        except Exception:
            # Rollback on error
            frappe.db.rollback()
            raise

        # Check if this was a first payment (sequenceType: "first") and activate subscription
        subscription_activation_result = None
        try:
            if payment.sequence_type == "first":
                # Check if this is for a donation or member subscription
                if payment.metadata.get("reference_doctype") == "Donation":
                    frappe.logger().info(
                        "First payment completed for donation, attempting subscription creation"
                    )
                    subscription_activation_result = _activate_donation_subscription_after_first_payment(
                        gateway, payment
                    )
                else:
                    frappe.logger().info(
                        f"First payment completed for member {member_name}, attempting subscription activation"
                    )
                    subscription_activation_result = _activate_subscription_after_first_payment(
                        gateway, member_name, member_customer, payment_id
                    )
        except Exception as activation_error:
            frappe.log_error(
                f"Subscription activation failed for payment {payment_id}: {str(activation_error)}",
                "Mollie Subscription Activation Error",
            )
            subscription_activation_result = {"status": "error", "message": str(activation_error)}

        result = {
            "status": "success",
            "payment_entry": payment_entry.name,
            "invoice": invoice["name"],
            "amount": payment_amount,
            "payment_id": payment_id,
        }

        if subscription_activation_result:
            result["subscription_activation"] = subscription_activation_result

        return result

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
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_member_subscription(member_id):
    """Cancel Mollie subscription for a member - SECURED: users can only cancel their own subscriptions"""

    # SECURITY: Validate user can only cancel their own subscription
    validate_member_ownership(member_id, _("You can only cancel your own subscription"))

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
