"""
Donation Management Service

Handles donation-related operations for webhook processing.
Extracted from monolithic webhook handler for better maintainability.
"""

from typing import Any, Dict, Optional, Tuple

import frappe
from frappe.utils import nowdate


class DonationManagementService:
    """Service class for handling donation management operations"""

    def __init__(self, debug_context: str = "webhook"):
        self.debug_context = debug_context
        self.logger = frappe.logger()

    def determine_donation_flow(self, payment_data: Any) -> Tuple[str, Dict[str, Any]]:
        """
        Determine if this is payment-first or donation-first flow

        Args:
            payment_data: Mollie payment object

        Returns:
            Tuple of (flow_type, flow_details)
        """
        metadata = payment_data.metadata or {}

        is_payment_first = metadata.get("create_donation_on_success") == "true"
        is_donation_first = metadata.get("reference_doctype") == "Donation" and metadata.get(
            "reference_docname"
        )

        if is_payment_first:
            return "payment_first", {"metadata": metadata}
        elif is_donation_first:
            return "donation_first", {
                "metadata": metadata,
                "donation_name": metadata.get("reference_docname"),
            }
        else:
            return "unknown", {"metadata": metadata}

    def find_or_create_donation(
        self, flow_type: str, flow_details: Dict[str, Any], payment_id: str, payment_data: Any
    ) -> Tuple[Any, bool]:
        """
        Find existing donation or create new one based on flow type

        Args:
            flow_type: Type of donation flow (payment_first, donation_first)
            flow_details: Details from determine_donation_flow
            payment_id: Mollie payment ID
            payment_data: Mollie payment object

        Returns:
            Tuple of (donation_document, is_new_donation)
        """
        try:
            if flow_type == "donation_first":
                # Donation-first flow: Find existing donation by reference
                donation_name = flow_details["donation_name"]
                if frappe.db.exists("Donation", donation_name):
                    donation = frappe.get_doc("Donation", donation_name)
                    self.logger.info(
                        f"🔍 [{self.debug_context}] Found existing donation {donation.name} for donation-first payment"
                    )
                    return donation, False
                else:
                    raise frappe.DoesNotExistError(f"Referenced donation {donation_name} not found")

            elif flow_type == "payment_first":
                # Payment-first flow: For subscription payments, find by subscription_id first
                # Extract IDs from payment data
                subscription_id = None
                mandate_id = None
                if hasattr(payment_data, "_data") and isinstance(payment_data._data, dict):
                    subscription_id = payment_data._data.get("subscriptionId")
                    mandate_id = payment_data._data.get("mandateId")
                if not subscription_id and hasattr(payment_data, "subscription_id"):
                    subscription_id = payment_data.subscription_id

                # For recurring payments with subscription_id, find existing donation
                if subscription_id:
                    existing_donations = frappe.get_all(
                        "Donation", filters={"mollie_subscription_id": subscription_id}
                    )
                    if existing_donations:
                        donation = frappe.get_doc("Donation", existing_donations[0]["name"])
                        self.logger.info(
                            f"🔍 [{self.debug_context}] Found existing subscription donation {donation.name} for subscription {subscription_id}"
                        )
                        return donation, False

                # For first payments with mandate_id (sequenceType: "first"), find by mandate_id
                # This handles the case where subscription_id doesn't exist yet but mandate_id does
                # Since mandate_id is unique to a subscription, no need to filter by is_recurring
                if not subscription_id and mandate_id:
                    existing_donations = frappe.get_all("Donation", filters={"mollie_mandate_id": mandate_id})
                    if existing_donations:
                        donation = frappe.get_doc("Donation", existing_donations[0]["name"])
                        self.logger.info(
                            f"🔍 [{self.debug_context}] Found existing subscription donation {donation.name} for mandate {mandate_id}"
                        )
                        return donation, False

                # If not a recurring payment, check by payment_id (for single payments)
                existing_donations = frappe.get_all("Donation", filters={"payment_id": payment_id})
                if existing_donations:
                    donation = frappe.get_doc("Donation", existing_donations[0]["name"])
                    self.logger.info(
                        f"🔍 [{self.debug_context}] Found existing donation {donation.name} for payment {payment_id}"
                    )
                    return donation, False

                # No existing donation found - create new donation
                donation = self._create_new_donation(payment_data, payment_id, flow_details["metadata"])
                return donation, True

            else:
                raise ValueError(f"Unknown flow type: {flow_type}")

        except Exception as e:
            error_msg = f"Failed to find or create donation: {str(e)}"
            self.logger.error(f"❌ [{self.debug_context}] {error_msg}")
            raise

    def _create_new_donation(self, payment_data: Any, payment_id: str, metadata: Dict[str, Any]) -> Any:
        """
        Create new donation from payment metadata

        Args:
            payment_data: Mollie payment object
            payment_id: Mollie payment ID
            metadata: Payment metadata

        Returns:
            New donation document
        """
        donation = frappe.new_doc("Donation")

        # Handle different Mollie amount formats
        if hasattr(payment_data.amount, "value"):
            donation.amount = float(payment_data.amount.value)
        elif isinstance(payment_data.amount, dict):
            donation.amount = float(payment_data.amount.get("value", 0))
        else:
            donation.amount = float(payment_data.amount)

        donation.payment_id = payment_id
        donation.payment_method = "Mollie"
        donation.mode_of_payment = "Mollie"
        donation.payment_status = "Completed"
        donation.donation_date = nowdate()

        # Set donation details from metadata
        if metadata.get("donation_type"):
            donation.donation_type = metadata["donation_type"]
        if metadata.get("purpose_type"):
            donation.donation_purpose_type = metadata["purpose_type"]

        # Set company - use metadata company if it exists, otherwise use settings default
        self._set_donation_company(donation, metadata)

        if metadata.get("donation_notes"):
            donation.notes = metadata["donation_notes"]

        # Set donor information
        if metadata.get("donor_id"):
            donation.donor = metadata["donor_id"]

        # Set recurring donation fields
        if metadata.get("subscription_interval"):
            donation.is_recurring = 1
            donation.frequency = metadata["subscription_interval"]

        # Insert donation to get auto-generated name
        donation.insert()

        # Note: The custom autoname() method will generate human-readable names automatically
        self.logger.info(
            f"✅ [{self.debug_context}] Created donation with human-readable name: {donation.name}"
        )

        return donation

    def _set_donation_company(self, donation, metadata: Dict[str, Any]) -> None:
        """Set company for donation based on metadata or defaults"""
        company_from_metadata = metadata.get("company")
        if company_from_metadata and frappe.db.exists("Company", company_from_metadata):
            donation.company = company_from_metadata
        else:
            # Use default company from settings
            verenigingen_settings = frappe.get_single("Verenigingen Settings")
            default_company = (
                verenigingen_settings.get("default_donation_company") if verenigingen_settings else None
            )
            donation.company = (
                default_company
                or frappe.defaults.get_user_default("Company")
                or frappe.db.get_single_value("Global Defaults", "default_company")
            )

    def update_donation_with_payment_details(
        self, donation, payment_id: str, is_donation_first: bool
    ) -> None:
        """
        Update donation with payment details

        Args:
            donation: Donation document
            payment_id: Mollie payment ID
            is_donation_first: Whether this is donation-first flow
        """
        try:
            if is_donation_first:
                # Update existing donation with payment details
                donation.payment_id = payment_id
                donation.payment_status = "Completed"
                donation.mode_of_payment = "Mollie"
                # Don't overwrite the amount - it should already be set correctly

                donation.save()
                self.logger.info(
                    f"✅ [{self.debug_context}] Updated donation-first donation {donation.name} with payment details"
                )

        except Exception as e:
            self.logger.error(
                f"❌ [{self.debug_context}] Failed to update donation with payment details: {str(e)}"
            )
            raise

    def update_donation_with_mollie_ids(self, donation, mollie_ids: Dict[str, Optional[str]]) -> None:
        """
        Update donation with Mollie IDs (customer, mandate, subscription)

        Args:
            donation: Donation document
            mollie_ids: Dict with customer_id, mandate_id, subscription_id
        """
        try:
            donation_updated = False

            if mollie_ids.get("mandate_id"):
                donation.mollie_mandate_id = mollie_ids["mandate_id"]
                donation_updated = True

            if mollie_ids.get("customer_id"):
                donation.mollie_customer_id = mollie_ids["customer_id"]
                donation_updated = True

            if mollie_ids.get("subscription_id"):
                donation.mollie_subscription_id = mollie_ids["subscription_id"]
                donation_updated = True

            if donation_updated:
                donation.save()
                self.logger.info(
                    f"✅ [{self.debug_context}] Updated donation {donation.name} with Mollie IDs: customer={mollie_ids.get('customer_id')}, mandate={mollie_ids.get('mandate_id')}, subscription={mollie_ids.get('subscription_id')}"
                )

        except Exception as e:
            self.logger.error(f"❌ [{self.debug_context}] Failed to update donation with Mollie IDs: {str(e)}")
            # Don't raise - this is non-critical

    def validate_donation_compatibility(self, flow_type: str) -> Dict[str, Any]:
        """
        Validate that the donation flow is compatible with our system

        Args:
            flow_type: Type of donation flow

        Returns:
            Validation result dict
        """
        if flow_type == "unknown":
            return {"status": "ignored", "message": "Not a donation-related payment"}

        if flow_type not in ["payment_first", "donation_first"]:
            return {"status": "error", "message": f"Unsupported donation flow type: {flow_type}"}

        return {"status": "valid", "message": "Flow type is supported"}
