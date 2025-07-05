import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate, today


class VolunteerExpense(Document):
    def validate(self):
        """Validate volunteer expense"""
        self.validate_expense_date()
        self.validate_amount()
        self.validate_organization_selection()
        self.validate_volunteer_organization_access()
        self.set_organization_from_volunteer()
        self.set_company_default()

    def validate_expense_date(self):
        """Ensure expense date is not in the future"""
        if self.expense_date and getdate(self.expense_date) > getdate(today()):
            frappe.throw(_("Expense date cannot be in the future"))

    def validate_amount(self):
        """Validate amount is positive"""
        if self.amount and flt(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero"))

    def validate_organization_selection(self):
        """Ensure either chapter or team is selected based on organization type"""
        if self.organization_type == "Chapter" and not self.chapter:
            frappe.throw(_("Please select a Chapter when Organization Type is Chapter"))
        elif self.organization_type == "Team" and not self.team:
            frappe.throw(_("Please select a Team when Organization Type is Team"))
        elif self.organization_type == "Chapter" and self.team:
            self.team = None  # Clear team if chapter is selected
        elif self.organization_type == "Team" and self.chapter:
            self.chapter = None  # Clear chapter if team is selected

    def validate_volunteer_organization_access(self):
        """Ensure volunteer has access to the specified chapter or team"""
        if not self.volunteer:
            return

        volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)

        if self.organization_type == "Chapter" and self.chapter:
            # Check if volunteer has member record linked to this chapter
            if hasattr(volunteer_doc, "member") and volunteer_doc.member:
                # Get the chapter document and check if the member is in its members table
                chapter_doc = frappe.get_doc("Chapter", self.chapter)
                member_in_chapter = False

                for member_row in chapter_doc.members:
                    if member_row.member == volunteer_doc.member and getattr(member_row, "enabled", True):
                        member_in_chapter = True
                        break

                if not member_in_chapter:
                    frappe.throw(
                        _(f"Volunteer {self.volunteer} does not have access to chapter {self.chapter}")
                    )

        elif self.organization_type == "Team" and self.team:
            # Check if volunteer is a member of this team
            team_members = frappe.get_all(
                "Team Member",
                filters={"parent": self.team, "volunteer": self.volunteer, "status": "Active"},
                fields=["name"],
            )

            if not team_members:
                frappe.throw(_(f"Volunteer {self.volunteer} is not a member of team {self.team}"))

    def set_organization_from_volunteer(self):
        """Auto-set organization if volunteer has only one active chapter/team"""
        if self.volunteer and not self.chapter and not self.team:
            volunteer_doc = frappe.get_doc("Volunteer", self.volunteer)

            # Try to set chapter first
            if hasattr(volunteer_doc, "member") and volunteer_doc.member:
                # Find chapters where this member is active
                chapters_with_member = []
                all_chapters = frappe.get_all("Chapter", fields=["name"])

                for chapter_name in all_chapters:
                    chapter_doc = frappe.get_doc("Chapter", chapter_name.name)
                    for member_row in chapter_doc.members:
                        if member_row.member == volunteer_doc.member and getattr(member_row, "enabled", True):
                            chapters_with_member.append(chapter_name.name)
                            break

                if len(chapters_with_member) == 1:
                    self.organization_type = "Chapter"
                    self.chapter = chapters_with_member[0]
                    return

            # Try to set team if no single chapter found
            team_memberships = frappe.get_all(
                "Team Member", filters={"volunteer": self.volunteer, "status": "Active"}, fields=["parent"]
            )

            if len(team_memberships) == 1:
                self.organization_type = "Team"
                self.team = team_memberships[0].parent

    def set_company_default(self):
        """Set default company if not specified"""
        if not self.company:
            self.company = frappe.defaults.get_global_default("company")

    def on_submit(self):
        """Actions on submit"""
        self.status = "Submitted"
        self.create_expense_approval_notification()

    def on_cancel(self):
        """Actions on cancel"""
        if self.status in ["Approved", "Reimbursed"]:
            frappe.throw(_("Cannot cancel expense that has been approved or reimbursed"))
        self.status = "Draft"

    def create_expense_approval_notification(self):
        """Create notification for organization leaders to approve expense using enhanced system"""
        try:
            from verenigingen.utils.expense_notifications import ExpenseNotificationManager

            notification_manager = ExpenseNotificationManager()
            notification_manager.send_approval_request_notification(self)
        except Exception as e:
            frappe.log_error(
                f"Failed to send expense approval notification: {str(e)}",
                "Volunteer Expense Notification Error",
            )

    def get_expense_approvers(self):
        """Get list of users who can approve this expense using enhanced permission system"""
        from verenigingen.utils.expense_permissions import ExpensePermissionManager

        manager = ExpensePermissionManager()
        approvers = []

        if self.organization_type == "Chapter" and self.chapter:
            # Use enhanced chapter approver system with amount-based permissions
            required_level = manager.get_required_permission_level(self.amount)
            chapter_approvers = manager.get_chapter_approvers(self.chapter, required_level)

            # Convert to expected format (email, full_name)
            approvers = [(email, full_name) for email, full_name, level, role in chapter_approvers]

        elif self.organization_type == "Team" and self.team:
            # Get team leads (they have financial level permission up to €500)
            team_leads = frappe.get_all(
                "Team Member",
                filters={"parent": self.team, "status": "Active", "role_type": "Team Leader"},
                fields=["volunteer"],
            )

            # Check if team leads can approve this amount
            required_level = manager.get_required_permission_level(self.amount)
            if manager._can_approve_at_level("financial", required_level):
                for team_lead in team_leads:
                    try:
                        volunteer = frappe.get_doc("Volunteer", team_lead.volunteer)
                        if hasattr(volunteer, "member") and volunteer.member:
                            member = frappe.get_doc("Member", volunteer.member)
                            if member.email:
                                approvers.append((member.email, member.full_name))
                    except Exception:
                        continue
            else:
                # Amount too high for team leads, need chapter approval
                # Find the chapter this team belongs to and get chapter approvers
                team_doc = frappe.get_doc("Team", self.team)
                if team_doc.chapter:
                    chapter_approvers = manager.get_chapter_approvers(team_doc.chapter, required_level)
                    approvers = [(email, full_name) for email, full_name, level, role in chapter_approvers]

        return approvers


@frappe.whitelist()
def approve_expense(expense_name):
    """Approve a volunteer expense using enhanced permission system"""
    from verenigingen.utils.expense_permissions import ExpensePermissionManager

    expense = frappe.get_doc("Volunteer Expense", expense_name)

    # Check permissions using enhanced system
    manager = ExpensePermissionManager()
    manager.validate_approval_permission(expense)

    # Update expense
    expense.status = "Approved"
    expense.approved_by = frappe.session.user
    expense.approved_on = frappe.utils.now()
    expense.save()

    # Send notification to volunteer using enhanced system
    from verenigingen.utils.expense_notifications import send_approval_confirmation

    send_approval_confirmation(expense)

    frappe.msgprint(_("Expense approved successfully"))


@frappe.whitelist()
def reject_expense(expense_name, reason=""):
    """Reject a volunteer expense"""
    expense = frappe.get_doc("Volunteer Expense", expense_name)

    # Check permissions
    if not can_approve_expense(expense):
        frappe.throw(_("You do not have permission to reject this expense"))

    # Update expense
    expense.status = "Rejected"
    if reason:
        expense.notes = (expense.notes or "") + f"\n\nRejection Reason: {reason}"
    expense.save()

    # Send notification to volunteer using enhanced system
    from verenigingen.utils.expense_notifications import send_rejection_notification

    send_rejection_notification(expense, reason)

    frappe.msgprint(_("Expense rejected"))


@frappe.whitelist()
def can_approve_expense(expense):
    """Check if current user can approve the expense using enhanced permission system"""
    from verenigingen.utils.expense_permissions import ExpensePermissionManager

    manager = ExpensePermissionManager()
    return manager.can_approve_expense(expense)


def get_permission_query_conditions(user=None):
    """Get permission query conditions for Volunteer Expense list filtering"""
    from verenigingen.utils.expense_permissions import get_expense_permission_query_conditions

    return get_expense_permission_query_conditions(user)
