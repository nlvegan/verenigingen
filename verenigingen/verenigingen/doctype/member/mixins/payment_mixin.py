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

        self.payment_history = []

        # 1. Get all submitted invoices for this customer
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": self.customer, "docstatus": 1},
            fields=["name", "posting_date", "due_date", "grand_total", "outstanding_amount", "status"],
            order_by="posting_date desc",
        )

        reconciled_payments = []

        # 2. Process each invoice and its payment status
        for invoice in invoices:
            invoice_doc = frappe.get_doc("Sales Invoice", invoice.name)

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

            # Set payment status based on invoice and payment data
            if invoice.status == "Paid":
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

            # Add invoice to payment history
            self.append(
                "payment_history",
                {
                    "invoice": invoice.name,
                    "posting_date": invoice.posting_date,
                    "due_date": invoice.due_date,
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

    def validate_payment_method(self):
        """Validate payment method and related fields"""
        if not hasattr(self, "payment_method"):
            memberships = frappe.get_all(
                "Membership",
                filters={"member": self.name, "status": ["!=", "Cancelled"]},
                fields=["name", "payment_method"],
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

        from verenigingen.utils.iban_validator import derive_bic_from_iban, format_iban, validate_iban

        # Validate IBAN
        validation_result = validate_iban(iban)
        if not validation_result["valid"]:
            frappe.throw(_(validation_result["message"]))

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
                self.payment_amount = membership_type.amount

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
        Comprehensive financial history refresh.
        This is the method called by the "Refresh Financial History" button and scheduled tasks.
        """
        try:
            # 1. Load payment history (invoices, payments, etc.)
            self.load_payment_history()

            # 2. Refresh subscription history if the method exists
            if hasattr(self, "refresh_subscription_history"):
                self.refresh_subscription_history()

            # 3. Update current subscription details if the method exists
            if hasattr(self, "get_current_subscription_details"):
                self.get_current_subscription_details()

            return {
                "success": True,
                "message": f"Financial history refreshed for member {self.name}",
                "payment_history_count": len(self.payment_history) if hasattr(self, "payment_history") else 0,
            }

        except Exception as e:
            frappe.logger().error(f"Error refreshing financial history for member {self.name}: {str(e)}")
            return {"success": False, "message": f"Error refreshing financial history: {str(e)}"}
