"""
Member Address Management Service

Handles all address-related operations for Member DocType including:
- Dutch address normalization and fingerprinting
- Address matching and duplicate detection
- Co-located member discovery and relationship management
- Address display and UI generation

This service extracts address management business logic from the Member controller
to enable better testing, caching, and reusability across DocTypes.

Architecture:
    - Service-oriented pattern following SEPA Mandate service design
    - Singleton pattern for consistent state management
    - Integration with existing Dutch address utilities
    - Performance optimization through caching and batch operations

Author: Verenigingen Development Team
Created: 2025-09-18
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe.utils import get_datetime, getdate, now

from verenigingen.utils.address_matching.dutch_address_normalizer import (
    AddressFingerprintCollisionHandler,
    DutchAddressNormalizer,
)
from verenigingen.utils.address_matching.simple_optimized_matcher import SimpleOptimizedAddressMatcher
from verenigingen.utils.validation_utilities import AgeValidator, DocumentExistenceValidator


class MemberAddressService:
    """
    Service for managing Member address operations with Dutch-specific normalization.

    Provides centralized address processing including normalization, fingerprinting,
    duplicate detection, and co-located member discovery with optimized performance.

    Key Features:
        - Dutch address normalization with linguistic patterns
        - O(log N) address matching and duplicate detection
        - Co-located member discovery with relationship inference
        - Address display generation for UI components
        - Performance optimization through caching
        - Collision handling for address fingerprints

    Business Rules:
        - All addresses normalized to consistent Dutch format
        - Fingerprints generated for efficient matching
        - Collision detection prevents false duplicates
        - Member relationships inferred based on address + demographics
        - Display generation handles various member states
    """

    _instance = None
    _settings_cache = None
    _last_cache_update = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.logger = frappe.logger("MemberAddressService")

    def update_member_address_fields(self, member) -> Dict[str, Any]:
        """
        Update computed address fields for a member with optimized performance.

        Creates normalized address representations and fingerprints for efficient
        duplicate member detection and address matching operations.

        Args:
            member: Member document instance

        Returns:
            Dict containing:
                - success: Boolean operation success
                - updated_fields: Dict of fields that were updated
                - fingerprint: Generated address fingerprint
                - errors: List of any errors encountered
                - warnings: List of any warnings

        Side Effects:
            - Updates member.address_fingerprint
            - Updates member.normalized_address_line
            - Updates member.normalized_city
            - Updates member.address_last_updated
        """
        try:
            result = {
                "success": False,
                "updated_fields": {},
                "fingerprint": None,
                "errors": [],
                "warnings": [],
            }

            # Handle case where member has no primary address
            if not member.primary_address:
                self._clear_address_fields(member, result)
                result["success"] = True
                return result

            # Check if address normalization is needed
            needs_update = self._should_update_address_fields(member)
            if not needs_update and member.address_fingerprint:
                result["success"] = True
                result["fingerprint"] = member.address_fingerprint
                return result

            # Perform address normalization
            normalization_result = self._normalize_member_address(member)
            if not normalization_result["success"]:
                result["errors"].extend(normalization_result["errors"])
                self._clear_address_fields(member, result)
                return result

            # Set computed fields
            member.address_fingerprint = normalization_result["fingerprint"]
            member.normalized_address_line = normalization_result["normalized_line"]
            member.normalized_city = normalization_result["normalized_city"]
            member.address_last_updated = now()

            result.update(
                {
                    "success": True,
                    "updated_fields": {
                        "address_fingerprint": normalization_result["fingerprint"],
                        "normalized_address_line": normalization_result["normalized_line"],
                        "normalized_city": normalization_result["normalized_city"],
                        "address_last_updated": now(),
                    },
                    "fingerprint": normalization_result["fingerprint"],
                }
            )

            self.logger.debug(f"Successfully updated address fields for member {member.name}")
            return result

        except Exception as e:
            error_msg = f"Error updating address fields for member {member.name}: {str(e)}"
            self.logger.error(error_msg)
            result = {
                "success": False,
                "updated_fields": {},
                "fingerprint": None,
                "errors": [error_msg],
                "warnings": [],
            }
            self._clear_address_fields(member, result)
            return result

    def get_colocated_members(self, member) -> Dict[str, Any]:
        """
        Get other members living at the same address with relationship inference.

        Uses optimized O(log N) address matching to find members sharing the same
        normalized address, enriched with relationship and demographic data.

        Args:
            member: Member document instance

        Returns:
            Dict containing:
                - success: Boolean operation success
                - members: List of member data dictionaries
                - count: Number of co-located members found
                - errors: List of any errors encountered
                - warnings: List of any warnings
        """
        try:
            result = {"success": False, "members": [], "count": 0, "errors": [], "warnings": []}

            if not member.primary_address:
                self.logger.info(f"No primary address for member {member.name}")
                result["success"] = True
                return result

            # Use optimized matcher for O(log N) performance
            matching_members = SimpleOptimizedAddressMatcher.get_other_members_at_address_simple(member)

            # Enrich member data with relationships and demographics
            enriched_members = []
            for member_data in matching_members:
                enriched_member = self._enrich_member_data(member_data, member)
                if enriched_member:
                    enriched_members.append(enriched_member)

            result.update({"success": True, "members": enriched_members, "count": len(enriched_members)})

            self.logger.info(f"Found {len(enriched_members)} co-located members for {member.name}")
            return result

        except Exception as e:
            error_msg = f"Error getting co-located members for {member.name}: {str(e)}"
            self.logger.error(error_msg)
            return {"success": False, "members": [], "count": 0, "errors": [error_msg], "warnings": []}

    def generate_address_display_html(self, member, save_to_db: bool = False) -> Dict[str, Any]:
        """
        Generate HTML display of co-located members for UI components.

        Creates formatted HTML showing other members at the same address with
        status indicators, age information, and relationship data.

        Args:
            member: Member document instance
            save_to_db: Whether to save the generated HTML to the member document

        Returns:
            Dict containing:
                - success: Boolean operation success
                - html_content: Generated HTML string
                - member_count: Number of members displayed
                - errors: List of any errors encountered
                - warnings: List of any warnings
        """
        try:
            result = {"success": False, "html_content": "", "member_count": 0, "errors": [], "warnings": []}

            # Get co-located members
            colocated_result = self.get_colocated_members(member)
            if not colocated_result["success"]:
                result["errors"].extend(colocated_result["errors"])
                return result

            other_members = colocated_result["members"]

            if not other_members:
                result["success"] = True
                if save_to_db:
                    member.other_members_at_address = ""
                return result

            # Generate HTML content
            html_content = self._build_address_members_html(other_members)

            result.update({"success": True, "html_content": html_content, "member_count": len(other_members)})

            if save_to_db:
                member.other_members_at_address = html_content

            self.logger.debug(
                f"Generated address display HTML for {member.name} with {len(other_members)} members"
            )
            return result

        except Exception as e:
            error_msg = f"Error generating address display HTML for {member.name}: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "html_content": "",
                "member_count": 0,
                "errors": [error_msg],
                "warnings": [],
            }

    def _clear_address_fields(self, member, result: Dict[str, Any]) -> None:
        """Clear all computed address fields to maintain data consistency."""
        member.address_fingerprint = None
        member.normalized_address_line = None
        member.normalized_city = None
        member.address_last_updated = None

        result["updated_fields"] = {
            "address_fingerprint": None,
            "normalized_address_line": None,
            "normalized_city": None,
            "address_last_updated": None,
        }

    def _should_update_address_fields(self, member) -> bool:
        """Determine if address normalization is needed based on changes."""
        # New documents always need processing
        if member.is_new():
            return True

        # Check if address has changed
        if hasattr(member, "has_value_changed") and member.has_value_changed("primary_address"):
            return True

        # Process if no fingerprint exists
        if not member.address_fingerprint:
            return True

        return False

    def _normalize_member_address(self, member) -> Dict[str, Any]:
        """Perform address normalization and collision handling."""
        try:
            # Get address document
            address = frappe.get_doc("Address", member.primary_address)

            # Generate normalized forms and fingerprint
            normalized_line, normalized_city, fingerprint = DutchAddressNormalizer.normalize_address_pair(
                address.address_line1 or "", address.city or ""
            )

            # Handle potential collisions
            if AddressFingerprintCollisionHandler.detect_collision(
                fingerprint, normalized_line, normalized_city, member.name
            ):
                fingerprint = AddressFingerprintCollisionHandler.resolve_collision(
                    fingerprint, normalized_line, normalized_city, member.name
                )

            return {
                "success": True,
                "normalized_line": normalized_line,
                "normalized_city": normalized_city,
                "fingerprint": fingerprint,
                "errors": [],
                "warnings": [],
            }

        except Exception as e:
            return {
                "success": False,
                "normalized_line": None,
                "normalized_city": None,
                "fingerprint": None,
                "errors": [f"Address normalization failed: {str(e)}"],
                "warnings": [],
            }

    def _enrich_member_data(self, member_data: Dict, source_member) -> Optional[Dict[str, Any]]:
        """Enrich member data with additional information and validation."""
        try:
            member_name = member_data.get("name", "")
            if not member_name or not member_name.strip():
                self.logger.warning(f"Empty member name in co-located members for {source_member.name}")
                return None

            # Validate member existence
            if not DocumentExistenceValidator.validate_document_exists(
                "Member", member_name, throw_on_error=False
            ):
                self.logger.warning(f"Member {member_name} does not exist")
                return None

            # Calculate age information
            age_text = ""
            if member_data.get("birth_date"):
                age_years = int(AgeValidator.calculate_age(member_data["birth_date"]))
                age_text = f"{age_years} years old"

            # Enrich with standardized data
            enriched_data = {
                "name": member_name,
                "full_name": member_data.get("full_name", ""),
                "email": member_data.get("email", ""),
                "status": member_data.get("status", ""),
                "member_since": member_data.get("member_since"),
                "birth_date": member_data.get("birth_date"),
                "relationship": member_data.get("relationship", "Unknown"),
                "age_group": member_data.get("age_group", ""),
                "age_text": age_text,
                "contact_number": member_data.get("contact_number", ""),
                "days_member": member_data.get("days_member", 0),
            }

            return enriched_data

        except Exception as e:
            self.logger.error(f"Error enriching member data for {member_data}: {str(e)}")
            return None

    def _build_address_members_html(self, members: List[Dict]) -> str:
        """Build HTML content for address members display."""
        html_content = '<div class="other-members-container">'
        html_content += f'<h6 class="text-muted"><i class="fa fa-users"></i> Other Members at Same Address ({len(members)})</h6>'

        for member in members:
            member_name = member.get("name", "")
            member_full_name = member.get("full_name", "")

            status_color = {"Active": "success", "Pending": "warning", "Suspended": "danger"}.get(
                member.get("status", ""), "secondary"
            )

            age_text = member.get("age_text", "")
            relationship = member.get("relationship", "Unknown")

            html_content += f"""
            <div class="member-row" style="margin-bottom: 8px; padding: 6px; border-left: 3px solid var(--bs-{status_color}); background-color: #f8f9fa;">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <a href="/app/member/{member_name}" class="fw-bold text-decoration-none">
                            {member_full_name}
                        </a>
                        <span class="badge badge-{status_color} ms-2">{member.get("status", "")}</span>
                    </div>
                    <small class="text-muted">{age_text}</small>
                </div>
                {f'<small class="text-muted">Relationship: {relationship}</small>' if relationship != "Unknown" else ""}
            </div>
            """

        html_content += "</div>"
        return html_content

    def guess_relationship(self, member, other_member) -> str:
        """
        Attempt to guess relationship between two members based on name patterns and demographics.

        Uses heuristics including shared last names and age differences to infer likely
        relationships between household members.

        Args:
            member: Primary member (can be Member doc or dict)
            other_member: Other member to compare (can be Member doc or dict)

        Returns:
            str: Relationship label (e.g., "Spouse/Partner", "Parent/Child", "Sibling",
                 "Family Member", "Household Member")

        Business Logic:
            - Same last name + age diff < 5 years: "Spouse/Partner"
            - Same last name + age diff > 15 years: "Parent/Child"
            - Same last name + age diff 5-15 years: "Sibling"
            - Same last name (no age data): "Family Member"
            - Different last name: "Partner/Spouse"
            - No name data: "Household Member"
        """
        # Handle both dict and object inputs for flexibility
        member_full_name = (
            member.get("full_name") if isinstance(member, dict) else getattr(member, "full_name", None)
        )
        member_birth_date = (
            member.get("birth_date") if isinstance(member, dict) else getattr(member, "birth_date", None)
        )
        other_full_name = (
            other_member.get("full_name")
            if isinstance(other_member, dict)
            else getattr(other_member, "full_name", None)
        )
        other_birth_date = (
            other_member.get("birth_date")
            if isinstance(other_member, dict)
            else getattr(other_member, "birth_date", None)
        )

        # Default to generic household member if no names available
        if not other_full_name or not member_full_name:
            return "Household Member"

        # Extract last names for comparison
        member_parts = member_full_name.strip().split()
        other_parts = other_full_name.strip().split()

        if len(member_parts) > 0 and len(other_parts) > 0:
            member_last = member_parts[-1].lower()
            other_last = other_parts[-1].lower()

            # Same last name - likely family
            if member_last == other_last:
                # Use age difference for more specific relationship
                if member_birth_date and other_birth_date:
                    try:
                        member_date = getdate(member_birth_date)
                        other_date = getdate(other_birth_date)
                        age_diff = abs((member_date - other_date).days // 365)

                        if age_diff < 5:
                            return "Spouse/Partner"
                        elif age_diff > 15:
                            return "Parent/Child"
                        else:
                            return "Sibling"
                    except Exception:
                        # Invalid date format - fall through to generic
                        pass

                return "Family Member"
            else:
                # Different last names - likely partner/spouse
                return "Partner/Spouse"

        return "Household Member"


# Singleton instance for global access
member_address_service = MemberAddressService()
