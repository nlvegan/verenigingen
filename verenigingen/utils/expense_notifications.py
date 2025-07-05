"""
Enhanced expense notification system with professional email templates
and escalation workflows
"""

import frappe
from frappe.utils import add_days, flt, get_url, getdate, today


class ExpenseNotificationManager:
    """Centralized expense notification management"""

    def __init__(self):
        self.company = frappe.defaults.get_global_default("company") or "Verenigingen"
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

        subject = f"✅ Expense Approved - {expense_doc.name}"

        message = self._render_template(
            "expense_approved",
            {
                "expense": expense_doc,
                "expense_details": expense_details,
                "volunteer_name": expense_details["volunteer_name"],
                "approved_by_name": frappe.db.get_value("User", expense_doc.approved_by, "full_name"),
                "company": self.company,
                "base_url": self.base_url,
            },
        )

        frappe.sendmail(
            recipients=[volunteer_email],
            subject=subject,
            message=message,
            header=f"Expense Approved - {self.company}",
        )

    def send_rejection_notification(self, expense_doc, reason):
        """Send notification when expense is rejected"""
        volunteer_email = self._get_volunteer_email(expense_doc.volunteer)
        if not volunteer_email:
            return

        expense_details = self._get_expense_details(expense_doc)

        subject = f"❌ Expense Rejected - {expense_doc.name}"

        message = self._render_template(
            "expense_rejected",
            {
                "expense": expense_doc,
                "expense_details": expense_details,
                "volunteer_name": expense_details["volunteer_name"],
                "rejection_reason": reason,
                "rejected_by_name": frappe.db.get_value("User", frappe.session.user, "full_name"),
                "company": self.company,
                "base_url": self.base_url,
            },
        )

        frappe.sendmail(
            recipients=[volunteer_email],
            subject=subject,
            message=message,
            header=f"Expense Rejected - {self.company}",
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

        subject = f"⬆️ Expense Escalated - {expense_doc.name}"

        message = self._render_template(
            "expense_escalated",
            {
                "expense": expense_doc,
                "expense_details": expense_details,
                "escalation_reason": escalation_reason,
                "company": self.company,
                "base_url": self.base_url,
            },
        )

        frappe.sendmail(
            recipients=approver_emails,
            subject=subject,
            message=message,
            header=f"Expense Escalation - {self.company}",
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

        message = self._render_template(
            "expense_approval_request",
            {
                "expense": expense_doc,
                "expense_details": expense_details,
                "approver_name": approver_name,
                "required_level": required_level.title(),
                "approval_url": f"{self.base_url}/app/volunteer-expense/{expense_doc.name}",
                "dashboard_url": f"{self.base_url}/app/expense-approval-dashboard",
                "company": self.company,
                "base_url": self.base_url,
            },
        )

        frappe.sendmail(
            recipients=[approver_email],
            subject=subject,
            message=message,
            header=f"Expense Approval - {self.company}",
        )

    def _send_overdue_reminder_email(self, approver_email, approver_name, expenses, days_overdue):
        """Send overdue reminder email"""
        subject = f"⏰ Overdue Expense Approvals ({len(expenses)} pending)"

        message = self._render_template(
            "expense_overdue_reminder",
            {
                "approver_name": approver_name,
                "expenses": expenses,
                "days_overdue": days_overdue,
                "total_amount": sum(flt(exp.amount) for exp in expenses),
                "dashboard_url": f"{self.base_url}/app/expense-approval-dashboard",
                "company": self.company,
                "base_url": self.base_url,
            },
        )

        frappe.sendmail(
            recipients=[approver_email],
            subject=subject,
            message=message,
            header=f"Overdue Approvals - {self.company}",
        )

    def _get_expense_details(self, expense_doc):
        """Get formatted expense details for templates"""
        volunteer_name = frappe.db.get_value("Volunteer", expense_doc.volunteer, "volunteer_name")
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

    def _render_template(self, template_name, context):
        """Render email template with context using Email Template system"""
        from verenigingen.api.email_template_manager import get_email_template

        # Map internal names to Email Template names
        template_mapping = {
            "expense_approval_request": "expense_approval_request",
            "expense_approved": "expense_approved",
            "expense_rejected": "expense_rejected",
            "expense_escalated": "expense_escalated",
            "expense_overdue_reminder": "expense_overdue_reminder",
        }

        email_template_name = template_mapping.get(template_name)
        if email_template_name:
            try:
                template = get_email_template(email_template_name, context)
                return template["message"]
            except Exception as e:
                frappe.log_error(f"Error using Email Template '{email_template_name}': {str(e)}")

        # Fallback to hardcoded templates if Email Template fails
        templates = {
            "expense_approval_request": self._get_approval_request_template(),
            "expense_approved": self._get_approval_confirmation_template(),
            "expense_rejected": self._get_rejection_template(),
            "expense_escalated": self._get_escalation_template(),
            "expense_overdue_reminder": self._get_overdue_reminder_template(),
        }

        template = templates.get(template_name, "")

        # Simple template rendering (replace variables)
        for key, value in context.items():
            placeholder = f"{{{{{key}}}}}"
            template = template.replace(placeholder, str(value))

        return template

    def _get_approval_request_template(self):
        """Professional approval request email template"""
        return """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #2c3e50; margin: 0;">💰 Expense Approval Required</h2>
                <p style="color: #7f8c8d; margin: 5px 0 0 0;">{{company}}</p>
            </div>

            <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                <p>Dear {{approver_name}},</p>

                <p>A new expense has been submitted and requires your <strong>{{required_level}} level</strong> approval:</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{expense.name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Volunteer:</td><td>{{expense_details.volunteer_name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{expense.description}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td style="font-size: 18px; color: #e74c3c;">{{expense_details.formatted_amount}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Date:</td><td>{{expense_details.formatted_date}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Category:</td><td>{{expense_details.category_name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Organization:</td><td>{{expense_details.organization_name}} ({{expense.organization_type}})</td></tr>
                    </table>
                </div>

                <div style="text-align: center; margin: 25px 0;">
                    <a href="{{approval_url}}" style="background-color: #28a745; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                        Review & Approve Expense
                    </a>
                </div>

                <p style="text-align: center; margin-top: 15px;">
                    <a href="{{dashboard_url}}" style="color: #007bff;">View All Pending Approvals</a>
                </p>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated notification from {{company}}.
                    Please do not reply to this email.
                </p>
            </div>
        </div>
        """

    def _get_approval_confirmation_template(self):
        """Approval confirmation email template"""
        return """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #d4edda; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #155724; margin: 0;">✅ Expense Approved</h2>
                <p style="color: #155724; margin: 5px 0 0 0;">{{company}}</p>
            </div>

            <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                <p>Dear {{volunteer_name}},</p>

                <p>Great news! Your expense has been approved by {{approved_by_name}}.</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{expense.name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{expense.description}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td style="font-size: 18px; color: #28a745;">{{expense_details.formatted_amount}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Approved On:</td><td>{{expense.approved_on}}</td></tr>
                    </table>
                </div>

                <p>Your expense will be processed for reimbursement according to the organization's payment schedule.</p>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated notification from {{company}}.
                </p>
            </div>
        </div>
        """

    def _get_rejection_template(self):
        """Rejection notification email template"""
        return """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #f8d7da; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #721c24; margin: 0;">❌ Expense Rejected</h2>
                <p style="color: #721c24; margin: 5px 0 0 0;">{{company}}</p>
            </div>

            <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                <p>Dear {{volunteer_name}},</p>

                <p>We regret to inform you that your expense has been rejected by {{rejected_by_name}}.</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{expense.name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Description:</td><td>{{expense.description}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td>{{expense_details.formatted_amount}}</td></tr>
                    </table>
                </div>

                <div style="background-color: #fff3cd; padding: 15px; border-radius: 5px; margin: 15px 0; border-left: 4px solid #ffc107;">
                    <p style="margin: 0; font-weight: bold;">Rejection Reason:</p>
                    <p style="margin: 5px 0 0 0;">{{rejection_reason}}</p>
                </div>

                <p>If you have questions about this decision, please contact your organization's board or the person who rejected the expense.</p>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated notification from {{company}}.
                </p>
            </div>
        </div>
        """

    def _get_escalation_template(self):
        """Escalation notification email template"""
        return """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #856404; margin: 0;">⬆️ Expense Escalated</h2>
                <p style="color: #856404; margin: 5px 0 0 0;">{{company}}</p>
            </div>

            <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                <p>Dear Administrator,</p>

                <p>An expense has been escalated and requires your admin-level approval:</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr><td style="padding: 5px 0; font-weight: bold;">Expense ID:</td><td>{{expense.name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Volunteer:</td><td>{{expense_details.volunteer_name}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Amount:</td><td style="font-size: 18px; color: #e74c3c;">{{expense_details.formatted_amount}}</td></tr>
                        <tr><td style="padding: 5px 0; font-weight: bold;">Escalation Reason:</td><td>{{escalation_reason}}</td></tr>
                    </table>
                </div>

                <div style="text-align: center; margin: 25px 0;">
                    <a href="{{base_url}}/app/volunteer-expense/{{expense.name}}" style="background-color: #dc3545; color: white; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                        Review Escalated Expense
                    </a>
                </div>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated escalation notification from {{company}}.
                </p>
            </div>
        </div>
        """

    def _get_overdue_reminder_template(self):
        """Overdue reminder email template"""
        return """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #fff3cd; padding: 20px; border-radius: 8px; margin-bottom: 20px;">
                <h2 style="color: #856404; margin: 0;">⏰ Overdue Expense Approvals</h2>
                <p style="color: #856404; margin: 5px 0 0 0;">{{company}}</p>
            </div>

            <div style="background-color: white; padding: 20px; border: 1px solid #e9ecef; border-radius: 8px;">
                <p>Dear {{approver_name}},</p>

                <p>You have {{expenses|length}} expense(s) that have been pending approval for more than {{days_overdue}} days:</p>

                <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0;">
                    <p><strong>Total Amount Pending:</strong> €{{total_amount:,.2f}}</p>
                </div>

                <p>Please review and approve these expenses as soon as possible to ensure timely reimbursement for volunteers.</p>

                <div style="text-align: center; margin: 25px 0;">
                    <a href="{{dashboard_url}}" style="background-color: #ffc107; color: #212529; padding: 12px 25px; text-decoration: none; border-radius: 5px; font-weight: bold; display: inline-block;">
                        Review Pending Expenses
                    </a>
                </div>

                <hr style="margin: 20px 0; border: none; border-top: 1px solid #e9ecef;">
                <p style="font-size: 12px; color: #6c757d;">
                    This is an automated reminder from {{company}}.
                </p>
            </div>
        </div>
        """


# Convenience functions for external use


@frappe.whitelist()
def send_approval_notification(expense_name):
    """Send approval request notification for an expense"""
    expense = frappe.get_doc("Volunteer Expense", expense_name)
    manager = ExpenseNotificationManager()
    manager.send_approval_request_notification(expense)


@frappe.whitelist()
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
