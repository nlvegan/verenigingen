"""
SEPA Direct Debit processor for the flexible membership dues system
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cstr, flt, getdate, today

from verenigingen.verenigingen_payments.utils.sepa_config_manager import get_sepa_config_manager
from verenigingen.verenigingen_payments.utils.sepa_error_handler import get_sepa_error_handler, sepa_retry
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import get_sepa_mandate_service


class SEPAProcessor:
    """SEPA processor that handles membership dues schedules"""

    def __init__(self):
        self.config_manager = get_sepa_config_manager()
        self.mandate_service = get_sepa_mandate_service()
        self.error_handler = get_sepa_error_handler()

        # Get company from centralized config
        company_config = self.config_manager.get_company_sepa_config()
        self.company = (
            frappe.get_doc("Company", company_config["company"]) if company_config["company"] else None
        )

    def create_dues_collection_batch(self, collection_date=None, verify_invoicing=True):
        """
        Create a direct debit batch for membership dues collection
        Processes existing unpaid invoices and verifies complete invoicing coverage

        Args:
            collection_date: Date for batch processing (default: today)
            verify_invoicing: Whether to run invoice coverage verification
        """
        if not collection_date:
            collection_date = today()

        # Step 1: Verify invoice coverage if requested
        if verify_invoicing:
            verification_result = self.verify_invoice_coverage(collection_date)
            if not verification_result["complete"]:
                frappe.log_error(
                    f"Invoice coverage verification failed: {verification_result['issues']}",
                    "SEPA Batch - Invoice Coverage Issues",
                )
                # Continue with batch creation but log the issues

        # Step 2: Get existing unpaid invoices instead of creating new ones
        eligible_invoices = self.get_existing_unpaid_sepa_invoices(collection_date)

        if not eligible_invoices:
            frappe.logger().info(f"No unpaid SEPA invoices found for collection on {collection_date}")
            return None

        # Step 3: Create batch from existing invoices
        batch = self.create_batch_from_invoices(eligible_invoices, collection_date)

        # Batch process sequence types for all invoices at once
        self.add_invoices_to_batch_optimized(batch, eligible_invoices)

        if batch.invoices:
            batch.calculate_totals()
            batch.save()

            # Handle validation and notifications for automated processing
            self.handle_automated_batch_validation(batch)

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
            "payment_terms_template": "SEPA Direct Debit",
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
                "dues_rate",
                "billing_frequency",
                "next_invoice_date",
                "invoice_days_before",
                "contribution_mode",
                "billing_day",
            ],
        )

        # Filter based on invoice_days_before
        eligible = []
        for schedule in schedules:
            days_before = schedule.invoice_days_before or 30
            generate_date = add_days(schedule.next_invoice_date, -days_before)

            if getdate(collection_date) >= getdate(generate_date):
                # Always include eligible schedules - we'll handle existing invoices in the main loop
                schedule_doc = frappe.get_doc("Membership Dues Schedule", schedule.name)
                eligible.append(schedule_doc)

        frappe.logger().info(f"Found {len(eligible)} eligible dues schedules for collection")
        return eligible

    def find_existing_invoice_for_schedule(self, schedule):
        """Find existing invoice for the current coverage period"""
        existing = frappe.get_all(
            "Sales Invoice",
            filters={
                "customer": schedule.member,
                "membership_dues_schedule_display": schedule.name,
                "custom_coverage_start_date": schedule.last_invoice_coverage_start,
                "docstatus": ["!=", 2],  # Not cancelled
                "status": ["in", ["Unpaid", "Overdue"]],  # Only unpaid invoices
            },
            fields=["name", "grand_total", "status"],
            limit=1,
        )
        return existing[0] if existing else None

    def member_has_sepa_enabled(self, schedule):
        """Check if member has SEPA Direct Debit enabled and active mandate"""
        try:
            # Check if schedule has SEPA payment method
            if getattr(schedule, "payment_terms_template", None) != "SEPA Direct Debit":
                return False

            # Check if member has active SEPA mandate
            mandate = self.get_active_mandate(schedule)
            return mandate is not None

        except Exception as e:
            frappe.log_error(f"Error checking SEPA status for schedule {schedule.name}: {str(e)}")
            return False

    def create_batch_document(self, schedules, collection_date):
        """Create the SEPA Direct Debit Batch document"""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = collection_date
        batch.batch_description = f"Membership dues collection - {collection_date}"
        batch.batch_type = "RCUR"  # Default to recurring
        batch.currency = "EUR"
        batch.status = "Draft"

        # Set flag for automated processing (affects validation behavior)
        batch._automated_processing = True

        return batch

    def create_dues_invoice(self, schedule, collection_date):
        """Create invoice for membership dues"""
        try:
            # Get member details
            member = frappe.get_doc("Member", schedule.member)

            # For daily billing: Check if member has too many unpaid invoices
            if schedule.billing_frequency == "Daily":
                unpaid_count = frappe.db.count(
                    "Sales Invoice",
                    {
                        "customer": member.customer or schedule.member,
                        "status": ["in", ["Unpaid", "Overdue"]],
                        "outstanding_amount": [">", 0],
                    },
                )

                # Skip if member has more than 5 unpaid invoices (configurable)
                max_unpaid = 5  # Could be moved to settings
                if unpaid_count >= max_unpaid:
                    frappe.logger().info(
                        f"Skipping invoice creation for {member.full_name} - "
                        f"has {unpaid_count} unpaid invoices (max: {max_unpaid})"
                    )
                    return None

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
            invoice.membership_dues_schedule_display = schedule.name
            invoice.custom_coverage_start_date = schedule.last_invoice_coverage_start
            invoice.custom_coverage_end_date = schedule.last_invoice_coverage_end
            invoice.custom_contribution_mode = schedule.contribution_mode

            # Add reference
            invoice.remarks = (
                f"Membership dues for {member.full_name}\n"
                f"Period: {schedule.last_invoice_coverage_start} to {schedule.last_invoice_coverage_end}\n"
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

        base_desc += (
            f"\nCoverage: {schedule.last_invoice_coverage_start} to {schedule.last_invoice_coverage_end}"
        )

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
        """Add invoice to SEPA batch with proper sequence type determination"""
        # Get SEPA mandate details
        mandate = self.get_active_mandate(schedule)
        if not mandate:
            frappe.log_error(
                f"No active SEPA mandate found for schedule {schedule.name}", "SEPA Mandate Missing"
            )
            return

        # Get member details
        member = frappe.get_doc("Member", schedule.member)

        # Determine correct sequence type using mandate history
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
            get_mandate_sequence_type,
        )

        sequence_info = get_mandate_sequence_type(mandate.name, invoice.name)
        correct_sequence_type = sequence_info["sequence_type"]

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
                "sequence_type": correct_sequence_type,  # Use properly determined sequence type
            },
        )

        # Create mandate usage record for tracking
        try:
            create_mandate_usage_record(
                mandate_name=mandate.name,
                reference_doctype="Sales Invoice",
                reference_name=invoice.name,
                amount=invoice.grand_total,
                sequence_type=correct_sequence_type,
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to create mandate usage record for {mandate.name}: {str(e)}",
                "Enhanced SEPA Processor - Mandate Usage Creation Error",
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

        # NOTE: Sequence type is now determined by mandate usage history
        # No longer need to update schedule.next_sequence_type as it's determined dynamically
        # The actual sequence type is determined in add_invoice_to_batch() using mandate history

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
            if invoice.membership_dues_schedule_display:
                schedule = frappe.get_doc(
                    "Membership Dues Schedule", invoice.membership_dues_schedule_display
                )

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

    def verify_invoice_coverage(self, collection_date):
        """
        Verify that all eligible members have been properly invoiced
        Optimized with batch processing for better performance
        """
        issues = []
        total_checked = 0

        try:
            # Batch query to get all schedules with their invoice status
            coverage_data = frappe.db.sql(
                """
                SELECT
                    mds.name as schedule_name,
                    mds.member,
                    mds.billing_frequency,
                    mds.next_invoice_date,
                    mds.last_invoice_coverage_start,
                    mds.last_invoice_coverage_end,
                    mds.payment_terms_template,
                    COUNT(si.name) as invoice_count
                FROM `tabMembership Dues Schedule` mds
                LEFT JOIN `tabSales Invoice` si ON (
                    si.membership_dues_schedule_display = mds.name
                    AND si.custom_coverage_start_date = mds.last_invoice_coverage_start
                    AND si.custom_coverage_end_date = mds.last_invoice_coverage_end
                    AND si.docstatus != 2
                )
                WHERE
                    mds.status = 'Active'
                    AND mds.auto_generate = 1
                    AND mds.test_mode = 0
                GROUP BY mds.name
                LIMIT 500  -- Pagination for large datasets
            """,
                as_dict=True,
            )

            # Batch validate coverage periods
            schedule_data = [
                {
                    "name": row["schedule_name"],
                    "member": row["member"],
                    "billing_frequency": row["billing_frequency"],
                    "last_invoice_coverage_start": row["last_invoice_coverage_start"],
                    "last_invoice_coverage_end": row["last_invoice_coverage_end"],
                    "payment_terms_template": row["payment_terms_template"],
                }
                for row in coverage_data
            ]

            coverage_issues = self.validate_coverage_periods_batch(schedule_data, collection_date)

            for row in coverage_data:
                total_checked += 1
                schedule_name = row["schedule_name"]

                # Check for coverage period issues
                if schedule_name in coverage_issues:
                    issues.append(
                        {
                            "schedule": schedule_name,
                            "member": row["member"],
                            "issue": coverage_issues[schedule_name],
                            "billing_frequency": row["billing_frequency"],
                        }
                    )

                # Check if invoice exists for SEPA schedules
                if row["payment_terms_template"] == "SEPA Direct Debit" and row["invoice_count"] == 0:
                    issues.append(
                        {
                            "schedule": schedule_name,
                            "member": row["member"],
                            "issue": "Missing invoice for current coverage period",
                            "billing_frequency": row["billing_frequency"],
                        }
                    )

            frappe.logger().info(
                f"Invoice coverage verification: {total_checked} schedules checked, "
                f"{len(issues)} issues found"
            )

            return {
                "complete": len(issues) == 0,
                "total_checked": total_checked,
                "issues_count": len(issues),
                "issues": issues,
            }

        except Exception as e:
            frappe.log_error(
                f"Error in invoice coverage verification: {str(e)}", "Invoice Coverage Verification Error"
            )
            return {"complete": False, "error": str(e), "total_checked": total_checked, "issues": issues}

    def validate_coverage_period(self, schedule, collection_date):
        """Validate coverage period against billing frequency (rolling periods)"""
        if not schedule["last_invoice_coverage_start"] or not schedule["last_invoice_coverage_end"]:
            return "Missing coverage period dates"

        start_date = getdate(schedule["last_invoice_coverage_start"])
        end_date = getdate(schedule["last_invoice_coverage_end"])
        billing_freq = schedule["billing_frequency"]

        # Calculate expected period length
        period_days = (end_date - start_date).days + 1  # +1 to include end date

        if billing_freq == "Daily":
            expected_days = 1
            tolerance = 0
        elif billing_freq == "Weekly":
            expected_days = 7
            tolerance = 1
        elif billing_freq == "Monthly":
            # Rolling months: 28-31 days
            expected_days = 30  # Average
            tolerance = 3
        elif billing_freq == "Quarterly":
            # Rolling quarters: ~90 days
            expected_days = 90
            tolerance = 7
        elif billing_freq == "Annual":
            # Rolling years: 365/366 days
            expected_days = 365
            tolerance = 2
        else:
            # Custom billing frequency
            return None  # Skip validation for custom frequencies

        if abs(period_days - expected_days) > tolerance:
            return (
                f"Coverage period ({period_days} days) doesn't match "
                f"{billing_freq} billing frequency (expected ~{expected_days} days)"
            )

        return None

    def validate_coverage_periods_batch(self, schedules, collection_date):
        """Batch validate coverage periods for multiple schedules"""
        issues = {}

        for schedule in schedules:
            issue = self.validate_coverage_period(schedule, collection_date)
            if issue:
                issues[schedule["name"]] = issue

        return issues

    def get_existing_unpaid_sepa_invoices(self, collection_date):
        """Get existing unpaid invoices for SEPA Direct Debit members using optimized service"""
        # Get lookback days from centralized config
        processing_config = self.config_manager.get_processing_config()
        lookback_days = processing_config["lookback_days"]

        invoices = self.mandate_service.get_sepa_invoices_with_mandates(
            collection_date, lookback_days=lookback_days
        )

        frappe.logger().info(f"Found {len(invoices)} existing unpaid SEPA invoices")
        return invoices

    def create_batch_from_invoices(self, invoices, collection_date):
        """Create SEPA batch from existing invoices"""
        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = collection_date
        batch.batch_description = f"Monthly SEPA collection - {collection_date.strftime('%B %Y')}"
        batch.batch_type = "RCUR"  # Default to recurring
        batch.currency = "EUR"
        batch.status = "Draft"

        # Set flag for automated processing
        batch._automated_processing = True

        return batch

    def add_invoices_to_batch_optimized(self, batch, invoices):
        """Add multiple invoices to batch with optimized sequence type determination"""
        if not invoices:
            return

        # Prepare mandate-invoice pairs for batch sequence type lookup
        mandate_invoice_pairs = []
        invoice_lookup = {}

        for invoice_data in invoices:
            mandate_name = invoice_data.get("mandate_name")
            invoice_name = invoice_data.get("name")

            if mandate_name and invoice_name:
                mandate_invoice_pairs.append((mandate_name, invoice_name))
                invoice_lookup[f"{mandate_name}:{invoice_name}"] = invoice_data

        # Batch get sequence types
        sequence_types = self.mandate_service.get_sequence_types_batch(mandate_invoice_pairs)

        # Add invoices to batch with pre-determined sequence types
        successful_count = 0
        for pair in mandate_invoice_pairs:
            mandate_name, invoice_name = pair
            cache_key = f"{mandate_name}:{invoice_name}"
            invoice_data = invoice_lookup[cache_key]
            sequence_type = sequence_types.get(cache_key, "RCUR")  # Default to RCUR

            try:
                self.add_invoice_to_batch_with_sequence(batch, invoice_data, sequence_type)
                successful_count += 1
            except Exception as e:
                frappe.log_error(
                    f"Error adding invoice {invoice_name} to batch: {str(e)}",
                    "Enhanced SEPA Processor - Batch Addition Error",
                )
                continue

        frappe.logger().info(f"Successfully added {successful_count}/{len(invoices)} invoices to batch")

    def add_invoice_to_batch_with_sequence(self, batch, invoice_data, sequence_type):
        """Add single invoice to batch with pre-determined sequence type"""
        batch.append(
            "invoices",
            {
                "invoice": invoice_data["name"],
                "membership": invoice_data["membership"],
                "member": invoice_data["member"],
                "member_name": invoice_data["member_name"],
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "iban": invoice_data["iban"],
                "mandate_reference": invoice_data["mandate_reference"],
                "status": "Pending",
                "sequence_type": sequence_type,
            },
        )

        # Create mandate usage record for tracking
        try:
            from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
                create_mandate_usage_record,
            )

            create_mandate_usage_record(
                mandate_name=invoice_data["mandate_name"],
                reference_doctype="Sales Invoice",
                reference_name=invoice_data["name"],
                amount=invoice_data["amount"],
                sequence_type=sequence_type,
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to create mandate usage record for {invoice_data['mandate_name']}: {str(e)}",
                "Enhanced SEPA Processor - Mandate Usage Creation Error",
            )

    def add_existing_invoice_to_batch(self, batch, invoice_data):
        """Add existing invoice to SEPA batch with proper sequence type determination"""
        # Determine correct sequence type using mandate history
        from verenigingen.verenigingen_payments.doctype.sepa_mandate_usage.sepa_mandate_usage import (
            create_mandate_usage_record,
            get_mandate_sequence_type,
        )

        mandate_name = invoice_data["mandate_name"]
        if not mandate_name:
            frappe.log_error(
                f"No active SEPA mandate found for invoice {invoice_data['name']}",
                "SEPA Batch - Missing Mandate",
            )
            return

        sequence_info = get_mandate_sequence_type(mandate_name, invoice_data["name"])
        correct_sequence_type = sequence_info["sequence_type"]

        batch.append(
            "invoices",
            {
                "invoice": invoice_data["name"],
                "membership": invoice_data["membership"],
                "member": invoice_data["member"],
                "member_name": invoice_data["member_name"],
                "amount": invoice_data["amount"],
                "currency": invoice_data["currency"],
                "iban": invoice_data["iban"],
                "mandate_reference": invoice_data["mandate_reference"],
                "status": "Pending",
                "sequence_type": correct_sequence_type,
            },
        )

        # Create mandate usage record for tracking
        try:
            create_mandate_usage_record(
                mandate_name=mandate_name,
                reference_doctype="Sales Invoice",
                reference_name=invoice_data["name"],
                amount=invoice_data["amount"],
                sequence_type=correct_sequence_type,
            )
        except Exception as e:
            frappe.log_error(
                f"Failed to create mandate usage record for {mandate_name}: {str(e)}",
                "Enhanced SEPA Processor - Mandate Usage Creation Error",
            )

    def handle_automated_batch_validation(self, batch):
        """
        Handle validation results for automated batch creation
        Uses the same validation system as the Direct Debit Batch
        """
        try:
            # Check if batch has validation results
            if not hasattr(batch, "validation_status") or not batch.validation_status:
                # Batch doesn't have validation results, skip notification
                return

            critical_errors = []
            warnings = []

            # Parse validation results if they exist
            if batch.validation_errors:
                try:
                    critical_errors = frappe.parse_json(batch.validation_errors)
                except (ValueError, TypeError) as e:
                    frappe.log_error(f"Failed to parse validation_errors: {e}", "SEPAProcessorValidation")
                    critical_errors = []

            if batch.validation_warnings:
                try:
                    warnings = frappe.parse_json(batch.validation_warnings)
                except (ValueError, TypeError) as e:
                    frappe.log_error(f"Failed to parse validation_warnings: {e}", "SEPAProcessorValidation")
                    warnings = []

            # Use the existing notification system
            from verenigingen.verenigingen_payments.api.sepa_batch_notifications import (
                handle_automated_batch_validation,
            )

            result = handle_automated_batch_validation(batch, critical_errors, warnings)

            frappe.logger().info(
                f"Enhanced SEPA Processor batch validation handled: {result['action']} for batch {batch.name}"
            )

        except Exception as e:
            frappe.log_error(
                f"Error handling automated batch validation for {batch.name}: {str(e)}",
                "Enhanced SEPA Processor - Validation Handler Error",
            )


@frappe.whitelist()
def create_monthly_dues_collection_batch():
    """
    Scheduled job to create monthly SEPA collection batch
    Uses centralized configuration for timing and settings
    """
    from frappe.utils import getdate, today

    # Use centralized configuration manager
    config_manager = get_sepa_config_manager()
    timing_config = config_manager.get_batch_timing_config()

    current_date = getdate(today())

    # Check if auto creation is enabled
    if not timing_config["auto_creation_enabled"]:
        frappe.logger().info("Auto batch creation is disabled in configuration")
        return None

    # Check if today is a batch creation day
    if not timing_config["is_creation_day"]:
        creation_days = ", ".join([str(day) for day in timing_config["creation_days"]])
        frappe.logger().info(
            f"Skipping SEPA batch creation - today is {current_date.day}, runs on: {creation_days}"
        )
        return None

    # Use configured processing date
    processing_date = timing_config["next_processing_date"]

    # Create batch with error handling
    error_handler = get_sepa_error_handler()

    def create_batch_operation():
        processor = SEPAProcessor()
        return processor.create_dues_collection_batch(collection_date=processing_date)

    result = error_handler.execute_with_retry(create_batch_operation)

    if result["success"]:
        batch = result["result"]
        if batch:
            frappe.logger().info(
                f"Created monthly SEPA batch {batch.name} on {current_date} "
                f"for processing on {processing_date} (Dutch payroll timing)"
            )

            # Auto-submit if configured
            if timing_config["auto_submit_enabled"]:
                try:
                    batch.submit()
                    batch.generate_sepa_xml()
                    frappe.logger().info(f"Auto-submitted and generated SEPA file for batch: {batch.name}")
                except Exception as e:
                    frappe.log_error(
                        f"Failed to auto-submit batch {batch.name}: {str(e)}", "SEPA Auto-Submit Error"
                    )

            return batch.name
        else:
            frappe.logger().info("No invoices found for SEPA batch creation")
            return None
    else:
        frappe.log_error(
            f"Failed to create monthly SEPA batch: {result['error']}", "Monthly SEPA Batch Creation Error"
        )
        return None


@frappe.whitelist()
def process_sepa_returns(batch_name, return_file):
    """Process SEPA return file for a batch"""
    processor = SEPAProcessor()
    failed_count = processor.process_batch_returns(batch_name, return_file)

    frappe.msgprint(_("Processed {0} failed payments from SEPA return file").format(failed_count))

    return failed_count


@frappe.whitelist()
def verify_invoice_coverage_status(collection_date=None):
    """API to check invoice coverage for a specific date"""
    processor = SEPAProcessor()
    if not collection_date:
        collection_date = today()

    result = processor.verify_invoice_coverage(collection_date)
    return result


@frappe.whitelist()
def get_sepa_batch_preview(collection_date=None):
    """Preview what SEPA batch would be created without actually creating it"""
    processor = SEPAProcessor()
    if not collection_date:
        collection_date = today()

    invoices = processor.get_existing_unpaid_sepa_invoices(collection_date)

    return {
        "success": True,
        "collection_date": collection_date,
        "unpaid_invoices_found": len(invoices),
        "total_amount": sum(flt(inv["amount"]) for inv in invoices),
        "sample_invoices": invoices[:5],  # Show first 5 as preview
        "members_affected": len(set(inv["member"] for inv in invoices)),
    }


@frappe.whitelist()
def get_upcoming_dues_collections(days_ahead=30):
    """Get upcoming dues collections for review"""
    # Get schedules that will be collected in the next X days
    future_date = add_days(today(), days_ahead)

    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={
            "status": "Active",
            "payment_terms_template": "SEPA Direct Debit",
            "next_invoice_date": ["between", [today(), future_date]],
        },
        fields=[
            "name",
            "member",
            "minimum_amount",
            "suggested_amount",
            "uses_custom_amount",
            "billing_frequency",
            "next_invoice_date",
            "contribution_mode",
            "last_invoice_coverage_start",
            "last_invoice_coverage_end",
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
        # Use suggested_amount if available, otherwise minimum_amount
        amount = schedule.suggested_amount if schedule.suggested_amount else schedule.minimum_amount
        collections_by_date[date_key]["total_amount"] += flt(amount)
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
    try:
        from verenigingen.utils.iban_validator import validate_iban

        iban_validation = validate_iban(settings.company_iban)
    except ImportError:
        # Fallback if IBAN validator is not available
        iban_validation = {"valid": True, "bic": None}

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
