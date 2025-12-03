# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberAddressDisplayService - HTML generation for address member displays

This service handles HTML templating for displaying members at the same address
and formatting address information for display on the Member form.

Extracted from member.py:
- get_address_members_html() - lines 587-623 (original extraction)
- update_address_display() - lines 2117-2158 (43 LOC)

Architecture:
- Separates presentation logic (HTML) from business logic (address queries)
- Uses existing get_other_members_at_address() for data retrieval
- Generates responsive HTML with Bootstrap styling
- Provides formatted address display HTML
"""

from typing import TYPE_CHECKING

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService
from verenigingen.services.member.core.member_status_service import get_member_status_color

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberAddressDisplayService(StatelessService):
    """
    Service for generating HTML displays of address-related member information.

    This service focuses on presentation logic, delegating data retrieval
    to the appropriate services (e.g., MemberAddressService).
    """

    def __init__(self) -> None:
        """Initialize the member address display service."""
        super().__init__(service_name="MemberAddressDisplayService")

    def get_address_members_html(self, member_doc: "Document") -> str:
        """
        Generate HTML content for displaying other members at the same address.

        This method is called from JavaScript to populate address member displays
        in the Member form.

        Args:
            member_doc: Member document or document object

        Returns:
            str: HTML content ready for injection into DOM
                - Empty state HTML if no address selected
                - Member cards HTML if other members found
                - Error HTML if exception occurs
        """
        try:
            # Check if member has a primary address
            if not member_doc.primary_address:
                return '<div class="text-muted"><i class="fa fa-home"></i> No address selected</div>'

            # Get other members at the same address (delegates to member_doc method)
            other_members = member_doc.get_other_members_at_address()

            if other_members:
                # Create HTML content for display
                html_content = f'<div class="address-members-display"><h6>Other Members at This Address ({len(other_members)} found): </h6>'

                for other in other_members:
                    status_color = get_member_status_color(other.get("status", "Unknown"))
                    html_content += f"""
                    <div class="member-card" style="border: 1px solid #ddd; padding: 8px; margin: 4px 0; border-radius: 4px; background: #f8f9fa;">
                        <strong>{other.get("full_name", "Unknown")}</strong>
                        <span class="text-muted">({other.get("name", "Unknown ID")})</span>
                        <br><small class="text-muted">
                            <i class="fa fa-users"></i> {other.get("relationship", "Unknown")} |
                            <i class="fa fa-birthday-cake"></i> {other.get("age_group", "Unknown")} |
                            <i class="fa fa-circle text-{status_color}"></i> {other.get("status", "Unknown")}
                        </small>
                        <br><small class="text-muted">
                            <i class="fa fa-envelope"></i> {other.get("email", "Unknown")}
                        </small>
                    </div>
                    """
                html_content += "</div>"
                return html_content
            else:
                # No other members found
                return '<div class="text-muted"><i class="fa fa-info-circle"></i> No other members found at this address</div>'

        except Exception as e:
            # Log detailed error for administrators
            self.logger.error(
                f"Error loading address members for {member_doc.name}: {str(e)}\n\nTraceback: {frappe.get_traceback()}"
            )
            # Return generic error message to users (don't expose internal details)
            return '<div class="text-danger"><i class="fa fa-exclamation-triangle"></i> Error loading member information. Please contact your administrator.</div>'

    def update_address_display(self, member_doc: "Document") -> str:
        """
        Update the address_display HTML field with formatted address information.

        Generates formatted HTML display of the member's primary address with
        proper styling and error handling.

        Args:
            member_doc: Member document object

        Returns:
            str: Formatted HTML string containing address information
                - Styled address display if address exists
                - Empty string if no address
                - Error message HTML if exception occurs
        """
        try:
            if not member_doc.primary_address:
                return ""

            # Get the address document
            address_doc = frappe.get_doc("Address", member_doc.primary_address)

            # Format the address as HTML
            html_content = '<div class="address-display" style="background: #f8f9fa; border-left: 3px solid #28a745; padding: 10px; margin: 5px 0;">'

            if address_doc.address_line1:
                html_content += f"<strong>{address_doc.address_line1}</strong><br>"

            if address_doc.address_line2:
                html_content += f"{address_doc.address_line2}<br>"

            address_parts = []
            if address_doc.pincode:
                address_parts.append(address_doc.pincode)
            if address_doc.city:
                address_parts.append(address_doc.city)

            if address_parts:
                html_content += f'{" ".join(address_parts)}<br>'

            if address_doc.state:
                html_content += f"{address_doc.state}<br>"

            if address_doc.country:
                html_content += f'<small class="text-muted">{address_doc.country}</small>'

            html_content += "</div>"

            return html_content

        except Exception as e:
            self.logger.error(f"Error updating address display for member {member_doc.name}: {str(e)}")
            return '<p style="color: #dc3545;">Error loading address information</p>'

    def update_other_members_at_address_display(self, member_doc: "Document") -> str:
        """
        Update the other_members_at_address HTML field with data from get_other_members_at_address.

        Generates formatted HTML display of other members living at the same address
        with proper styling, security escaping, and error handling.

        Args:
            member_doc: Member document object

        Returns:
            str: Formatted HTML string containing other members information
                - Member cards with links if members found
                - Empty string if no address or no other members
                - Error message HTML if exception occurs
        """
        try:
            if not member_doc.primary_address:
                return ""

            # Get other members at the same address
            other_members = member_doc.get_other_members_at_address()

            if not other_members or not isinstance(other_members, list) or len(other_members) == 0:
                return ""

            # Format the data as HTML with cleaner styling (no blue container)
            html_content = '<div class="other-members-container">'
            html_content += f'<h6 class="text-muted"><i class="fa fa-users"></i> Other Members at Same Address ({len(other_members)})</h6>'

            for member in other_members:
                member_name = member.get("name", "")
                member_full_name = member.get("full_name", "")

                # Skip if member_name is empty - this prevents broken links
                if not member_name or not member_name.strip():
                    self.logger.warning(f"Empty member name in same address display: {member}")
                    continue

                status_color = {"Active": "success", "Pending": "warning", "Suspended": "danger"}.get(
                    member.get("status", ""), "secondary"
                )

                # Calculate age in years
                age_text = ""
                if member.get("birth_date"):
                    # Using standardized age calculation utility
                    from verenigingen.utils.validation_utilities import AgeValidator

                    age_years = int(AgeValidator.calculate_age(member["birth_date"]))
                    age_text = f"{age_years} years old"

                # Validate member name format and existence using standardized validator
                from verenigingen.utils.validation_utilities import DocumentExistenceValidator

                if not DocumentExistenceValidator.validate_document_exists(
                    "Member", member_name, throw_on_error=False
                ):
                    self.logger.warning(f"Invalid member reference in same address display: {member_name}")
                    continue

                # Use Frappe's built-in escaping for security
                import json

                member_name_html = (
                    frappe.utils.cstr(member_name)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;")
                )
                member_full_name_html = (
                    frappe.utils.cstr(member_full_name)
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#39;")
                )
                member_name_js = json.dumps(member_name)  # Proper JavaScript string escaping

                html_content += '<div class="member-card" style="border-left: 3px solid #dee2e6; padding: 10px; margin: 8px 0; background: #f8f9fa;">'
                html_content += f'<a href="/app/member/{member_name_html}" onclick="event.preventDefault(); frappe.set_route(\'Form\', \'Member\', {member_name_js}); return false;" style="font-weight: 600; color: #007bff; text-decoration: none; cursor: pointer;" title="View {member_full_name_html}">{member_full_name_html}</a><br>'
                html_content += (
                    f'<span class="badge badge-{status_color}">{member.get("status", "Unknown")}</span>'
                )

                if member.get("member_since"):
                    html_content += (
                        f' <small class="text-muted">• Member since: {member["member_since"]}</small>'
                    )

                if age_text:
                    html_content += f' <small class="text-muted">• {age_text}</small>'

                html_content += "</div>"

            html_content += "</div>"
            return html_content

        except Exception as e:
            self.logger.error(
                f"Error updating other members at address display for member {member_doc.name}: {str(e)}"
            )
            return '<p style="color: #dc3545;">Error loading address information</p>'


def get_member_address_display_service() -> MemberAddressDisplayService:
    """Get singleton instance of MemberAddressDisplayService"""
    return MemberAddressDisplayService()
