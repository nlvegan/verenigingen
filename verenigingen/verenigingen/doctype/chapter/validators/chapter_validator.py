# verenigingen/verenigingen/doctype/chapter/validators/chaptervalidator.py
from typing import Dict, List

import frappe

from .base_validator import BaseValidator, ValidationResult
from .board_member_validator import BoardMemberValidator
from .chapter_info_validator import ChapterInfoValidator
from .postal_code_validator import PostalCodeValidator


class ChapterValidator(BaseValidator):
    """Main validator that coordinates all chapter validation"""

    def __init__(self, chapter_doc=None):
        super().__init__(chapter_doc)

        # Initialize component validators
        self.board_validator = BoardMemberValidator(chapter_doc)
        self.postal_validator = PostalCodeValidator(chapter_doc)
        self.info_validator = ChapterInfoValidator(chapter_doc)

    def validate_all(self) -> ValidationResult:
        """Validate all aspects of the chapter"""
        if not self.chapter_doc:
            result = self.create_result(False)
            result.add_error(("No chapter document provided for validation"))
            return result

        result = self.create_result()

        # Convert chapter doc to dict for validation
        chapter_data = self._chapter_to_dict(self.chapter_doc)

        # Validate chapter information
        info_result = self.info_validator.validate_chapter_info(chapter_data)
        result.merge(info_result)

        # Validate board members
        if hasattr(self.chapter_doc, "board_members") and self.chapter_doc.board_members:
            board_data = self._board_members_to_list(self.chapter_doc.board_members)
            board_result = self.board_validator.validate_all_board_members(board_data)
            result.merge(board_result)

        # Validate postal codes
        if chapter_data.get("postal_codes"):
            postal_result = self.postal_validator.validate_postal_codes(chapter_data["postal_codes"])
            result.merge(postal_result)

        # Validate cross-cutting concerns
        cross_result = self._validate_cross_cutting_concerns(chapter_data)
        result.merge(cross_result)

        return result

    def validate_before_save(self) -> ValidationResult:
        """Validation to run before saving"""
        result = self.validate_all()

        # Additional pre-save validations
        if self.chapter_doc:
            # Validate route generation
            if not self.chapter_doc.route and self.chapter_doc.name:
                suggested_route = self._generate_route(self.chapter_doc.name)
                if suggested_route:
                    self.chapter_doc.route = suggested_route

            # Auto-update chapter head if needed
            self._auto_update_chapter_head()

        return result

    def validate_before_submit(self) -> ValidationResult:
        """Validation to run before submitting (if applicable)"""
        result = self.validate_before_save()

        # Additional submit validations
        if self.chapter_doc and self.chapter_doc.published:
            publish_result = self._validate_for_publication()
            result.merge(publish_result)

        return result

    def validate_board_member_change(
        self, old_board_members: List[Dict], new_board_members: List[Dict]
    ) -> ValidationResult:
        """Validate changes to board members"""
        return self.board_validator.validate_board_member_changes(old_board_members, new_board_members)

    def validate_role_assignment(
        self, role: str, member_id: str, active_members: List[Dict]
    ) -> ValidationResult:
        """Validate a specific role assignment"""
        return self.board_validator.validate_role_uniqueness(role, member_id, active_members)

    def validate_postal_code_match(self, postal_code: str) -> bool:
        """Test if a postal code matches chapter's patterns"""
        if not self.chapter_doc or not self.chapter_doc.postal_codes:
            return False

        patterns = self.postal_validator._parse_postal_codes(self.chapter_doc.postal_codes)
        return self.postal_validator.test_postal_code_match(postal_code, patterns)

    def _validate_cross_cutting_concerns(self, chapter_data: Dict) -> ValidationResult:
        """Validate concerns that span multiple validators"""
        result = self.create_result()

        # Validate consistency between chapter head and board members
        self._validate_chapter_head_consistency(chapter_data, result)

        # Validate member management
        self._validate_member_management(chapter_data, result)

        return result

    def _validate_chapter_head_consistency(self, chapter_data: Dict, result: ValidationResult):
        """Validate chapter head is consistent with board members"""
        chapter_head = chapter_data.get("chapter_head")
        if not chapter_head:
            return

        # Get board members
        board_members = chapter_data.get("board_members", [])
        if not board_members:
            result.add_warning(("Chapter head is set but there are no board members"))
            return

        # Check if chapter head corresponds to a board member with chair role
        chair_members = []
        for member in board_members:
            if member.get("is_active") and member.get("chapter_role"):
                try:
                    role_doc = frappe.get_doc("Chapter Role", member.get("chapter_role"))
                    if role_doc.is_chair and role_doc.is_active:
                        # Get member from volunteer
                        volunteer_doc = frappe.get_doc("Volunteer", member.get("volunteer"))
                        if volunteer_doc.member:
                            chair_members.append(volunteer_doc.member)
                except frappe.DoesNotExistError:
                    continue

        if chair_members and chapter_head not in chair_members:
            result.add_warning(
                (
                    "Chapter head '{0}' is not associated with any active board member with a chair role"
                ).format(chapter_head)
            )

    def _validate_member_management(self, chapter_data: Dict, result: ValidationResult):
        """Validate member management consistency"""
        # This can include validation of member lists, permissions, etc.
        # For now, basic validation

        members = chapter_data.get("members", [])
        board_members = chapter_data.get("board_members", [])

        # Check that all active board members are also chapter members
        active_board_volunteers = {m.get("volunteer") for m in board_members if m.get("is_active")}

        for volunteer_id in active_board_volunteers:
            if volunteer_id:
                try:
                    volunteer_doc = frappe.get_doc("Volunteer", volunteer_id)
                    if volunteer_doc.member:
                        member_in_chapter = any(
                            m.get("member") == volunteer_doc.member and m.get("enabled") for m in members
                        )
                        if not member_in_chapter:
                            result.add_warning(
                                ("Board member {0} is not listed as an active chapter member").format(
                                    volunteer_doc.volunteer_name
                                )
                            )
                except frappe.DoesNotExistError:
                    continue

    def _validate_for_publication(self) -> ValidationResult:
        """Additional validation for published chapters"""
        result = self.create_result()

        if not self.chapter_doc:
            return result

        # Check required content for publication
        if not self.chapter_doc.introduction or len(self.chapter_doc.introduction) < 100:
            result.add_error(
                ("Published chapters must have a detailed introduction (at least 100 characters)")
            )

        if not self.chapter_doc.region:
            result.add_error(("Published chapters must have a region specified"))

        # Check that chapter has some activity/content
        has_board_members = bool(self.chapter_doc.board_members)
        has_members = bool(self.chapter_doc.members)

        if not has_board_members and not has_members:
            result.add_warning(("Published chapter has no board members or regular members"))

        return result

    def _auto_update_chapter_head(self):
        """Automatically update chapter head based on board members"""
        if not self.chapter_doc or not hasattr(self.chapter_doc, "board_members"):
            return

        # Find active board members with chair roles
        chair_member = None

        for board_member in self.chapter_doc.board_members:
            if not board_member.is_active or not board_member.chapter_role:
                continue

            try:
                role = frappe.get_doc("Chapter Role", board_member.chapter_role)
                if role.is_chair and role.is_active:
                    # Get member from volunteer
                    volunteer = frappe.get_doc("Volunteer", board_member.volunteer)
                    if volunteer.member:
                        chair_member = volunteer.member
                        break
            except frappe.DoesNotExistError:
                continue

        # Update chapter head if different
        if self.chapter_doc.chapter_head != chair_member:
            self.chapter_doc.chapter_head = chair_member

    def _generate_route(self, chapter_name: str) -> str:
        """Generate a route for the chapter"""
        if not chapter_name:
            return ""

        # Convert to URL-friendly format
        route = chapter_name.lower()
        route = route.replace(" ", "-")
        route = "".join(c for c in route if c.isalnum() or c in "-")

        return f"chapters/{route}"

    def _chapter_to_dict(self, chapter_doc) -> Dict:
        """Convert chapter document to dictionary for validation"""
        data = {}

        # Basic fields
        fields = [
            "name",
            "region",
            "introduction",
            "address",
            "route",
            "published",
            "chapter_head",
            "postal_codes",
            "meetup_embed_html",
        ]

        for field in fields:
            if hasattr(chapter_doc, field):
                data[field] = getattr(chapter_doc, field)

        # Child tables
        if hasattr(chapter_doc, "board_members"):
            data["board_members"] = self._board_members_to_list(chapter_doc.board_members)

        if hasattr(chapter_doc, "members"):
            data["members"] = self._members_to_list(chapter_doc.members)

        return data

    def _board_members_to_list(self, board_members) -> List[Dict]:
        """Convert board members to list of dictionaries"""
        result = []

        for member in board_members:
            member_dict = {}
            fields = [
                "name",
                "volunteer",
                "volunteer_name",
                "email",
                "chapter_role",
                "from_date",
                "to_date",
                "is_active",
                "notes",
            ]

            for field in fields:
                if hasattr(member, field):
                    member_dict[field] = getattr(member, field)

            result.append(member_dict)

        return result

    def _members_to_list(self, members) -> List[Dict]:
        """Convert members to list of dictionaries"""
        result = []

        for member in members:
            member_dict = {}
            fields = ["member", "member_name", "introduction", "website_url", "enabled", "leave_reason"]

            for field in fields:
                if hasattr(member, field):
                    member_dict[field] = getattr(member, field)

            result.append(member_dict)

        return result

    def get_validation_summary(self) -> Dict:
        """Get comprehensive validation summary"""
        if not self.chapter_doc:
            return {"overall_status": "error", "message": "No chapter document provided"}

        result = self.validate_all()
        chapter_data = self._chapter_to_dict(self.chapter_doc)

        # Get component summaries
        info_summary = self.info_validator.get_validation_summary(chapter_data)
        board_summary = self.board_validator.get_validation_summary(chapter_data.get("board_members", []))
        postal_summary = self.postal_validator.get_pattern_summary(chapter_data.get("postal_codes", ""))

        return {
            "overall_status": "valid" if result.is_valid else "invalid",
            "total_errors": len(result.errors),
            "total_warnings": len(result.warnings),
            "errors": result.errors,
            "warnings": result.warnings,
            "component_status": {
                "chapter_info": info_summary,
                "board_members": board_summary,
                "postal_codes": postal_summary,
            },
            "ready_for_publication": self._check_publication_readiness(chapter_data),
            "last_validated": frappe.utils.now(),
        }

    def _check_publication_readiness(self, chapter_data: Dict) -> Dict:
        """Check if chapter is ready for publication"""
        issues = []

        if not chapter_data.get("introduction") or len(chapter_data.get("introduction", "")) < 50:
            issues.append("Introduction too short")

        if not chapter_data.get("region"):
            issues.append("No region specified")

        board_members = chapter_data.get("board_members", [])
        active_board = [m for m in board_members if m.get("is_active")]

        if len(active_board) < 2:
            issues.append("Insufficient board members")

        has_chair = any(
            self._is_chair_role(m.get("chapter_role")) for m in active_board if m.get("chapter_role")
        )

        if not has_chair:
            issues.append("No chair role assigned")

        return {
            "ready": len(issues) == 0,
            "issues": issues,
            "score": max(0, 100 - len(issues) * 20),  # Simple scoring
        }

    def _is_chair_role(self, role_name: str) -> bool:
        """Check if a role is a chair role"""
        if not role_name:
            return False

        try:
            role = frappe.get_doc("Chapter Role", role_name)
            return role.is_chair and role.is_active
        except frappe.DoesNotExistError:
            return False
