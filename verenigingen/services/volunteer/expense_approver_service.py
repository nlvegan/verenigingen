"""
Volunteer Expense Approver Service

Handles determination of appropriate expense approvers for volunteers based on
their organizational assignments (board positions, chapter memberships, teams).

Business Logic:
    - Priority 1: National board members → other national board financial officer
    - Priority 2: Chapter members → chapter treasurer/financial officer
    - Priority 3: Team members → team's chapter approver
    - Priority 4: Fallback to system manager with expense approver role

Financial Roles Priority Order:
    1. Treasurer
    2. Financial Officer
    3. Secretary-Treasurer
    4. Board Chair
    5. Secretary

Author: Verenigingen Development Team
License: MIT
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation


class VolunteerExpenseApproverService:
    """Service for managing volunteer expense approver logic"""

    # Financial roles priority order for board approvers
    FINANCIAL_ROLES = [
        "Treasurer",
        "Financial Officer",
        "Secretary-Treasurer",
        "Board Chair",
        "Secretary",
    ]

    def __init__(self, volunteer_name: str):
        """Initialize service for specific volunteer

        Args:
            volunteer_name: Volunteer record name
        """
        self.volunteer_name = volunteer_name
        self.volunteer_doc = None  # Lazy loaded

    def get_expense_approver(self) -> str:
        """Get appropriate expense approver based on volunteer's assignments

        Uses a priority-based approach:
        1. National board members get another national board financial officer
        2. Chapter members get their chapter's treasurer/financial officer
        3. Team members get approver through their team's chapter
        4. Fallback to system manager with expense approver role
        5. Last resort: Administrator

        Returns:
            str: User email of the expense approver

        Raises:
            frappe.DoesNotExistError: If volunteer not found
        """
        try:
            # Load volunteer document
            self._load_volunteer()

            # Priority 1: National board members
            national_approver = self._get_national_board_approver()
            if national_approver:
                return national_approver

            # Priority 2: Chapter members
            chapter_approver = self._get_chapter_member_approver()
            if chapter_approver:
                return chapter_approver

            # Priority 3: Team members
            team_approver = self._get_team_member_approver()
            if team_approver:
                return team_approver

            # Priority 4: Fallback to system manager
            fallback_approver = self._get_fallback_approver()
            if fallback_approver:
                return fallback_approver

            # Last resort: Administrator
            return "Administrator"

        except Exception as e:
            frappe.log_error(
                f"Error determining expense approver for volunteer {self.volunteer_name}: {str(e)}",
                "Expense Approver Error",
            )
            return "Administrator"  # Safe fallback

    def get_board_financial_approver(
        self, chapter_name: str, exclude_volunteer: Optional[str] = None
    ) -> Optional[str]:
        """Get financial approver from chapter board

        Searches for board members in priority order of financial roles:
        Treasurer > Financial Officer > Secretary-Treasurer > Board Chair > Secretary

        Args:
            chapter_name: Chapter record name
            exclude_volunteer: Volunteer to exclude (for self-approval prevention)

        Returns:
            Optional[str]: User email or None if no approver found
        """
        for role in self.FINANCIAL_ROLES:
            board_members = frappe.get_all(
                "Chapter Board Member",
                filters={
                    "parent": chapter_name,
                    "chapter_role": role,
                    "is_active": 1,
                    "volunteer": ["!=", exclude_volunteer] if exclude_volunteer else ["!=", ""],
                },
                fields=["volunteer"],
            )

            for member in board_members:
                volunteer_doc = frappe.get_doc("Volunteer", member.volunteer)
                user_email = volunteer_doc.email or volunteer_doc.personal_email

                if user_email and frappe.db.exists("User", user_email):
                    user = frappe.get_doc("User", user_email)
                    if user.enabled:
                        # Ensure user has expense approver role
                        self.ensure_user_has_expense_approver_role(user_email)
                        return user_email

        return None

    def ensure_user_has_expense_approver_role(self, user_email: str) -> None:
        """Ensure user has Expense Approver role assigned

        Uses secure document operation to assign role with proper auditing.

        Args:
            user_email: User to assign role to

        Raises:
            frappe.ValidationError: If role assignment fails
        """
        user = frappe.get_doc("User", user_email)

        if "Expense Approver" not in [r.role for r in user.roles]:
            user.append("roles", {"role": "Expense Approver"})

            # Use secure document operation instead of permission bypass
            result = secure_document_operation(
                operation="save",
                doc=user,
                justification="Adding Expense Approver role for volunteer expense management",
                required_permissions=["User:write", "Role:assign"],
            )

            if not result.success:
                frappe.throw(
                    _("Failed to assign Expense Approver role: {0}").format("; ".join(result.errors))
                )

    def _load_volunteer(self):
        """Lazy load volunteer document"""
        if not self.volunteer_doc:
            self.volunteer_doc = frappe.get_doc("Volunteer", self.volunteer_name)
        return self.volunteer_doc

    def _get_national_board_approver(self) -> Optional[str]:
        """Get approver for national board members

        National board members cannot approve their own expenses,
        so find another national board financial officer.

        Returns:
            Optional[str]: User email or None
        """
        settings = frappe.get_single("Verenigingen Settings")
        if not settings.national_board_chapter:
            return None

        # Check if volunteer is on national board
        national_board_member = frappe.db.exists(
            "Chapter Board Member",
            {
                "parent": settings.national_board_chapter,
                "volunteer": self.volunteer_name,
                "is_active": 1,
            },
        )

        if national_board_member:
            # Find another national board member who can approve
            return self.get_board_financial_approver(
                settings.national_board_chapter, exclude_volunteer=self.volunteer_name
            )

        return None

    def _get_chapter_member_approver(self) -> Optional[str]:
        """Get approver for chapter members

        Finds treasurer or financial officer from volunteer's chapter(s).

        Returns:
            Optional[str]: User email or None
        """
        volunteer = self._load_volunteer()

        if not volunteer.member:
            return None

        chapter_memberships = frappe.get_all(
            "Chapter Member", filters={"member": volunteer.member, "enabled": 1}, fields=["parent"]
        )

        for membership in chapter_memberships:
            chapter_approver = self.get_board_financial_approver(membership.parent)
            if chapter_approver:
                return chapter_approver

        return None

    def _get_team_member_approver(self) -> Optional[str]:
        """Get approver for team members

        Finds approver through team's chapter. Uses optimized batch fetch
        to avoid N+1 queries (2 queries total instead of 1+N).

        Returns:
            Optional[str]: User email or None
        """
        team_memberships = frappe.get_all(
            "Team Member", filters={"volunteer": self.volunteer_name, "status": "Active"}, fields=["parent"]
        )

        if not team_memberships:
            return None

        # OPTIMIZED: Batch fetch all team data at once (N+1 → 2 queries)
        team_names = [tm.parent for tm in team_memberships]
        all_teams = frappe.get_all(
            "Team",
            filters={"name": ["in", team_names]},
            fields=["name", "chapter"],
        )

        # Build lookup: team_name → team_data
        teams_by_name = {t.name: t for t in all_teams}

        # Iterate using lookups (no queries!)
        for team_membership in team_memberships:
            team_data = teams_by_name.get(team_membership.parent)
            if team_data and team_data.chapter:
                team_chapter_approver = self.get_board_financial_approver(team_data.chapter)
                if team_chapter_approver:
                    return team_chapter_approver

        return None

    def _get_fallback_approver(self) -> Optional[str]:
        """Get fallback approver from system managers

        Returns:
            Optional[str]: User email or None
        """
        fallback_approver = frappe.db.get_value(
            "User", {"enabled": 1, "name": ["!=", "Administrator"]}, "name", order_by="creation"
        )

        if fallback_approver:
            # Ensure user has expense approver role
            self.ensure_user_has_expense_approver_role(fallback_approver)
            return fallback_approver

        return None
