from typing import Dict, List, Set

import frappe
from frappe.utils import getdate, today

from .base_validator import BaseValidator, ValidationResult


class BoardMemberValidator(BaseValidator):
    """Validator for chapter board members"""

    def __init__(self, chapter_doc=None):
        super().__init__(chapter_doc)
        self._unique_roles_cache = None

    def validate_all_board_members(self, board_members: List[Dict]) -> ValidationResult:
        """Validate all board members"""
        result = self.create_result()

        if not board_members:
            return result

        # Validate individual board members
        for i, member in enumerate(board_members):
            member_result = self.validate_single_board_member(member, i)
            result.merge(member_result)

        # Validate board-level constraints
        board_result = self.validate_board_constraints(board_members)
        result.merge(board_result)

        return result

    def validate_single_board_member(self, member: Dict, index: int = 0) -> ValidationResult:
        """Validate a single board member"""
        result = self.create_result()

        member_name = member.get("volunteer_name", f"Board Member {index + 1}")

        # Required fields
        self.validate_required_field(member.get("volunteer"), "volunteer", result)
        self.validate_required_field(member.get("chapter_role"), "chapter_role", result)
        self.validate_required_field(member.get("from_date"), "from_date", result)

        # Date validation
        if member.get("from_date") and member.get("to_date"):
            self.validate_date_range(
                member.get("from_date"), member.get("to_date"), "Start Date", "End Date", result
            )

        # Validate active member with past end date
        if member.get("is_active") and member.get("to_date"):
            try:
                to_date = getdate(member.get("to_date"))
                if to_date < getdate(today()):
                    result.add_error(("Active board member {0} has end date in the past").format(member_name))
            except (ValueError, TypeError):
                pass  # Date validation will catch this

        # Validate volunteer exists
        if member.get("volunteer"):
            if not frappe.db.exists("Volunteer", member.get("volunteer")):
                result.add_error(("Volunteer {0} does not exist").format(member.get("volunteer")))

        # Validate role exists
        if member.get("chapter_role"):
            if not frappe.db.exists("Chapter Role", member.get("chapter_role")):
                result.add_error(("Chapter Role {0} does not exist").format(member.get("chapter_role")))

        # Validate email format if provided
        if member.get("email"):
            self.validate_email(member.get("email"), "email", result)

        return result

    def validate_board_constraints(self, board_members: List[Dict]) -> ValidationResult:
        """Validate board-level constraints (unique roles, minimum size, etc.)"""
        result = self.create_result()

        active_members = [m for m in board_members if m.get("is_active")]

        # Validate unique role assignments
        self._validate_unique_roles(active_members, result)

        # Validate board size (optional - can be configured)
        self._validate_board_size(active_members, result)

        # Validate required roles (optional - can be configured)
        self._validate_required_roles(active_members, result)

        return result

    def _validate_unique_roles(self, active_members: List[Dict], result: ValidationResult):
        """Validate that unique roles are only assigned once"""
        unique_roles = self._get_unique_roles()

        role_assignments = {}
        for member in active_members:
            role = member.get("chapter_role")
            if role and role in unique_roles:
                if role in role_assignments:
                    result.add_error(
                        ("Unique role '{0}' is assigned to multiple active board members").format(role)
                    )
                else:
                    role_assignments[role] = member.get("volunteer_name", member.get("volunteer"))

    def _validate_board_size(self, active_members: List[Dict], result: ValidationResult):
        """Validate board size constraints"""
        # Get configuration from settings or use defaults
        min_size = self._get_setting("minimum_board_size", 3)
        max_size = self._get_setting("maximum_board_size", 15)

        if len(active_members) < min_size:
            result.add_warning(
                ("Board has only {0} active members. Recommended minimum is {1}").format(
                    len(active_members), min_size
                )
            )

        if len(active_members) > max_size:
            result.add_warning(
                ("Board has {0} active members. Recommended maximum is {1}").format(
                    len(active_members), max_size
                )
            )

    def _validate_required_roles(self, active_members: List[Dict], result: ValidationResult):
        """Validate that required roles are assigned"""
        required_roles = self._get_setting("required_board_roles", ["Chair", "Secretary", "Treasurer"])

        assigned_roles = {m.get("chapter_role") for m in active_members if m.get("chapter_role")}

        for required_role in required_roles:
            if required_role not in assigned_roles:
                result.add_warning(
                    ("Required role '{0}' is not assigned to any active board member").format(required_role)
                )

    def _get_unique_roles(self) -> Set[str]:
        """Get list of roles marked as unique"""
        if self._unique_roles_cache is None:
            try:
                unique_roles = frappe.get_all(
                    "Chapter Role", filters={"is_unique": 1, "is_active": 1}, pluck="name"
                )
                self._unique_roles_cache = set(unique_roles)
            except Exception as e:
                frappe.log_error(f"Error fetching unique roles: {str(e)}")
                self._unique_roles_cache = set()

        return self._unique_roles_cache

    def _get_setting(self, setting_name: str, default_value):
        """Get a setting value from Verenigingen Settings or use default"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            return getattr(settings, setting_name, default_value)
        except Exception:
            return default_value

    def validate_role_uniqueness(
        self, role: str, current_member_id: str, active_members: List[Dict]
    ) -> ValidationResult:
        """Validate that a role assignment doesn't violate uniqueness"""
        result = self.create_result()

        unique_roles = self._get_unique_roles()
        if role not in unique_roles:
            return result

        # Check if role is already assigned to another active member
        for member in active_members:
            if (
                member.get("chapter_role") == role
                and member.get("is_active")
                and member.get("name") != current_member_id
            ):
                result.add_error(
                    (
                        "Role '{0}' is already assigned to {1}. This role can only be assigned to one person at a time."
                    ).format(role, member.get("volunteer_name", member.get("volunteer")))
                )
                break

        return result

    def validate_board_member_changes(
        self, old_members: List[Dict], new_members: List[Dict]
    ) -> ValidationResult:
        """Validate changes to board members (for update scenarios)"""
        result = self.create_result()

        # Create lookup for old members
        old_members_lookup = {m.get("name"): m for m in old_members if m.get("name")}

        # Validate changes
        for new_member in new_members:
            if new_member.get("name") in old_members_lookup:
                old_member = old_members_lookup[new_member.get("name")]
                change_result = self._validate_member_change(old_member, new_member)
                result.merge(change_result)

        return result

    def _validate_member_change(self, old_member: Dict, new_member: Dict) -> ValidationResult:
        """Validate changes to a single board member"""
        result = self.create_result()

        # Check if member is being deactivated
        if old_member.get("is_active") and not new_member.get("is_active"):
            # Ensure to_date is set
            if not new_member.get("to_date"):
                result.add_warning(
                    ("Board member {0} is being deactivated but no end date is set").format(
                        new_member.get("volunteer_name", new_member.get("volunteer"))
                    )
                )

        # Check for role changes
        if old_member.get("chapter_role") != new_member.get("chapter_role") and new_member.get("is_active"):
            # Validate new role uniqueness
            if new_member.get("chapter_role"):
                unique_result = self.validate_role_uniqueness(
                    new_member.get("chapter_role"),
                    new_member.get("name"),
                    [new_member],  # This would need the full active list in real implementation
                )
                result.merge(unique_result)

        return result

    def get_validation_summary(self, board_members: List[Dict]) -> Dict:
        """Get a summary of board validation status"""
        result = self.validate_all_board_members(board_members)

        active_members = [m for m in board_members if m.get("is_active")]
        unique_roles = self._get_unique_roles()

        return {
            "is_valid": result.is_valid,
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "active_members_count": len(active_members),
            "unique_roles_assigned": len(
                [m for m in active_members if m.get("chapter_role") in unique_roles]
            ),
            "errors": result.errors,
            "warnings": result.warnings,
        }
