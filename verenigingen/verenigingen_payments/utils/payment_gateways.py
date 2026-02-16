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
from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, public_api
from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.utils.validation_utilities import DocumentExistenceValidator
from verenigingen.verenigingen_payments.mollie.utils.common_helpers import (
    convert_frequency_to_mollie_interval,
    create_error_response,
    create_success_response,
    format_mollie_amount,
    format_mollie_amount_string,
    get_member_by_customer_id,
    get_member_by_subscription_id,
    get_members_by_customer,
    log_mollie_error,
)
from verenigingen.verenigingen_payments.utils.payment_data_extractor import get_payment_data_extractor


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
        payments_settings = get_payments_settings()
        company = frappe.get_doc("Company", settings.company)

        # Generate unique payment reference
        payment_reference = f"DON-{donation.name}-{donation.creation.strftime('%Y%m%d')}"

        # Update donation with payment reference
        donation.db_set("payment_id", payment_reference)

        return {
            "status": "awaiting_transfer",
            "payment_reference": payment_reference,
            "bank_details": {
                "account_holder": company.company_name,
                "iban": getattr(payments_settings, "company_iban", ""),
                "bic": getattr(payments_settings, "company_bic", ""),
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
                "amount": format_mollie_amount(donation.amount, currency),
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

                # Add subscription metadata for webhook processing
                subscription_interval = form_data.get("subscription_interval", "1 month")
                payment_data["metadata"].update(
                    {
                        "subscription_setup": "true",
                        "subscription_interval": subscription_interval,
                        "subscription_amount": format_mollie_amount_string(donation.amount),
                        "subscription_currency": currency,
                    }
                )
                frappe.logger().info(f"📋 Added subscription metadata: interval={subscription_interval}")

                # Add customerId if available for recurring payments
                if form_data.get("customer_id"):
                    payment_data["customerId"] = form_data.get("customer_id")
                    payment_data["metadata"]["customer_id"] = form_data.get("customer_id")
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
            print(f"🔍 WEBHOOK START: Processing payment_id = {payment_id}")
            if not payment_id:
                print("❌ WEBHOOK ERROR: No payment ID in payload")
                return {"status": "ignored", "reason": "No payment ID in payload"}

            # Get payment from Mollie
            print(f"🔍 MOLLIE API: Calling client.payments.get({payment_id})")
            payment = self.client.payments.get(payment_id)
            print("✅ MOLLIE API: Payment retrieved successfully")

            # Debug: Print payment data structure
            print("🔍 MOLLIE API RESPONSE:")
            print(f"   Payment ID: {payment.id}")
            print(f"   Status: {payment.status}")
            print(f"   Amount: {payment.amount}")
            print(
                f"   Currency: {getattr(payment.amount, 'currency', 'N/A') if hasattr(payment, 'amount') else 'N/A'}"
            )
            print(f"   Description: {getattr(payment, 'description', 'N/A')}")
            print(f"   Method: {getattr(payment, 'method', 'N/A')}")
            print(f"   Created: {getattr(payment, 'created_at', 'N/A')}")
            print(f"   Paid at: {getattr(payment, 'paid_at', 'N/A')}")
            print(f"   Metadata: {getattr(payment, 'metadata', 'N/A')}")
            print(f"   Checkout URL: {getattr(payment, 'checkout_url', 'N/A')}")

            # Find the related document
            metadata = getattr(payment, "metadata", {})
            reference_doctype = metadata.get("reference_doctype") if metadata else None
            reference_docname = metadata.get("reference_docname") if metadata else None

            print("🔍 METADATA EXTRACTION:")
            print(f"   reference_doctype: {reference_doctype}")
            print(f"   reference_docname: {reference_docname}")

            if not (reference_doctype and reference_docname):
                print("❌ WEBHOOK IGNORED: No reference document in metadata")
                print(f"   Expected metadata fields but got: {metadata}")
                return {"status": "ignored", "reason": "No reference document in metadata"}

            # Update document based on payment status
            doc = frappe.get_doc(reference_doctype, reference_docname)

            if payment.is_paid():
                print("✅ PAYMENT PAID: Processing payment completion")
                # Payment successful
                doc.db_set("paid", 1)
                print(f"✅ Set paid = 1 on {reference_docname}")

                if hasattr(doc, "payment_status"):
                    doc.db_set("payment_status", "Completed")
                    print(f"✅ Set payment_status = Completed on {reference_docname}")

                # Create payment entry if method exists
                if hasattr(doc, "create_payment_entry"):
                    print(f"🔍 CALLING: doc.create_payment_entry() on {reference_docname}")
                    result = doc.create_payment_entry()
                    print(f"✅ create_payment_entry() returned: {result}")
                else:
                    print(f"❌ NO create_payment_entry method on {reference_doctype}")

                # Call custom payment completion hook if exists
                if hasattr(doc, "on_payment_authorized"):
                    print(f"🔍 CALLING: doc.on_payment_authorized('Completed') on {reference_docname}")
                    doc.on_payment_authorized("Completed")
                    print("✅ on_payment_authorized() completed")
                else:
                    print(f"❌ NO on_payment_authorized method on {reference_doctype}")

                frappe.logger().info(f"Payment {payment_id} completed for {reference_docname}")
                print(f"✅ WEBHOOK SUCCESS: Payment {payment_id} completed for {reference_docname}")
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
            log_mollie_error("Webhook Processing", e)
            return create_error_response(str(e))

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
            log_mollie_error(
                "Payment Recreation",
                e,
                {"donation": donation.name if hasattr(donation, "name") else "Unknown"},
            )
            return create_error_response(_("Could not create new payment. Please try again."))

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
                "amount": format_mollie_amount(
                    subscription_data["amount"], subscription_data.get("currency", "EUR")
                ),
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
                return create_error_response(_("Could not retrieve subscription status"))

        except Exception as e:
            log_mollie_error(
                "Subscription Status Retrieval",
                e,
                {"member": member.name if hasattr(member, "name") else "Unknown"},
            )
            return create_error_response(f"Error retrieving subscription status: {str(e)}")

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
                return create_error_response(_("No active subscription found for this member"))

            success = self.settings.cancel_subscription(customer_id, subscription_id)

            if success:
                # Update member subscription status
                member.db_set("subscription_status", "cancelled")
                member.db_set("subscription_cancelled_date", frappe.utils.today())

                return create_success_response(_("Subscription cancelled successfully"))
            else:
                return create_error_response(_("Failed to cancel subscription"))

        except Exception as e:
            log_mollie_error("Subscription Cancellation", e, {"member": member.name})
            return create_error_response(f"Error cancelling subscription: {str(e)}")

    def update_subscription(self, customer_id, subscription_id, update_data):
        """
        Update Mollie subscription with new data

        Args:
            customer_id: Mollie customer ID
            subscription_id: Mollie subscription ID
            update_data: Dictionary with update data (e.g., {"amount": {"value": "25.00", "currency": "EUR"}})

        Returns:
            dict: Status and result information
        """
        try:
            # Get Mollie client
            mollie_client = self.client

            # Get the customer
            customer = mollie_client.customers.get(customer_id)

            # Get the subscription
            subscription = customer.subscriptions.get(subscription_id)

            # Update the subscription
            updated_subscription = subscription.update(update_data)

            return {
                "status": "success",
                "message": _("Subscription updated successfully"),
                "subscription": {
                    "id": updated_subscription.id,
                    "status": updated_subscription.status,
                    "amount": updated_subscription.amount,
                    "next_payment_date": getattr(updated_subscription, "next_payment_date", None),
                },
            }

        except Exception as e:
            frappe.log_error(
                f"Error updating Mollie subscription {subscription_id}: {str(e)}",
                "Mollie Subscription Update",
            )
            return create_error_response(f"Error updating subscription: {str(e)}")


class SEPAGateway(PaymentGateway):
    """Handler for SEPA Direct Debit"""

    def process_payment(self, donation, form_data):
        """Set up SEPA direct debit mandate"""
        iban = form_data.get("donor_iban", "").replace(" ", "").upper()

        if not iban:
            return create_error_response("IBAN is required for SEPA payments")

        # Validate IBAN format with comprehensive validation
        from verenigingen.utils.validation.iban_validator import validate_iban

        validation_result = validate_iban(iban)
        if not validation_result["valid"]:
            return create_error_response(validation_result["message"])

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
            return create_error_response("Failed to create SEPA mandate")

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


class PontoGateway(PaymentGateway):
    """
    Handler for Ponto payment requests (betaalverzoek).

    Creates a Ponto Payment Link that customers can use to authorize
    a bank-to-bank payment from their account to the organization's account.
    """

    def process_payment(self, donation, form_data):
        """
        Create Ponto payment link for the donation.

        Returns a redirect URL where the customer can authorize the payment
        at their own bank.
        """
        settings = frappe.get_single("Verenigingen Settings")
        payments_settings = get_payments_settings()

        # Get creditor details
        creditor_name = getattr(payments_settings, "company_account_holder", None) or frappe.get_value(
            "Company", settings.company, "company_name"
        )
        creditor_iban = getattr(payments_settings, "company_iban", "")

        if not creditor_iban:
            return {
                "status": "error",
                "message": _("Company IBAN not configured for Ponto payments"),
            }

        # Build description
        description = f"Donation {donation.name}"
        if form_data.get("donor_name"):
            description = f"Donation from {form_data.get('donor_name')}"

        try:
            # Create Ponto Payment Link document
            payment_link = frappe.new_doc("Ponto Payment Link")
            payment_link.amount = donation.amount
            payment_link.currency = "EUR"
            payment_link.creditor_name = creditor_name
            payment_link.creditor_iban = creditor_iban
            payment_link.description = description
            payment_link.reference_doctype = "Donation"
            payment_link.reference_name = donation.name
            payment_link.payment_type = "One-Time"

            # === System User Context for Public Donation Flow ===
            # WHY allow_system_user=True is required here:
            #
            # 1. CONTEXT: Public donation page (allow_guest=True) runs as Guest user
            #    who has no document creation permissions.
            #
            # 2. SECURITY MODEL:
            #    - Donation has ALREADY been validated and created via secure_document_operation
            #    - Ponto Payment Link is an internal tracking document, not user-facing data
            #    - Payment Link creation is gated by donation existence (can't create orphaned links)
            #    - All input (amount, creditor, description) comes from validated donation/settings
            #
            # 3. AUDIT TRAIL (automatic via secure_document_operation):
            #    - Original user (Guest) is logged in audit_entry
            #    - System user fallback is explicitly recorded with justification
            #    - Full context preserved in SecureOperationResult.audit_trail
            #
            # 4. ALTERNATIVE APPROACHES REJECTED:
            #    - Dedicated "Ponto Payment Processor" role: Over-engineering for single use case
            #    - Anonymous API endpoint: Would bypass all permission checks entirely
            #    - Deferred background job: Would break redirect flow timing
            #
            # See: secure_document_operation() in utils/secure_operations.py for audit implementation
            insert_result = secure_document_operation(
                operation="insert",
                doc=payment_link,
                justification=f"Create Ponto payment link for donation {donation.name}",
                required_permissions=[],  # Guest has no permissions - system fallback expected
                allow_system_user=True,  # Audited system user fallback for public donation flow
            )

            if not insert_result.success:
                frappe.log_error(
                    f"Failed to create Ponto payment link: {'; '.join(insert_result.errors)}",
                    "Ponto Gateway - Insert Error",
                )
                return {
                    "status": "error",
                    "message": _("Failed to create payment link"),
                }

            # Submit triggers Ponto API call
            payment_link.submit()

            # Update donation with payment link reference
            donation.db_set("payment_id", payment_link.name)

            return {
                "status": "redirect_required",
                "payment_url": payment_link.redirect_link,
                "payment_id": payment_link.name,
                "ponto_request_id": payment_link.ponto_request_id,
                "message": _("Redirecting to your bank for payment authorization..."),
            }

        except Exception as e:
            frappe.log_error(f"Ponto payment link creation failed: {e}", "Ponto Gateway Error")
            return {
                "status": "error",
                "message": _("Failed to create Ponto payment link: {0}").format(str(e)),
            }

    def handle_webhook(self, payload):
        """
        Handle Ponto webhook for payment status updates.

        Ponto webhooks are handled separately via the betaalverzoek_callback endpoint.
        """
        # Ponto webhooks are handled by the Ponto Payment Link controller
        return {"status": "delegated", "message": "Handled by Ponto Payment Link controller"}

    def get_payment_status(self, payment_id):
        """Get payment status from Ponto Payment Link document."""
        try:
            payment_link = frappe.get_doc("Ponto Payment Link", payment_id)

            # Map Ponto statuses to standard statuses
            status_mapping = {
                "Draft": "pending",
                "Pending Authorization": "pending",
                "Authorized": "pending",
                "Executed": "paid",
                "Rejected": "failed",
                "Cancelled": "cancelled",
                "Expired": "expired",
                "Failed": "failed",
            }

            return {
                "status": status_mapping.get(payment_link.status, "unknown"),
                "ponto_status": payment_link.status,
                "redirect_link": payment_link.redirect_link,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}


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
        "Ponto": PontoGateway,
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

        # Convert billing frequency to Mollie interval format using consolidated utility
        interval = convert_frequency_to_mollie_interval(dues_schedule["billing_frequency"])

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
        return create_error_response(str(e))


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

            # Find member for this customer using consolidated utility
            members = get_members_by_customer(
                customer_name, fields=["name", "mollie_subscription_id", "subscription_status"]
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


def _activate_direct_subscription_after_first_payment(gateway, payment):
    """
    Create Mollie subscription directly from payment metadata (no donation agreement needed)

    Args:
        gateway: MollieGateway instance
        payment: Mollie payment object from first payment

    Returns:
        dict: Subscription creation result
    """
    try:
        # Check if this payment has subscription setup metadata
        if payment.metadata.get("subscription_setup") != "true":
            return {"status": "skipped", "reason": "Payment not marked for subscription setup"}

        # Get subscription details from payment metadata
        subscription_interval = payment.metadata.get("subscription_interval")
        subscription_amount = payment.metadata.get("subscription_amount")
        subscription_currency = payment.metadata.get("subscription_currency", "EUR")
        donation_id = payment.metadata.get("donation_id")

        if not (subscription_interval and subscription_amount):
            return create_error_response(
                "Missing subscription details in payment metadata", {"reason": "missing_subscription_details"}
            )

        # Get customer ID from payment
        customer_id = payment.customer_id
        if not customer_id:
            return create_error_response("No customer ID found in payment", {"reason": "missing_customer_id"})

        # Create subscription data
        subscription_data = {
            "amount": {"currency": subscription_currency, "value": subscription_amount},
            "interval": subscription_interval,  # Use original format from metadata
            "description": f"Recurring donation {donation_id}" if donation_id else "Recurring donation",
            "metadata": {
                "payment_id": payment.id,
                "donation_id": donation_id,
                "created_from": "direct_subscription",
                "original_amount": subscription_amount,
                "original_interval": subscription_interval,
            },
        }

        # For quarterly/yearly subscriptions, calculate optimal start date
        if subscription_interval in ["3 months", "6 months", "12 months"]:
            mollie_settings = frappe.get_single("Mollie Settings")
            calculated_start = mollie_settings.get_next_payment_date_for_scheduled_months(min_months_ahead=2)
            if calculated_start:
                subscription_data["startDate"] = calculated_start
                frappe.logger().info(
                    f"Auto-calculated subscription start date: {calculated_start} "
                    f"(interval: {subscription_interval}, configured months: {mollie_settings.quarterly_yearly_payment_months})"
                )

        # Create subscription using Mollie API directly
        customer = gateway.client.customers.get(customer_id)
        subscription = customer.subscriptions.create(data=subscription_data)

        frappe.logger().info(
            f"Successfully created direct subscription {subscription.id} for payment {payment.id}"
        )

        # Update donation with subscription ID if donation exists
        if donation_id:
            try:
                donation = frappe.get_doc("Donation", donation_id)
                donation.db_set("mollie_subscription_id", subscription.id)
            except:
                pass  # Don't fail subscription creation if donation update fails

        return {
            "status": "success",
            "subscription_id": subscription.id,
            "customer_id": customer_id,
            "donation_id": donation_id,
            "interval": subscription_interval,
            "amount": subscription_amount,
        }

    except Exception as e:
        frappe.log_error(
            f"Error creating direct subscription after first payment: {str(e)}",
            "Mollie Direct Subscription Creation",
        )
        return create_error_response(str(e))


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
            return create_error_response("No customer ID found in payment", {"reason": "missing_customer_id"})

        # Create subscription data based on agreement
        subscription_data = {
            "amount": format_mollie_amount(agreement.amount),
            "interval": convert_frequency_to_mollie_interval(agreement.recurring_frequency),
            "description": f"Recurring donation - {getattr(donation, 'donation_category', None) or donation.donation_purpose_type}",
            "startDate": agreement.next_due_date.strftime("%Y-%m-%d") if agreement.next_due_date else None,
            "metadata": {
                "donation_agreement_id": agreement.name,
                "donation_id": donation_id,
                "donor_id": donation.donor,
                "donation_type": getattr(donation, "donation_category", None)
                or donation.donation_purpose_type,
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
        return create_error_response(str(e))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def manual_subscription_retry():
    """
    Manual trigger for subscription activation retry
    Requires appropriate permissions
    """
    return retry_failed_subscription_activations()


# Webhook endpoints
def _create_webhook_processing_log(
    webhook_id, webhook_type, status, payload, processing_result=None, error_details=None
):
    """
    Create a webhook processing log entry for audit trail

    Args:
        webhook_id: Mollie webhook ID (payment ID, subscription ID, etc.)
        webhook_type: Type of webhook (payment, subscription, etc.)
        status: Processing status (success, error, ignored)
        payload: Raw webhook payload for debugging
        processing_result: Success result details
        error_details: Error details if status is 'error'
    """
    try:
        import hashlib
        import json

        # Generate unique hash for deduplication
        payload_str = str(payload) if payload else ""
        webhook_hash = hashlib.md5(
            f"{webhook_id}_{payload_str}_{frappe.utils.now_datetime()}".encode()
        ).hexdigest()

        log_entry = frappe.new_doc("Webhook Processing Log")
        # Safe payload serialization
        safe_payload = None
        if payload:
            try:
                if isinstance(payload, bytes):
                    safe_payload = payload.decode("utf-8", errors="replace")
                elif isinstance(payload, str):
                    safe_payload = payload
                else:
                    safe_payload = json.dumps(payload, indent=2, default=str)
            except Exception as e:
                safe_payload = f"<Serialization failed: {str(e)}>"

        log_entry.update(
            {
                "webhook_id": webhook_id or "unknown",
                "webhook_type": webhook_type,
                "webhook_hash": webhook_hash,
                "processed_at": frappe.utils.now_datetime(),
                "status": status,
                "processing_result": (
                    json.dumps(processing_result, default=str) if processing_result else None
                ),
                "error_details": error_details,
                "raw_payload": safe_payload,
            }
        )

        print(f"🗃️ Creating webhook processing log: {webhook_id} - {status}")

        # Use secure document operation instead of permission bypass
        result = secure_document_operation(
            operation="insert",
            doc=log_entry,
            justification="System webhook processing log creation for audit trail",
            required_permissions=["Webhook Processing Log:create"],
        )

        if result.success:
            print(f"✅ Webhook processing log created: {log_entry.name}")
        else:
            print(f"❌ Failed to create webhook log: {'; '.join(result.errors)}")

    except Exception as e:
        print(f"❌ Failed to create webhook processing log: {str(e)}")
        frappe.log_error(f"Webhook logging failed: {str(e)}", "Webhook Log Creation Error")


@frappe.whitelist(allow_guest=True)
@public_api
def mollie_webhook():
    """
    Simplified Mollie webhook handler for existing donations

    Redirects to the robust service-based handler for proper PE creation
    """
    frappe.logger().info("🔄 Main Mollie webhook redirecting to service handler")

    from verenigingen.verenigingen_payments.mollie.api.payment_webhook import handle_mollie_payment_webhook

    return handle_mollie_payment_webhook()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def mollie_subscription_webhook():
    """
    Handle Mollie subscription webhook notifications with security verification.

    Processes subscription payments by:
    1. Verifying webhook signature for security
    2. Finding the member with the subscription
    3. Processing any new payments (creating Payment Entry for unpaid invoices)
    4. Updating member subscription status
    """
    try:
        parsed, error_response = _authenticate_and_parse_subscription_payload()
        if error_response:
            return error_response

        subscription_id = parsed["subscription_id"]
        payment_id = parsed["payment_id"]

        member_name, customer_name, customer_id = _find_member_for_subscription(subscription_id)
        if not member_name:
            return {"status": "ignored", "reason": "No member found for subscription"}

        result = {
            "status": "processed",
            "member": member_name,
            "subscription_id": subscription_id,
            "actions": [],
        }

        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Process payment if this webhook includes a payment
        if payment_id:
            try:
                payment_result = _process_subscription_payment(
                    gateway, member_name, customer_name, payment_id, subscription_id
                )
                result["payment_processed"] = payment_result
                result["actions"].append("payment_processed")
                frappe.logger().info(f"Processed subscription payment {payment_id} for member {member_name}")
            except Exception as e:
                frappe.log_error(
                    f"Failed to process subscription payment {payment_id} "
                    f"for member {member_name}: {str(e)}",
                    "Mollie Subscription Payment Processing",
                )
                result["payment_error"] = str(e)

        _update_subscription_status(gateway, customer_id, subscription_id, member_name, result)

        return result

    except Exception as e:
        frappe.log_error(f"Mollie subscription webhook error: {str(e)}", "Mollie Subscription Webhook")
        return create_error_response(str(e))


def _authenticate_and_parse_subscription_payload():
    """Authenticate webhook and parse payload into structured subscription data.

    Handles JSON, form-encoded, and truncated payloads. Uses MollieWebhookParser
    for event routing and ID extraction.

    Returns:
        tuple: (parsed_dict, error_response_or_None)
            Success: ({"subscription_id": str, "payment_id": str|None}, None)
            Error/ping: (None, response_dict)
    """
    from verenigingen.utils.webhook_security import (
        authenticate_mollie_webhook,
        log_webhook_security_event,
    )
    from verenigingen.verenigingen_payments.mollie.utils.webhook_parser import MollieWebhookParser

    # Authenticate webhook
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
        return None, create_error_response("Webhook authentication failed", {"details": str(auth_error)})

    frappe.logger().info("Mollie subscription webhook received and authenticated")
    frappe.logger().info(f"Payload length: {len(payload) if payload else 0}")

    # Parse payload - handle both JSON and form-encoded data
    try:
        data = frappe.parse_json(payload)
        frappe.logger().info("Successfully parsed subscription JSON payload")
    except (ValueError, TypeError) as json_error:
        frappe.logger().info(f"Subscription JSON parsing failed, trying form-encoded: {str(json_error)}")

        if "=" in payload and not payload.strip().startswith("{"):
            try:
                from urllib.parse import parse_qs, unquote_plus

                if "&" in payload:
                    parsed_data = parse_qs(payload)
                    data = {k: (v[0] if len(v) == 1 else v) for k, v in parsed_data.items()}
                else:
                    key, value = payload.split("=", 1)
                    data = {unquote_plus(key): unquote_plus(value)}

                frappe.logger().info(f"Successfully parsed subscription form-encoded payload: {data}")
            except Exception as form_error:
                frappe.logger().error(f"Subscription form-encoded parsing also failed: {str(form_error)}")
                frappe.log_error(
                    f"Mollie subscription webhook parsing failed: Neither JSON nor form-encoded\n"
                    f"JSON error: {str(json_error)}\nForm error: {str(form_error)}\n"
                    f"Full payload: {repr(payload)}",
                    "Mollie Subscription Webhook Parsing Error",
                )
                return None, create_error_response("Invalid payload format")
        else:
            is_truncated = (
                payload.endswith("{")
                or payload.endswith(",")
                or payload.count("{") > payload.count("}")
                or payload.count("[") > payload.count("]")
            )
            if is_truncated:
                frappe.logger().error(
                    "Subscription payload appears to be truncated - possible size limit issue"
                )
                error_msg = f"Subscription webhook payload appears truncated: {str(json_error)}"
            else:
                error_msg = f"Invalid JSON in subscription webhook payload: {str(json_error)}"

            frappe.log_error(
                f"Mollie subscription webhook JSON parsing failed: {error_msg}\n"
                f"Full payload: {repr(payload)}",
                "Mollie Subscription Webhook JSON Error",
            )
            return None, create_error_response("Invalid JSON payload")

    # Delegate event routing and ID extraction to MollieWebhookParser
    parsed = MollieWebhookParser.parse_webhook_data(data)

    if parsed["is_ping"]:
        return None, {"status": "success", "message": "Subscription webhook ping received"}

    subscription_id = parsed["subscription_id"]
    payment_id = parsed["payment_id"]

    # Fallback: legacy nested payment.id format not handled by parser
    if not payment_id and isinstance(data.get("payment"), dict):
        payment_id = data["payment"].get("id")

    if not subscription_id:
        return None, {"status": "ignored", "reason": "No subscription ID in payload"}

    # Idempotency: skip already-processed payments
    if payment_id and DocumentExistenceValidator.check_document_exists(
        "Payment Entry", {"reference_no": payment_id}
    ):
        frappe.logger().info(f"Payment {payment_id} already processed, skipping webhook")
        return None, {"status": "already_processed", "payment_id": payment_id}

    return {"subscription_id": subscription_id, "payment_id": payment_id}, None


def _find_member_for_subscription(subscription_id):
    """Find the member and customer linked to a Mollie subscription.

    Returns:
        tuple: (member_name, customer_name, customer_id) or (None, None, None)
    """
    customers = frappe.get_all(
        "Customer",
        filters={"custom_mollie_subscription_id": subscription_id},
        fields=["name", "custom_mollie_customer_id"],
    )

    if not customers:
        frappe.log_error(
            f"No customer found for subscription {subscription_id}",
            "Mollie Subscription Webhook",
        )
        return None, None, None

    customer_name = customers[0]["name"]
    customer_id = customers[0]["custom_mollie_customer_id"]

    members = get_members_by_customer(customer_name, fields=["name"])

    if not members:
        frappe.log_error(
            f"No member found for customer {customer_name} with subscription {subscription_id}",
            "Mollie Subscription Webhook",
        )
        return None, None, None

    return members[0]["name"], customer_name, customer_id


def _update_subscription_status(gateway, customer_id, subscription_id, member_name, result):
    """Fetch subscription status from Mollie and update member fields.

    Updates result dict with subscription_status and actions.
    """
    status_result = gateway.get_subscription_status(customer_id, subscription_id)

    if status_result["status"] == "success":
        subscription = status_result["subscription"]

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
        # Use centralized extractor for payment amount
        extractor = get_payment_data_extractor()
        payment_amount = extractor.extract_amount(payment, allow_zero=False)
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
                # Priority 1: Check if payment has direct subscription metadata
                if payment.metadata.get("subscription_setup") == "true":
                    frappe.logger().info(
                        "First payment completed with subscription metadata, attempting direct subscription creation"
                    )
                    subscription_activation_result = _activate_direct_subscription_after_first_payment(
                        gateway, payment
                    )
                # Priority 2: Check if this is for a donation agreement
                elif payment.metadata.get("reference_doctype") == "Donation":
                    frappe.logger().info(
                        "First payment completed for donation, attempting subscription creation via agreement"
                    )
                    subscription_activation_result = _activate_donation_subscription_after_first_payment(
                        gateway, payment
                    )
                # Priority 3: Member subscription (legacy approach)
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
@high_security_api(operation_type=OperationType.FINANCIAL)
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
@high_security_api(operation_type=OperationType.FINANCIAL)
def get_payment_status(donation_id):
    """Get payment status for a donation"""
    try:
        donation = frappe.get_doc("Donation", donation_id)

        if donation.paid:
            return {"status": "paid", "payment_date": donation.modified}

        if donation.mode_of_payment and donation.payment_id:
            gateway = PaymentGatewayFactory.get_gateway(donation.mode_of_payment)
            return gateway.get_payment_status(donation.payment_id)

        return {"status": "pending", "message": "Payment not yet initiated"}

    except Exception as e:
        frappe.log_error(f"Payment status check error: {str(e)}", "Payment Gateway Status")
        return create_error_response(str(e))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def create_member_subscription(member_id, amount, interval="1 month", description=None, start_date=None):
    """Create Mollie subscription for a member with optional start date"""
    if not frappe.has_permission("Member", "write"):
        frappe.throw(_("Insufficient permissions"))

    try:
        member = frappe.get_doc("Member", member_id)

        # Check if member already has an active subscription
        if member.mollie_subscription_id and member.subscription_status == "Active":
            return {
                "status": "error",
                "message": _(
                    "You already have an active Mollie subscription. Please cancel the existing subscription first if you want to create a new one."
                ),
                "existing_subscription_id": member.mollie_subscription_id,
            }

        # Get Mollie customer ID from member
        if not member.mollie_customer_id:
            return {
                "status": "error",
                "message": _("No Mollie customer ID found. Please set up payment details first."),
            }

        # Use existing MollieDebugService for subscription creation
        # This handles mandate auto-selection and all the edge cases
        from verenigingen.services.mollie_debug_service import MollieDebugService

        debug_service = MollieDebugService()

        # Create subscription using the existing service method
        result = debug_service.create_subscription(
            customer_id=member.mollie_customer_id,
            amount=float(amount),
            interval=interval,
            description=description or f"Membership dues for {member.first_name} {member.last_name}",
            mandate_id=None,  # Let Mollie auto-select active mandate
            start_date=start_date,
        )

        # If successful, update member record
        if result.get("status") == "success" and result.get("subscription_id"):
            member.db_set("mollie_subscription_id", result["subscription_id"])
            member.db_set("payment_method", "Mollie")

        return result

    except Exception as e:
        frappe.log_error(
            f"Error creating subscription for member {member_id}: {str(e)}", "Member Subscription"
        )
        return create_error_response(str(e))


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
        return create_error_response(str(e))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
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
        return create_error_response(str(e))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def cancel_mollie_subscription_by_id(subscription_id):
    """Cancel Mollie subscription by subscription ID"""
    try:
        # Find member with this subscription ID using consolidated utility
        member = get_member_by_subscription_id(subscription_id, fields=["name"])

        if not member:
            return create_error_response("No member found for subscription ID")

        member_id = member["name"]
        return cancel_member_subscription(member_id)

    except Exception as e:
        frappe.log_error(
            f"Error cancelling subscription by ID {subscription_id}: {str(e)}",
            "Mollie Subscription Cancellation",
        )
        return create_error_response(str(e))


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def update_mollie_subscription_amount(subscription_id, new_amount):
    """Update Mollie subscription amount"""
    try:
        # Find member with this subscription ID using consolidated utility
        member_data = get_member_by_subscription_id(subscription_id, fields=["name", "mollie_customer_id"])

        if not member_data:
            return create_error_response("No member found for subscription ID")

        customer_id = member_data["mollie_customer_id"]

        if not customer_id:
            return create_error_response("No Mollie customer ID found")

        # Get Mollie gateway
        gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")

        # Update subscription amount via Mollie API
        result = gateway.update_subscription(
            customer_id, subscription_id, {"amount": format_mollie_amount(new_amount)}
        )

        if result.get("status") == "success":
            # Update related donation records
            donations = frappe.get_all(
                "Donation",
                filters={"mollie_subscription_id": subscription_id, "status": "Recurring"},
                fields=["name"],
            )

            for donation in donations:
                frappe.db.set_value("Donation", donation.name, "amount", new_amount)

            frappe.db.commit()

            return {
                "status": "success",
                "message": f"Subscription amount updated to €{format_mollie_amount_string(new_amount)}",
                "subscription_id": subscription_id,
                "new_amount": new_amount,
            }
        else:
            return create_error_response(result.get("message", "Failed to update subscription"))

    except Exception as e:
        frappe.log_error(
            f"Error updating subscription amount for {subscription_id}: {str(e)}",
            "Mollie Subscription Update",
        )
        return create_error_response(str(e))
