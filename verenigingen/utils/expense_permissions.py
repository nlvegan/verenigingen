"""
Expense permission management system
"""
import frappe
from frappe import _
from frappe.utils import flt


class ExpensePermissionManager:
    """Manages expense approval permissions based on user roles and amounts"""

    def __init__(self):
        self.user = frappe.session.user

    def can_approve_expense(self, expense_doc):
        """Check if current user can approve the given expense"""
        # Admin users can approve everything
        admin_roles = ["System Manager", "Verenigingen Administrator"]
        if any(role in frappe.get_roles() for role in admin_roles):
            return True

        # Get user's board role for the expense's organization
        if expense_doc.organization_type == "Chapter" and expense_doc.chapter:
            return self._can_approve_chapter_expense(expense_doc)
        elif expense_doc.organization_type == "Team" and expense_doc.team:
            return self._can_approve_team_expense(expense_doc)

        return False

    def _can_approve_chapter_expense(self, expense_doc):
        """Check if user can approve expense for a chapter"""
        from verenigingen.templates.pages.chapter_dashboard import get_user_board_role

        board_role = get_user_board_role(expense_doc.chapter)
        if not board_role:
            return False

        permissions = board_role.get("permissions", {})
        can_approve = permissions.get("can_approve_expenses", False)
        expense_limit = permissions.get("expense_limit", 0)

        if not can_approve:
            return False

        # Check amount limit
        if flt(expense_doc.amount) > expense_limit:
            return False

        return True

    def _can_approve_team_expense(self, expense_doc):
        """Check if user can approve expense for a team"""
        # For team expenses, check if user is team leader with financial permissions
        # or has chapter-level approval for the team's chapter

        # First check if user is team leader
        team_leads = frappe.get_all(
            "Team Member",
            filters={"parent": expense_doc.team, "status": "Active", "role_type": "Team Leader"},
            fields=["volunteer"],
        )

        # Get current user's volunteer record
        user_email = frappe.session.user
        member = frappe.db.get_value("Member", {"email": user_email}, "name")
        if member:
            volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
            if volunteer:
                # Check if user is team leader
                if any(lead.volunteer == volunteer for lead in team_leads):
                    # Team leaders can approve up to €500
                    if flt(expense_doc.amount) <= 500:
                        return True

        # If amount is too high or user is not team leader,
        # check if they have chapter-level approval
        team_doc = frappe.get_doc("Team", expense_doc.team)
        if team_doc.chapter:
            # Create temporary expense doc for chapter to check permissions
            temp_expense = frappe._dict(
                {"organization_type": "Chapter", "chapter": team_doc.chapter, "amount": expense_doc.amount}
            )
            return self._can_approve_chapter_expense(temp_expense)

        return False

    def get_required_permission_level(self, amount):
        """Get required permission level based on amount"""
        amount = flt(amount)

        if amount <= 100:
            return "basic"
        elif amount <= 500:
            return "financial"
        elif amount <= 1000:
            return "management"
        else:
            return "admin"

    def _can_approve_at_level(self, level_type, required_level):
        """Check if given level type can approve required level"""
        level_hierarchy = {"basic": 1, "financial": 2, "management": 3, "admin": 4}

        type_levels = {
            "financial": 2,  # Financial level can approve up to management
            "management": 3,
            "admin": 4,
        }

        user_level = type_levels.get(level_type, 1)
        needed_level = level_hierarchy.get(required_level, 4)

        return user_level >= needed_level

    def get_chapter_approvers(self, chapter_name, required_level):
        """Get list of users who can approve at the required level for a chapter"""
        approvers = []

        # Get chapter board members
        chapter_doc = frappe.get_doc("Chapter", chapter_name)

        for board_member in chapter_doc.board_members:
            if not board_member.is_active:
                continue

            # Get role permissions
            from verenigingen.templates.pages.chapter_dashboard import get_role_permissions

            permissions = get_role_permissions(board_member.chapter_role)

            if not permissions.get("can_approve_expenses", False):
                continue

            # Check if they can approve this level/amount
            expense_limit = permissions.get("expense_limit", 0)

            # Convert required level to amount for comparison
            level_amounts = {"basic": 100, "financial": 500, "management": 1000, "admin": 10000}

            required_amount = level_amounts.get(required_level, 10000)

            if expense_limit >= required_amount:
                approvers.append(
                    (
                        board_member.email,
                        board_member.volunteer_name,
                        required_level,
                        board_member.chapter_role,
                    )
                )

        return approvers

    def validate_approval_permission(self, expense_doc):
        """Validate that current user can approve the expense (throws error if not)"""
        if not self.can_approve_expense(expense_doc):
            frappe.throw(_("You do not have permission to approve this expense"))


def get_expense_permission_query_conditions(user=None):
    """Get permission query conditions for Volunteer Expense list filtering"""
    if not user:
        user = frappe.session.user

    # Admin users can see all expenses
    admin_roles = ["System Manager", "Verenigingen Administrator"]
    user_roles = frappe.get_roles(user)
    if any(role in admin_roles for role in user_roles):
        return ""

    # Get user's member and volunteer records
    member = frappe.db.get_value("Member", {"email": user}, "name")
    if not member:
        return "1=0"  # No access if no member record

    volunteer = frappe.db.get_value("Volunteer", {"member": member}, "name")
    if not volunteer:
        return "1=0"  # No access if no volunteer record

    # User can see their own expenses
    conditions = ["`tabVolunteer Expense`.volunteer = f'{volunteer}'"]

    # Get chapters where user is board member
    from verenigingen.templates.pages.chapter_dashboard import get_user_board_chapters

    board_chapters = get_user_board_chapters()

    if board_chapters:
        chapter_names = [ch["chapter_name"] for ch in board_chapters]
        chapter_conditions = "', '".join(chapter_names)
        conditions.append(
            f"(`tabVolunteer Expense`.organization_type = 'Chapter' AND `tabVolunteer Expense`.chapter IN ('{chapter_conditions}'))"
        )

        # Also include team expenses for teams in those chapters
        team_conditions = []
        for chapter_name in chapter_names:
            teams = frappe.get_all("Team", filters={"chapter": chapter_name}, fields=["name"])
            if teams:
                team_names = [team.name for team in teams]
                team_list = "', '".join(team_names)
                team_conditions.append(f"`tabVolunteer Expense`.team IN ('{team_list}')")

        if team_conditions:
            conditions.append(
                "(`tabVolunteer Expense`.organization_type = 'Team' AND ({' OR '.join(team_conditions)}))"
            )

    # Get teams where user is leader
    team_memberships = frappe.get_all(
        "Team Member",
        filters={"volunteer": volunteer, "status": "Active", "role_type": "Team Leader"},
        fields=["parent"],
    )

    if team_memberships:
        team_names = [tm.parent for tm in team_memberships]
        team_conditions = "', '".join(team_names)
        conditions.append(
            f"(`tabVolunteer Expense`.organization_type = 'Team' AND `tabVolunteer Expense`.team IN ('{team_conditions}'))"
        )

    if conditions:
        return "({' OR '.join(conditions)})"
    else:
        return "1=0"  # No access if no permissions found
