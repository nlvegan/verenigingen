"""
Donation Agreement DocType Implementation

This module implements the Donation Agreement DocType, which serves as the master
record for recurring and pledge-based donations. It separates the donation intent
and schedule from individual payment transactions.

Key Features:
- Recurring donation scheduling and management
- Multi-payment method support (SEPA, Mollie, Bank Transfer)
- ANBI tax exemption integration via PDA links
- Financial tracking and forecasting
- Automated transaction generation
- Payment reminder system

Business Logic:
- Agreement represents the donor's commitment/intent
- Individual Donation records represent actual transactions
- Supports income forecasting through active agreements
- Integrates with existing payment processing systems
- Maintains audit trail for all changes

Author: Verenigingen Development Team
Date: 2025-08-30
"""

from datetime import datetime

import frappe
from dateutil.relativedelta import relativedelta
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, cint, flt, getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api, standard_api


class DonationAgreement(Document):
    def validate(self):
        """Validate donation agreement before saving"""
        self.validate_dates()
        self.validate_payment_method_details()
        self.calculate_commitment_amounts()
        self.validate_anbi_settings()
        self.set_next_due_date()

    def on_submit(self):
        """Actions when agreement is submitted"""
        if self.status == "Draft":
            self.db_set("status", "Active")

        # Create initial transaction if needed
        if self.auto_create_transactions and self.agreement_type == "Recurring":
            self.create_next_donation_transaction()

    def on_update_after_submit(self):
        """Actions when submitted agreement is updated"""
        # Update financial tracking
        self.update_financial_tracking()

        # Process status changes
        if self.has_value_changed("status"):
            self.handle_status_change()

    def validate_dates(self):
        """Validate date logic"""
        if self.start_date and getdate(self.start_date) < getdate(today()):
            if self.is_new():
                # For new agreements, don't allow past start dates
                frappe.throw(_("Start Date cannot be in the past"))

        if self.end_date and self.start_date:
            if getdate(self.end_date) <= getdate(self.start_date):
                frappe.throw(_("End Date must be after Start Date"))

    def validate_payment_method_details(self):
        """Validate payment method specific fields"""
        # If SEPA mandate is specified, validate it's active
        if self.sepa_mandate:
            mandate_status = frappe.db.get_value("SEPA Mandate", self.sepa_mandate, "mandate_status")
            if mandate_status not in ["Active", "Pending"]:
                frappe.throw(_("SEPA Mandate must be Active or Pending"))

        # For recurring agreements, suggest enabling reminders if no SEPA/Mollie setup
        if self.agreement_type == "Recurring":
            if not self.sepa_mandate and not self.enable_mollie_subscription and not self.send_reminders:
                frappe.msgprint(
                    _(
                        "Consider enabling payment reminders for recurring agreements without automated payment setup"
                    ),
                    indicator="yellow",
                )

    def validate_anbi_settings(self):
        """Validate ANBI tax exemption settings"""
        if self.periodic_donation_agreement:
            # Auto-set ANBI eligibility based on PDA
            pda_doc = frappe.get_doc("Periodic Donation Agreement", self.periodic_donation_agreement)

            # Validate donor matches
            if pda_doc.donor != self.donor:
                frappe.throw(_("Donor must match the Periodic Donation Agreement"))

            # Set ANBI eligibility
            self.anbi_eligible = 1

        elif self.amount:
            # Check if amount qualifies for ANBI
            settings = frappe.get_single("Verenigingen Settings")
            min_amount = flt(getattr(settings, "anbi_minimum_reportable_amount", 500))

            # For recurring agreements, check annual amount
            if self.agreement_type == "Recurring" and self.recurring_frequency:
                # Calculate annual amount directly for validation (don't depend on status)
                if self.recurring_frequency == "1 month":
                    annual_amount = flt(self.amount) * 12
                elif self.recurring_frequency == "3 months":
                    annual_amount = flt(self.amount) * 4
                elif self.recurring_frequency == "6 months":
                    annual_amount = flt(self.amount) * 2
                elif self.recurring_frequency == "1 year":
                    annual_amount = flt(self.amount)
                else:
                    annual_amount = 0

                if annual_amount >= min_amount:
                    self.anbi_eligible = 1
            else:
                # For one-time pledges, check the pledge amount
                if flt(self.amount) >= min_amount:
                    self.anbi_eligible = 1

    def calculate_commitment_amounts(self):
        """Calculate total committed amount based on agreement terms"""
        if not self.amount:
            return

        if self.agreement_type == "One-time Pledge":
            self.total_committed_amount = flt(self.amount)

        elif self.agreement_type == "Recurring" and self.start_date:
            if not self.end_date:
                # Open-ended recurring - calculate for next 12 months for forecasting
                periods = self.get_periods_in_range(self.start_date, add_to_date(self.start_date, years=1))
            else:
                # Fixed-term recurring
                periods = self.get_periods_in_range(self.start_date, self.end_date)

            self.total_committed_amount = flt(self.amount) * periods

        else:
            self.total_committed_amount = 0

    def get_periods_in_range(self, start_date, end_date):
        """Calculate number of payment periods in date range"""
        if not self.recurring_frequency:
            return 0

        start_dt = getdate(start_date)
        end_dt = getdate(end_date)

        if self.recurring_frequency == "1 month":
            delta = relativedelta(months=1)
        elif self.recurring_frequency == "3 months":
            delta = relativedelta(months=3)
        elif self.recurring_frequency == "6 months":
            delta = relativedelta(months=6)
        elif self.recurring_frequency == "1 year":
            delta = relativedelta(years=1)
        else:
            return 0

        periods = 0
        current_date = start_dt

        while current_date <= end_dt:
            periods += 1
            current_date += delta

        return periods

    def set_next_due_date(self):
        """Set the next due date for recurring agreements"""
        if self.agreement_type != "Recurring" or not self.recurring_frequency:
            return

        if not self.next_due_date:
            # Set initial due date
            if self.start_date:
                self.next_due_date = self.start_date
            else:
                self.next_due_date = today()

    def create_next_donation_transaction(self):
        """Create the next donation transaction for this agreement"""
        if self.status != "Active" or self.agreement_type != "Recurring":
            return None

        # Check if we should create a transaction
        if self.next_due_date and getdate(self.next_due_date) > getdate(today()):
            return None  # Not due yet

        if self.end_date and getdate(self.next_due_date) > getdate(self.end_date):
            # Agreement has ended
            self.db_set("status", "Completed")
            return None

        # Create donation transaction
        donation = frappe.new_doc("Donation")
        donation.update(
            {
                "donation_agreement": self.name,
                "donor": self.donor,
                "donation_date": self.next_due_date or today(),
                "amount": self.amount,
                "donation_type": frappe.db.get_single_value("Verenigingen Settings", "default_donation_type")
                or "General",
                "donation_purpose": self.donation_purpose,
                "donation_notes": f"Generated from agreement {self.name}. {self.donor_remarks or ''}",
                "company": self.get_default_company(),
            }
        )

        # Set payment method based on available payment setup
        if self.sepa_mandate:
            donation.sepa_mandate = self.sepa_mandate
            donation.mode_of_payment = "SEPA Direct Debit"
            donation.status = "Promised"  # Will be paid when SEPA batch processes
        elif self.enable_mollie_subscription and self.mollie_subscription_id:
            donation.payment_id = self.mollie_subscription_id
            donation.mode_of_payment = "Mollie"
            donation.status = "Promised"  # Will be paid when Mollie processes
        else:
            # Default to bank transfer for manual payment
            donation.mode_of_payment = "Bank Transfer"
            donation.status = "Promised"  # Waiting for bank transfer

        # ANBI details
        if self.anbi_eligible and self.periodic_donation_agreement:
            donation.periodic_donation_agreement = self.periodic_donation_agreement
            donation.anbi_agreement_number = self.anbi_agreement_number
            donation.anbi_agreement_date = self.anbi_agreement_date
            donation.belastingdienst_reportable = 1

        # Use secure operations for creation
        from verenigingen.utils.secure_operations import secure_document_operation

        result = secure_document_operation(
            operation="insert",
            doc=donation,
            justification=f"Automatic donation creation from agreement {self.name}",
            required_permissions=["Donation:create"],
        )

        if not result.success:
            frappe.log_error(
                f"Failed to create donation from agreement {self.name}: {'; '.join(result.errors)}",
                "Donation Agreement Transaction Creation",
            )
            return None

        # Submit the donation
        submit_result = secure_document_operation(
            operation="submit",
            doc=donation,
            justification=f"Auto-submit donation from agreement {self.name}",
            required_permissions=["Donation:submit"],
        )

        if submit_result.success:
            # Update agreement tracking
            self.update_next_due_date()
            self.update_financial_tracking()

            # Send notifications if configured
            if self.notification_settings in ["Donor Only", "Both"]:
                self.send_transaction_notification(donation.name)

            frappe.db.commit()
            return donation.name
        else:
            # Use structured error logging instead of truncation
            error_summary = f"Donation submission failed for agreement {self.name}"
            error_details = {
                "agreement_id": self.name,
                "donor": self.donor,
                "amount": self.amount,
                "currency": self.currency,
                "errors": submit_result.errors,
                "context": "create_next_donation_transaction",
                "timestamp": frappe.utils.now(),
            }

            # Log with proper title and structured details
            frappe.log_error(
                message=frappe.as_json(error_details, indent=2),
                title=error_summary,
            )
            return None

    def update_next_due_date(self):
        """Update next due date based on frequency"""
        if not self.recurring_frequency or self.agreement_type != "Recurring":
            return

        current_due = getdate(self.next_due_date) if self.next_due_date else getdate(today())

        if self.recurring_frequency == "1 month":
            next_due = current_due + relativedelta(months=1)
        elif self.recurring_frequency == "3 months":
            next_due = current_due + relativedelta(months=3)
        elif self.recurring_frequency == "6 months":
            next_due = current_due + relativedelta(months=6)
        elif self.recurring_frequency == "1 year":
            next_due = current_due + relativedelta(years=1)
        else:
            return

        self.db_set("next_due_date", next_due, update_modified=False)
        self.db_set("last_processed_date", today(), update_modified=False)

    def update_financial_tracking(self):
        """Update financial tracking fields"""
        # Get all donations for this agreement
        donations = frappe.get_all(
            "Donation",
            filters={"donation_agreement": self.name, "docstatus": 1},
            fields=["amount", "paid", "donation_date"],
        )

        total_received = sum(flt(d.amount) for d in donations if d.paid)
        total_transactions = len(donations)
        last_transaction = max([getdate(d.donation_date) for d in donations]) if donations else None

        # Update tracking fields
        self.db_set("total_received_amount", total_received, update_modified=False)
        self.db_set(
            "total_outstanding_amount",
            flt(self.total_committed_amount) - total_received,
            update_modified=False,
        )
        self.db_set("total_transactions", total_transactions, update_modified=False)

        if last_transaction:
            self.db_set("last_transaction_date", last_transaction, update_modified=False)

    def handle_status_change(self):
        """Handle status changes"""
        if self.status == "Cancelled":
            # Cancel any pending donations
            pending_donations = frappe.get_all(
                "Donation", filters={"donation_agreement": self.name, "docstatus": 0, "paid": 0}
            )

            for donation in pending_donations:
                try:
                    donation_doc = frappe.get_doc("Donation", donation.name)
                    if donation_doc.docstatus == 1:
                        donation_doc.cancel()
                    else:
                        frappe.delete_doc("Donation", donation.name)
                except Exception as e:
                    frappe.log_error(f"Error cancelling donation {donation.name}: {str(e)}")

        elif self.status == "Suspended":
            # Log suspension
            frappe.log_error(
                f"Donation agreement {self.name} suspended. Reason: {self.internal_notes}",
                "Agreement Suspension",
            )

    def send_transaction_notification(self, donation_name):
        """Send notification about transaction creation"""
        # This would integrate with your email system
        # For now, just log it as info (not error)
        frappe.logger().info(
            f"Donation Agreement Notification: Transaction {donation_name} created for agreement {self.name}"
        )

    def get_default_company(self):
        """Get default company for donations"""
        company = frappe.db.get_single_value("Verenigingen Settings", "donation_company")
        if not company:
            from verenigingen.utils import get_company

            company = get_company()
        return company

    def get_projected_annual_income(self):
        """Get projected annual income from this agreement"""
        if self.status != "Active" or not self.amount:
            return 0

        if self.agreement_type == "One-time Pledge":
            return flt(self.amount) if not self.total_received_amount else 0

        elif self.agreement_type == "Recurring":
            if self.recurring_frequency == "1 month":
                return flt(self.amount) * 12
            elif self.recurring_frequency == "3 months":
                return flt(self.amount) * 4
            elif self.recurring_frequency == "6 months":
                return flt(self.amount) * 2
            elif self.recurring_frequency == "1 year":
                return flt(self.amount)

        return 0


# Utility functions
@frappe.whitelist()
@standard_api(operation_type=OperationType.FINANCIAL)
def create_donation_agreement_from_form(donor_data, agreement_data):
    """Create donation agreement from web form submission"""
    # This would be called from the enhanced donation form
    pass


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_income_forecast(months=12):
    """Get income forecast from active donation agreements"""
    active_agreements = frappe.get_all(
        "Donation Agreement",
        filters={"status": "Active", "docstatus": 1},
        fields=["name", "amount", "recurring_frequency", "agreement_type", "next_due_date"],
    )

    forecast = {"total_annual": 0, "by_month": {}, "agreements": len(active_agreements)}

    for agreement in active_agreements:
        doc = frappe.get_doc("Donation Agreement", agreement.name)
        annual_income = doc.get_projected_annual_income()
        forecast["total_annual"] += annual_income

    return forecast


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def process_due_agreements():
    """Process all agreements that are due for transaction creation"""
    due_agreements = frappe.get_all(
        "Donation Agreement",
        filters={
            "status": "Active",
            "docstatus": 1,
            "agreement_type": "Recurring",
            "auto_create_transactions": 1,
            "next_due_date": ["<=", today()],
        },
    )

    results = {"processed": 0, "errors": 0, "donations_created": []}

    for agreement in due_agreements:
        try:
            doc = frappe.get_doc("Donation Agreement", agreement.name)
            donation_name = doc.create_next_donation_transaction()

            if donation_name:
                results["processed"] += 1
                results["donations_created"].append(donation_name)
            else:
                results["errors"] += 1

        except Exception as e:
            frappe.log_error(
                f"Error processing agreement {agreement.name}: {str(e)}", "Agreement Processing Error"
            )
            results["errors"] += 1

    return results


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def suspend_agreement(agreement_name, reason):
    """Suspend a donation agreement"""
    doc = frappe.get_doc("Donation Agreement", agreement_name)
    doc.status = "Suspended"
    doc.internal_notes = f"{doc.internal_notes or ''}\n\nSuspended: {reason}"
    doc.save()
    return doc


@frappe.whitelist()
@standard_api(operation_type=OperationType.REPORTING)
def get_agreement_summary_for_donor(donor):
    """Get all agreements for a specific donor"""
    agreements = frappe.get_all(
        "Donation Agreement",
        filters={"donor": donor, "docstatus": 1},
        fields=[
            "name",
            "status",
            "agreement_type",
            "amount",
            "recurring_frequency",
            "total_received_amount",
            "next_due_date",
        ],
    )

    summary = {
        "agreements": agreements,
        "total_active": len([a for a in agreements if a.status == "Active"]),
        "total_committed": sum(flt(a.amount) for a in agreements if a.status == "Active"),
        "total_received": sum(flt(a.total_received_amount) for a in agreements),
    }

    return summary
