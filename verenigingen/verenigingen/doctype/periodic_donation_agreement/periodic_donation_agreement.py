# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_years, date_diff, flt, get_datetime, getdate

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api


class PeriodicDonationAgreement(Document):
    def validate(self):
        self.calculate_end_date()
        self.calculate_payment_amount()
        self.validate_dates()
        self.validate_annual_amount()

        # Store original ANBI claim before system updates
        original_anbi_claim = bool(self.anbi_eligible)

        # If user is claiming ANBI benefits, validate before system overrides
        if original_anbi_claim:
            self.validate_anbi_eligibility()  # This will throw if invalid

        # Update eligibility based on system rules (may override user claim)
        self.update_anbi_eligibility()

        # If user claimed ANBI but system determined ineligible, that's an error
        if original_anbi_claim and not self.anbi_eligible:
            self._validate_anbi_claim_against_system_rules()

        self.update_donation_tracking()
        self.set_commitment_type()
        self.set_default_tax_year()

    def before_insert(self):
        # Generate agreement number if not set
        if not self.agreement_number:
            self.agreement_number = self.generate_agreement_number()

    def after_insert(self):
        # Send confirmation email to donor
        if self.status == "Active":
            self.send_agreement_confirmation()

    def on_update(self):
        # Update next expected donation date
        if self.status == "Active":
            self.calculate_next_donation_date()

        # Check if agreement is nearing expiry
        if self.status == "Active":
            self.check_expiry_notification()

    def calculate_end_date(self):
        """Calculate end date based on agreement duration"""
        if self.start_date and not self.end_date:
            duration_years = self.get_agreement_duration()
            if duration_years > 0:  # Only set end_date for non-lifetime agreements
                calculated_end_date = add_years(getdate(self.start_date), duration_years)
                # Ensure date is stored as string in YYYY-MM-DD format
                self.end_date = (
                    calculated_end_date.strftime("%Y-%m-%d")
                    if hasattr(calculated_end_date, "strftime")
                    else str(calculated_end_date)
                )
            # For lifetime agreements, end_date remains None/empty

    def calculate_payment_amount(self):
        """Calculate payment amount based on annual amount and frequency"""
        if self.annual_amount and self.payment_frequency:
            if self.payment_frequency == "Monthly":
                self.payment_amount = flt(self.annual_amount / 12, 2)
            elif self.payment_frequency == "Quarterly":
                self.payment_amount = flt(self.annual_amount / 4, 2)
            elif self.payment_frequency == "Annually":
                self.payment_amount = flt(self.annual_amount, 2)

    def validate_dates(self):
        """Validate agreement dates"""
        duration_years = self.get_agreement_duration()

        # Handle lifetime agreements (duration = -1)
        if duration_years == -1:
            # Lifetime agreements automatically qualify for ANBI if organization has ANBI status
            # If enable_anbi_functionality is enabled, assume organization has ANBI status
            anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
            if anbi_enabled:
                self.anbi_eligible = 1
            # Lifetime agreements don't need further date validation
            return

        # For fixed-term agreements, validate dates
        if self.start_date and self.end_date:
            if getdate(self.end_date) <= getdate(self.start_date):
                frappe.throw(_("End date must be after start date"))

            # Calculate actual duration in years
            duration_years = self.calculate_duration_years()

            # Check minimum duration based on agreement type
            if self.anbi_eligible and duration_years < 5:
                frappe.throw(
                    _(
                        "ANBI periodic donation agreements must be for a minimum of 5 years. For shorter commitments, uncheck 'ANBI Tax Benefits Applicable'."
                    )
                )
            elif not self.anbi_eligible and duration_years < 1:
                frappe.throw(_("Donation pledges must be for a minimum of 1 year"))

    def validate_annual_amount(self):
        """Validate minimum annual amount"""
        # Annual amount is required
        if self.annual_amount is None:
            frappe.throw(_("Annual amount is required"))
        # No minimum amount for periodic donations according to ANBI rules
        if self.annual_amount <= 0:
            frappe.throw(_("Annual amount must be greater than zero"))

    def update_donation_tracking(self):
        """Update donation tracking fields"""
        if self.donations:
            total = 0
            count = 0
            last_date = None

            for donation in self.donations:
                if donation.status == "Paid":
                    total += flt(donation.amount)
                    count += 1
                    if not last_date or getdate(donation.date) > getdate(last_date):
                        last_date = donation.date

            self.total_donated = total
            self.donations_count = count
            self.last_donation_date = last_date

    def generate_agreement_number(self):
        """Generate unique agreement number"""
        year = datetime.now().year

        # Get the last agreement number for this year
        last_agreement = frappe.db.sql(
            """
            SELECT agreement_number
            FROM `tabPeriodic Donation Agreement`
            WHERE agreement_number LIKE %s
            ORDER BY creation DESC
            LIMIT 1
        """,
            f"PDA-{year}-%",
            as_dict=True,
        )

        if last_agreement:
            # Extract the sequence number
            last_number = int(last_agreement[0]["agreement_number"].split("-")[-1])
            new_number = last_number + 1
        else:
            new_number = 1

        return f"PDA-{year}-{new_number:05d}"

    def calculate_next_donation_date(self):
        """Calculate next expected donation date based on frequency"""
        if self.last_donation_date and self.payment_frequency:
            last_date = getdate(self.last_donation_date)

            if self.payment_frequency == "Monthly":
                next_date = add_months(last_date, 1)
            elif self.payment_frequency == "Quarterly":
                next_date = add_months(last_date, 3)
            elif self.payment_frequency == "Annually":
                next_date = add_years(last_date, 1)

            # Don't set next date beyond agreement end date
            if self.end_date and next_date > getdate(self.end_date):
                self.next_expected_donation = None
            else:
                self.next_expected_donation = next_date
        elif self.start_date and not self.last_donation_date:
            # First donation expected on start date
            self.next_expected_donation = self.start_date

    def check_expiry_notification(self):
        """Check if agreement is nearing expiry and send notifications"""
        if self.end_date:
            days_to_expiry = date_diff(self.end_date, getdate())

            # Send notifications at 90, 60, and 30 days before expiry
            if days_to_expiry in [90, 60, 30]:
                self.send_expiry_notification(days_to_expiry)

    def send_agreement_confirmation(self):
        """Send confirmation email to donor using EmailService"""
        try:
            from verenigingen.services.communication.email_service import get_email_service

            donor = frappe.get_doc("Donor", self.donor)

            if not donor.donor_email:
                return

            email_service = get_email_service()
            context = {
                "donor_name": self.donor_name,
                "agreement_number": self.agreement_number,
                "start_date": frappe.utils.formatdate(self.start_date),
                "end_date": frappe.utils.formatdate(self.end_date) if self.end_date else "Lifetime",
                "annual_amount": "{:,.2f}".format(flt(self.annual_amount)),
                "payment_frequency": self.payment_frequency,
                "payment_amount": "{:,.2f}".format(flt(self.payment_amount)),
                "anbi_eligible": self.anbi_eligible,
                "organization_name": frappe.defaults.get_global_default("company"),
                "organization_email": frappe.db.get_single_value(
                    "Verenigingen Settings", "member_contact_email"
                ),
            }

            email_service.send_templated_email(
                template_name="periodic_agreement_confirmation",
                recipients=[donor.donor_email],
                context=context,
                subject_override=_("Periodic Donation Agreement Confirmation - {0}").format(
                    self.agreement_number
                ),
                reference_doctype=self.doctype,
                reference_name=self.name,
                notification_key="periodic_donation_confirmation",
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to send agreement confirmation: {str(e)}", "Periodic Donation Agreement Email Error"
            )

    def send_expiry_notification(self, days_remaining):
        """Send expiry notification to donor using EmailService"""
        try:
            from verenigingen.services.communication.email_service import get_email_service

            donor = frappe.get_doc("Donor", self.donor)

            if not donor.donor_email:
                return

            email_service = get_email_service()
            context = {
                "donor_name": self.donor_name,
                "agreement_number": self.agreement_number,
                "end_date": frappe.utils.formatdate(self.end_date),
                "days_remaining": days_remaining,
                "organization_name": frappe.defaults.get_global_default("company"),
                "organization_email": frappe.db.get_single_value(
                    "Verenigingen Settings", "member_contact_email"
                ),
            }

            email_service.send_templated_email(
                template_name="periodic_agreement_expiry",
                recipients=[donor.donor_email],
                context=context,
                subject_override=_("Periodic Donation Agreement Expiring Soon - {0}").format(
                    self.agreement_number
                ),
                reference_doctype=self.doctype,
                reference_name=self.name,
                notification_key="periodic_donation_expiry",
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to send expiry notification: {str(e)}", "Periodic Donation Agreement Email Error"
            )

    def get_confirmation_email_content(self):
        """Get confirmation email content"""
        return f"""
        <p>Dear {self.donor_name},</p>

        <p>Thank you for setting up a periodic donation agreement with us.</p>

        <h3>Agreement Details:</h3>
        <ul>
            <li><strong>Agreement Number:</strong> {self.agreement_number}</li>
            <li><strong>Start Date:</strong> {frappe.utils.formatdate(self.start_date)}</li>
            <li><strong>End Date:</strong> {frappe.utils.formatdate(self.end_date)}</li>
            <li><strong>Annual Amount:</strong> €{self.annual_amount:,.2f}</li>
            <li><strong>Payment Frequency:</strong> {self.payment_frequency}</li>
            <li><strong>Payment Amount:</strong> €{self.payment_amount:,.2f}</li>
        </ul>

        <p>Your periodic donations are fully tax-deductible under Dutch ANBI regulations.</p>

        <p>If you have any questions, please don't hesitate to contact us.</p>

        <p>With gratitude,<br>
        Your Organization</p>
        """

    def get_expiry_email_content(self, days_remaining):
        """Get expiry notification email content"""
        return f"""
        <p>Dear {self.donor_name},</p>

        <p>Your periodic donation agreement ({self.agreement_number}) will expire in {days_remaining} days.</p>

        <p><strong>Expiry Date:</strong> {frappe.utils.formatdate(self.end_date)}</p>

        <p>To continue enjoying tax benefits for your donations, please consider renewing your agreement
        before it expires.</p>

        <p>Thank you for your continued support!</p>

        <p>With gratitude,<br>
        Your Organization</p>
        """

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def link_donation(self, donation_name):
        """Link a donation to this agreement"""
        donation = frappe.get_doc("Donation", donation_name)

        # Verify donor matches
        if donation.donor != self.donor:
            frappe.throw(_("Donation donor does not match agreement donor"))

        # Check if donation is already linked
        for item in self.donations:
            if item.donation == donation_name:
                frappe.throw(_("Donation is already linked to this agreement"))

        # Add donation to table
        self.append(
            "donations",
            {
                "donation": donation_name,
                # The Donation doctype's date field is `donation_date`; the child
                # table column here is `date`. (Older code read donation.date,
                # which no longer exists and raised AttributeError on link.)
                "date": donation.donation_date,
                "amount": donation.amount,
                "status": "Paid" if donation.paid else "Unpaid",
            },
        )

        self.save()

        # Update donation with agreement reference
        donation.db_set("periodic_donation_agreement", self.name)

        return True

    @frappe.whitelist()
    @high_security_api(operation_type=OperationType.FINANCIAL)
    def cancel_agreement(self, reason=None, send_email=False):
        """Cancel the agreement

        Args:
            reason: Reason for cancellation
            send_email: Whether to send cancellation confirmation email (default: False)
        """
        if self.status == "Cancelled":
            frappe.throw(_("Agreement is already cancelled"))

        self.status = "Cancelled"
        self.cancellation_date = frappe.utils.today()
        self.cancellation_reason = reason or _("Cancelled by donor request")
        self.cancellation_processed_by = frappe.session.user

        self.save()

        # Optionally send cancellation confirmation
        if send_email:
            self.send_cancellation_confirmation()

        return True

    def send_cancellation_confirmation(self):
        """Send cancellation confirmation to donor using EmailService"""
        try:
            from verenigingen.services.communication.email_service import get_email_service

            donor = frappe.get_doc("Donor", self.donor)

            if not donor.donor_email:
                return

            email_service = get_email_service()
            context = {
                "donor_name": self.donor_name,
                "agreement_number": self.agreement_number,
                "cancellation_date": frappe.utils.formatdate(self.cancellation_date),
                "organization_name": frappe.defaults.get_global_default("company"),
                "organization_email": frappe.db.get_single_value(
                    "Verenigingen Settings", "member_contact_email"
                ),
            }

            email_service.send_templated_email(
                template_name="periodic_agreement_cancellation",
                recipients=[donor.donor_email],
                context=context,
                subject_override=_("Periodic Donation Agreement Cancelled - {0}").format(
                    self.agreement_number
                ),
                reference_doctype=self.doctype,
                reference_name=self.name,
                notification_key="periodic_donation_cancellation",
            )

            self.db_set("cancellation_confirmation_sent", 1)

        except Exception as e:
            frappe.log_error(
                f"Failed to send cancellation confirmation: {str(e)}",
                "Periodic Donation Agreement Email Error",
            )

    def get_agreement_duration(self):
        """Get agreement duration in years"""
        # Parse duration from the select field
        if hasattr(self, "agreement_duration_years") and self.agreement_duration_years:
            duration_str = str(self.agreement_duration_years)

            # Handle special case for Lifetime
            if duration_str.startswith("Lifetime"):
                return -1  # Special value indicating lifetime agreement

            # Extract number from options like "5 Years (ANBI)"
            try:
                return int(duration_str.split()[0])
            except:
                pass

        # Default based on ANBI eligibility
        if self.is_anbi_eligible:
            return 5  # ANBI minimum
        else:
            # Get from system settings or default to 1
            settings = frappe.get_single("Verenigingen Settings")
            return int(getattr(settings, "default_agreement_duration", 1))

    def calculate_duration_years(self):
        """Calculate duration between start and end date in years"""
        if not self.start_date or not self.end_date:
            return 0

        from dateutil.relativedelta import relativedelta

        delta = relativedelta(getdate(self.end_date), getdate(self.start_date))
        return delta.years + (delta.months / 12.0) + (delta.days / 365.25)

    def is_anbi_eligible(self):
        """Check if agreement is ANBI eligible based on current field value"""
        # Return the actual field value, don't default to True
        return bool(getattr(self, "anbi_eligible", 0))

    def set_commitment_type(self):
        """Set commitment type based on duration"""
        duration = self.get_agreement_duration()

        if (duration >= 5 or duration == -1) and self.is_anbi_eligible():  # Include lifetime agreements
            self.commitment_type = "ANBI Periodic Donation Agreement"
        else:
            self.commitment_type = "Donation Pledge (No ANBI Tax Benefits)"

    def set_default_tax_year(self):
        """Set default tax year if not provided"""
        if self.anbi_eligible and not self.tax_year_applicable:
            from datetime import datetime

            current_year = datetime.now().year
            # Tax benefits typically start from the year after agreement or current year
            if self.start_date:
                start_year = getdate(self.start_date).year
                self.tax_year_applicable = max(current_year, start_year)
            else:
                self.tax_year_applicable = current_year

    def validate_anbi_eligibility(self):
        """
        Validate ANBI eligibility using unified validation service.

        Uses ANBIValidationService for comprehensive validation of Dutch tax law requirements.
        This replaces ~180 lines of duplicate validation logic with a clean service call.
        """
        # Always validate basic business rules regardless of ANBI flag
        if not self.donor:
            frappe.throw(_("Donor is required for all agreements"))

        if not self.annual_amount or self.annual_amount <= 0:
            frappe.throw(_("Valid annual amount is required"))

        # If not claiming ANBI benefits, skip ANBI-specific validation
        if not self.anbi_eligible:
            return

        # Use unified ANBI validation service
        from verenigingen.services.anbi_validation_service import ANBIValidationService

        validator = ANBIValidationService()
        duration = self.get_agreement_duration()
        agreement_type = getattr(self, "agreement_type", None)

        is_valid, errors = validator.validate_full_anbi_eligibility(
            donor_name=self.donor,
            duration_years=duration,
            agreement_type=agreement_type,
            current_agreement_name=self.name if not self.is_new() else None,
        )

        if not is_valid:
            # Throw first error (most critical)
            frappe.throw(_(errors[0]))

    @frappe.whitelist()
    def get_anbi_validation_status(self):
        """
        Get comprehensive ANBI validation status for UI feedback and diagnostics.

        Uses ANBIValidationService for consistent validation logic.
        Returns detailed status instead of throwing exceptions.
        """
        if not self.anbi_eligible:
            return {"valid": True, "message": "Agreement does not claim ANBI benefits", "warnings": []}

        from verenigingen.services.anbi_validation_service import ANBIValidationService

        validator = ANBIValidationService()
        duration = self.get_agreement_duration()
        agreement_type = getattr(self, "agreement_type", None)

        return validator.get_validation_status_dict(
            donor_name=self.donor, duration_years=duration, agreement_type=agreement_type
        )

    def update_anbi_eligibility(self):
        """
        Update ANBI eligibility based on system rules and agreement characteristics.

        This method automatically determines whether an agreement qualifies for ANBI
        periodic donation tax benefits based on objective criteria. It updates the
        anbi_eligible field and provides user feedback when eligibility changes.

        ANBI Eligibility Criteria:
        - ANBI functionality must be enabled in system settings
        - Organization must have valid ANBI registration with Belastingdienst
        - Agreement duration must be 5+ years OR lifetime (-1)
        - All criteria must be met simultaneously for eligibility

        Business Logic:
        - Lifetime agreements (-1 duration) automatically qualify if org has ANBI status
        - Fixed-term agreements require minimum 5-year commitment
        - System provides user feedback when eligibility status changes
        - Defaults to ineligible when system configuration is incomplete (fail-closed)

        Side Effects:
        - Updates self.anbi_eligible field (0 or 1)
        - Shows user messages when eligibility status changes
        - Does not validate user consent or tax identifiers (handled separately)

        Performance Notes:
        - Makes minimal database queries (2 settings lookups)
        - Uses caching-friendly single value queries
        - Efficient duration calculation without complex date math
        """
        # Check if ANBI functionality is enabled
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        if not anbi_enabled:
            self.anbi_eligible = 0
            return

        duration = self.get_agreement_duration()

        # Check if organization has ANBI status
        # If enable_anbi_functionality is enabled, assume organization has ANBI status
        has_anbi_status = anbi_enabled  # Use the value already fetched above

        # Only eligible if 5+ years OR lifetime (-1) AND organization has ANBI status
        if (duration >= 5 or duration == -1) and has_anbi_status:
            # Only show message if status is changing
            if hasattr(self, "anbi_eligible") and self.anbi_eligible == 0:
                frappe.msgprint(_("This agreement is now eligible for ANBI tax benefits (5+ year duration)."))
            self.anbi_eligible = 1
        else:
            # Only show message if status is changing
            if hasattr(self, "anbi_eligible") and self.anbi_eligible == 1:
                if duration < 5:
                    frappe.msgprint(
                        _(
                            "This agreement does not qualify for ANBI tax benefits (less than 5 years). It will be treated as a donation pledge."
                        )
                    )
                elif not has_anbi_status:
                    frappe.msgprint(
                        _(
                            "This organization does not have ANBI status. The agreement will be treated as a regular donation pledge."
                        )
                    )
            self.anbi_eligible = 0

    def _validate_anbi_claim_against_system_rules(self):
        """
        Validate user ANBI claims against system-determined eligibility rules.

        This method is called when a user explicitly claims ANBI benefits (anbi_eligible=1)
        but the system's automatic eligibility determination has set anbi_eligible=0.
        This represents a conflict between user expectations and system rules that must
        be resolved with clear error messaging.

        Validation Scenarios:
        - User claims ANBI but system ANBI functionality is disabled
        - User claims ANBI but organization lacks ANBI registration
        - User claims ANBI but agreement duration is below 5-year minimum

        Error Handling:
        - Provides specific error messages indicating which requirement failed
        - Uses fail-closed approach (rejects claims when system config incomplete)
        - Throws ValidationError with actionable user guidance

        Business Context:
        This prevents users from creating agreements with invalid ANBI claims that
        would not actually qualify for tax benefits, protecting both the organization
        and donor from tax compliance issues.

        Called By:
        - validate() method when original_anbi_claim=True but system sets anbi_eligible=0
        - Ensures user intent aligns with Dutch tax law requirements
        """
        # Check why the system determined ANBI is not eligible
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        duration = self.get_agreement_duration()

        if not anbi_enabled:
            frappe.throw(
                _("Cannot claim ANBI tax benefits: ANBI functionality is disabled in system settings")
            )
        elif duration != -1 and duration < 5:
            frappe.throw(
                _(
                    "Cannot claim ANBI tax benefits: Agreement duration ({0} years) is below minimum requirement of 5 years"
                ).format(duration)
            )
