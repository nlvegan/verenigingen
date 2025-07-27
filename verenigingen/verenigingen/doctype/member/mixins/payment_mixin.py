import frappe
from frappe import _
from frappe.utils import date_diff, today


class PaymentMixin:
    """Mixin for payment-related functionality"""

    @frappe.whitelist()
    def load_payment_history(self):
        """
        Load payment history for this member with focus on invoices.
        Also include unreconciled payments, but maintain separation from the Donation system.
        Then save the document to persist the changes.
        """
        self._load_payment_history_without_save()
        # Use flags to reduce activity logging for bulk payment history updates
        self.flags.ignore_version = True
        self.flags.ignore_links = True
        # Allow updates after submit for payment history refresh
        self.flags.ignore_validate_update_after_submit = True
        self.save(ignore_permissions=True)
        return True

    def on_load(self):
        """Load payment history when the document is loaded"""
        if self.customer:
            self._load_payment_history_without_save()

    def _load_payment_history_without_save(self):
        """Internal method to load payment history without saving"""
        if not self.customer:
            return

        # New approach: Only show 20 most recent entries
        # Limit to 20 most recent entries
        MAX_PAYMENT_HISTORY_ENTRIES = 20

        self.payment_history = []

        try:
            # 1. Get all invoices for this customer (including drafts)
            # Build field list dynamically to handle missing custom fields gracefully
            base_fields = [
                "name",
                "posting_date",
                "due_date",
                "grand_total",
                "outstanding_amount",
                "status",
                "docstatus",
            ]

            # Safely check for coverage custom fields existence
            coverage_fields = []
            try:
                if frappe.db.has_column("Sales Invoice", "custom_coverage_start_date"):
                    coverage_fields.append("custom_coverage_start_date")
                if frappe.db.has_column("Sales Invoice", "custom_coverage_end_date"):
                    coverage_fields.append("custom_coverage_end_date")
            except Exception as e:
                frappe.log_error(
                    f"Error checking for coverage fields: {str(e)}", "Coverage Field Check Error"
                )

            query_fields = base_fields + coverage_fields

            # Only get the most recent invoices
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "customer": self.customer,
                    "docstatus": ["in", [0, 1]],
                },  # Include both draft and submitted
                fields=query_fields,
                order_by="posting_date desc",
                limit=MAX_PAYMENT_HISTORY_ENTRIES,
            )

        except Exception as e:
            # Critical error - log and continue with empty payment history
            frappe.log_error(
                f"Critical error loading invoices for customer {self.customer}: {str(e)}",
                "Payment History Load Error",
            )
            return

        reconciled_payments = []

        # 2. Process each invoice and its payment status
        for invoice in invoices:
            try:
                # Safely get invoice document with error handling
                try:
                    invoice_doc = frappe.get_doc("Sales Invoice", invoice.name)
                except Exception as e:
                    frappe.log_error(
                        f"Error loading invoice document {invoice.name}: {str(e)}",
                        "Invoice Document Load Error",
                    )
                    continue  # Skip this invoice and continue with others

                reference_doctype = None
                reference_name = None
                transaction_type = "Regular Invoice"

                # Check if invoice is linked to a membership
                if hasattr(invoice_doc, "membership") and invoice_doc.membership:
                    transaction_type = "Membership Invoice"
                    reference_doctype = "Membership"
                    reference_name = invoice_doc.membership

                # Find linked payment entries
                payment_entries = frappe.get_all(
                    "Payment Entry Reference",
                    filters={"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
                    fields=["parent", "allocated_amount"],
                )

                payment_status = "Unpaid"
                payment_date = None
                payment_entry = None
                payment_method = None
                paid_amount = 0
                reconciled = 0

                if payment_entries:
                    for pe in payment_entries:
                        reconciled_payments.append(pe.parent)
                        # Validate allocated amount before adding
                        allocated_amount = pe.allocated_amount or 0
                        if allocated_amount < 0:
                            frappe.log_error(
                                f"Negative allocated amount in payment entry {pe.parent}: {allocated_amount}",
                                "PaymentValidation",
                            )
                        paid_amount += float(allocated_amount)

                    most_recent_payment = frappe.get_all(
                        "Payment Entry",
                        filters={"name": ["in", [pe.parent for pe in payment_entries]]},
                        fields=["name", "posting_date", "mode_of_payment", "paid_amount"],
                        order_by="posting_date desc",
                    )

                    if most_recent_payment:
                        payment_entry = most_recent_payment[0].name
                        payment_date = most_recent_payment[0].posting_date
                        payment_method = most_recent_payment[0].mode_of_payment
                        reconciled = 1

                # Set payment status based on invoice and payment data
                if invoice.docstatus == 0:
                    payment_status = "Draft"
                elif invoice.status == "Paid":
                    payment_status = "Paid"
                elif invoice.status == "Overdue":
                    payment_status = "Overdue"
                elif invoice.status == "Cancelled":
                    payment_status = "Cancelled"
                elif paid_amount > 0 and paid_amount < invoice.grand_total:
                    payment_status = "Partially Paid"

                # Check for SEPA mandate
                has_mandate = 0
                sepa_mandate = None
                mandate_status = None
                mandate_reference = None

                if reference_doctype == "Membership" and reference_name:
                    try:
                        membership_doc = frappe.get_doc("Membership", reference_name)
                        if hasattr(membership_doc, "sepa_mandate") and membership_doc.sepa_mandate:
                            has_mandate = 1
                            sepa_mandate = membership_doc.sepa_mandate
                            mandate_doc = frappe.get_doc("SEPA Mandate", sepa_mandate)
                            mandate_status = mandate_doc.status
                            mandate_reference = mandate_doc.mandate_id
                    except Exception as e:
                        frappe.log_error(
                            f"Error checking membership mandate for invoice {invoice.name}: {str(e)}"
                        )

                if not has_mandate:
                    default_mandate = self.get_default_sepa_mandate()
                    if default_mandate:
                        has_mandate = 1
                        sepa_mandate = default_mandate.name
                        mandate_status = default_mandate.status
                        mandate_reference = default_mandate.mandate_id

                # ✅ ENHANCED: Get coverage from schedule (SSoT) with invoice fallback
                coverage_start_date = None
                coverage_end_date = None

                try:
                    # PRIMARY: Get coverage from schedule (authoritative source)
                    schedule_coverage = self._get_coverage_from_schedule(invoice.name)

                    # FALLBACK: Use invoice cache if schedule lookup fails
                    invoice_coverage = self._get_coverage_from_invoice(invoice)

                    # Use best available source
                    coverage_start_date = schedule_coverage[0] or invoice_coverage[0]
                    coverage_end_date = schedule_coverage[1] or invoice_coverage[1]

                    # Validate coverage dates if both are present
                    if coverage_start_date and coverage_end_date:
                        # Ensure start date is not after end date
                        if coverage_start_date > coverage_end_date:
                            frappe.log_error(
                                f"Invalid coverage period for invoice {invoice.name}: "
                                f"start_date ({coverage_start_date}) > end_date ({coverage_end_date})",
                                "Coverage Date Validation Error",
                            )
                            # Reset to None for invalid data
                            coverage_start_date = None
                            coverage_end_date = None

                except Exception as e:
                    # Log error but don't fail payment history loading
                    frappe.log_error(
                        f"Error extracting coverage fields for invoice {invoice.name}: {str(e)}",
                        "Coverage Field Access Error",
                    )
                    coverage_start_date = None
                    coverage_end_date = None

                # Add invoice to payment history
                self.append(
                    "payment_history",
                    {
                        "invoice": invoice.name,
                        "posting_date": invoice.posting_date,
                        "due_date": invoice.due_date,
                        "coverage_start_date": coverage_start_date,
                        "coverage_end_date": coverage_end_date,
                        "transaction_type": transaction_type,
                        "reference_doctype": reference_doctype,
                        "reference_name": reference_name,
                        "amount": invoice.grand_total,
                        "outstanding_amount": invoice.outstanding_amount,
                        "status": invoice.status,
                        "payment_status": payment_status,
                        "payment_date": payment_date,
                        "payment_entry": payment_entry,
                        "payment_method": payment_method,
                        "paid_amount": paid_amount,
                        "reconciled": reconciled,
                        "has_mandate": has_mandate,
                        "sepa_mandate": sepa_mandate,
                        "mandate_status": mandate_status,
                        "mandate_reference": mandate_reference,
                    },
                )

            except Exception as e:
                # Log individual invoice processing error but continue with other invoices
                frappe.log_error(
                    f"Error processing invoice {invoice.name} for payment history: {str(e)}",
                    "Individual Invoice Processing Error",
                )
                continue  # Skip this invoice and continue with others

        # 3. Find payments that aren't reconciled with any invoice
        unreconciled_payments = frappe.get_all(
            "Payment Entry",
            filters={
                "party_type": "Customer",
                "party": self.customer,
                "docstatus": 1,
                "name": ["not in", reconciled_payments or [""]],
            },
            fields=[
                "name",
                "posting_date",
                "paid_amount",
                "mode_of_payment",
                "status",
                "reference_no",
                "reference_date",
            ],
            order_by="posting_date desc",
        )

        for payment in unreconciled_payments:
            donation = None
            if payment.reference_no:
                donations = frappe.get_all(
                    "Donation", filters={"payment_id": payment.reference_no}, fields=["name"]
                )
                if donations:
                    donation = donations[0].name

            transaction_type = "Unreconciled Payment"
            reference_doctype = None
            reference_name = None
            notes = "Payment without matching invoice"

            if donation:
                transaction_type = "Donation Payment"
                reference_doctype = "Donation"
                reference_name = donation
                notes = "Payment linked to donation"

            self.append(
                "payment_history",
                {
                    "invoice": None,
                    "posting_date": payment.posting_date,
                    "due_date": None,
                    "transaction_type": transaction_type,
                    "reference_doctype": reference_doctype,
                    "reference_name": reference_name,
                    "amount": payment.paid_amount,
                    "outstanding_amount": 0,
                    "status": "N/A",
                    "payment_status": "Paid",
                    "payment_date": payment.posting_date,
                    "payment_entry": payment.name,
                    "payment_method": payment.mode_of_payment,
                    "paid_amount": payment.paid_amount,
                    "reconciled": 0,
                    "notes": notes,
                },
            )

    def _get_coverage_from_schedule(self, invoice_name):
        """Get coverage from schedule - direct link, no heuristics (authoritative source)"""
        try:
            # First try direct link lookup
            schedule = frappe.db.get_value(
                "Membership Dues Schedule",
                {"member": self.name, "last_generated_invoice": invoice_name},
                ["last_invoice_coverage_start", "last_invoice_coverage_end"],
                as_dict=True,
            )

            if schedule and schedule.last_invoice_coverage_start:
                return (schedule.last_invoice_coverage_start, schedule.last_invoice_coverage_end)

            # If no direct link, try to find schedule by member and calculate
            schedules = frappe.get_all(
                "Membership Dues Schedule",
                filters={"member": self.name, "status": "Active"},
                fields=["name", "billing_frequency", "custom_frequency_number", "custom_frequency_unit"],
                order_by="creation desc",
                limit=1,
            )

            if schedules and invoice_name:
                # Get invoice posting date to calculate coverage
                invoice_date = frappe.db.get_value("Sales Invoice", invoice_name, "posting_date")
                if invoice_date:
                    return self._calculate_coverage_from_invoice_date(invoice_date, schedules[0])

            return (None, None)

        except Exception as e:
            frappe.log_error(
                f"Error getting coverage from schedule for invoice {invoice_name}: {str(e)}",
                "Schedule Coverage Lookup Error",
            )
            return (None, None)

    def _calculate_coverage_from_invoice_date(self, invoice_date, schedule_info):
        """Calculate coverage period from invoice date and billing frequency"""
        try:
            from frappe.utils import add_days, add_months, add_years, getdate

            invoice_date = getdate(invoice_date)
            billing_frequency = schedule_info.get("billing_frequency", "Daily")

            # Calculate coverage based on billing frequency
            if billing_frequency == "Daily":
                # Daily billing: coverage is the same day
                return (invoice_date, invoice_date)
            elif billing_frequency == "Weekly":
                # Weekly billing: coverage is 7 days from invoice date
                return (invoice_date, add_days(invoice_date, 6))
            elif billing_frequency == "Monthly":
                # Monthly billing: coverage is 1 month from invoice date
                end_date = add_months(invoice_date, 1)
                end_date = add_days(end_date, -1)  # Last day of coverage month
                return (invoice_date, end_date)
            elif billing_frequency == "Quarterly":
                # Quarterly billing: coverage is 3 months from invoice date
                end_date = add_months(invoice_date, 3)
                end_date = add_days(end_date, -1)
                return (invoice_date, end_date)
            elif billing_frequency == "Semi-Annual":
                # Semi-annual billing: coverage is 6 months from invoice date
                end_date = add_months(invoice_date, 6)
                end_date = add_days(end_date, -1)
                return (invoice_date, end_date)
            elif billing_frequency == "Annual":
                # Annual billing: coverage is 1 year from invoice date
                end_date = add_years(invoice_date, 1)
                end_date = add_days(end_date, -1)
                return (invoice_date, end_date)
            elif billing_frequency == "Custom":
                # Custom frequency: calculate based on custom settings
                number = schedule_info.get("custom_frequency_number", 1)
                unit = schedule_info.get("custom_frequency_unit", "Days")

                if unit == "Days":
                    end_date = add_days(invoice_date, number - 1)
                elif unit == "Weeks":
                    end_date = add_days(invoice_date, (number * 7) - 1)
                elif unit == "Months":
                    end_date = add_months(invoice_date, number)
                    end_date = add_days(end_date, -1)
                elif unit == "Years":
                    end_date = add_years(invoice_date, number)
                    end_date = add_days(end_date, -1)
                else:
                    # Default to same day
                    end_date = invoice_date

                return (invoice_date, end_date)
            else:
                # Unknown frequency, default to same day
                return (invoice_date, invoice_date)

        except Exception as e:
            frappe.log_error(
                f"Error calculating coverage from invoice date {invoice_date}: {str(e)}",
                "Coverage Calculation Error",
            )
            return (None, None)

    def _get_coverage_from_invoice(self, invoice):
        """Fallback: get coverage from invoice cache"""
        try:
            return (
                getattr(invoice, "custom_coverage_start_date", None),
                getattr(invoice, "custom_coverage_end_date", None),
            )
        except Exception as e:
            frappe.log_error(
                f"Error getting coverage from invoice cache: {str(e)}", "Invoice Coverage Cache Error"
            )
            return (None, None)

    def validate_payment_method(self):
        """Validate payment method and related fields"""
        if not hasattr(self, "payment_method"):
            memberships = frappe.get_all(
                "Membership",
                filters={"member": self.name, "status": ["!=", "Cancelled"]},
                fields=["name"],
            )

            for membership in memberships:
                if membership.payment_method == "SEPA Direct Debit":
                    default_mandate = self.get_default_sepa_mandate()
                    if not default_mandate:
                        frappe.msgprint(
                            _(
                                "Member {0} has a membership with SEPA Direct Debit payment method but no active SEPA mandate."
                            ).format(self.name),
                            indicator="yellow",
                        )
                    break

            return

    def set_payment_reference(self):
        """Generate a unique payment reference for this membership"""
        if not self.payment_reference and self.name:
            self.payment_reference = self.name

    def validate_bank_details(self):
        """Validate bank details if payment method is SEPA Direct Debit"""
        # Track IBAN changes for history
        if hasattr(self, "iban") and self.iban:
            # Format and validate IBAN
            self.iban = self.validate_iban_format(self.iban)

            # Check if IBAN has changed on existing records
            if not self.is_new() and self.has_value_changed("iban"):
                self.track_iban_change()

        # Additional validation for SEPA Direct Debit
        if getattr(self, "payment_method", None) == "SEPA Direct Debit":
            if not self.iban:
                frappe.throw(_("IBAN is required for SEPA Direct Debit payment method"))

            if not self.bank_account_name:
                frappe.throw(_("Account Holder Name is required for SEPA Direct Debit payment method"))

    def validate_iban_format(self, iban):
        """Comprehensive IBAN validation and formatting using enhanced validator"""
        if not iban:
            return None

        from verenigingen.utils.validation.iban_validator import (
            derive_bic_from_iban,
            format_iban,
            validate_iban,
        )

        # Validate IBAN
        validation_result = validate_iban(iban)
        if not validation_result["valid"]:
            error_message = validation_result["message"]

            # Provide more user-friendly error messages
            if "checksum" in error_message.lower():
                error_message = _(
                    "The IBAN you entered appears to be incorrect. "
                    "Please double-check the account number and try again. "
                    "Common issues include typos or missing/extra digits."
                )
            elif "too short" in error_message.lower():
                error_message = _(
                    "The IBAN you entered is too short. " "Please enter the complete IBAN number."
                )
            elif "invalid characters" in error_message.lower():
                error_message = _(
                    "The IBAN contains invalid characters. " "IBANs should only contain letters and numbers."
                )
            elif "must be" in error_message and "characters" in error_message:
                # Keep the country-specific length message as it's already helpful
                pass

            frappe.throw(error_message, title=_("Invalid IBAN"), exc=frappe.ValidationError)

        # Format IBAN properly
        formatted_iban = format_iban(iban)

        # Auto-derive BIC if not provided
        if hasattr(self, "bic") and not self.bic:
            derived_bic = derive_bic_from_iban(iban)
            if derived_bic:
                self.bic = derived_bic
                frappe.msgprint(_("BIC automatically derived from IBAN: {0}").format(derived_bic))

        return formatted_iban

    def track_iban_change(self):
        """Track IBAN changes in history"""
        try:
            # Get old IBAN from database
            old_iban = frappe.db.get_value("Member", self.name, "iban")

            if old_iban and old_iban != self.iban:
                # Close the previous IBAN history record
                if hasattr(self, "iban_history"):
                    for history in self.iban_history:
                        if history.is_active and history.iban == old_iban:
                            history.is_active = 0
                            history.to_date = today()

                # Add new IBAN history record
                self.append(
                    "iban_history",
                    {
                        "iban": self.iban,
                        "bic": self.bic,
                        "bank_account_name": self.bank_account_name,
                        "from_date": today(),
                        "is_active": 1,
                        "changed_by": frappe.session.user,
                        "change_reason": "Bank Change" if old_iban else "Initial Setup",
                    },
                )

                # Log the change
                frappe.logger().info(f"IBAN changed for member {self.name} from {old_iban} to {self.iban}")

                # Check if SEPA mandates need to be updated
                if hasattr(self, "payment_method") and self.payment_method == "SEPA Direct Debit":
                    frappe.msgprint(
                        _(
                            "IBAN has been changed. Please review SEPA mandates as they may need to be updated."
                        ),
                        indicator="orange",
                        alert=True,
                    )
        except Exception as e:
            frappe.logger().error(f"Error tracking IBAN change for member {self.name}: {str(e)}")

    def sync_payment_amount(self):
        """Sync payment amount from membership type"""
        if hasattr(self, "payment_amount") and not self.payment_amount:
            active_membership = self.get_active_membership()
            if active_membership and active_membership.membership_type:
                membership_type = frappe.get_doc("Membership Type", active_membership.membership_type)
                if not membership_type.dues_schedule_template:
                    frappe.throw(
                        f"Membership Type '{membership_type.name}' must have a dues schedule template"
                    )
                template = frappe.get_doc("Membership Dues Schedule", membership_type.dues_schedule_template)
                self.payment_amount = template.suggested_amount or 0

    def create_payment_entry(self, payment_date=None, amount=None):
        """Create a payment entry for this membership"""
        if not payment_date:
            payment_date = today()

        if not amount:
            amount = self.payment_amount or 0

        member = frappe.get_doc("Member", self.member)
        if not member.customer:
            frappe.throw(_("Member must have a linked customer for payment processing"))

        settings = frappe.get_single("Verenigingen Settings")

        payment_entry = frappe.new_doc("Payment Entry")
        payment_entry.payment_type = "Receive"
        payment_entry.party_type = "Customer"
        payment_entry.party = member.customer
        payment_entry.posting_date = payment_date
        payment_entry.paid_from = settings.membership_debit_account
        payment_entry.paid_to = settings.membership_payment_account
        payment_entry.paid_amount = amount
        payment_entry.received_amount = amount
        payment_entry.reference_no = self.payment_reference
        payment_entry.reference_date = payment_date
        payment_entry.mode_of_payment = self.payment_method

        payment_entry.append(
            "references",
            {"reference_doctype": "Membership", "reference_name": self.name, "allocated_amount": amount},
        )

        payment_entry.flags.ignore_mandatory = True
        payment_entry.insert(ignore_permissions=True)
        payment_entry.submit()

        self.payment_status = "Paid"
        self.payment_date = payment_date
        self.paid_amount = amount
        self.db_set("payment_status", "Paid")
        self.db_set("payment_date", payment_date)
        self.db_set("paid_amount", amount)

        return payment_entry.name

    def process_payment(self, payment_method=None):
        """Process payment for this membership"""
        if payment_method:
            self.payment_method = payment_method

        if self.payment_method == "SEPA Direct Debit":
            batch = self.add_to_direct_debit_batch()
            self.payment_status = "Pending"
            self.db_set("payment_status", "Pending")
            return batch
        else:
            payment_entry = self.create_payment_entry()
            return payment_entry

    def add_to_direct_debit_batch(self):
        """Add this membership to a direct debit batch"""
        open_batch = frappe.get_all(
            "SEPA Direct Debit Batch", filters={"status": "Draft", "docstatus": 0}, limit=1
        )

        if open_batch:
            batch = frappe.get_doc("SEPA Direct Debit Batch", open_batch[0].name)
        else:
            batch = frappe.new_doc("SEPA Direct Debit Batch")
            batch.batch_date = today()
            batch.batch_description = f"Membership payments - {today()}"
            batch.batch_type = "RCUR"
            batch.currency = "EUR"

        batch.append(
            "invoices",
            {
                "membership": self.name,
                "member": self.member,
                "member_name": self.member_name,
                "amount": self.payment_amount,
                "currency": "EUR",
                "iban": self.iban,
                "mandate_reference": self.mandate_reference or self.sepa_mandate,
                "status": "Pending",
            },
        )

        batch.calculate_totals()
        batch.save()

        return batch.name

    @frappe.whitelist()
    def mark_as_paid(self, payment_date=None, amount=None):
        """Mark membership as paid"""
        if not payment_date:
            payment_date = today()

        if not amount:
            amount = self.payment_amount

        self.payment_status = "Paid"
        self.payment_date = payment_date
        self.paid_amount = amount

        self.save()

        settings = frappe.get_single("Verenigingen Settings")
        if not settings.automate_membership_payment_entries:
            self.create_payment_entry(payment_date, amount)

        return True

    def check_payment_status(self):
        """Check and update payment status"""
        if self.payment_status == "Paid":
            return

        if self.payment_status == "Unpaid" and self.start_date:
            days_overdue = date_diff(today(), self.start_date)
            if days_overdue > 30:
                self.payment_status = "Overdue"
                self.db_set("payment_status", "Overdue")

    def can_view_member_payments(self, view_member):
        """Check if this member can view another member's payment info"""
        if "System Manager" in frappe.get_roles(self.user):
            return True

        if self.name == view_member:
            return True

        if not self._is_chapter_management_enabled():
            return False

        member_obj = frappe.get_doc("Member", view_member)

        if member_obj.permission_category == "Public":
            return True

        if member_obj.permission_category == "Admin Only":
            return False

        # Check if member belongs to any chapters
        member_chapters = self.get_member_chapters()
        if member_chapters:
            # Check if any of the member's chapters allow viewing payments
            for chapter_name in member_chapters:
                chapter = frappe.get_doc("Chapter", chapter_name)
                if chapter.can_view_member_payments(self.name):
                    return True

        return False

    def get_member_chapters(self):
        """Get list of chapters this member belongs to"""
        try:
            chapters = frappe.get_all(
                "Chapter Member",
                filters={"member": self.name, "enabled": 1},
                fields=["parent"],
                order_by="chapter_join_date desc",
            )
            return [ch.parent for ch in chapters]
        except Exception:
            return []

    def _is_chapter_management_enabled(self):
        """Check if chapter management is enabled"""
        try:
            return frappe.db.get_single_value("Verenigingen Settings", "enable_chapter_management") == 1
        except Exception:
            return True

    @frappe.whitelist()
    def refresh_financial_history(self):
        """
        Atomic financial history refresh - adds missing entries without clearing existing data.
        This is the method called by the "Refresh Financial History" button and scheduled tasks.
        """
        try:
            # Set flags to reduce activity logging for bulk financial updates
            self.flags.ignore_version = True
            self.flags.ignore_links = True

            # Use atomic approach: only add missing invoices
            added_count = self._atomic_payment_history_refresh()

            # 2. Refresh dues schedule history if the method exists
            if hasattr(self, "refresh_dues_schedule_history"):
                self.refresh_dues_schedule_history()

            # 3. Update current dues schedule details if the method exists
            if hasattr(self, "get_current_dues_schedule_details"):
                self.get_current_dues_schedule_details()

            # Save once with reduced logging
            self.save(ignore_permissions=True)

            return {
                "success": True,
                "message": f"Financial history refreshed for member {self.name} - {added_count} new entries added",
                "payment_history_count": len(self.payment_history) if hasattr(self, "payment_history") else 0,
                "added_entries": added_count,
                "method": "atomic_updates_only",
            }

        except Exception as e:
            frappe.logger().error(f"Error refreshing financial history for member {self.name}: {str(e)}")
            return {"success": False, "message": f"Error refreshing financial history: {str(e)}"}

    def _atomic_payment_history_refresh(self):
        """
        Atomic payment history refresh - only adds missing invoices, never clears existing data
        Returns the number of new entries added
        """
        if not self.customer:
            return 0

        try:
            # Get all invoices for this customer
            invoices = frappe.get_all(
                "Sales Invoice",
                filters={
                    "customer": self.customer,
                    "docstatus": ["in", [0, 1]],  # Include both draft and submitted
                },
                fields=["name", "posting_date", "creation"],
                order_by="creation desc",
            )

            # Get existing payment history invoice names for quick lookup
            existing_invoices = set()
            for row in self.payment_history or []:
                if row.invoice:
                    existing_invoices.add(row.invoice)

            # Add missing invoices only
            added_count = 0
            for invoice_data in invoices:
                invoice_name = invoice_data.name
                if invoice_name not in existing_invoices:
                    # Add this invoice using the existing atomic method
                    self.add_invoice_to_payment_history(invoice_name)
                    added_count += 1

            return added_count

        except Exception as e:
            frappe.logger().error(f"Error in atomic payment history refresh: {str(e)}")
            return 0

    @frappe.whitelist()
    def force_full_payment_history_rebuild(self):
        """
        Legacy method for full payment history rebuild - ONLY use when atomic updates fail
        This method clears and rebuilds the entire payment history table
        """
        try:
            # Set flags to reduce activity logging for bulk financial updates
            self.flags.ignore_version = True
            self.flags.ignore_links = True

            # LEGACY: Use the old full refresh method
            self._load_payment_history_without_save()

            # Save once with reduced logging
            self.save(ignore_permissions=True)

            return {
                "success": True,
                "message": f"Full payment history rebuild completed for member {self.name} (LEGACY METHOD USED)",
                "payment_history_count": len(self.payment_history) if hasattr(self, "payment_history") else 0,
                "method": "full_table_clear_and_rebuild",
                "warning": "This method clears all existing payment history and rebuilds it",
            }

        except Exception as e:
            frappe.logger().error(f"Error in full payment history rebuild for member {self.name}: {str(e)}")
            return {"success": False, "message": f"Error in full rebuild: {str(e)}"}

    # ===== NEW INCREMENTAL UPDATE METHODS =====

    def add_invoice_to_payment_history(self, invoice_name):
        """Add a single invoice to payment history incrementally"""
        if not self.customer:
            return

        try:
            # Check if invoice already exists in payment history
            existing_idx = None
            for idx, row in enumerate(self.payment_history or []):
                if row.invoice == invoice_name:
                    existing_idx = idx
                    break

            # Get invoice details
            invoice = frappe.get_doc("Sales Invoice", invoice_name)

            # Skip if not for this customer
            if invoice.customer != self.customer:
                return

            # Build payment history entry
            entry_data = self._build_payment_history_entry(invoice)

            if existing_idx is not None:
                # Update existing entry
                for key, value in entry_data.items():
                    setattr(self.payment_history[existing_idx], key, value)
            else:
                # Add new entry at the beginning - use append to create proper Document object
                self.append("payment_history", entry_data)

                # Keep only 20 most recent entries
                if len(self.payment_history) > 20:
                    self.payment_history = self.payment_history[:20]

            # Save with minimal logging
            self.flags.ignore_version = True
            self.flags.ignore_links = True
            self.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error adding invoice {invoice_name} to payment history: {str(e)}",
                "Incremental Payment History Update",
            )

    def remove_invoice_from_payment_history(self, invoice_name):
        """Remove a cancelled invoice from payment history"""
        if not hasattr(self, "payment_history") or not self.payment_history:
            return

        try:
            # Find and remove the invoice
            updated_history = []
            removed = False

            for row in self.payment_history:
                if row.invoice != invoice_name:
                    updated_history.append(row)
                else:
                    removed = True

            if removed:
                self.payment_history = updated_history

                # Save with minimal logging
                self.flags.ignore_version = True
                self.flags.ignore_links = True
                self.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error removing invoice {invoice_name} from payment history: {str(e)}",
                "Incremental Payment History Update",
            )

    def update_invoice_in_payment_history(self, invoice_name):
        """Update an existing invoice in payment history"""
        if not hasattr(self, "payment_history") or not self.payment_history:
            # If no history exists, just add it
            self.add_invoice_to_payment_history(invoice_name)
            return

        try:
            # Find the invoice in payment history
            found = False
            for idx, row in enumerate(self.payment_history):
                if row.invoice == invoice_name:
                    found = True
                    # Get updated invoice details
                    invoice = frappe.get_doc("Sales Invoice", invoice_name)
                    entry_data = self._build_payment_history_entry(invoice)

                    # Update the entry
                    for key, value in entry_data.items():
                        setattr(self.payment_history[idx], key, value)
                    break

            if not found:
                # Invoice not in history, add it
                self.add_invoice_to_payment_history(invoice_name)
            else:
                # Save the updates with minimal logging
                self.flags.ignore_version = True
                self.flags.ignore_links = True
                self.save(ignore_permissions=True)

        except Exception as e:
            frappe.log_error(
                f"Error updating invoice {invoice_name} in payment history: {str(e)}",
                "Incremental Payment History Update",
            )

    def _build_payment_history_entry(self, invoice):
        """Build a payment history entry from an invoice document"""
        try:
            # Extract all the invoice details as in the original method
            reference_doctype = None
            reference_name = None
            transaction_type = "Regular Invoice"

            # Check if invoice is linked to a membership
            if hasattr(invoice, "membership") and invoice.membership:
                transaction_type = "Membership Invoice"
                reference_doctype = "Membership"
                reference_name = invoice.membership

            # Find linked payment entries
            payment_entries = frappe.get_all(
                "Payment Entry Reference",
                filters={"reference_doctype": "Sales Invoice", "reference_name": invoice.name},
                fields=["parent", "allocated_amount"],
            )

            payment_status = "Unpaid"
            payment_date = None
            payment_entry = None
            payment_method = None
            paid_amount = 0
            reconciled = 0

            if payment_entries:
                for pe in payment_entries:
                    paid_amount += float(pe.allocated_amount or 0)

                most_recent_payment = frappe.get_all(
                    "Payment Entry",
                    filters={"name": ["in", [pe.parent for pe in payment_entries]]},
                    fields=["name", "posting_date", "mode_of_payment", "paid_amount"],
                    order_by="posting_date desc",
                )

                if most_recent_payment:
                    payment_entry = most_recent_payment[0].name
                    payment_date = most_recent_payment[0].posting_date
                    payment_method = most_recent_payment[0].mode_of_payment
                    reconciled = 1

            # Set payment status
            if invoice.docstatus == 0:
                payment_status = "Draft"
            elif invoice.status == "Paid":
                payment_status = "Paid"
            elif invoice.status == "Overdue":
                payment_status = "Overdue"
            elif invoice.status == "Cancelled":
                payment_status = "Cancelled"
            elif paid_amount > 0 and paid_amount < invoice.grand_total:
                payment_status = "Partially Paid"

            # Get coverage dates
            coverage_start_date = None
            coverage_end_date = None

            try:
                schedule_coverage = self._get_coverage_from_schedule(invoice.name)
                invoice_coverage = self._get_coverage_from_invoice(invoice)

                coverage_start_date = schedule_coverage[0] or invoice_coverage[0]
                coverage_end_date = schedule_coverage[1] or invoice_coverage[1]
            except (AttributeError, IndexError, TypeError) as e:
                frappe.log_error(
                    f"Error getting coverage dates for invoice {invoice.name}: {e}", "CoverageExtraction"
                )
                coverage_start_date = None
                coverage_end_date = None

            # Check for SEPA mandate
            has_mandate = 0
            sepa_mandate = None
            mandate_status = None
            mandate_reference = None

            default_mandate = self.get_default_sepa_mandate()
            if default_mandate:
                has_mandate = 1
                sepa_mandate = default_mandate.name
                mandate_status = default_mandate.status
                mandate_reference = default_mandate.mandate_id

            return {
                "invoice": invoice.name,
                "posting_date": invoice.posting_date,
                "due_date": invoice.due_date,
                "coverage_start_date": coverage_start_date,
                "coverage_end_date": coverage_end_date,
                "transaction_type": transaction_type,
                "reference_doctype": reference_doctype,
                "reference_name": reference_name,
                "amount": invoice.grand_total,
                "outstanding_amount": invoice.outstanding_amount,
                "status": invoice.status,
                "payment_status": payment_status,
                "payment_date": payment_date,
                "payment_entry": payment_entry,
                "payment_method": payment_method,
                "paid_amount": paid_amount,
                "reconciled": reconciled,
                "has_mandate": has_mandate,
                "sepa_mandate": sepa_mandate,
                "mandate_status": mandate_status,
                "mandate_reference": mandate_reference,
            }

        except Exception as e:
            frappe.log_error(
                f"Error building payment history entry for invoice {invoice.name}: {str(e)}",
                "Payment History Entry Build Error",
            )
            # Return minimal entry on error
            return {
                "invoice": invoice.name,
                "posting_date": invoice.posting_date,
                "amount": invoice.grand_total,
                "status": invoice.status,
                "payment_status": "Unknown",
            }
