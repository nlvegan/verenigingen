"""
Volunteer Expense Approver Service

Handles determination of appropriate expense approvers for volunteers based on
their organizational assignments (board positions, chapter memberships, teams).

Business Logic:
    - Priority 1: National board members → other national board financial officer
    - Priority 2: Chapter members → chapter treasurer/financial officer
    - Priority 3: Team members → team's chapter approver
    - Priority 4: No chapter/team approver → national board financial seat
    - Otherwise: unassigned (None); there is no generic fallback

Financial seats are defined by the flag ``Chapter Role.permissions_level == "Financial"``
(#1650), never by role name. Admin does not imply financial. A seat holder never
approves their own claim: it goes to the national board's financial seat instead.

Author: Verenigingen Development Team
License: MIT
"""

from typing import Optional

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.utils.secure_operations import secure_document_operation
from verenigingen.utils.user_role_grant import ensure_role_survives_profile_resync


class VolunteerExpenseApproverService(StatelessService):
    """Service for managing volunteer expense approver logic"""

    def __init__(self, volunteer_name: str):
        """Initialize service for specific volunteer

        Args:
            volunteer_name: Volunteer record name
        """
        super().__init__(service_name="VolunteerExpenseApproverService")
        self.volunteer_name = volunteer_name
        self.volunteer_doc = None  # Lazy loaded

    def get_expense_approver(self) -> Optional[str]:
        """Get appropriate expense approver based on volunteer's assignments

        Uses a priority-based approach:
        1. National board members get another national board financial officer
        2. Chapter members get their chapter's treasurer/financial officer
        3. Team members get approver through their team's chapter
        4. Anyone without a chapter/team approver gets the national board's financial seat

        When no financial seat exists anywhere the claim is left UNASSIGNED (None): there
        is no generic fallback and nobody is auto-granted Expense Approver (#1650 ruling).

        Returns:
            Optional[str]: User email of the expense approver, or None when there is none

        Raises:
            frappe.DoesNotExistError: If volunteer not found
        """
        # Load volunteer document (raises DoesNotExistError for an unknown volunteer: a failed
        # lookup is not "no approver", so it is not swallowed into None)
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

        # Priority 4: national board financial seat (a chapter treasurer's own claim, or a
        # chapter with no financial seat). None = nobody: the claim is left unassigned.
        return self._get_national_financial_approver()

    def get_board_financial_approver(
        self, chapter_name: str, exclude_volunteer: Optional[str] = None
    ) -> Optional[str]:
        """Get financial approver from chapter board

        A financial seat is one whose Chapter Role has ``permissions_level`` Financial
        (#1650). Role names and the Admin level carry no financial meaning.

        Args:
            chapter_name: Chapter record name
            exclude_volunteer: Volunteer to exclude (for self-approval prevention)

        Returns:
            Optional[str]: User email or None if no approver found
        """
        financial_roles = frappe.get_all(
            "Chapter Role", filters={"permissions_level": "Financial", "is_active": 1}, pluck="name"
        )
        if not financial_roles:
            return None

        board_members = frappe.get_all(
            "Chapter Board Member",
            filters={
                "parent": chapter_name,
                "chapter_role": ["in", financial_roles],
                "is_active": 1,
                "volunteer": ["!=", exclude_volunteer] if exclude_volunteer else ["!=", ""],
            },
            fields=["volunteer"],
            order_by="idx asc",
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

        if "Expense Approver" in [r.role for r in user.roles]:
            return

        user.append("roles", {"role": "Expense Approver"})

        # Use secure document operation instead of permission bypass
        result = secure_document_operation(
            operation="save",
            doc=user,
            justification="Adding Expense Approver role for volunteer expense management",
            required_permissions=["User:write", "Role:assign"],
        )

        if not result.success:
            frappe.throw(_("Failed to assign Expense Approver role: {0}").format("; ".join(result.errors)))

        # A user carrying a Role Profile has its `roles` table re-synced from the
        # profile on every save (User.populate_role_profile_roles), which silently
        # strips this ad-hoc role -- so the save above "succeeds" without granting
        # it (#1195). Since the security hardening made role PROFILES the norm
        # (HIGH/CRITICAL tiers are profile-only), that is the common case. Verify
        # and fall back to a direct Has Role insert -- the sanctioned pattern for
        # adding a single role without re-validating (hence re-syncing) the whole
        # roles table, shared with every other affected call site (#1195).
        ensure_role_survives_profile_resync(user_email, "Expense Approver")

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
            chapter_approver = self.get_board_financial_approver(
                membership.parent, exclude_volunteer=self.volunteer_name
            )
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
                team_chapter_approver = self.get_board_financial_approver(
                    team_data.chapter, exclude_volunteer=self.volunteer_name
                )
                if team_chapter_approver:
                    return team_chapter_approver

        return None

    def _get_national_financial_approver(self) -> Optional[str]:
        """The national board's financial seat, for a claim no chapter treasurer can decide.

        A chapter treasurer does not approve their own claim (#1650 ruling), so when the
        chapter path excludes them the claim goes to the national treasurer.

        Returns:
            Optional[str]: User email or None
        """
        national_chapter = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        if not national_chapter:
            return None
        return self.get_board_financial_approver(national_chapter, exclude_volunteer=self.volunteer_name)


def get_volunteer_expense_approver_service(volunteer_name: str) -> VolunteerExpenseApproverService:
    """Get instance of VolunteerExpenseApproverService."""
    return VolunteerExpenseApproverService(volunteer_name)
