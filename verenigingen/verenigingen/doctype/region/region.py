# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.utils import validate_email_address
from frappe.website.website_generator import WebsiteGenerator


class Region(WebsiteGenerator):
    """Region document for managing geographic regions"""

    def validate(self):
        """Validate region data"""
        self.validate_required_fields()
        self.validate_region_code()
        self.validate_coordinators()
        self.validate_postal_codes()
        self.validate_contact_info()
        self.validate_membership_fee_adjustment()

    def validate_required_fields(self):
        """Validate required fields"""
        if not self.region_name:
            frappe.throw(_("Region Name is required"))

        if not self.region_code:
            frappe.throw(_("Region Code is required"))

    def validate_region_code(self):
        """Validate region code format and uniqueness"""
        if self.region_code:
            # Ensure uppercase
            self.region_code = self.region_code.upper().strip()

            # Validate format (2-5 uppercase letters/numbers)
            if not re.match(r"^[A-Z0-9]{2,5}$", self.region_code):
                frappe.throw(_("Region Code must be 2-5 uppercase letters or numbers"))

            # Check uniqueness
            existing = frappe.db.get_value(
                "Region", {"region_code": self.region_code, "name": ["!=", self.name]}
            )
            if existing:
                frappe.throw(_("Region Code {0} already exists").format(self.region_code))

    def validate_coordinators(self):
        """Validate regional coordinators"""
        if self.regional_coordinator:
            if not frappe.db.exists("Member", self.regional_coordinator):
                frappe.throw(_("Regional Coordinator {0} does not exist").format(self.regional_coordinator))

            # Check if coordinator is active
            coordinator_status = frappe.db.get_value("Member", self.regional_coordinator, "status")
            if coordinator_status != "Active":
                frappe.msgprint(_("Warning: Regional Coordinator is not active"), indicator="orange")

        if self.backup_coordinator:
            if not frappe.db.exists("Member", self.backup_coordinator):
                frappe.throw(_("Backup Coordinator {0} does not exist").format(self.backup_coordinator))

            # Ensure backup coordinator is different from main coordinator
            if self.backup_coordinator == self.regional_coordinator:
                frappe.throw(_("Backup Coordinator cannot be the same as Regional Coordinator"))

    def validate_postal_codes(self):
        """Validate postal code patterns"""
        if self.postal_code_patterns:
            try:
                patterns = self.parse_postal_code_patterns()
                # Basic validation - ensure patterns are reasonable
                for pattern in patterns:
                    if len(pattern.strip()) < 1:
                        continue
                    # Allow patterns like: 1000-1999, 2*, 3000, etc.
                    if not re.match(r"^[\d\*\-\s]+$", pattern.strip()):
                        frappe.msgprint(
                            _("Postal code pattern '{0}' may not be valid").format(pattern),
                            indicator="orange",
                        )
            except Exception:
                frappe.msgprint(_("Error parsing postal code patterns"), indicator="orange")

    def validate_contact_info(self):
        """Validate contact information"""
        if self.regional_email:
            try:
                validate_email_address(self.regional_email)
            except Exception:
                frappe.throw(_("Invalid regional email address"))

        if self.website_url:
            # Basic URL validation
            if not (self.website_url.startswith("http://") or self.website_url.startswith("https://")):
                self.website_url = "https://" + self.website_url.lstrip("/")

    def validate_membership_fee_adjustment(self):
        """Validate membership fee adjustment"""
        if self.membership_fee_adjustment is not None:
            if self.membership_fee_adjustment < 0.1 or self.membership_fee_adjustment > 2.0:
                frappe.throw(_("Membership fee adjustment must be between 0.1 and 2.0"))

    def before_save(self):
        """Before save operations"""
        self.update_route()

    def update_route(self):
        """Update web route"""
        if self.region_name:
            self.route = f"regions/{self.scrub(self.region_name)}"

    def get_context(self, context):
        """Get context for web view"""
        # Handle both dict and object contexts
        if hasattr(context, "__dict__"):
            # Object context
            context.no_cache = 1
            context.show_sidebar = True
            context.chapters = self.get_region_chapters()
            context.stats = self.get_region_statistics()
        else:
            # Dict context
            context["no_cache"] = 1
            context["show_sidebar"] = True
            context["chapters"] = self.get_region_chapters()
            context["stats"] = self.get_region_statistics()

        # Get regional coordinator info
        if self.regional_coordinator:
            if hasattr(context, "__dict__"):
                context.coordinator = frappe.get_doc("Member", self.regional_coordinator)
            else:
                context["coordinator"] = frappe.get_doc("Member", self.regional_coordinator)

        return context

    def get_region_chapters(self):
        """Get all chapters in this region"""
        try:
            chapters = frappe.get_all(
                "Chapter",
                filters={"region": self.name},
                fields=["name", "chapter_head", "published", "introduction"],
                order_by="name",
            )
            return chapters
        except Exception as e:
            frappe.log_error(f"Error getting region chapters: {str(e)}")
            return []

    def get_region_statistics(self):
        """Get regional statistics"""
        try:
            stats = {}

            # Count chapters
            stats["total_chapters"] = frappe.db.count("Chapter", {"region": self.name})
            stats["published_chapters"] = frappe.db.count("Chapter", {"region": self.name, "published": 1})

            # Count members in region
            chapter_members = frappe.db.sql(
                """
                SELECT COUNT(DISTINCT cm.member) as member_count
                FROM `tabChapter Member` cm
                INNER JOIN `tabChapter` ch ON cm.parent = ch.name
                WHERE ch.region = %s AND cm.enabled = 1
            """,
                (self.name,),
                as_dict=True,
            )

            stats["total_members"] = chapter_members[0].member_count if chapter_members else 0

            return stats
        except Exception as e:
            frappe.log_error(f"Error getting region statistics: {str(e)}")
            return {}

    def parse_postal_code_patterns(self):
        """Parse postal code patterns into list"""
        if not self.postal_code_patterns:
            return []

        patterns = [p.strip() for p in self.postal_code_patterns.split(",")]
        return [p for p in patterns if p]  # Remove empty patterns

    def matches_postal_code(self, postal_code):
        """Check if postal code matches this region's patterns"""
        if not self.postal_code_patterns or not postal_code:
            return False

        patterns = self.parse_postal_code_patterns()
        postal_code = postal_code.strip().replace(" ", "")  # Normalize

        for pattern in patterns:
            pattern = pattern.strip().replace(" ", "")

            if self._postal_code_matches_pattern(postal_code, pattern):
                return True

        return False

    def _postal_code_matches_pattern(self, postal_code, pattern):
        """Check if postal code matches a specific pattern"""
        try:
            # Handle wildcard patterns (e.g., "3*" matches 3000-3999)
            if "*" in pattern:
                prefix = pattern.replace("*", "")
                return postal_code.startswith(prefix)

            # Handle range patterns (e.g., "1000-1999")
            if "-" in pattern:
                start, end = pattern.split("-", 1)
                start_num = int(start)
                end_num = int(end)
                postal_num = int(postal_code[: len(start)])
                return start_num <= postal_num <= end_num

            # Handle exact match
            return postal_code.startswith(pattern)

        except (ValueError, IndexError):
            return False


# Utility functions


@frappe.whitelist()
def get_regions_for_dropdown():
    """Get regions for dropdown selection"""
    return frappe.get_all(
        "Region",
        filters={"is_active": 1},
        fields=["name", "region_name", "region_code"],
        order_by="region_name",
    )


@frappe.whitelist()
def find_region_by_postal_code(postal_code):
    """Find region that matches postal code"""
    if not postal_code:
        return None

    regions = frappe.get_all("Region", filters={"is_active": 1}, fields=["name", "postal_code_patterns"])

    for region in regions:
        if region.postal_code_patterns:
            region_doc = frappe.get_doc("Region", region.name)
            if region_doc.matches_postal_code(postal_code):
                return region.name

    return None


@frappe.whitelist()
def get_regional_coordinator(region_name):
    """Get regional coordinator for a region"""
    if not region_name:
        return None

    return frappe.db.get_value(
        "Region", region_name, ["regional_coordinator", "backup_coordinator"], as_dict=True
    )


@frappe.whitelist()
def validate_postal_code_patterns(patterns):
    """Validate postal code patterns"""
    try:
        if not patterns:
            return {"valid": True}

        pattern_list = [p.strip() for p in patterns.split(",")]
        errors = []

        for pattern in pattern_list:
            if not pattern:
                continue

            # Basic validation
            if not re.match(r"^[\d\*\-\s]+$", pattern):
                errors.append(f"Invalid pattern: {pattern}")

            # Range validation
            if "-" in pattern and pattern.count("-") == 1:
                try:
                    start, end = pattern.split("-")
                    start_num = int(start.strip())
                    end_num = int(end.strip())
                    if start_num >= end_num:
                        errors.append(f"Invalid range: {pattern}")
                except ValueError:
                    errors.append(f"Invalid range format: {pattern}")

        return {"valid": len(errors) == 0, "errors": errors}

    except Exception as e:
        return {"valid": False, "errors": [str(e)]}
