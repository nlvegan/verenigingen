"""
Enhanced expense notification system with professional email templates
and escalation workflows
"""

import frappe
from frappe.utils import add_days, flt, get_url, getdate, today

from verenigingen.utils.security.api_security_framework import OperationType, high_security_api
from verenigingen.verenigingen_payments.services.mollie_configuration_service import get_mollie_config


class ExpenseNotificationManager:
    """Centralized expense notification management"""

    def __init__(self):
        self.company = get_mollie_config().get_default_company()
        self.base_url = get_url()

    def send_approval_request_notification(self, expense_doc):
        """Send enhanced approval request notification to approvers"""
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        manager = ExpensePermissionManager()
        approvers = expense_doc.get_expense_approvers()

        if not approvers:
            frappe.log_error(f"No approvers found for expense {expense_doc.name}")
            return

        # Get expense details
        expense_details = self._get_expense_details(expense_doc)
        required_level = manager.get_required_permission_level(expense_doc.amount)

        # Send to each approver
        for approver_email, approver_name in approvers:
            try:
                self._send_approval_email(
                    expense_doc, expense_details, approver_email, approver_name, required_level
                )
            except Exception as e:
                frappe.log_error(f"Failed to send approval notification to {approver_email}: {str(e)}")

    def send_approval_confirmation(self, expense_doc):
        """Send confirmation when expense is approved"""
        volunteer_email = self._get_volunteer_email(expense_doc.volunteer)
        if not volunteer_email:
            return

        expense_details = self._get_expense_details(expense_doc)

        # MIGRATED: Use unified EmailService for approval confirmation
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "expense": expense_doc,
            "expense_details": expense_details,
            "volunteer_name": expense_details["volunteer_name"],
            "approved_by_name": frappe.db.get_value("User", expense_doc.approved_by, "full_name"),
            "company": self.company,
            "base_url": self.base_url,
        }

        email_service.send_templated_email(
            template_name="expense_approved",
            recipients=[volunteer_email],
            context=context,
            subject_override=f"✅ Expense Approved - {expense_doc.name}",
            reference_doctype="Volunteer Expense",
            reference_name=expense_doc.name,
        )

    def send_rejection_notification(self, expense_doc, reason):
        """Send notification when expense is rejected"""
        volunteer_email = self._get_volunteer_email(expense_doc.volunteer)
        if not volunteer_email:
            return

        expense_details = self._get_expense_details(expense_doc)

        # MIGRATED: Use unified EmailService for rejection notification
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "expense": expense_doc,
            "expense_details": expense_details,
            "volunteer_name": expense_details["volunteer_name"],
            "rejection_reason": reason,
            "rejected_by_name": frappe.db.get_value("User", frappe.session.user, "full_name"),
            "company": self.company,
            "base_url": self.base_url,
        }

        email_service.send_templated_email(
            template_name="expense_rejected",
            recipients=[volunteer_email],
            context=context,
            subject_override=f"❌ Expense Rejected - {expense_doc.name}",
            reference_doctype="Volunteer Expense",
            reference_name=expense_doc.name,
        )

    def send_escalation_notification(self, expense_doc, escalation_reason):
        """Send notification when expense is escalated to higher approval level"""
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        manager = ExpensePermissionManager()

        # Get higher level approvers
        if expense_doc.organization_type == "Chapter":
            admin_approvers = manager.get_chapter_approvers(expense_doc.chapter, "admin")
            approver_emails = [email for email, name, level, role in admin_approvers]
        else:
            # For team expenses, escalate to chapter
            team_doc = frappe.get_doc("Team", expense_doc.team)
            if team_doc.chapter:
                admin_approvers = manager.get_chapter_approvers(team_doc.chapter, "admin")
                approver_emails = [email for email, name, level, role in admin_approvers]
            else:
                # Escalate to association managers
                approver_emails = self._get_association_manager_emails()

        if not approver_emails:
            return

        expense_details = self._get_expense_details(expense_doc)

        # MIGRATED: Use unified EmailService for expense escalation
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "expense": expense_doc,
            "expense_details": expense_details,
            "escalation_reason": escalation_reason,
            "volunteer_name": expense_details["volunteer_name"],
            "formatted_amount": expense_details["formatted_amount"],
            "formatted_date": expense_details["formatted_date"],
            "category_name": expense_details["category_name"],
            "organization_name": expense_details["organization_name"],
            "company": self.company,
            "base_url": self.base_url,
        }

        email_service.send_templated_email(
            template_name="expense_escalated",
            recipients=approver_emails,
            context=context,
            subject_override=f"🔺 Expense Escalated - {expense_doc.name}",
            reference_doctype="Volunteer Expense",
            reference_name=expense_doc.name,
        )

    def send_overdue_reminder(self, days_overdue=7):
        """Send reminder for overdue expense approvals"""
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        # Get overdue expenses
        cutoff_date = add_days(today(), -days_overdue)
        overdue_expenses = frappe.get_all(
            "Volunteer Expense",
            filters={"status": "Submitted", "expense_date": ["<=", cutoff_date], "docstatus": 1},
            fields=["name", "volunteer", "amount", "expense_date", "organization_type", "chapter", "team"],
        )

        if not overdue_expenses:
            return

        # Group by organization and approvers
        manager = ExpensePermissionManager()
        approver_reminders = {}

        for expense_data in overdue_expenses:
            expense_doc = frappe.get_doc("Volunteer Expense", expense_data.name)

            # Skip if user can't approve
            if not manager.can_approve_expense(expense_doc):
                continue

            approvers = expense_doc.get_expense_approvers()
            for approver_email, approver_name in approvers:
                if approver_email not in approver_reminders:
                    approver_reminders[approver_email] = {"name": approver_name, "expenses": []}
                approver_reminders[approver_email]["expenses"].append(expense_data)

        # Send reminder emails
        for approver_email, data in approver_reminders.items():
            self._send_overdue_reminder_email(approver_email, data["name"], data["expenses"], days_overdue)

    def _send_approval_email(
        self, expense_doc, expense_details, approver_email, approver_name, required_level
    ):
        """Send individual approval request email"""
        subject = f"💰 Expense Approval Required - {expense_doc.name}"

        # MIGRATED: Use unified EmailService for approval request
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "doc": expense_doc,  # Templates expect 'doc'
            "expense": expense_doc,
            "expense_details": expense_details,
            "approver_name": approver_name,
            "required_level": required_level.title(),
            "volunteer_name": expense_details["volunteer_name"],
            "formatted_amount": expense_details["formatted_amount"],
            "formatted_date": expense_details["formatted_date"],
            "category_name": expense_details["category_name"],
            "organization_name": expense_details["organization_name"],
            "approval_url": f"{self.base_url}/app/volunteer-expense/{expense_doc.name}",
            "dashboard_url": f"{self.base_url}/app/expense-approval-dashboard",
            "company": self.company,
            "base_url": self.base_url,
            "support_email": frappe.db.get_single_value("Verenigingen Settings", "contact_email")
            or "info@verenigingen.nl",
        }

        email_service.send_templated_email(
            template_name="expense_approval_request",
            recipients=[approver_email],
            context=context,
            subject_override=subject,
            reference_doctype="Volunteer Expense",
            reference_name=expense_doc.name,
        )

    def _send_overdue_reminder_email(self, approver_email, approver_name, expenses, days_overdue):
        """Send overdue reminder email"""
        # MIGRATED: Use unified EmailService for overdue reminder
        from verenigingen.services.communication.email_service import get_email_service

        email_service = get_email_service()

        context = {
            "approver_name": approver_name,
            "expenses": expenses,
            "days_overdue": days_overdue,
            "total_amount": sum(flt(exp.amount) for exp in expenses),
            "dashboard_url": f"{self.base_url}/app/expense-approval-dashboard",
            "company": self.company,
            "base_url": self.base_url,
        }

        email_service.send_templated_email(
            template_name="expense_overdue_reminder",
            recipients=[approver_email],
            context=context,
            subject_override=f"⏰ Overdue Expense Approvals ({len(expenses)} pending)",
            reference_doctype="Volunteer Expense",
            reference_name=expenses[0].name if expenses else None,
        )

    def _get_expense_details(self, expense_doc):
        """Get formatted expense details for templates"""
        volunteer_name = frappe.db.get_value(
            "Verenigingen Volunteer", expense_doc.volunteer, "volunteer_name"
        )
        category_name = (
            frappe.db.get_value("Expense Category", expense_doc.category, "category_name")
            if expense_doc.category
            else "Uncategorized"
        )

        organization_name = expense_doc.chapter or expense_doc.team

        return {
            "volunteer_name": volunteer_name,
            "category_name": category_name,
            "organization_name": organization_name,
            "formatted_amount": f"{expense_doc.currency} {flt(expense_doc.amount):,.2f}",
            "formatted_date": frappe.utils.formatdate(expense_doc.expense_date),
            "days_since_submission": (getdate(today()) - getdate(expense_doc.expense_date)).days,
        }

    def _get_volunteer_email(self, volunteer_name):
        """Get volunteer's email address"""
        volunteer = frappe.get_doc("Volunteer", volunteer_name)
        if hasattr(volunteer, "member") and volunteer.member:
            return frappe.db.get_value("Member", volunteer.member, "email")
        return volunteer.email if hasattr(volunteer, "email") else None

    def _get_association_manager_emails(self):
        """Get association manager email addresses"""
        managers = frappe.get_all(
            "Has Role", filters={"role": "Verenigingen Administrator"}, fields=["parent"]
        )
        return [
            frappe.db.get_value("User", m.parent, "email")
            for m in managers
            if frappe.db.get_value("User", m.parent, "enabled")
        ]

    # Template rendering methods removed - now using unified EmailService


# Convenience functions for external use


@frappe.whitelist()
@high_security_api(operation_type=OperationType.FINANCIAL)
def send_approval_notification(expense_name):
    """Send approval request notification for an expense"""
    expense = frappe.get_doc("Volunteer Expense", expense_name)
    manager = ExpenseNotificationManager()
    manager.send_approval_request_notification(expense)


@frappe.whitelist()
@high_security_api(operation_type=OperationType.ADMIN)
def send_overdue_reminders(days_overdue=7):
    """Send overdue reminders for expenses pending approval"""
    manager = ExpenseNotificationManager()
    manager.send_overdue_reminder(days_overdue)


def send_approval_confirmation(expense_doc):
    """Send approval confirmation - called from expense approval"""
    manager = ExpenseNotificationManager()
    manager.send_approval_confirmation(expense_doc)


def send_rejection_notification(expense_doc, reason):
    """Send rejection notification - called from expense rejection"""
    manager = ExpenseNotificationManager()
    manager.send_rejection_notification(expense_doc, reason)
