# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe.model.document import Document
from frappe.utils import add_days, add_months, add_years, flt, getdate, today


class MembershipDuesSchedule(Document):
    def validate(self):
        self.validate_member_membership()
        self.validate_dates()
        self.set_amount_from_membership_type()

    def validate_member_membership(self):
        """Ensure the membership belongs to the member"""
        if self.membership and self.member:
            membership_member = frappe.db.get_value("Membership", self.membership, "member")
            if membership_member != self.member:
                frappe.throw(f"Membership {self.membership} does not belong to Member {self.member}")

    def validate_dates(self):
        """Validate schedule dates"""
        if self.last_invoice_date and self.next_invoice_date:
            if getdate(self.last_invoice_date) >= getdate(self.next_invoice_date):
                frappe.throw("Next Invoice Date must be after Last Invoice Date")

    def set_amount_from_membership_type(self):
        """Set amount based on membership type if not already set"""
        if not self.amount and self.membership_type:
            # Get the fee from membership type
            membership_type_doc = frappe.get_doc("Membership Type", self.membership_type)
            if hasattr(membership_type_doc, "amount"):
                self.amount = membership_type_doc.amount
            elif hasattr(membership_type_doc, "fee"):
                self.amount = membership_type_doc.fee

    def can_generate_invoice(self):
        """Check if invoice can be generated"""
        if self.status != "Active":
            return False, "Schedule is not active"

        if not self.auto_generate:
            return False, "Auto generation is disabled"

        if self.test_mode:
            return True, "Test mode - can generate"

        # Check if it's time to generate invoice
        days_before = self.invoice_days_before or 30
        generate_on_date = add_days(self.next_invoice_date, -days_before)

        if getdate(today()) < getdate(generate_on_date):
            return False, f"Too early - will generate on {generate_on_date}"

        # Check if invoice already exists for this period
        if self.last_invoice_date == self.next_invoice_date:
            return False, "Invoice already generated for this period"

        return True, "Can generate invoice"

    def generate_invoice(self, force=False):
        """Generate invoice for the current period"""
        can_generate, reason = self.can_generate_invoice()

        if not can_generate and not force:
            frappe.log_error(f"Cannot generate invoice: {reason}", f"Membership Dues Schedule {self.name}")
            return None

        if self.test_mode:
            # In test mode, just log and update dates
            frappe.logger().info(
                f"TEST MODE: Would generate invoice for {self.member} - Amount: {self.amount}"
            )
            self.update_schedule_dates()
            return "TEST_INVOICE"

        # Create actual invoice
        invoice = self.create_sales_invoice()

        # Update schedule
        self.update_schedule_dates()

        # Payment history is automatically tracked via the Member Payment History table
        # when the invoice is created with the customer (member) reference

        return invoice

    def create_sales_invoice(self):
        """Create a sales invoice for membership dues"""
        # Get member details
        member = frappe.get_doc("Member", self.member)

        # Create invoice
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = self.member
        invoice.due_date = self.next_invoice_date
        invoice.posting_date = today()

        # Set payment terms if specified
        if self.payment_terms_template:
            invoice.payment_terms_template = self.payment_terms_template

        # Add membership dues item
        invoice.append(
            "items",
            {
                "item_code": self.get_membership_dues_item(),
                "qty": 1,
                "rate": self.amount,
                "description": self.get_invoice_description(),
            },
        )

        # Add reference to this schedule (as a custom field or in remarks)
        invoice.remarks = (
            f"Generated from Membership Dues Schedule: {self.name}\n{self.get_invoice_description()}"
        )

        # Save and optionally submit
        invoice.insert()

        # Auto-submit if configured
        if frappe.db.get_single_value("Verenigingen Settings", "auto_submit_membership_invoices"):
            invoice.submit()

        return invoice.name

    def get_membership_dues_item(self):
        """Get or create the membership dues item"""
        item_name = f"Membership Dues - {self.billing_frequency}"

        if not frappe.db.exists("Item", item_name):
            item = frappe.new_doc("Item")
            item.item_code = item_name
            item.item_name = item_name
            item.item_group = "Services"
            item.is_sales_item = 1
            item.is_service_item = 1
            item.insert()

        return item_name

    def get_invoice_description(self):
        """Generate invoice description"""
        period_start = self.last_invoice_date or self.next_invoice_date
        period_end = self.calculate_next_date(self.next_invoice_date)

        return f"Membership dues for {self.member_name} ({self.membership_type}) - Period: {period_start} to {period_end}"

    def update_schedule_dates(self):
        """Update schedule dates after invoice generation"""
        self.last_invoice_date = self.next_invoice_date
        self.next_invoice_date = self.calculate_next_date(self.next_invoice_date)
        self.save()

    def calculate_next_date(self, from_date):
        """Calculate next invoice date based on billing frequency"""
        from_date = getdate(from_date)

        frequency_map = {
            "Annual": lambda d: add_years(d, 1),
            "Semi-Annual": lambda d: add_months(d, 6),
            "Quarterly": lambda d: add_months(d, 3),
            "Monthly": lambda d: add_months(d, 1),
        }

        if self.billing_frequency in frequency_map:
            return frequency_map[self.billing_frequency](from_date)
        else:
            # Custom frequency - default to annual
            return add_years(from_date, 1)

    def pause_schedule(self, reason=None):
        """Pause the dues schedule"""
        self.status = "Paused"
        if reason:
            self.notes = (
                f"{self.notes}\n\nPaused on {today()}: {reason}"
                if self.notes
                else f"Paused on {today()}: {reason}"
            )
        self.save()

    def resume_schedule(self, new_next_date=None):
        """Resume the dues schedule"""
        self.status = "Active"
        if new_next_date:
            self.next_invoice_date = new_next_date
        self.notes = f"{self.notes}\n\nResumed on {today()}" if self.notes else f"Resumed on {today()}"
        self.save()


@frappe.whitelist()
def generate_dues_invoices(test_mode=False):
    """Scheduled job to generate membership dues invoices"""

    # Get all active schedules that need processing
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "auto_generate": 1, "next_invoice_date": ["<=", add_days(today(), 30)]},
        pluck="name",
    )

    results = {"processed": 0, "generated": 0, "errors": [], "invoices": []}

    for schedule_name in schedules:
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

            # Skip if test_mode flag doesn't match
            if test_mode and not schedule.test_mode:
                continue
            elif not test_mode and schedule.test_mode:
                continue

            can_generate, reason = schedule.can_generate_invoice()

            if can_generate:
                invoice = schedule.generate_invoice()
                if invoice:
                    results["generated"] += 1
                    results["invoices"].append(
                        {"schedule": schedule_name, "member": schedule.member_name, "invoice": invoice}
                    )

            results["processed"] += 1

        except Exception as e:
            error_msg = f"Error processing schedule {schedule_name}: {str(e)}"
            frappe.log_error(error_msg, "Membership Dues Generation")
            results["errors"].append(error_msg)

    # Log results
    frappe.logger().info(
        f"Membership dues generation completed: {results['generated']} invoices from {results['processed']} schedules"
    )

    return results


@frappe.whitelist()
def create_test_schedule(member_name, membership_name=None):
    """Create a test dues schedule for development"""

    # Get membership if not provided
    if not membership_name:
        membership_name = frappe.db.get_value("Membership", {"member": member_name}, "name")

    if not membership_name:
        frappe.throw(f"No membership found for member {member_name}")

    # Create test schedule
    schedule = frappe.new_doc("Membership Dues Schedule")
    schedule.member = member_name
    schedule.membership = membership_name
    schedule.billing_frequency = "Monthly"
    schedule.amount = 10.00  # Test amount
    schedule.next_invoice_date = today()
    schedule.invoice_days_before = 0  # Generate immediately
    schedule.test_mode = 1
    schedule.auto_generate = 1
    schedule.status = "Test"
    schedule.insert()

    return schedule.name
