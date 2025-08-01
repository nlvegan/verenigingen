# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, add_years, date_diff, flt, get_datetime, getdate


class PeriodicDonationAgreement(Document):
    def validate(self):
        self.calculate_end_date()
        self.calculate_payment_amount()
        self.validate_dates()
        self.validate_annual_amount()
        # Store original ANBI eligibility claim before any auto-updates
        original_anbi_claim = self.anbi_eligible
        self.validate_anbi_eligibility()  # Validate ANBI business rules first
        self.update_anbi_eligibility()  # Then update eligibility based on system rules
        # If user claimed ANBI but system determined not eligible, validate the claim
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
            org_anbi_status = frappe.db.get_single_value(
                "Verenigingen Settings", "organization_has_anbi_status"
            )
            if org_anbi_status:
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
        """Send confirmation email to donor"""
        try:
            donor = frappe.get_doc("Donor", self.donor)

            if donor.donor_email:
                frappe.sendmail(
                    recipients=[donor.donor_email],
                    subject=_("Periodic Donation Agreement Confirmation - {0}").format(self.agreement_number),
                    message=self.get_confirmation_email_content(),
                    reference_doctype=self.doctype,
                    reference_name=self.name,
                )
        except Exception as e:
            frappe.log_error(
                f"Failed to send agreement confirmation: {str(e)}", "Periodic Donation Agreement Email Error"
            )

    def send_expiry_notification(self, days_remaining):
        """Send expiry notification to donor"""
        try:
            donor = frappe.get_doc("Donor", self.donor)

            if donor.donor_email:
                frappe.sendmail(
                    recipients=[donor.donor_email],
                    subject=_("Periodic Donation Agreement Expiring Soon - {0}").format(
                        self.agreement_number
                    ),
                    message=self.get_expiry_email_content(days_remaining),
                    reference_doctype=self.doctype,
                    reference_name=self.name,
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
                "date": donation.date,
                "amount": donation.amount,
                "status": "Paid" if donation.paid else "Unpaid",
            },
        )

        self.save()

        # Update donation with agreement reference
        donation.db_set("periodic_donation_agreement", self.name)

        return True

    @frappe.whitelist()
    def cancel_agreement(self, reason=None):
        """Cancel the agreement"""
        if self.status == "Cancelled":
            frappe.throw(_("Agreement is already cancelled"))

        self.status = "Cancelled"
        self.cancellation_date = frappe.utils.today()
        self.cancellation_reason = reason or _("Cancelled by donor request")
        self.cancellation_processed_by = frappe.session.user

        self.save()

        # Send cancellation confirmation
        self.send_cancellation_confirmation()

        return True

    def send_cancellation_confirmation(self):
        """Send cancellation confirmation to donor"""
        try:
            donor = frappe.get_doc("Donor", self.donor)

            if donor.donor_email:
                frappe.sendmail(
                    recipients=[donor.donor_email],
                    subject=_("Periodic Donation Agreement Cancelled - {0}").format(self.agreement_number),
                    message=f"""
                    <p>Dear {self.donor_name},</p>

                    <p>Your periodic donation agreement ({self.agreement_number}) has been cancelled
                    as requested.</p>

                    <p><strong>Cancellation Date:</strong> {frappe.utils.formatdate(self.cancellation_date)}</p>

                    <p>Thank you for your past support. If you wish to set up a new agreement in the
                    future, we would be happy to assist you.</p>

                    <p>With gratitude,<br>
                    Your Organization</p>
                    """,
                    reference_doctype=self.doctype,
                    reference_name=self.name,
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
        """Validate ANBI eligibility based on comprehensive business rules"""
        # Always validate basic business rules regardless of ANBI flag
        # This prevents data integrity issues

        # First validate basic agreement requirements
        if not self.donor:
            frappe.throw(_("Donor is required for all agreements"))

        if not self.annual_amount or self.annual_amount <= 0:
            frappe.throw(_("Valid annual amount is required"))

        # If not claiming ANBI benefits, skip ANBI-specific validation
        if not self.anbi_eligible:
            return

        # 1. Check if ANBI functionality is enabled in system (fail-closed)
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        if anbi_enabled is None:
            frappe.throw(
                _(
                    "ANBI functionality is not configured in system settings. Please contact administrator to configure ANBI settings."
                )
            )
        if not anbi_enabled:
            frappe.throw(
                _("ANBI functionality is disabled in system settings. Please contact administrator.")
            )

        # 2. Check organization has valid ANBI registration (fail-closed)
        org_anbi_status = frappe.db.get_single_value("Verenigingen Settings", "organization_has_anbi_status")
        if org_anbi_status is None:
            frappe.throw(
                _(
                    "Organization ANBI status is not configured in system settings. Please contact administrator to configure ANBI registration status."
                )
            )
        if org_anbi_status is False:
            frappe.throw(
                _("Organization does not have valid ANBI registration. ANBI tax benefits cannot be offered.")
            )

        # 3. Validate donor has provided ANBI consent
        if not self.donor:
            frappe.throw(_("Donor is required for ANBI agreements"))

        # Use get_doc with proper error handling
        try:
            donor_doc = frappe.get_doc("Donor", self.donor)
        except frappe.DoesNotExistError:
            frappe.throw(
                _(
                    "Donor record '{0}' not found. Please ensure donor exists before creating agreement."
                ).format(self.donor)
            )

        if not getattr(donor_doc, "anbi_consent", False):
            frappe.throw(
                _(
                    "Donor must provide ANBI consent before creating ANBI-eligible agreement. Please update donor record first."
                )
            )

        # Check if donor has required tax identifier
        donor_type = getattr(donor_doc, "donor_type", None)
        if donor_type == "Individual":
            if not getattr(donor_doc, "bsn_citizen_service_number", None):
                frappe.throw(
                    _("Individual donors require valid BSN (Citizen Service Number) for ANBI agreements")
                )
        elif donor_type == "Organization":
            if not getattr(donor_doc, "rsin_organization_tax_number", None):
                frappe.throw(
                    _("Organization donors require valid RSIN (Organization Tax Number) for ANBI agreements")
                )
        else:
            frappe.throw(_("Donor type must be 'Individual' or 'Organization' for ANBI agreements"))

        # 4. Validate duration meets ANBI requirements
        duration = self.get_agreement_duration()
        if duration != -1 and duration < 5:  # Not lifetime and less than 5 years
            frappe.throw(
                _("ANBI periodic donation agreements require minimum 5-year commitment or lifetime agreement")
            )

        # 5. Validate minimum annual amount (if any restrictions exist)
        if self.annual_amount and self.annual_amount <= 0:
            frappe.throw(_("ANBI agreements must have positive annual amount"))

        # 6. Validate agreement type supports ANBI
        if getattr(self, "agreement_type", None) and self.agreement_type not in [
            "Notarial",
            "Private Written",
        ]:
            frappe.throw(_("ANBI agreements require formal documentation (Notarial or Private Written)"))

        # 7. Check for duplicate active ANBI agreements (business rule)
        if self.status in ["Active", "Draft"]:
            existing_agreements = frappe.get_all(
                "Periodic Donation Agreement",
                filters={
                    "donor": self.donor,
                    "anbi_eligible": 1,
                    "status": ["in", ["Active", "Draft"]],
                    "name": ["!=", self.name],
                },
                fields=["name", "status"],
            )

            if existing_agreements:
                active_agreements = [ag.name for ag in existing_agreements if ag.status == "Active"]
                if active_agreements:
                    frappe.throw(
                        _(
                            "Donor already has active ANBI agreement: {0}. Only one active ANBI agreement per donor is allowed."
                        ).format(", ".join(active_agreements))
                    )

    def get_anbi_validation_status(self):
        """Get comprehensive ANBI validation status for UI feedback"""
        if not self.anbi_eligible:
            return {"valid": True, "message": "Agreement does not claim ANBI benefits", "warnings": []}

        warnings = []
        errors = []

        # Check each validation rule and collect issues
        try:
            # Bulk fetch system settings to avoid multiple queries
            settings_values = frappe.db.get_singles_dict(
                "Verenigingen Settings", ["enable_anbi_functionality", "organization_has_anbi_status"]
            )

            anbi_enabled = settings_values.get("enable_anbi_functionality")
            org_anbi_status = settings_values.get("organization_has_anbi_status")

            if anbi_enabled is None:
                errors.append("ANBI functionality not configured in system")
            elif not anbi_enabled:
                errors.append("ANBI functionality disabled in system")

            if org_anbi_status is None:
                warnings.append("Organization ANBI status not configured")
            elif org_anbi_status is False:
                errors.append("Organization does not have ANBI registration")

            # Donor validation - use get_value for specific fields only
            if self.donor:
                donor_fields = frappe.db.get_value(
                    "Donor",
                    self.donor,
                    [
                        "anbi_consent",
                        "donor_type",
                        "bsn_citizen_service_number",
                        "rsin_organization_tax_number",
                    ],
                    as_dict=True,
                )

                if not donor_fields:
                    errors.append("Donor record not found")
                else:
                    if not donor_fields.get("anbi_consent"):
                        errors.append("Donor has not provided ANBI consent")

                    donor_type = donor_fields.get("donor_type")
                    if donor_type == "Individual" and not donor_fields.get("bsn_citizen_service_number"):
                        errors.append("Individual donor missing BSN")
                    elif donor_type == "Organization" and not donor_fields.get(
                        "rsin_organization_tax_number"
                    ):
                        errors.append("Organization donor missing RSIN")

            # Duration validation
            duration = self.get_agreement_duration()
            if duration != -1 and duration < 5:
                errors.append(f"Duration ({duration} years) below ANBI minimum (5 years)")

            # Amount validation
            if not self.annual_amount or self.annual_amount <= 0:
                errors.append("Invalid annual amount")

        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "message": "ANBI validation passed"
            if len(errors) == 0
            else f"{len(errors)} validation errors found",
        }

    def update_anbi_eligibility(self):
        """Update ANBI eligibility based on duration and organization status"""
        # Check if ANBI functionality is enabled
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        if not anbi_enabled:
            self.anbi_eligible = 0
            return

        duration = self.get_agreement_duration()

        # Check if organization has ANBI status
        has_anbi_status = frappe.db.get_single_value("Verenigingen Settings", "organization_has_anbi_status")
        if has_anbi_status is None:
            has_anbi_status = True  # Default to True if not set

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
        """Validate when user claims ANBI but system rules prevent it"""
        # Check why the system determined ANBI is not eligible
        anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")
        org_anbi_status = frappe.db.get_single_value("Verenigingen Settings", "organization_has_anbi_status")
        duration = self.get_agreement_duration()

        if not anbi_enabled:
            frappe.throw(
                _("Cannot claim ANBI tax benefits: ANBI functionality is disabled in system settings")
            )
        elif org_anbi_status is False:
            frappe.throw(
                _("Cannot claim ANBI tax benefits: Organization does not have valid ANBI registration")
            )
        elif duration != -1 and duration < 5:
            frappe.throw(
                _(
                    "Cannot claim ANBI tax benefits: Agreement duration ({0} years) is below minimum requirement of 5 years"
                ).format(duration)
            )
