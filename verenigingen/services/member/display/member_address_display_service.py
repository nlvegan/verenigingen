# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberAddressDisplayService - HTML generation for address member displays

This service handles HTML templating for displaying members at the same address.
Extracted from Member.get_address_members_html() - lines 587-623

Architecture:
- Separates presentation logic (HTML) from business logic (address queries)
- Uses existing get_other_members_at_address() for data retrieval
- Generates responsive HTML with Bootstrap styling
"""

from typing import TYPE_CHECKING

import frappe

from verenigingen.services.member.core.member_status_service import get_member_status_color

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberAddressDisplayService:
    """
    Service for generating HTML displays of address-related member information.

    This service focuses on presentation logic, delegating data retrieval
    to the appropriate services (e.g., MemberAddressService).
    """

    @staticmethod
    def get_address_members_html(member_doc: "Document") -> str:
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
            frappe.log_error(
                f"Error loading address members for {member_doc.name}: {str(e)}\n\nTraceback: {frappe.get_traceback()}",
                "Address Display Error",
            )
            # Return generic error message to users (don't expose internal details)
            return '<div class="text-danger"><i class="fa fa-exclamation-triangle"></i> Error loading member information. Please contact your administrator.</div>'


def get_member_address_display_service() -> MemberAddressDisplayService:
    """Get singleton instance of MemberAddressDisplayService"""
    return MemberAddressDisplayService()
