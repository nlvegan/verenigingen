# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, add_months, flt, getdate, today


class PaymentPlan(Document):
    def validate(self):
        self.validate_plan_details()
        self.validate_member_and_schedule()
        self.calculate_end_date()
        self.generate_installments()
        self.update_tracking_fields()

    def validate_plan_details(self):
        """Validate payment plan configuration"""
        if self.plan_type == "Equal Installments":
            if not self.number_of_installments or self.number_of_installments <= 0:
                frappe.throw(_("Number of installments must be greater than 0"))

            if not self.frequency:
                frappe.throw(_("Payment frequency is required for equal installments"))

            # Calculate installment amount
            self.installment_amount = flt(self.total_amount / self.number_of_installments, 2)

        elif self.plan_type == "Custom Schedule":
            # For custom schedules, installments will be manually added
            pass

        elif self.plan_type == "Deferred Payment":
            # Single payment at end date
            self.number_of_installments = 1
            self.installment_amount = self.total_amount

    def validate_member_and_schedule(self):
        """Validate member and associated dues schedule"""
        if not frappe.db.exists("Member", self.member):
            frappe.throw(_("Invalid member selected"))

        if self.membership_dues_schedule:
            if not frappe.db.exists("Membership Dues Schedule", self.membership_dues_schedule):
                frappe.throw(_("Invalid membership dues schedule"))

            # Check that the schedule belongs to the member
            schedule_member = frappe.db.get_value(
                "Membership Dues Schedule", self.membership_dues_schedule, "member"
            )
            if schedule_member != self.member:
                frappe.throw(_("Membership dues schedule does not belong to selected member"))

    def calculate_end_date(self):
        """Calculate expected end date based on plan configuration"""
        if not self.start_date:
            return

        if self.plan_type == "Equal Installments" and self.frequency and self.number_of_installments:
            start = getdate(self.start_date)

            if self.frequency == "Weekly":
                self.end_date = start + timedelta(weeks=self.number_of_installments - 1)
            elif self.frequency == "Bi-weekly":
                self.end_date = start + timedelta(weeks=(self.number_of_installments - 1) * 2)
            elif self.frequency == "Monthly":
                self.end_date = add_months(start, self.number_of_installments - 1)

        elif self.plan_type == "Deferred Payment":
            # For deferred payment, end date should be manually set
            if not self.end_date:
                # Default to 3 months from start
                self.end_date = add_months(getdate(self.start_date), 3)

    def generate_installments(self):
        """Generate installment schedule"""
        if self.plan_type == "Custom Schedule":
            # Don't auto-generate for custom schedules
            return

        # Clear existing installments
        self.set("installments", [])

        if self.plan_type == "Equal Installments":
            self._generate_equal_installments()
        elif self.plan_type == "Deferred Payment":
            self._generate_deferred_payment()

    def _generate_equal_installments(self):
        """Generate equal installment schedule"""
        if not self.start_date or not self.number_of_installments:
            return

        current_date = getdate(self.start_date)

        for i in range(self.number_of_installments):
            # Calculate due date
            if self.frequency == "Weekly":
                due_date = current_date + timedelta(weeks=i)
            elif self.frequency == "Bi-weekly":
                due_date = current_date + timedelta(weeks=i * 2)
            elif self.frequency == "Monthly":
                due_date = add_months(current_date, i)
            else:
                due_date = current_date + timedelta(days=i * 30)  # Default fallback

            # Handle rounding for the last installment
            amount = self.installment_amount
            if i == self.number_of_installments - 1:
                # Last installment gets any remaining amount due to rounding
                total_previous = flt(self.installment_amount * (self.number_of_installments - 1), 2)
                amount = flt(self.total_amount - total_previous, 2)

            self.append(
                "installments",
                {"installment_number": i + 1, "due_date": due_date, "amount": amount, "status": "Pending"},
            )

    def _generate_deferred_payment(self):
        """Generate single deferred payment"""
        self.append(
            "installments",
            {
                "installment_number": 1,
                "due_date": self.end_date or add_months(getdate(self.start_date), 3),
                "amount": self.total_amount,
                "status": "Pending",
            },
        )

    def update_tracking_fields(self):
        """Update payment tracking fields"""
        if not self.installments:
            return

        # Calculate totals
        total_paid = 0
        last_payment_date = None
        next_payment_date = None
        consecutive_missed = 0

        today_date = getdate(today())

        for installment in self.installments:
            if installment.status == "Paid":
                total_paid += flt(installment.amount)
                if installment.payment_date:
                    if not last_payment_date or getdate(installment.payment_date) > getdate(
                        last_payment_date
                    ):
                        last_payment_date = installment.payment_date

            elif installment.status == "Pending":
                if not next_payment_date or getdate(installment.due_date) < getdate(next_payment_date):
                    next_payment_date = installment.due_date

            elif installment.status == "Overdue" and getdate(installment.due_date) < today_date:
                consecutive_missed += 1
            else:
                consecutive_missed = 0  # Reset counter if we find a non-overdue payment

        self.total_paid = total_paid
        self.remaining_balance = flt(self.total_amount - total_paid, 2)
        self.last_payment_date = last_payment_date
        self.next_payment_date = next_payment_date
        self.consecutive_missed_payments = consecutive_missed

        # Update status based on progress
        if self.remaining_balance <= 0:
            self.status = "Completed"
        elif consecutive_missed >= 3:
            self.status = "Suspended"
        elif self.status in ["Draft", "Pending Approval"]:
            pass  # Keep as draft/pending until approved
        elif self.status not in ["Cancelled", "Completed", "Suspended"]:
            self.status = "Active"

    def on_submit(self):
        """Handle payment plan submission"""
        if self.approval_required and not self.approved_by:
            frappe.throw(_("Payment plan requires approval before activation"))

        if self.status in ["Draft", "Pending Approval"]:
            self.status = "Active"

        # Update associated dues schedule if exists
        if self.membership_dues_schedule:
            self.update_dues_schedule_for_payment_plan()

    def activate_plan(self):
        """Activate the payment plan (used for direct activation without submission)"""
        if self.status == "Draft":
            self.status = "Active"
            self.save()

            # Update associated dues schedule if exists
            if self.membership_dues_schedule:
                self.update_dues_schedule_for_payment_plan()

            return True
        return False

    def update_dues_schedule_for_payment_plan(self):
        """Update membership dues schedule when payment plan is activated"""
        try:
            schedule = frappe.get_doc("Membership Dues Schedule", self.membership_dues_schedule)

            # Pause regular billing while payment plan is active
            schedule.status = "Payment Plan Active"
            schedule.payment_plan = self.name
            schedule.add_comment(text=f"Payment plan {self.name} activated. Regular billing paused.")
            schedule.save()

        except Exception as e:
            frappe.log_error(f"Error updating dues schedule: {str(e)}")

    @frappe.whitelist()
    def process_payment(self, installment_number, payment_amount, payment_reference=None, payment_date=None):
        """Process a payment for a specific installment"""
        if not payment_date:
            payment_date = today()

        # Find the installment
        installment = None
        for inst in self.installments:
            if inst.installment_number == installment_number:
                installment = inst
                break

        if not installment:
            frappe.throw(_("Installment {0} not found").format(installment_number))

        if installment.status == "Paid":
            frappe.throw(_("Installment {0} is already paid").format(installment_number))

        # Update installment
        installment.status = "Paid"
        installment.payment_date = payment_date
        installment.payment_reference = payment_reference or ""

        # Handle partial payments
        if flt(payment_amount) < flt(installment.amount):
            # Create a note about partial payment
            installment.notes = f"Partial payment of €{payment_amount} received. Outstanding: €{flt(installment.amount) - flt(payment_amount)}"
            installment.amount = flt(installment.amount) - flt(payment_amount)
            installment.status = "Pending"  # Keep as pending for remaining amount

        self.update_tracking_fields()
        self.save()

        # Create payment entry if ERPNext integration is available
        self.create_payment_entry(payment_amount, payment_reference, payment_date)

        # Send payment confirmation
        self.send_payment_confirmation(installment_number, payment_amount)

    def create_payment_entry(self, amount, reference, payment_date):
        """Create ERPNext payment entry for the payment"""
        try:
            # Get member's customer record
            member = frappe.get_doc("Member", self.member)
            if not member.customer:
                return  # Skip if no customer record

            # Create payment entry
            payment_entry = frappe.new_doc("Payment Entry")
            payment_entry.payment_type = "Receive"
            payment_entry.party_type = "Customer"
            payment_entry.party = member.customer
            payment_entry.paid_amount = amount
            payment_entry.received_amount = amount
            payment_entry.posting_date = payment_date
            payment_entry.reference_no = reference or f"Payment Plan {self.name}"
            payment_entry.reference_date = payment_date

            # Set accounts (you may need to adjust these based on your setup)
            payment_entry.paid_to = frappe.db.get_single_value(
                "Verenigingen Settings", "default_receivable_account"
            )
            payment_entry.paid_from = frappe.db.get_single_value(
                "Verenigingen Settings", "default_cash_account"
            )

            payment_entry.save()
            payment_entry.submit()

        except Exception as e:
            frappe.log_error(f"Error creating payment entry: {str(e)}")

    def send_payment_confirmation(self, installment_number, amount):
        """Send payment confirmation email"""
        try:
            member = frappe.get_doc("Member", self.member)

            subject = _("Payment Received - Payment Plan {0}").format(self.name)
            message = f"""
            Dear {member.full_name},

            We have received your payment of €{amount:.2f} for installment #{installment_number} of your payment plan.

            Payment Plan: {self.name}
            Remaining Balance: €{self.remaining_balance:.2f}
            Next Payment Due: {self.next_payment_date or 'N/A'}

            Thank you for your payment.

            Best regards,
            The Membership Team
            """

            frappe.sendmail(
                recipients=[member.email],
                subject=subject,
                message=message,
                reference_doctype="Payment Plan",
                reference_name=self.name,
            )

        except Exception as e:
            frappe.log_error(f"Error sending payment confirmation: {str(e)}")

    def mark_installment_overdue(self, installment_number):
        """Mark an installment as overdue"""
        for installment in self.installments:
            if installment.installment_number == installment_number:
                if installment.status == "Pending":
                    installment.status = "Overdue"
                    break

        self.update_tracking_fields()
        self.save()

        # Send overdue notification
        self.send_overdue_notification(installment_number)

    def send_overdue_notification(self, installment_number):
        """Send overdue payment notification"""
        try:
            member = frappe.get_doc("Member", self.member)

            subject = _("Payment Overdue - Payment Plan {0}").format(self.name)
            message = f"""
            Dear {member.full_name},

            Your payment for installment #{installment_number} is now overdue.

            Payment Plan: {self.name}
            Outstanding Amount: €{self.remaining_balance:.2f}
            Consecutive Missed Payments: {self.consecutive_missed_payments}

            Please make your payment as soon as possible to avoid suspension of your payment plan.

            If you are experiencing financial difficulties, please contact us to discuss options.

            Best regards,
            The Membership Team
            """

            frappe.sendmail(
                recipients=[member.email],
                subject=subject,
                message=message,
                reference_doctype="Payment Plan",
                reference_name=self.name,
            )

        except Exception as e:
            frappe.log_error(f"Error sending overdue notification: {str(e)}")

    def cancel_plan(self, reason=None):
        """Cancel the payment plan"""
        self.status = "Cancelled"
        if reason:
            self.add_comment(text=f"Plan cancelled: {reason}")

        # Reactivate dues schedule if it was paused
        if self.membership_dues_schedule:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", self.membership_dues_schedule)
                if schedule.status == "Payment Plan Active":
                    schedule.status = "Active"
                    schedule.payment_plan = ""
                    schedule.add_comment(text=f"Payment plan {self.name} cancelled. Regular billing resumed.")
                    schedule.save()
            except Exception as e:
                frappe.log_error(f"Error reactivating dues schedule: {str(e)}")

        self.save()


# API Functions


@frappe.whitelist()
def create_payment_plan_from_application(member, total_amount, installments, frequency, reason=None):
    """Create payment plan from membership application or dues schedule"""
    try:
        payment_plan = frappe.new_doc("Payment Plan")
        payment_plan.member = member
        payment_plan.plan_type = "Equal Installments"
        payment_plan.total_amount = total_amount
        payment_plan.number_of_installments = installments
        payment_plan.frequency = frequency
        payment_plan.start_date = today()
        payment_plan.status = "Pending Approval"
        payment_plan.approval_required = 1
        payment_plan.reason = reason or "Member requested installment payments"

        payment_plan.save()
        return payment_plan.name

    except Exception as e:
        frappe.log_error(f"Error creating payment plan: {str(e)}")
        frappe.throw(_("Error creating payment plan: {0}").format(str(e)))


@frappe.whitelist()
def approve_payment_plan(plan_name, approver_notes=None):
    """Approve a payment plan"""
    try:
        plan = frappe.get_doc("Payment Plan", plan_name)

        if plan.status != "Pending Approval":
            frappe.throw(_("Payment plan is not pending approval"))

        plan.approved_by = frappe.session.user
        plan.approval_date = datetime.now()
        plan.status = "Active"

        if approver_notes:
            plan.add_comment(text=f"Approved: {approver_notes}")

        plan.save()
        plan.submit()

        return True

    except Exception as e:
        frappe.log_error(f"Error approving payment plan: {str(e)}")
        frappe.throw(_("Error approving payment plan: {0}").format(str(e)))


@frappe.whitelist()
def process_overdue_installments():
    """Scheduled function to mark overdue installments"""
    try:
        # Get all active payment plans
        active_plans = frappe.get_all(
            "Payment Plan", filters={"status": ["in", ["Active", "Pending Approval"]]}, fields=["name"]
        )

        today_date = getdate(today())
        updated_count = 0

        for plan_data in active_plans:
            plan = frappe.get_doc("Payment Plan", plan_data.name)

            for installment in plan.installments:
                if installment.status == "Pending" and getdate(installment.due_date) < today_date:
                    plan.mark_installment_overdue(installment.installment_number)
                    updated_count += 1

        frappe.logger().info(f"Marked {updated_count} installments as overdue")
        return updated_count

    except Exception as e:
        frappe.log_error(f"Error processing overdue installments: {str(e)}")
        return 0
