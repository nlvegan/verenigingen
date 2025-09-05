"""
Donation Validation Service

Handles all donation validation logic extracted from the monolithic donation controller.
Provides comprehensive validation for ANBI compliance, payment methods, and donation purposes.
"""

from typing import Any, Dict, List, Optional

import frappe
from frappe import _
from frappe.utils import flt, getdate


class DonationValidationService:
    """Service for handling donation validation logic"""

    def __init__(self, donation_doc):
        self.donation = donation_doc
        self.logger = frappe.logger()

    def validate_all(self) -> List[str]:
        """
        Run all validations and return list of validation errors

        Returns:
            List of validation error messages (empty if all valid)
        """
        errors = []

        # Check if this is a website user to apply different validation rules
        user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
        is_website_user = user_type == "Website User"

        try:
            self.validate_donor_existence()
        except frappe.ValidationError as e:
            errors.append(str(e))

        try:
            self.validate_payment_method()
        except frappe.ValidationError as e:
            if is_website_user and ("bank transfers" in str(e).lower() or "payment id" in str(e).lower()):
                # For website users, log payment method issues as warnings rather than errors
                frappe.logger().warning(f"Payment method validation warning for website user: {str(e)}")
            else:
                errors.append(str(e))

        try:
            self.validate_anbi_agreement()
        except frappe.ValidationError as e:
            errors.append(str(e))

        try:
            self.validate_periodic_donation_agreement()
        except frappe.ValidationError as e:
            errors.append(str(e))

        try:
            self.validate_donation_purpose()
        except frappe.ValidationError as e:
            if is_website_user and ("campaign" in str(e).lower() or "chapter" in str(e).lower()):
                # For website users, log purpose validation issues as warnings
                frappe.logger().warning(f"Donation purpose validation warning for website user: {str(e)}")
            else:
                errors.append(str(e))

        return errors

    def validate_donor_existence(self) -> None:
        """Validate that donor exists or can be created"""
        if not self.donation.donor or not frappe.db.exists("Donor", self.donation.donor):
            # Check if this is a website user (can auto-create donor)
            user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
            if user_type == "Website User":
                # This will be handled by donor management service
                self.logger.info("Website user donation - donor will be auto-created")
                return
            else:
                frappe.throw(_("Please select a Donor"))

    def validate_payment_method(self) -> None:
        """Validate payment method dependencies and requirements"""
        if not self.donation.mode_of_payment:
            return  # Payment method is optional in some flows

        # Validate that payment method exists
        if not frappe.db.exists("Mode of Payment", self.donation.mode_of_payment):
            frappe.throw(_("Invalid payment method: {0}").format(self.donation.mode_of_payment))

        # Validate payment method specific requirements
        payment_method = frappe.get_doc("Mode of Payment", self.donation.mode_of_payment)

        # Check if payment method requires payment ID
        if hasattr(payment_method, "requires_payment_id") and payment_method.requires_payment_id:
            if not self.donation.payment_id:
                frappe.throw(
                    _("Payment ID is required for payment method: {0}").format(self.donation.mode_of_payment)
                )

        # Validate bank transfer requirements
        if self.donation.mode_of_payment == "Bank Transfer":
            # For web form submissions, bank reference/payment ID can be optional
            # They will be provided later in the payment flow
            user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
            if (
                user_type != "Website User"
                and not self.donation.bank_reference
                and not self.donation.payment_id
            ):
                frappe.throw(_("Bank reference or payment ID is required for bank transfers"))

    def validate_anbi_agreement(self) -> None:
        """Validate ANBI (Dutch tax-exempt) agreement requirements"""
        # NOTE: ANBI fields were removed when Donation Agreement DocType was archived
        # Skip ANBI validation as the required fields no longer exist in the schema
        if not hasattr(self.donation, "anbi_eligible") or not self.donation.get("anbi_eligible"):
            return  # No ANBI validation needed

        # Check if donation amount meets ANBI minimum threshold
        verenigingen_settings = frappe.get_single("Verenigingen Settings")
        min_anbi_amount = flt(verenigingen_settings.get("minimum_anbi_donation_amount", 0))

        if min_anbi_amount > 0 and flt(self.donation.amount) < min_anbi_amount:
            frappe.throw(_("ANBI donations must be at least €{0}").format(min_anbi_amount))

        # Validate ANBI agreement fields if marked as ANBI eligible
        if hasattr(self.donation, "anbi_eligible") and self.donation.get("anbi_eligible"):
            if not self.donation.get("anbi_agreement_date"):
                frappe.throw(_("ANBI Agreement Date is required for tax-exempt donations"))

            if not self.donation.get("anbi_agreement_number"):
                # Auto-generate if not provided
                self.donation.anbi_agreement_number = self._generate_anbi_agreement_number()

            # Validate donor has given ANBI consent
            if self.donation.donor:
                donor = frappe.get_doc("Donor", self.donation.donor)
                if not getattr(donor, "anbi_consent", False):
                    frappe.throw(_("Donor must provide ANBI consent for tax-exempt donations"))

    def validate_periodic_donation_agreement(self) -> None:
        """Validate periodic donation agreement requirements"""
        if not self.donation.get("is_recurring"):
            return  # No periodic validation needed for one-time donations

        # NOTE: periodic_donation_agreement field was removed when Donation Agreement DocType was archived
        # Skip this validation as the required field no longer exists in the schema
        if not hasattr(self.donation, "periodic_donation_agreement"):
            return

        if not self.donation.get("periodic_donation_agreement"):
            frappe.throw(_("Periodic Donation Agreement is required for recurring donations"))

        # Validate the agreement exists and is active
        if not frappe.db.exists("Periodic Donation Agreement", self.donation.periodic_donation_agreement):
            frappe.throw(_("Invalid Periodic Donation Agreement"))

        agreement = frappe.get_doc("Periodic Donation Agreement", self.donation.periodic_donation_agreement)

        # Validate agreement is active
        if agreement.status != "Active":
            frappe.throw(_("Periodic Donation Agreement must be active"))

        # Validate agreement donor matches donation donor
        if agreement.donor != self.donation.donor:
            frappe.throw(_("Periodic Donation Agreement donor must match donation donor"))

        # Validate amount matches agreement (if specified in agreement)
        if hasattr(agreement, "fixed_amount") and agreement.fixed_amount:
            if flt(self.donation.amount) != flt(agreement.fixed_amount):
                frappe.throw(_("Donation amount must match Periodic Donation Agreement amount"))

    def validate_donation_purpose(self) -> None:
        """Validate donation purpose fields and categorization"""
        # Set default donation type if not provided
        if not self.donation.get("donation_purpose_type"):
            self.donation.donation_purpose_type = "General"

        # Validate purpose-specific requirements
        if self.donation.donation_purpose_type == "Campaign":
            if not self.donation.campaign:
                # For web forms, campaign may be optional or handled differently
                user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
                if user_type != "Website User":
                    frappe.throw(_("Campaign is required when donation purpose is Campaign"))
            else:
                # Check both "Campaign" and "Donation Campaign" doctypes
                campaign_exists = frappe.db.exists("Campaign", self.donation.campaign) or frappe.db.exists(
                    "Donation Campaign", self.donation.campaign
                )

                if not campaign_exists:
                    frappe.throw(_("Invalid campaign specified"))

                # If it's a regular Campaign, check if active
                if frappe.db.exists("Campaign", self.donation.campaign):
                    campaign = frappe.get_doc("Campaign", self.donation.campaign)
                    if hasattr(campaign, "campaign_status") and campaign.campaign_status != "Active":
                        frappe.throw(_("Campaign must be active to receive donations"))

        elif self.donation.donation_purpose_type == "Chapter":
            if not self.donation.chapter_reference:
                frappe.throw(_("Chapter is required when donation purpose is Chapter"))

            # Validate chapter exists
            if not frappe.db.exists("Chapter", self.donation.chapter_reference):
                frappe.throw(_("Invalid chapter specified"))

        elif self.donation.donation_purpose_type == "Project":
            if not self.donation.project:
                frappe.throw(_("Project is required when donation purpose is Project"))

            # Validate project exists
            if not frappe.db.exists("Project", self.donation.project):
                frappe.throw(_("Invalid project specified"))

        # Validate fund designation
        if self.donation.fund_designation:
            allowed_designations = self._get_allowed_fund_designations()
            if self.donation.fund_designation not in allowed_designations:
                frappe.throw(_("Invalid fund designation: {0}").format(self.donation.fund_designation))

    def validate_business_rules(self) -> None:
        """Validate business-specific rules and constraints"""
        # Validate donation date is not in future
        if self.donation.donation_date and getdate(self.donation.donation_date) > getdate():
            frappe.throw(_("Donation date cannot be in the future"))

        # Validate amount is positive
        if flt(self.donation.amount) <= 0:
            frappe.throw(_("Donation amount must be greater than zero"))

        # Validate currency if specified
        if hasattr(self.donation, "currency") and self.donation.currency:
            if not frappe.db.exists("Currency", self.donation.currency):
                frappe.throw(_("Invalid currency specified"))

    def _generate_anbi_agreement_number(self) -> str:
        """Generate next ANBI agreement number"""
        # Get the latest ANBI agreement number
        latest = frappe.db.sql(
            """
            SELECT anbi_agreement_number
            FROM `tabDonation`
            WHERE anbi_agreement_number IS NOT NULL
            ORDER BY creation DESC
            LIMIT 1
        """
        )

        if latest and latest[0][0]:
            try:
                # Extract number from format like "ANBI-2024-001"
                parts = latest[0][0].split("-")
                if len(parts) >= 3:
                    year = parts[1]
                    num = int(parts[2]) + 1
                else:
                    year = str(getdate().year)
                    num = 1
            except Exception:
                year = str(getdate().year)
                num = 1
        else:
            year = str(getdate().year)
            num = 1

        return f"ANBI-{year}-{num:03d}"

    def _get_allowed_fund_designations(self) -> List[str]:
        """Get list of allowed fund designations from settings"""
        settings = frappe.get_single("Verenigingen Settings")
        if hasattr(settings, "allowed_fund_designations") and settings.allowed_fund_designations:
            return [d.strip() for d in settings.allowed_fund_designations.split(",")]

        # Default fund designations
        return [
            "General Fund",
            "Emergency Fund",
            "Campaign Fund",
            "Chapter Fund",
            "Project Fund",
            "Research Fund",
        ]

    def get_validation_context(self) -> Dict[str, Any]:
        """Get validation context for debugging and reporting"""
        return {
            "donation_id": self.donation.name,
            "donor": self.donation.donor,
            "amount": self.donation.amount,
            "payment_method": self.donation.mode_of_payment,
            "is_anbi": self.donation.get("anbi_eligible", False),
            "is_recurring": self.donation.is_recurring,
            "purpose_type": self.donation.donation_purpose_type,
            "user_type": frappe.db.get_value("User", frappe.session.user, "user_type"),
        }
