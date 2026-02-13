# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberFeeCalculationService - Membership fee calculation logic

This service handles all membership fee calculation logic that was previously
in the Member DocType class. It determines the effective membership fee for
a member based on overrides, active membership, and dues schedule templates.

Extracted from:
- Member.get_current_membership_fee() - lines 1872-1900
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.services.billing.template_configuration_service import load_template_for_membership_type
from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberFeeCalculationService(StatelessService):
    """
    Service for calculating membership fees with proper precedence handling.

    Fee calculation precedence:
    1. Custom override (Member.dues_rate field)
    2. Active membership template (Membership → Membership Type → Dues Schedule Template)
    3. Default (0.00)
    """

    def __init__(self) -> None:
        """Initialize the member fee calculation service."""
        super().__init__(service_name="MemberFeeCalculationService")

    def get_current_membership_fee(self, member_doc: "Document") -> Dict[str, Any]:
        """
        Get current effective membership fee for a member.

        Args:
            member_doc: Member document or document object

        Returns:
            Dict[str, Any]: Dictionary with keys:
                - amount (float): The fee amount
                - source (str): Source of fee ('custom_override', 'template', 'none', or 'error')
                - reason (str, optional): Reason for custom override
                - membership_type (str, optional): Membership type name if from template
                - error (str, optional): Error message if source is 'error'
        """
        # Priority 1: Custom override on member
        if getattr(member_doc, "dues_rate", None):
            return {
                "amount": member_doc.dues_rate,
                "source": "custom_override",
                "reason": getattr(member_doc, "fee_override_reason", None),
            }

        # Priority 2: Get from active membership template
        try:
            from verenigingen.services.member.core.member_membership_service import MemberMembershipService

            active_membership = MemberMembershipService().get_active_membership_for_member_doc(member_doc)
        except Exception as e:
            self.logger.error(f"Error retrieving active membership for member {member_doc.name}: {str(e)}")
            return {
                "amount": 0,
                "source": "error",
                "error": "Unable to retrieve membership information - please contact administrator",
            }

        if active_membership and active_membership.membership_type:
            try:
                membership_type = frappe.get_doc("Membership Type", active_membership.membership_type)

                # Load template (graceful — returns error dict if missing)
                template = load_template_for_membership_type(membership_type, required=False)
                if not template:
                    self.logger.error(
                        f"Membership Type '{membership_type.name}' missing dues schedule template"
                    )
                    return {
                        "amount": 0,
                        "source": "error",
                        "error": f"Membership Type '{membership_type.name}' has no dues schedule template assigned",
                    }
                amount = (
                    template.suggested_amount
                    or getattr(template, "dues_rate", None)
                    or getattr(template, "minimum_amount", None)
                    or 0
                )

                return {
                    "amount": amount,
                    "source": "template",
                    "membership_type": membership_type.membership_type_name,
                }
            except Exception as e:
                # Log error but don't crash the UI
                self.logger.error(f"Error calculating fee for member {member_doc.name}: {str(e)}")
                return {
                    "amount": 0,
                    "source": "error",
                    "error": "Unable to calculate fee - please contact administrator",
                }

        # Priority 3: Default (no fee)
        return {"amount": 0, "source": "none"}

    def get_display_membership_fee(self, member_doc) -> Dict:
        """
        Get membership fee with amendment status for display purposes.

        This method extends get_current_membership_fee() by checking for
        pending fee change amendments and returning display-appropriate data.

        Args:
            member_doc: Member document or document object

        Returns:
            Dict with keys:
            - current_amount (float): Current effective fee amount
            - display_amount (float): Amount to display (current or pending)
            - status (str): Display status ('Current' or 'Pending - Effective DATE')
            - source (str): Source of fee
            - amendment_status (str, optional): Status of pending amendment
            - amendment_id (str, optional): Name of pending amendment
            - reason (str, optional): Reason for fee/amendment
        """
        # Get base fee information
        current_fee = self.get_current_membership_fee(member_doc)

        # Check for pending amendments
        pending_amendments = frappe.get_all(
            "Contribution Amendment Request",
            filters={
                "member": member_doc.name,
                "status": ["in", ["Draft", "Pending Approval", "Approved"]],
                "amendment_type": "Fee Change",
            },
            fields=["name", "status", "requested_amount", "effective_date", "reason"],
            order_by="creation desc",
            limit=1,
        )

        if pending_amendments:
            amendment = pending_amendments[0]
            return {
                "current_amount": current_fee["amount"],
                "display_amount": amendment["requested_amount"],
                "status": f"Pending - Effective {frappe.utils.format_date(amendment['effective_date']) if amendment['effective_date'] else 'TBD'}",
                "amendment_status": amendment["status"],
                "amendment_id": amendment["name"],
                "reason": amendment["reason"],
                "source": "amendment_pending",
            }

        # No pending amendments, return current fee
        return {
            "current_amount": current_fee["amount"],
            "display_amount": current_fee["amount"],
            "status": "Current",
            "source": current_fee["source"],
            "reason": current_fee.get("reason"),
        }


def get_member_fee_calculation_service() -> MemberFeeCalculationService:
    """Get singleton instance of MemberFeeCalculationService"""
    return MemberFeeCalculationService()
