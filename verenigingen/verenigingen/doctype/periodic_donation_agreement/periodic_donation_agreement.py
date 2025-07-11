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
        self.update_anbi_eligibility()  # Update ANBI eligibility before date validation
        self.validate_dates()
        self.validate_annual_amount()
        self.update_donation_tracking()
        self.set_commitment_type()

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
            # Default to 5 years for ANBI compliance
            duration_years = self.get_agreement_duration()
            self.end_date = add_years(getdate(self.start_date), duration_years)

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
        if self.start_date and self.end_date:
            if getdate(self.end_date) <= getdate(self.start_date):
                frappe.throw(_("End date must be after start date"))

            # Calculate duration in years
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
            # Extract number from options like "5 Years (ANBI)"
            duration_str = str(self.agreement_duration_years)
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

    @property
    def is_anbi_eligible(self):
        """Check if agreement is ANBI eligible based on duration and settings"""
        # Check if ANBI eligibility is explicitly set
        if hasattr(self, "anbi_eligible"):
            return self.anbi_eligible

        # Default to True for backward compatibility
        return True

    def set_commitment_type(self):
        """Set commitment type based on duration"""
        duration = self.get_agreement_duration()

        if duration >= 5 and self.is_anbi_eligible:
            self.commitment_type = "ANBI Periodic Donation Agreement"
        else:
            self.commitment_type = "Donation Pledge (No ANBI Tax Benefits)"

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

        # Only eligible if 5+ years AND organization has ANBI status
        if duration >= 5 and has_anbi_status:
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
