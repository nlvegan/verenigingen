"""
Mollie Payment Service

Handles payment creation for both single and recurring donations with proper
metadata encoding for webhook-driven donation creation.
"""

import json
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

if TYPE_CHECKING:
    from frappe.model.document import Document


class MolliePaymentService:
    """
    Service for creating Mollie payments with proper metadata for webhook processing.

    Supports both single payments and first payments for subscription setup.
    """

    def __init__(self):
        from verenigingen.verenigingen_payments.utils.payment_gateways import PaymentGatewayFactory

        self.gateway = PaymentGatewayFactory.get_gateway("Mollie", "Default")
        self._validate_donor_fields()

    def _validate_donor_fields(self):
        """Validate that Donor DocType has required Mollie fields."""
        donor_meta = frappe.get_meta("Donor")
        mollie_fields = ["mollie_customer_id", "mollie_mandate_id", "mollie_subscription_id"]

        for field in mollie_fields:
            if not donor_meta.has_field(field):
                frappe.log_error(
                    f"Donor DocType missing field: {field}. This should be added as a custom field.",
                    "Donor Field Validation Warning",
                )

    def create_single_payment(self, donation_doc: "Document", form_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a single Mollie payment with metadata for webhook processing.

        Args:
            donation_doc: Non-submittable Donation document (draft state)
            form_data: Form data from donation submission

        Returns:
            Dict with payment_url, payment_id, and metadata for user redirect
        """
        try:
            # Create payment metadata for webhook processing
            payment_metadata = self._build_payment_metadata(donation_doc, form_data, is_recurring=False)

            # Set description to JSON metadata for webhook processing
            form_data_with_metadata = form_data.copy()
            form_data_with_metadata["description_override"] = json.dumps(
                payment_metadata, separators=(",", ":")
            )

            # Use gateway's process_payment method
            result = self.gateway.process_payment(donation_doc, form_data_with_metadata)

            if result.get("status") == "redirect_required":
                return {
                    "status": "redirect_required",
                    "payment_url": result["payment_url"],
                    "payment_id": result["payment_id"],
                    "message": _("Redirecting to Mollie for secure payment"),
                    "expires_at": result.get("expires_at"),
                }
            else:
                return {
                    "status": "error",
                    "message": result.get("message", _("Payment creation failed")),
                    "info": _("Please try again or contact support"),
                }

        except Exception as e:
            frappe.log_error(
                f"Single payment creation error for donation {donation_doc.name}: {str(e)}",
                "Mollie Single Payment Error",
            )
            return {
                "status": "error",
                "message": _("Payment setup temporarily unavailable"),
                "info": _("Please try again later or use a different payment method"),
            }

    def create_recurring_first_payment(
        self, donation_doc: "Document", form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create the first payment for a recurring donation to establish mandate.

        Args:
            donation_doc: Non-submittable Donation document (draft state)
            form_data: Form data including subscription interval

        Returns:
            Dict with payment_url, payment_id for mandate establishment
        """
        try:
            print(f"DEBUG: Starting recurring payment creation for donation {donation_doc.name}")

            # Create payment metadata for webhook processing
            payment_metadata = self._build_payment_metadata(donation_doc, form_data, is_recurring=True)
            print("DEBUG: Payment metadata created successfully")

            # Create or get customer first for recurring payments
            customer_result = self._create_or_get_mollie_customer(donation_doc, form_data)
            print(f"DEBUG: Customer result status: {customer_result.get('status')}")

            if not customer_result.get("customer_id"):
                print(f"DEBUG: Customer creation failed: {customer_result}")
                return {
                    "status": "error",
                    "message": _("Failed to create customer for recurring payment"),
                    "info": customer_result.get("message", "Customer creation failed"),
                }

            # Prepare form data for subscription setup
            form_data_with_metadata = form_data.copy()
            form_data_with_metadata.update(
                {
                    "description_override": json.dumps(payment_metadata, separators=(",", ":")),
                    "subscription_setup": True,  # Flag for sequenceType: "first"
                    "customer_id": customer_result["customer_id"],
                    "subscription_interval": form_data.get("subscription_interval", "1 month"),
                }
            )

            print(f"DEBUG: Form data prepared with customer_id: {customer_result['customer_id']}")

            # Use gateway's process_payment method
            result = self.gateway.process_payment(donation_doc, form_data_with_metadata)
            print(f"DEBUG: Gateway result status: {result.get('status')}")

            if result.get("status") == "redirect_required":
                return {
                    "status": "subscription_redirect_required",
                    "payment_url": result["payment_url"],
                    "payment_id": result["payment_id"],
                    "customer_id": customer_result["customer_id"],
                    "message": _("Setting up recurring donation"),
                    "info": _("After this payment, you'll be charged automatically each period"),
                    "expires_at": result.get("expires_at"),
                }
            else:
                print(
                    f"DEBUG: Gateway returned non-redirect status: {result.get('status')} - {result.get('message')}"
                )
                return {
                    "status": "error",
                    "message": result.get("message", _("Recurring payment setup failed")),
                    "info": _("Please try a single donation instead or contact support"),
                }

        except Exception as e:
            frappe.log_error(
                f"Recurring payment creation error for donation {donation_doc.name}: {str(e)}\nTraceback: {frappe.get_traceback()}",
                "Mollie Recurring Payment Error",
            )
            return {
                "status": "error",
                "message": _("Recurring payment setup temporarily unavailable"),
                "info": _("Please try a single donation instead or contact support"),
            }

    def _build_payment_metadata(
        self, donation_doc: "Document", form_data: Dict[str, Any], is_recurring: bool
    ) -> Dict[str, Any]:
        """
        Build payment metadata JSON for webhook processing.

        This metadata will be stored in the Mollie payment description and used
        by the webhook processor to create the final donation and payment records.
        """
        donor_doc = frappe.get_doc("Donor", donation_doc.donor)

        metadata = {
            "type": "recurring_donation" if is_recurring else "single_donation",
            "donation_id": donation_doc.name,
            "donor_id": donor_doc.name,
            "donor_email": donor_doc.donor_email,
            "donor_name": donor_doc.donor_name,
            "amount": flt(donation_doc.amount),
            "currency": "EUR",
            "purpose_type": donation_doc.donation_purpose_type,
            "payment_method": "Mollie",
            "created_at": now_datetime().isoformat(),
        }

        # Add recurring-specific metadata
        if is_recurring:
            metadata.update(
                {
                    "subscription_interval": form_data.get("subscription_interval", "1 month"),
                    "next_payment_date": form_data.get("next_payment_date"),
                }
            )

        # Add optional purpose-specific data
        if donation_doc.donation_purpose_type == "Campaign" and donation_doc.get("campaign"):
            metadata["campaign"] = donation_doc.campaign
        elif donation_doc.donation_purpose_type == "Chapter" and donation_doc.get("chapter_reference"):
            metadata["chapter_reference"] = donation_doc.chapter_reference
        elif donation_doc.donation_purpose_type == "Specific Goal" and donation_doc.get(
            "specific_goal_description"
        ):
            metadata["specific_goal_description"] = donation_doc.specific_goal_description

        # Add notes if present
        if donation_doc.get("donation_notes"):
            metadata["donation_notes"] = donation_doc.donation_notes

        return metadata

    def _create_or_get_mollie_customer(
        self, donation_doc: "Document", form_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create or get existing Mollie customer for recurring payments.
        """
        try:
            donor_doc = frappe.get_doc("Donor", donation_doc.donor)
            print(f"DEBUG: Got donor doc: {donor_doc.donor_name} ({donor_doc.donor_email})")

            # Check if donor already has a Mollie customer ID
            # Use safe field access in case custom field doesn't exist
            existing_customer_id = (
                getattr(donor_doc, "mollie_customer_id", None)
                if hasattr(donor_doc, "mollie_customer_id")
                else None
            )

            if existing_customer_id:
                print(f"DEBUG: Using existing customer ID: {existing_customer_id}")
                return {"status": "existing", "customer_id": existing_customer_id}

            print("DEBUG: Creating new Mollie customer...")
            # Create new Mollie customer using gateway's client directly
            customer_data = {
                "name": donor_doc.donor_name,
                "email": donor_doc.donor_email,
                "metadata": {"donor_id": donor_doc.name, "created_for": "recurring_donations"},
            }

            # Add phone if available
            if hasattr(donor_doc, "phone") and donor_doc.phone:
                customer_data["phone"] = donor_doc.phone

            print(f"DEBUG: Customer data: {customer_data}")
            print(f"DEBUG: Gateway client type: {type(self.gateway.client)}")

            # Create customer using Mollie client directly
            try:
                customer = self.gateway.client.customers.create(customer_data)
                print(f"DEBUG: Customer creation successful: {customer.id if customer else 'None'}")
            except Exception as create_error:
                print(f"DEBUG: Customer creation failed with error: {str(create_error)}")
                return {
                    "status": "error",
                    "message": f"Customer creation API call failed: {str(create_error)}",
                }

            if customer and customer.id:
                # Store customer ID on donor (safe field access)
                try:
                    if hasattr(donor_doc, "mollie_customer_id"):
                        donor_doc.mollie_customer_id = customer.id
                        donor_doc.save(ignore_permissions=True)
                        print(f"DEBUG: Saved customer ID {customer.id} to donor")
                    else:
                        print("DEBUG: Donor DocType missing mollie_customer_id field")
                        frappe.log_error(
                            "Donor DocType missing mollie_customer_id field - customer ID not stored",
                            "Custom Field Missing",
                        )
                except Exception as e:
                    print(f"DEBUG: Failed to save customer ID: {str(e)}")
                    frappe.log_error(
                        f"Failed to save Mollie customer ID: {str(e)}", "Customer ID Storage Error"
                    )

                return {"status": "created", "customer_id": customer.id}
            else:
                print("DEBUG: Customer creation returned no valid response")
                return {"status": "error", "message": "Customer creation returned invalid response"}

        except Exception as e:
            print(f"DEBUG: Overall customer creation error: {str(e)}")
            frappe.log_error(f"Mollie customer creation error: {str(e)}", "Mollie Customer Error")
            return {"status": "error", "message": "Customer creation failed"}

    def _get_redirect_url(self, donation_id: str, result_type: str) -> str:
        """Get redirect URL for after payment completion."""
        base_url = frappe.utils.get_url()
        return f"{base_url}/donation-result?donation_id={donation_id}&result={result_type}"

    def _get_webhook_url(self) -> str:
        """Get webhook URL based on environment (test vs live)."""
        base_url = frappe.utils.get_url()

        # Determine if this is test or live environment
        # You might want to check Mollie settings or environment variables
        is_test_environment = self._is_test_environment()

        if is_test_environment:
            return f"{base_url}/api/method/verenigingen.verenigingen_payments.utils.mollie_webhook_handler.handle_mollie_webhook_test"
        else:
            return f"{base_url}/api/method/verenigingen.verenigingen_payments.utils.mollie_webhook_handler.handle_mollie_webhook_live"

    def _is_test_environment(self) -> bool:
        """Determine if we're in test environment based on Mollie API key."""
        try:
            # Check if Mollie API key starts with 'test_'
            mollie_settings = frappe.get_single("Mollie Settings")
            api_key = getattr(mollie_settings, "api_key", "")
            return api_key.startswith("test_")
        except Exception:
            # Default to test for safety
            return True
