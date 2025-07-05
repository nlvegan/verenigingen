# verenigingen/verenigingen/doctype/chapter/validators/chapter_infovalidator.py
import re
from typing import Dict, Optional

import frappe

from .base_validator import BaseValidator, ValidationResult


class ChapterInfoValidator(BaseValidator):
    """Validator for basic chapter information"""

    # Field length limits
    FIELD_LIMITS = {
        "name": 100,
        "region": 100,
        "introduction": 2000,
        "address": 500,
        "meetup_embed_html": 5000,
        "route": 200,
    }

    # Valid name pattern (alphanumeric, spaces, hyphens, underscores)
    NAMEPATTERN = re.compile(r"^[a-zA-Z0-9\s\-]+$")

    def __init__(self, chapter_doc=None):
        super().__init__(chapter_doc)

    def validate_chapter_info(self, chapter_data: Dict) -> ValidationResult:
        """Validate all chapter information"""
        result = self.create_result()

        # Validate required fields
        self._validate_required_fields(chapter_data, result)

        # Validate field formats
        self._validate_field_formats(chapter_data, result)

        # Validate field lengths
        self._validate_field_lengths(chapter_data, result)

        # Validate business rules
        self._validate_business_rules(chapter_data, result)

        return result

    def _validate_required_fields(self, chapter_data: Dict, result: ValidationResult):
        """Validate required fields are present"""
        # Always require name and region
        core_required_fields = ["name", "region"]

        for field in core_required_fields:
            self.validate_required_field(chapter_data.get(field), field, result)

        # Introduction is only required for published chapters
        if chapter_data.get("published"):
            self.validate_required_field(chapter_data.get("introduction"), "introduction", result)
        elif not chapter_data.get("introduction"):
            # Add warning for unpublished chapters without introduction
            result.add_warning("Introduction is recommended for better chapter presentation")

    def _validate_field_formats(self, chapter_data: Dict, result: ValidationResult):
        """Validate field formats"""
        # Validate chapter name format
        name = chapter_data.get("name")
        if name and not self.NAMEPATTERN.match(name):
            result.add_error(
                (
                    "Chapter name contains invalid characters. Only letters, numbers, spaces, hyphens and underscores are allowed"
                )
            )

        # Validate route format if provided
        route = chapter_data.get("route")
        if route:
            self._validate_route_format(route, result)

        # Validate HTML content if provided
        meetup_html = chapter_data.get("meetup_embed_html")
        if meetup_html:
            self._validate_html_content(meetup_html, result)

    def _validate_field_lengths(self, chapter_data: Dict, result: ValidationResult):
        """Validate field lengths don't exceed limits"""
        for field, max_length in self.FIELD_LIMITS.items():
            value = chapter_data.get(field)
            if value:
                self.validate_field_length(value, field, max_length, result)

    def _validate_business_rules(self, chapter_data: Dict, result: ValidationResult):
        """Validate business-specific rules"""
        # Check for duplicate chapter names
        self._validate_unique_name(chapter_data, result)

        # Validate region format
        self._validate_region(chapter_data.get("region"), result)

        # Validate chapter head assignment
        self._validate_chapter_head(chapter_data, result)

        # Validate published status
        self._validate_published_status(chapter_data, result)

    def _validate_route_format(self, route: str, result: ValidationResult):
        """Validate route format"""
        # Route should not start or end with slash
        if route.startswith("/") or route.endswith("/"):
            result.add_warning(("Route should not start or end with forward slash"))

        # Route should only contain valid URL characters
        if not re.match(r"^[a-zA-Z0-9\-_/]+$", route):
            result.add_error(("Route contains invalid characters"))

        # Check if route is already used
        if self.chapter_doc and frappe.db.exists(
            "Chapter", {"route": route, "name": ["!=", self.chapter_doc.name]}
        ):
            result.add_error(("Route '{0}' is already used by another chapter").format(route))

    def _validate_html_content(self, html_content: str, result: ValidationResult):
        """Validate HTML content for security and format"""
        # Basic HTML validation
        if "<script" in html_content.lower():
            result.add_error(("Script tags are not allowed in HTML content for security reasons"))

        # Check for potentially dangerous attributes
        dangerous_attrs = ["onclick", "onload", "onerror", "onmouseover"]
        for attr in dangerous_attrs:
            if attr in html_content.lower():
                result.add_warning(("HTML content contains potentially unsafe attribute: {0}").format(attr))

        # Validate HTML structure (basic check)
        self._validate_html_structure(html_content, result)

    def _validate_html_structure(self, html_content: str, result: ValidationResult):
        """Basic HTML structure validation"""
        # Count opening and closing tags for basic balance check
        import re

        # Find all opening tags
        opening_tags = re.findall(r"<(\w+)[^>]*(?<!/)>", html_content)

        # Find all closing tags
        closing_tags = re.findall(r"</(\w+)>", html_content)

        # Check for basic balance (this is not perfect but catches obvious issues)
        tag_counts = {}
        for tag in opening_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

        for tag in closing_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) - 1

        unbalanced_tags = [tag for tag, count in tag_counts.items() if count != 0]
        if unbalanced_tags:
            result.add_warning(
                ("HTML appears to have unbalanced tags: {0}").format(", ".join(unbalanced_tags))
            )

    def _validate_unique_name(self, chapter_data: Dict, result: ValidationResult):
        """Validate chapter name is unique"""
        name = chapter_data.get("name")
        if not name:
            return

        # Check if name already exists
        if self.chapter_doc and hasattr(self.chapter_doc, "name"):
            # Updating existing chapter - exclude current chapter from duplicate check
            existing_chapters = frappe.db.sql(
                """
                SELECT name FROM `tabChapter`
                WHERE name = %s AND name != %s
                LIMIT 1
            """,
                (name, self.chapter_doc.name),
                as_dict=True,
            )
            existing_chapter = existing_chapters[0] if existing_chapters else None
        else:
            # Creating new chapter - check for any existing chapter with same name
            existing_chapter = frappe.db.get_value("Chapter", {"name": name})

        if existing_chapter:
            # Debug info - log what was found
            frappe.log_error(
                f"Duplicate chapter validation: Found existing chapter '{existing_chapter}' when trying to create/update '{name}'"
            )
            result.add_error(("Chapter name '{0}' already exists").format(name))

    def _validate_region(self, region: str, result: ValidationResult):
        """Validate region field"""
        if not region:
            return

        # Check region format
        if len(region.strip()) < 2:
            result.add_error(("Region name is too short"))

        # Optional: Check against list of valid regions
        valid_regions = self._get_valid_regions()
        if valid_regions and region not in valid_regions:
            result.add_warning(("Region '{0}' is not in the standard regions list").format(region))

    def _validate_chapter_head(self, chapter_data: Dict, result: ValidationResult):
        """Validate chapter head assignment"""
        chapter_head = chapter_data.get("chapter_head")
        if not chapter_head:
            return

        # Check if member exists
        if not frappe.db.exists("Member", chapter_head):
            result.add_error(("Chapter head member '{0}' does not exist").format(chapter_head))
            return

        # Check if member is active
        member_status = frappe.db.get_value("Member", chapter_head, "status")
        if member_status != "Active":
            result.add_warning(("Chapter head member is not active (status: {0})").format(member_status))

        # Optional: Check if member is part of the chapter
        # This might be implemented based on your business logic

    def _validate_published_status(self, chapter_data: Dict, result: ValidationResult):
        """Validate published status"""
        if chapter_data.get("published"):
            # Check if chapter has minimum required information for publishing
            required_for_publish = ["introduction", "region"]
            missing_fields = []

            for field in required_for_publish:
                if not chapter_data.get(field):
                    missing_fields.append(field)

            if missing_fields:
                result.add_error(
                    ("Cannot publish chapter. Missing required fields: {0}").format(", ".join(missing_fields))
                )

            # Check if chapter has at least some content
            intro_length = len(chapter_data.get("introduction", ""))
            if intro_length < 50:
                result.add_warning(
                    (
                        "Chapter introduction is very short ({0} characters). Consider adding more detail before publishing"
                    ).format(intro_length)
                )

    def validate_chapter_route(self, route: str, chapter_name: str = None) -> ValidationResult:
        """Validate chapter route specifically"""
        result = self.create_result()

        if not route:
            return result

        # Format validation
        self._validate_route_format(route, result)

        # Check for conflicts with system routes
        system_routes = ["app", "api", "files", "assets", "desk"]
        route_parts = route.split("/")
        if route_parts[0] in system_routes:
            result.add_error(("Route conflicts with system route: {0}").format(route_parts[0]))

        return result

    def validate_address_format(self, address: str) -> ValidationResult:
        """Validate address format"""
        result = self.create_result()

        if not address:
            return result

        # Check minimum length
        if len(address.strip()) < 10:
            result.add_warning(("Address appears to be very short"))

        # Check for common address components
        address.lower()
        has_number = any(char.isdigit() for char in address)

        if not has_number:
            result.add_warning(("Address doesn't appear to contain a street number"))

        return result

    def _get_valid_regions(self) -> Optional[list]:
        """Get list of valid regions from settings"""
        try:
            settings = frappe.get_single("Verenigingen Settings")
            if hasattr(settings, "valid_regions") and settings.valid_regions:
                return [r.strip() for r in settings.valid_regions.split(",")]
        except Exception:
            pass
        return None

    def get_validation_summary(self, chapter_data: Dict) -> Dict:
        """Get comprehensive validation summary"""
        result = self.validate_chapter_info(chapter_data)

        return {
            "is_valid": result.is_valid,
            "error_count": len(result.errors),
            "warning_count": len(result.warnings),
            "errors": result.errors,
            "warnings": result.warnings,
            "field_status": {
                "name": bool(chapter_data.get("name")),
                "region": bool(chapter_data.get("region")),
                "introduction": bool(chapter_data.get("introduction")),
                "chapter_head": bool(chapter_data.get("chapter_head")),
                "published": bool(chapter_data.get("published")),
                "has_address": bool(chapter_data.get("address")),
                "has_postal_codes": bool(chapter_data.get("postal_codes")),
                "has_custom_route": bool(chapter_data.get("route")),
            },
            "content_stats": {
                "introduction_length": len(chapter_data.get("introduction", "")),
                "address_length": len(chapter_data.get("address", "")),
                "has_html_content": bool(chapter_data.get("meetup_embed_html")),
            },
        }
