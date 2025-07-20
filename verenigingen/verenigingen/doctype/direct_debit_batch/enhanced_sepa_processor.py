"""
Enhanced SEPA Direct Debit processor for the flexible membership dues system
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cstr, flt, getdate, today


class EnhancedSEPAProcessor:
    """Enhanced SEPA processor that handles the new membership dues schedules"""

    def __init__(self):
        settings = frappe.get_single("Verenigingen Settings")
        company_name = getattr(settings, "company", None) or frappe.defaults.get_global_default("company")
        self.company = frappe.get_doc("Company", company_name)

    def create_dues_collection_batch(self, collection_date=None):
        """
        Create a direct debit batch for membership dues collection
        Processes membership dues schedules that are due for collection
        """
        if not collection_date:
            collection_date = today()

        # Get eligible dues schedules
        eligible_schedules = self.get_eligible_dues_schedules(collection_date)

        if not eligible_schedules:
            frappe.logger().info(f"No eligible dues schedules found for collection on {collection_date}")
            return None

        # Create batch
        batch = self.create_batch_document(eligible_schedules, collection_date)

        # Generate invoices and add to batch
        for schedule in eligible_schedules:
            try:
                invoice = self.create_dues_invoice(schedule, collection_date)
                if invoice:
                    self.add_invoice_to_batch(batch, invoice, schedule)
            except Exception as e:
                frappe.log_error(
                    f"Error processing dues schedule {schedule.name}: {str(e)}", "SEPA Dues Collection Error"
                )
                continue

        if batch.invoices:
            batch.calculate_totals()
            batch.save()
            frappe.db.commit()

            frappe.logger().info(
                f"Created SEPA batch {batch.name} with {len(batch.invoices)} invoices for €{batch.total_amount}"
            )
            return batch
        else:
            # No valid invoices, delete empty batch
            batch.delete()
            return None

    def get_eligible_dues_schedules(self, collection_date):
        """Get membership dues schedules eligible for collection"""
        # Calculate the date range for eligible schedules
        # We want to collect dues that are due within the invoice_days_before period
        max_due_date = add_days(collection_date, 30)  # Default 30 days lookahead

        filters = {
            "status": "Active",
            "auto_generate": 1,
            "test_mode": 0,
            "payment_method": "SEPA Direct Debit",
            "next_invoice_date": ["<=", max_due_date],
        }

        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters=filters,
            fields=[
                "name",
                "member",
                "membership",
                "membership_type",
                "amount",
                "billing_frequency",
                "next_invoice_date",
                "invoice_days_before",
                "active_mandate",
                "contribution_mode",
                "billing_day",
                "current_coverage_start",
                "current_coverage_end",
            ],
        )

        # Filter based on invoice_days_before
        eligible = []
        for schedule in schedules:
            days_before = schedule.invoice_days_before or 30
            generate_date = add_days(schedule.next_invoice_date, -days_before)

            if getdate(collection_date) >= getdate(generate_date):
                # Check if invoice already exists for this period
                if not self.invoice_exists_for_period(schedule):
                    schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
                    eligible.append(schedule_doc)

        frappe.logger().info(f"Found {len(eligible)} eligible dues schedules for collection")
        return eligible

    def invoice_exists_for_period(self, schedule):
        """Check if an invoice already exists for the current coverage period"""
        existing = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": schedule.member,
                "custom_membership_dues_schedule": schedule.name,
                "custom_coverage_start_date": schedule.current_coverage_start,
                "docstatus": ["!=", 2],  # Not cancelled
            },
            limit=1,
        )
        return bool(existing)

    def create_batch_document(self, schedules, collection_date):
        """Create the SEPA Direct Debit Batch document"""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = collection_date
        batch.batch_description = f"Membership dues collection - {collection_date}"
        batch.batch_type = "RCUR"  # Recurring payments
        batch.currency = "EUR"
        batch.status = "Draft"

        # Determine sequence type based on schedules
        # If any are FRST, the whole batch should be FRST
        has_frst = any(s.next_sequence_type == "FRST" for s in schedules if hasattr(s, "next_sequence_type"))
        batch.batch_type = "FRST" if has_frst else "RCUR"

        return batch

    def create_dues_invoice(self, schedule, collection_date):
        """Create invoice for membership dues"""
        try:
            # Get member details
            member = frappe.get_doc("Member", schedule.member)

            # Create invoice
            invoice = frappe.new_doc("Sales Invoice")
            invoice.customer = member.customer or schedule.member
            invoice.posting_date = today()
            invoice.due_date = schedule.next_invoice_date

            # Set payment terms if available
            if schedule.payment_terms_template:
                invoice.payment_terms_template = schedule.payment_terms_template

            # Add membership dues item
            item_code = self.get_or_create_dues_item(schedule)

            # Generate description based on contribution mode
            description = self.generate_invoice_description(schedule)

            invoice.append(
                "items",
                {
                    "item_code": item_code,
                    "item_name": f"Membership Dues - {schedule.membership_type}",
                    "description": description,
                    "qty": 1,
                    "rate": schedule.dues_rate,
                    "amount": schedule.dues_rate,
                },
            )

            # Add custom fields for tracking
            invoice.custom_membership_dues_schedule = schedule.name
            invoice.custom_coverage_start_date = schedule.current_coverage_start
            invoice.custom_coverage_end_date = schedule.current_coverage_end
            invoice.custom_contribution_mode = schedule.contribution_mode

            # Add reference
            invoice.remarks = (
                f"Membership dues for {member.full_name}\n"
                f"Period: {schedule.current_coverage_start} to {schedule.current_coverage_end}\n"
                f"Schedule: {schedule.name}"
            )

            invoice.save()
            frappe.db.commit()

            # Update schedule after creating invoice
            self.update_schedule_after_invoice(schedule)

            return invoice

        except Exception as e:
            frappe.log_error(
                f"Error creating invoice for schedule {schedule.name}: {str(e)}",
                "Dues Invoice Creation Error",
            )
            raise

    def generate_invoice_description(self, schedule):
        """Generate invoice description based on contribution mode"""
        base_desc = f"Membership dues - {schedule.billing_frequency}"

        if schedule.contribution_mode == "Tier" and schedule.selected_tier:
            tier_doc = frappe.get_doc("Membership Tier", schedule.selected_tier)
            base_desc += f"\nTier: {tier_doc.display_name}"
        elif schedule.contribution_mode == "Calculator" and schedule.base_multiplier:
            percentage = int(schedule.base_multiplier * 100)
            base_desc += f"\nContribution: {percentage}% of suggested amount"
        elif schedule.contribution_mode == "Custom" and schedule.uses_custom_amount:
            base_desc += "\nCustom contribution"
            if schedule.custom_amount_reason:
                base_desc += f": {schedule.custom_amount_reason}"

        base_desc += f"\nCoverage: {schedule.current_coverage_start} to {schedule.current_coverage_end}"

        return base_desc

    def get_or_create_dues_item(self, schedule):
        """Get or create item for membership dues billing"""
        item_code = f"DUES-{schedule.membership_type}-{schedule.billing_frequency}".replace(" ", "-").upper()

        if not frappe.db.exists("Item", item_code):
            item = frappe.new_doc("Item")
            item.item_code = item_code
            item.item_name = f"Membership Dues - {schedule.membership_type} ({schedule.billing_frequency})"
            item.item_group = "Services"
            item.is_stock_item = 0
            item.is_sales_item = 1
            item.is_service_item = 1
            item.save()

        return item_code

    def add_invoice_to_batch(self, batch, invoice, schedule):
        """Add invoice to SEPA batch"""
        # Get SEPA mandate details
        mandate = self.get_active_mandate(schedule)
        if not mandate:
            frappe.log_error(
                f"No active SEPA mandate found for schedule {schedule.name}", "SEPA Mandate Missing"
            )
            return

        # Get member details
        member = frappe.get_doc("Member", schedule.member)

        batch.append(
            "invoices",
            {
                "invoice": invoice.name,
                "membership": schedule.membership,
                "member": schedule.member,
                "member_name": member.full_name,
                "amount": invoice.grand_total,
                "currency": invoice.currency,
                "bank_account": mandate.name,
                "iban": mandate.iban,
                "mandate_reference": mandate.mandate_id,
                "status": "Pending",
                "sequence_type": schedule.next_sequence_type or "RCUR",
            },
        )

    def get_active_mandate(self, schedule):
        """Get active SEPA mandate for the schedule"""
        if schedule.active_mandate:
            return frappe.get_doc("SEPA Mandate", schedule.active_mandate)

        # Try to find mandate by member
        mandates = frappe.get_all(
            "SEPA Mandate",
            filters={"member": schedule.member, "status": "Active"},
            order_by="creation desc",
            limit=1,
        )

        if mandates:
            mandate = frappe.get_doc("SEPA Mandate", mandates[0].name)
            # Update schedule with mandate reference
            schedule.db_set("active_mandate", mandate.name)
            return mandate

        return None

    def update_schedule_after_invoice(self, schedule):
        """Update dues schedule after creating invoice"""
        # Calculate next dates
        schedule.calculate_coverage_dates()

        # Update sequence type if this was first payment
        if schedule.next_sequence_type == "FRST":
            schedule.db_set("next_sequence_type", "RCUR")

        # Update last invoice date
        schedule.db_set("last_invoice_date", today())

        # Save changes
        schedule.save()

    def process_batch_returns(self, batch_name, return_file_path):
        """Process SEPA return file and handle failed payments"""
        try:
            batch = frappe.get_doc("Direct Debit Batch", batch_name)

            # Parse return file
            returns = self.parse_sepa_return_file(return_file_path)

            failed_count = 0
            for return_item in returns:
                # Find the invoice in the batch
                invoice_item = self.find_invoice_in_batch(batch, return_item)
                if invoice_item:
                    # Update invoice status
                    invoice_item.status = "Failed"
                    invoice_item.result_code = return_item.get("reason_code")
                    invoice_item.result_message = return_item.get("reason_description")

                    # Handle the failed payment
                    self.handle_failed_payment(invoice_item, return_item)
                    failed_count += 1

            # Update batch status
            if failed_count > 0:
                batch.status = "Partially Failed"
                batch.add_to_batch_log(f"Processed {failed_count} returned payments")

            batch.save()
            return failed_count

        except Exception as e:
            frappe.log_error(f"Error processing batch returns: {str(e)}", "SEPA Return Processing Error")
            raise

    def handle_failed_payment(self, invoice_item, return_info):
        """Handle a failed SEPA payment"""
        try:
            # Get the dues schedule
            invoice = frappe.get_doc("Sales Invoice", invoice_item.invoice)
            if invoice.custom_membership_dues_schedule:
                schedule = frappe.get_doc("Membership Dues Schedule", invoice.custom_membership_dues_schedule)

                # Increment failure count
                schedule.consecutive_failures = (schedule.consecutive_failures or 0) + 1

                # Update schedule status based on failure count
                if schedule.consecutive_failures >= 3:
                    schedule.status = "Suspended"
                    schedule.add_comment(
                        text=f"Suspended due to {schedule.consecutive_failures} consecutive payment failures"
                    )
                else:
                    schedule.status = "Grace Period"
                    schedule.grace_period_until = add_days(today(), 14)  # 14 day grace period

                schedule.save()

                # Notify member
                self.notify_payment_failure(schedule, return_info)

        except Exception as e:
            frappe.log_error(
                f"Error handling failed payment for invoice {invoice_item.invoice}: {str(e)}",
                "Failed Payment Handler Error",
            )

    def notify_payment_failure(self, schedule, return_info):
        """Send notification about payment failure"""
        try:
            member = frappe.get_doc("Member", schedule.member)

            reason = return_info.get("reason_description", "Payment was rejected by the bank")

            subject = _("Payment Failed - Action Required")
            message = f"""
            Dear {member.full_name},

            Your membership payment of €{schedule.dues_rate} has failed with the following reason:
            {reason}

            Please update your payment information or contact us to resolve this issue.
            You have a grace period until {schedule.grace_period_until} to resolve this.

            If you have any questions, please contact our membership team.

            Best regards,
Organization
            """

            frappe.sendmail(
                recipients=[member.email],
                subject=subject,
                message=message,
                reference_doctype="Membership Dues Schedule",
                reference_name=schedule.name,
            )

        except Exception as e:
            frappe.log_error(
                f"Error sending payment failure notification: {str(e)}", "Payment Failure Notification Error"
            )

    def parse_sepa_return_file(self, file_path):
        """Parse SEPA return file (pain.002 format)"""
        # This is a simplified parser - implement according to your bank's format
        returns = []

        try:
            ET.parse(file_path)
            # Navigate through the XML structure to find returns
            # This will vary based on your bank's implementation

            return returns

        except Exception as e:
            frappe.log_error(f"Error parsing SEPA return file: {str(e)}", "SEPA Return File Parser Error")
            return []

    def find_invoice_in_batch(self, batch, return_item):
        """Find invoice in batch based on return information"""
        # Match by end-to-end ID or other reference
        for invoice_item in batch.invoices:
            if invoice_item.invoice == return_item.get("end_to_end_id"):
                return invoice_item
        return None


@frappe.whitelist()
def create_monthly_dues_collection_batch():
    """
    Scheduled job to create monthly SEPA collection batch
    Run this via scheduler on a specific day each month
    """
    processor = EnhancedSEPAProcessor()
    batch = processor.create_dues_collection_batch()

    if batch:
        frappe.logger().info(f"Created monthly dues collection batch: {batch.name}")

        # Optionally auto-submit if configured
        if frappe.db.get_single_value("Verenigingen Settings", "auto_submit_sepa_batches"):
            batch.submit()
            batch.generate_sepa_xml()
            frappe.logger().info(f"Auto-submitted and generated SEPA file for batch: {batch.name}")

    return batch.name if batch else None


@frappe.whitelist()
def process_sepa_returns(batch_name, return_file):
    """Process SEPA return file for a batch"""
    processor = EnhancedSEPAProcessor()
    failed_count = processor.process_batch_returns(batch_name, return_file)

    frappe.msgprint(_("Processed {0} failed payments from SEPA return file").format(failed_count))

    return failed_count


@frappe.whitelist()
def get_upcoming_dues_collections(days_ahead=30):
    """Get upcoming dues collections for review"""
    # Get schedules that will be collected in the next X days
    future_date = add_days(today(), days_ahead)

    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "payment_method": "SEPA Direct Debit",
            "next_invoice_date": ["between", [today(), future_date]],
        },
        fields=[
            "name",
            "member",
            "member.full_name as member_name",
            "amount",
            "billing_frequency",
            "next_invoice_date",
            "contribution_mode",
            "current_coverage_start",
            "current_coverage_end",
        ],
        order_by="next_invoice_date",
    )

    # Group by collection date
    collections_by_date = {}
    for schedule in schedules:
        date_key = str(schedule.next_invoice_date)
        if date_key not in collections_by_date:
            collections_by_date[date_key] = {
                "date": schedule.next_invoice_date,
                "schedules": [],
                "total_amount": 0,
                "count": 0,
            }

        collections_by_date[date_key]["schedules"].append(schedule)
        collections_by_date[date_key]["total_amount"] += flt(schedule.dues_rate)
        collections_by_date[date_key]["count"] += 1

    return list(collections_by_date.values())


@frappe.whitelist()
def validate_sepa_configuration():
    """Validate SEPA configuration is complete"""
    settings = frappe.get_single("Verenigingen Settings")

    required_fields = {
        "company_iban": "Company IBAN",
        "creditor_id": "Creditor ID (Incassant ID)",
        "company_account_holder": "Company Account Holder Name",
    }

    missing = []
    for field, label in required_fields.items():
        if not getattr(settings, field, None):
            missing.append(label)

    if missing:
        return {"valid": False, "message": _("Missing SEPA configuration: {0}").format(", ".join(missing))}

    # Validate IBAN format
    from verenigingen.utils.iban_validator import validate_iban

    iban_validation = validate_iban(settings.company_iban)

    if not iban_validation["valid"]:
        return {"valid": False, "message": _("Invalid company IBAN: {0}").format(iban_validation["error"])}

    return {
        "valid": True,
        "message": _("SEPA configuration is valid"),
        "config": {
            "iban": settings.company_iban,
            "bic": settings.company_bic or iban_validation.get("bic"),
            "creditor_id": settings.creditor_id,
            "account_holder": settings.company_account_holder,
        },
    }
