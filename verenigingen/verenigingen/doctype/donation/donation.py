# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""
Donation DocType Implementation

This module implements the Donation DocType for the Verenigingen association
management system. It handles donation processing, validation, and integration
with donor management, financial systems, and ANBI tax-exempt status requirements.

Key Features:
    - Comprehensive donation processing and validation
    - Integration with donor management system
    - ANBI (Dutch tax-exempt) compliance and validation
    - Periodic donation agreement management
    - Payment method validation and processing
    - Automatic donor creation for website users
    - Donation purpose and category management

Business Logic:
    - Automatic donor creation for anonymous website donations
    - ANBI agreement validation for tax-exempt donations
    - Periodic donation agreement enforcement
    - Payment method dependency validation
    - Donation purpose categorization and validation
    - Integration with financial reporting systems

Compliance Features:
    - ANBI (Algemeen Nut Beogende Instelling) compliance
    - Dutch tax regulation compliance for charitable donations
    - Privacy protection for anonymous donations
    - Financial audit trail requirements
    - Data protection (GDPR) compliance

Architecture:
    - Document-based with comprehensive validation hooks
    - Integration with Donor DocType for relationship management
    - Website form integration for public donations
    - Payment system integration for processing
    - Financial system integration for accounting

Validation Rules:
    - Donor existence validation with automatic creation fallback
    - Payment method compatibility validation
    - ANBI agreement requirement validation
    - Periodic donation agreement validation
    - Donation purpose validation and categorization

Integration Points:
    - Donor DocType for donor relationship management
    - Verenigingen Settings for configuration management
    - Payment systems for donation processing
    - Financial reporting and accounting systems
    - Website forms for public donation collection
    - ANBI reporting systems for tax compliance

Author: Verenigingen Development Team
License: MIT
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from verenigingen.utils.security.api_security_framework import (
    OperationType,
    critical_api,
    high_security_api,
    standard_api,
)


class Donation(Document):
    def validate(self):
        # MariaDB permits many NULLs in a unique index but only one '', and most
        # donations have no Mollie payment at all, so an empty payment_id must be
        # absent rather than blank.
        #
        # This is defence-in-depth, not the mechanism: because payment_id is
        # declared unique, base_document.get_valid_dict() already maps '' to None
        # on the way to the database (verified with bank_reference, an otherwise
        # identical non-unique Data field, which keeps its ''). What this line
        # adds is the in-memory doc: later hooks and any code reading
        # self.payment_id after validate() see None rather than ''. It is also
        # what keeps the invariant true if the unique flag is ever removed.
        #
        # It does NOT cover db_set() callers, which bypass both validate() and
        # get_valid_dict() and must pass None themselves.
        # See patches/v2_2/enforce_unique_donation_payment_id.
        if not self.payment_id:
            self.payment_id = None

        if not self.donor or not frappe.db.exists("Donor", self.donor):
            # for web forms
            user_type = frappe.db.get_value("User", frappe.session.user, "user_type")
            if user_type == "Website User":
                self.create_donor_for_website_user()
            else:
                frappe.throw(_("Please select a Donor"))

        # Validate payment method dependencies
        self.validate_payment_method()
        self.validate_payment_rows()

        # Validate ANBI agreement requirements
        self.validate_anbi_agreement()

        # Validate periodic donation agreement
        self.validate_periodic_donation_agreement()

        # Validate donation purpose fields
        self.validate_donation_purpose()

    def create_donor_for_website_user(self):
        from verenigingen.services.donation.donor_service import get_donor_by_email

        existing_donor = get_donor_by_email(frappe.session.user)
        donor_name = existing_donor.name if existing_donor else None

        if not donor_name:
            user = frappe.get_doc("User", frappe.session.user)
            donor = frappe.get_doc(
                dict(
                    doctype="Donor",
                    donor_type=self.get("donor_type"),
                    email=frappe.session.user,
                    member_name=user.get_fullname(),
                )
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            from verenigingen.utils.secure_operations import secure_document_operation

            # Secure donor creation with explicit permission validation
            donor_result = secure_document_operation(
                operation="insert",
                doc=donor,
                justification=f"Automated donor creation for donation by {frappe.session.user}",
                required_permissions=["Donor:create"],
            )

            if not donor_result.success:
                frappe.logger().error(f"Failed to create donor: {'; '.join(donor_result.errors)}")
                frappe.throw(_("Failed to create donor record: {0}").format("; ".join(donor_result.errors)))
            donor_name = donor.name

        if self.get("__islocal"):
            self.donor = donor_name

    def on_payment_authorized(self, *args, **kwargs):
        """Called when payment is authorized (legacy hook - payment-first system doesn't use this)"""
        self.db_set("paid", 1)
        self.load_from_db()

    def validate_payment_method(self):
        """Validate payment method specific requirements"""
        if self.mode_of_payment == "SEPA Direct Debit" and self.status in ["Promised", "Recurring"]:
            if not getattr(self, "sepa_mandate", None):
                frappe.msgprint(_("SEPA mandate is recommended for recurring donations"), indicator="yellow")

        if self.mode_of_payment == "Bank Transfer" and not getattr(self, "bank_reference", None):
            if self.paid:
                frappe.msgprint(
                    _("Bank reference is recommended for tracking bank transfers"), indicator="yellow"
                )

    def validate_payment_rows(self):
        """Enforce the rule `Donation Payment.validate()` stated but never ran.

        Donation Payment is a child table (`"istable": 1`), so Frappe never calls
        its own validate() -- see #596. Its `amount > 0` check is deliberately NOT
        ported: production appends NEGATIVE amounts for refunds/reversals (see
        donation_payment.py), and reviving it here would reject those. The
        Mollie-requires-mollie_payment_id check had no other enforcement and is
        not violated by anything today, but nothing guaranteed that either.
        """
        for row in self.payments or []:
            if row.payment_method == "Mollie" and not row.mollie_payment_id:
                frappe.throw(_("Row {0}: Mollie Payment ID is required for Mollie payments").format(row.idx))

    def validate_anbi_agreement(self):
        """Validate ANBI agreement fields"""
        anbi_number = getattr(self, "anbi_agreement_number", None)
        anbi_date = getattr(self, "anbi_agreement_date", None)

        if anbi_number and not anbi_date:
            frappe.throw(_("ANBI Agreement Date is required when ANBI Agreement Number is provided"))

        if anbi_date and not anbi_number:
            frappe.throw(_("ANBI Agreement Number is required when ANBI Agreement Date is provided"))

    def validate_periodic_donation_agreement(self):
        """Validate periodic donation agreement link"""
        if hasattr(self, "periodic_donation_agreement") and self.periodic_donation_agreement:
            # Check if agreement exists and is active
            agreement = frappe.get_doc("Periodic Donation Agreement", self.periodic_donation_agreement)

            # Verify donor matches
            if agreement.donor != self.donor:
                frappe.throw(_("Donation donor does not match agreement donor"))

            # Check agreement status
            if agreement.status not in ["Active", "Completed"]:
                frappe.throw(_("Cannot link donation to {0} agreement").format(agreement.status))

            # Auto-populate ANBI fields if not set
            if not self.anbi_agreement_number and agreement.agreement_number:
                self.anbi_agreement_number = agreement.agreement_number

            if not self.anbi_agreement_date and agreement.agreement_date:
                self.anbi_agreement_date = agreement.agreement_date

            # Set donation status as recurring if not already set
            if not self.status or self.status == "One-time":
                self.status = "Recurring"

            # Donations under a periodic agreement (ANBI or pledge) are always
            # reportable to the Belastingdienst.
            self.belastingdienst_reportable = 1

        elif not self.is_new():
            # The agreement link was removed — clear the flag we auto-set when
            # it was linked. Only do this on the unlink transition so a manual
            # tick on a never-linked donation is left untouched.
            before = self.get_doc_before_save()
            if before and before.get("periodic_donation_agreement"):
                self.belastingdienst_reportable = 0

    def generate_anbi_report_data(self):
        """
        Generate data for ANBI reporting to Belastingdienst

        Note: ANBI reporting is handled via the separate ANBI Donation Agreement DocType.
        This method provides basic donation data for backward compatibility but actual
        ANBI compliance tracking should use the dedicated ANBI Agreement system.
        """
        if not self.anbi_agreement_number:
            return None

        donor_doc = frappe.get_doc("Donor", self.donor)
        return {
            "donation_id": self.name,
            "anbi_agreement_number": self.anbi_agreement_number,
            "anbi_agreement_date": self.anbi_agreement_date,
            "donation_date": self.donation_date,
            "amount": self.amount,
            "donor_name": donor_doc.donor_name,
            "donor_email": getattr(donor_doc, "donor_email", ""),
            # The Donation DocType has no `donation_type` field (it was removed);
            # mirror the reporting service's dict-based variant which uses a
            # tolerant .get() so this stays None instead of raising AttributeError.
            "donation_type": getattr(self, "donation_type", None),
        }

    def validate_donation_purpose(self):
        """Validate donation purpose and earmarking fields"""
        purpose_type = getattr(self, "donation_purpose_type", "General")
        campaign_ref = getattr(self, "campaign", None)
        chapter_ref = getattr(self, "chapter_reference", None)
        goal_desc = getattr(self, "specific_goal_description", None)

        # For Campaign purpose type, we allow the campaign reference to be stored in notes
        # if the actual Donation Campaign doesn't exist yet
        # This is handled in the donate.py submission logic
        if purpose_type == "Campaign" and not campaign_ref:
            # Check if there's a campaign reference in the notes (fallback for non-existent campaigns)
            # Look for "Campaign:" prefix which is how we store non-existent campaign references
            notes_check = self.donation_notes and "Campaign:" in self.donation_notes
            if not notes_check:
                frappe.throw(_("Campaign Reference is required when Purpose Type is Campaign"))

        if purpose_type == "Chapter" and not chapter_ref:
            frappe.throw(_("Chapter is required when Purpose Type is Chapter"))

        if purpose_type == "Specific Goal" and not goal_desc:
            # For public donation forms, gracefully fall back to General purpose if no description provided
            if frappe.session.user == "Guest" or not frappe.has_permission("Donation", "write"):
                self.donation_purpose_type = "General"
                frappe.msgprint(
                    _("Donation purpose changed to General as no specific goal description was provided"),
                    alert=True,
                )
            else:
                frappe.throw(_("Specific Goal Description is required when Purpose Type is Specific Goal"))

        # Validate chapter exists if specified
        if chapter_ref and not frappe.db.exists("Chapter", chapter_ref):
            frappe.throw(_("Invalid Chapter reference: {0}").format(chapter_ref))

    def get_earmarking_summary(self):
        """Get a summary of how this donation is earmarked"""
        if self.donation_purpose_type == "General":
            return "General Fund"
        elif self.donation_purpose_type == "Campaign":
            return f"Campaign: {self.campaign}"
        elif self.donation_purpose_type == "Chapter":
            chapter_name = frappe.db.get_value("Chapter", self.chapter_reference, "name")
            return f"Chapter: {chapter_name or self.chapter_reference}"
        elif self.donation_purpose_type == "Specific Goal":
            return (
                f"Specific Goal: {self.specific_goal_description[:50]}..."
                if len(self.specific_goal_description) > 50
                else f"Specific Goal: {self.specific_goal_description}"
            )
        else:
            # donation_category field may not exist - use getattr for safety
            return getattr(self, "donation_category", None) or "Unspecified"

    def after_insert(self):
        """Called after donation is created"""
        # A donation created from a Mollie subscription charge is not a new
        # donation from the donor's point of view -- they were thanked when they
        # set the subscription up. The per-period receipt is
        # send_payment_confirmation_email, which on_update still sends. Guarding
        # on the field rather than a flag means no future insert path can
        # forget it.
        if self.recurring_origin_donation:
            return

        # Send confirmation email for new donations using EmailService
        frappe.enqueue(
            "verenigingen.verenigingen.doctype.donation.donation.send_donation_confirmation_email",
            donation_id=self.name,
            queue="short",
            timeout=300,
        )

    def on_update(self):
        """Called when donation is updated"""
        # Send payment confirmation if marked as paid for first time using EmailService
        if self.paid and self.has_value_changed("paid"):
            frappe.enqueue(
                "verenigingen.verenigingen.doctype.donation.donation.send_payment_confirmation_email",
                donation_id=self.name,
                queue="short",
                timeout=300,
            )


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_donation_from_bank_transfer(donor: str, amount, date, bank_reference, donation_type=None):
    """Create donation from bank transfer details (payment-first architecture)"""
    from verenigingen.services.donation.financial_service import DonationFinancialService

    return DonationFinancialService().create_donation_from_bank_transfer(
        donor=donor, amount=amount, date=date, bank_reference=bank_reference, donation_type=donation_type
    )


def get_donor_by_email(email):
    """
    Get donor by email address.

    .. deprecated:: 1.0
        Use :func:`verenigingen.services.donation.donor_service.get_donor_by_email` instead.
        This wrapper is kept for backward compatibility only.
    """
    import warnings

    warnings.warn(
        "donation.get_donor_by_email() is deprecated. "
        "Use verenigingen.services.donation.donor_service.get_donor_by_email() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    from verenigingen.services.donation.donor_service import get_donor_by_email as _get_donor_func

    return _get_donor_func(email)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def create_donor_from_donation(donor_name: str, email: str, phone=None, donor_type: str = None):
    """Create a new donor from donation information"""
    if not donor_type:
        donor_type = frappe.db.get_single_value("Verenigingen Settings", "default_donor_type")

    donor = frappe.new_doc("Donor")
    donor.update(
        {"donor_name": donor_name, "donor_type": donor_type, "donor_email": email, "phone": phone or ""}
    )

    donor.insert()
    return donor


def get_company_for_donations():
    company = frappe.db.get_single_value("Verenigingen Settings", "company")
    if not company:
        from verenigingen.utils import get_company

        company = get_company()
    return company


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_sepa_donation(
    donor: str, amount, date, sepa_mandate, donation_type=None, recurring_frequency=None
):
    """Create donation for SEPA direct debit"""
    from verenigingen.services.donation.financial_service import DonationFinancialService

    return DonationFinancialService().create_sepa_donation(
        donor=donor,
        amount=amount,
        date=date,
        sepa_mandate=sepa_mandate,
        donation_type=donation_type,
        recurring_frequency=recurring_frequency,
    )


def create_mode_of_payment(method):
    """Create mode of payment if it doesn't exist"""
    if not frappe.db.exists("Mode of Payment", method):
        frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": method}).insert(
            ignore_mandatory=True
        )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_anbi_donations_for_reporting(from_date, to_date):
    """Get all ANBI donations requiring Belastingdienst reporting"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.get_anbi_donations_for_reporting(from_date, to_date)


@frappe.whitelist()
@critical_api(operation_type=OperationType.ADMIN)
def generate_anbi_agreement_number():
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


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_chapter(chapter: str, from_date=None, to_date=None):
    """Get all donations earmarked for a specific chapter"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.get_donations_by_chapter(chapter, from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donations_by_campaign(campaign, from_date=None, to_date=None):
    """Get all donations for a specific campaign"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.get_donations_by_campaign(campaign, from_date, to_date)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_summary_by_purpose(from_date=None, to_date=None):
    """Get donation summary grouped by purpose type"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.get_donation_summary_by_purpose(from_date, to_date)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def create_chapter_donation(donor: str, amount, chapter: str, date=None, donation_type=None, notes=None):
    """Create a donation earmarked for a specific chapter"""
    from verenigingen.services.donation.financial_service import DonationFinancialService

    return DonationFinancialService().create_chapter_donation(
        donor=donor, amount=amount, chapter=chapter, date=date, donation_type=donation_type, notes=notes
    )


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def get_donation_accounting_summary(from_date=None, to_date=None):
    """Get donation accounting summary with GL account details"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.get_donation_accounting_summary(from_date, to_date)


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def reconcile_donation_accounts():
    """Reconcile donation amounts with GL entries"""
    from verenigingen.services.donation.financial_service import DonationFinancialService

    return DonationFinancialService().reconcile_donation_accounts()


@frappe.whitelist()
@high_security_api(operation_type=OperationType.REPORTING)
def create_donation_allocation_report(chapter: str = None, from_date=None, to_date=None):
    """Create detailed allocation report for chapter or overall donations"""
    from verenigingen.services.donation.reporting_service import DonationReportingService

    service = DonationReportingService()
    return service.create_donation_allocation_report(chapter, from_date, to_date)


def update_campaign_progress(doc, method):
    """Update campaign progress when donation is created/updated"""
    if doc.campaign and doc.paid:
        from verenigingen.verenigingen.doctype.donation_campaign.donation_campaign import (
            update_campaign_progress,
        )

        update_campaign_progress(doc.campaign)


# Email sending functions using unified EmailService
def send_donation_confirmation_email(donation_id):
    """Send donation confirmation email using EmailService"""
    try:
        from verenigingen.services.communication.email_service import get_email_service

        # Verify donation exists
        if not frappe.db.exists("Donation", donation_id):
            return False

        donation = frappe.get_doc("Donation", donation_id)

        # Verify donor exists
        if not frappe.db.exists("Donor", donation.donor):
            return False

        donor = frappe.get_doc("Donor", donation.donor)
        donor_email = getattr(donor, "donor_email", "") or getattr(donor, "email", "")

        if not donor_email:
            frappe.log_error(f"No email address for donor {donor.name}", "Donation Email")
            return False

        # Prepare context
        settings = frappe.get_single("Verenigingen Settings")
        context = {
            "donation_id": donation.name,
            "donation_amount": "{:,.2f}".format(flt(donation.amount)),
            "donation_date": frappe.utils.formatdate(donation.donation_date),
            "donation_status": donation.status,
            "earmarking": (
                donation.get_earmarking_summary()
                if hasattr(donation, "get_earmarking_summary")
                else "General Fund"
            ),
            "donation_notes": donation.donation_notes or "",
            "donor_name": donor.donor_name,
            "donor_email": donor_email,
            "organization_name": frappe.defaults.get_global_default("company"),
            "organization_email": getattr(settings, "member_contact_email", ""),
        }

        # Send email via EmailService
        email_service = get_email_service()
        result = email_service.send_templated_email(
            template_name="donation_confirmation",
            recipients=[donor_email],
            context=context,
            subject_override=_("Thank you for your donation - {0}").format(donation.name),
            reference_doctype="Donation",
            reference_name=donation.name,
            notification_key="donation_confirmation",
        )

        return result.success

    except Exception as e:
        # Log error with truncated message to avoid field length issues
        error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
        frappe.log_error(f"Donation confirmation failed: {error_msg}", "Donation Email Error")
        return False


def send_payment_confirmation_email(donation_id):
    """Send payment confirmation email using EmailService"""
    try:
        from verenigingen.services.communication.email_service import get_email_service

        # Verify donation exists
        if not frappe.db.exists("Donation", donation_id):
            return False

        donation = frappe.get_doc("Donation", donation_id)

        # Verify donor exists
        if not frappe.db.exists("Donor", donation.donor):
            return False

        donor = frappe.get_doc("Donor", donation.donor)
        donor_email = getattr(donor, "donor_email", "") or getattr(donor, "email", "")

        if not donor_email:
            return False

        # Prepare context
        settings = frappe.get_single("Verenigingen Settings")
        context = {
            "donation_id": donation.name,
            "donation_amount": "{:,.2f}".format(flt(donation.amount)),
            "payment_date": frappe.utils.formatdate(donation.modified),
            "payment_method": getattr(donation, "payment_method", donation.mode_of_payment),
            "payment_reference": donation.payment_id or donation.name,
            "earmarking": (
                donation.get_earmarking_summary()
                if hasattr(donation, "get_earmarking_summary")
                else "General Fund"
            ),
            "donor_name": donor.donor_name,
            "donor_email": donor_email,
            "organization_name": frappe.defaults.get_global_default("company"),
            "organization_email": getattr(settings, "member_contact_email", ""),
        }

        # Send email via EmailService
        email_service = get_email_service()
        result = email_service.send_templated_email(
            template_name="donation_payment_confirmation",
            recipients=[donor_email],
            context=context,
            subject_override=_("Payment Received - Donation {0}").format(donation.name),
            reference_doctype="Donation",
            reference_name=donation.name,
            notification_key="donation_payment_confirmation",
        )

        return result.success

    except Exception as e:
        # Log error with truncated message to avoid field length issues
        error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
        frappe.log_error(f"Payment confirmation failed: {error_msg}", "Payment Email Error")
        return False
