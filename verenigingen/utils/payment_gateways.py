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
        payment_reference = "DON-{donation.name}-{donation.creation.strftime('%Y%m%d')}"

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
    """Handler for Mollie payments (placeholder for future implementation)"""

    def __init__(self):
        # This would load Mollie API credentials from settings
        self.api_key = self._get_api_key()
        self.webhook_url = self._get_webhook_url()

    def process_payment(self, donation, form_data):
        """Create Mollie payment"""
        # Placeholder for Mollie integration
        # payment_data = {
        #     "amount": {"currency": "EUR", "value": "{donation.amount:.2f}"},
        #     "description": "Donation {donation.name}",
        #     "redirectUrl": "{frappe.utils.get_url()}/donation-success?id={donation.name}",
        #     "webhookUrl": self.webhook_url,
        #     "metadata": {
        #         "donation_id": donation.name,
        #         "donor_email": donation.donor_email if hasattr(donation, "donor_email") else "",
        #     },
        # }

        # TODO: Implement actual Mollie API call
        # mollie_payment = mollie_client.payments.create(payment_data)

        return {
            "status": "redirect_required",
            "payment_url": "https://mollie.com/checkout/{donation.name}",  # Placeholder
            "payment_id": "tr_{donation.name}",  # Placeholder
            "expires_at": frappe.utils.add_to_date(frappe.utils.now(), hours=1),
        }

    def handle_webhook(self, payload):
        """Handle Mollie webhook notifications"""
        # Placeholder for webhook processing
        payment_id = payload.get("id")
        status = payload.get("status")

        if payment_id and status == "paid":
            # Find donation by payment ID
            donation_name = payload.get("metadata", {}).get("donation_id")
            if donation_name:
                donation = frappe.get_doc("Donation", donation_name)
                donation.db_set("paid", 1)
                donation.db_set("payment_id", payment_id)

                # Create payment entry
                if hasattr(donation, "create_payment_entry"):
                    donation.create_payment_entry()

                return {"status": "processed", "donation": donation_name}

        return {"status": "ignored"}

    def get_payment_status(self, payment_id):
        """Get payment status from Mollie"""
        # TODO: Implement Mollie API status check
        return {"status": "pending", "message": "Mollie integration pending"}

    def _get_api_key(self):
        """Get Mollie API key from settings"""
        # TODO: Add to Verenigingen Settings
        return frappe.db.get_single_value("Verenigingen Settings", "mollie_api_key")

    def _get_webhook_url(self):
        """Get webhook URL for Mollie"""
        return "{frappe.utils.get_url()}/api/method/verenigingen.utils.payment_gateways.mollie_webhook"


class SEPAGateway(PaymentGateway):
    """Handler for SEPA Direct Debit"""

    def process_payment(self, donation, form_data):
        """Set up SEPA direct debit mandate"""
        iban = form_data.get("donor_iban", "").replace(" ", "").upper()

        if not iban:
            return {"status": "error", "message": "IBAN is required for SEPA payments"}

        # Validate IBAN format with comprehensive validation
        from verenigingen.utils.iban_validator import validate_iban

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
        from verenigingen.utils.iban_validator import validate_iban

        result = validate_iban(iban)
        return result["valid"]

    def _create_sepa_mandate(self, donation, iban, form_data):
        """Create SEPA mandate record"""
        try:
            # Get donor information
            donor = frappe.get_doc("Donor", donation.donor)

            # Validate and format IBAN
            from verenigingen.utils.iban_validator import derive_bic_from_iban, validate_iban

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
    def get_gateway(cls, payment_method):
        """Get payment gateway instance for given method"""
        gateway_class = cls._gateways.get(payment_method)
        if gateway_class:
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
