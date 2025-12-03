# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberDonorIntegrationService - Donor record creation and synchronization

This service handles the integration between Member and Donor DocTypes,
providing functionality for creating donor records from member information
and maintaining the link between members and their donor profiles.

Extracted from member.py:
- create_donor_from_member() - lines 2800-2921 (123 LOC)

Architecture:
- Static methods for donor creation and linking
- Uses secure_document_operation for permission-validated operations
- Handles address information copying and phone number formatting
- Manages customer-to-donor linkage
- Dutch phone number formatting (+31 prefix handling)

Security:
- Uses secure_document_operation for all document creation/updates
- Explicit permission validation (Donor:create, Customer:write)
- No permission bypasses - proper user authentication required

Dependencies:
- secure_document_operation - Secure document operations with permission validation
- check_donor_exists - Donor existence validation utility
"""

from typing import TYPE_CHECKING, Any, Dict

import frappe
from frappe import _

from verenigingen.services.infrastructure.base_service import StatelessService

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberDonorIntegrationService(StatelessService):
    """
    Service for managing integration between Member and Donor DocTypes.

    This service handles:
    - Creating donor records from member information
    - Linking customers to donors
    - Copying address and contact information
    - Dutch phone number formatting
    """

    def __init__(self) -> None:
        """Initialize the member donor integration service."""
        super().__init__(service_name="MemberDonorIntegrationService")

    def create_donor_from_member(self, member_name: str) -> Dict[str, Any]:
        """
        Create a donor record from member information.

        Creates a new Donor DocType record populated with information from the
        specified Member. Includes address copying, phone number formatting
        (Dutch +31 prefix), and customer linkage.

        Args:
            member_name: Name/ID of the member document

        Returns:
            Dict[str, Any]: Result dictionary with keys:
                - success (bool): Whether operation succeeded
                - message (str): Human-readable result message
                - donor_name (str, optional): Name of created donor
                - error (str, optional): Error details if failed

        Security:
            - Uses secure_document_operation for donor creation
            - Requires Donor:create permission
            - Requires Customer:write for customer linkage

        Example:
            result = MemberDonorIntegrationService.create_donor_from_member("Member-001")
            if result["success"]:
                print(f"Created donor: {result['donor_name']}")
        """
        try:
            from verenigingen.services.member.donor.donor_management_service import (
                get_donor_management_service,
            )
            from verenigingen.utils.secure_operations import secure_document_operation

            member = frappe.get_doc("Member", member_name)

            # Check if donor already exists using donor management service
            donor_service = get_donor_management_service()
            existing_check = donor_service.check_donor_exists(member_name)
            if existing_check.success and existing_check.data:
                return {
                    "success": False,
                    "message": _("Donor record already exists for this member"),
                    "donor_name": existing_check.data.get("donor_name"),
                }

            # Create donor record
            donor = frappe.new_doc("Donor")

            # Copy basic information from member
            donor.donor_name = member.full_name
            donor.donor_email = member.email

            # Set mandatory fields (only donor_name, donor_type, and donor_email are required)
            donor.donor_type = "Individual"

            # Set optional fields only if they exist in the DocType and have values
            if member.full_name:
                donor.contact_person = member.full_name

            # Set phone only if member has a phone number (phone is NOT required in Donor DocType)
            if member.contact_number and member.contact_number.strip():
                # If the number doesn't start with +, assume it's Dutch and add +31
                phone_number = member.contact_number.replace(" ", "")  # Remove spaces for validation
                if not phone_number.startswith("+"):
                    # Check if it's a Dutch mobile number (starts with 06) or landline
                    if phone_number.startswith("06") or phone_number.startswith("0"):
                        phone_number = "+31" + phone_number[1:]  # Replace leading 0 with +31
                    else:
                        phone_number = "+31" + phone_number  # Add +31 prefix
                donor.phone = phone_number
            # No else clause - phone is optional, leave it empty if no phone number

            # Set donor category if available
            donor.donor_category = "Regular Donor"

            # Copy address information if available (using the 'address' field that exists in DocType)
            if member.primary_address:
                try:
                    address_doc = frappe.get_doc("Address", member.primary_address)
                    # Use the single 'address' field that exists in the DocType
                    address_parts = []
                    if address_doc.address_line1:
                        address_parts.append(address_doc.address_line1)
                    if address_doc.address_line2:
                        address_parts.append(address_doc.address_line2)
                    if address_doc.city:
                        address_parts.append(address_doc.city)
                    if address_doc.pincode:
                        address_parts.append(address_doc.pincode)
                    if address_doc.country:
                        address_parts.append(address_doc.country)
                    donor.address = ", ".join(address_parts)
                except Exception as addr_e:
                    self.logger.warning(f"Could not copy address from member {member_name}: {str(addr_e)}")

            # Link to the member record
            donor.member = member.name

            # Secure donor creation with explicit permission validation
            donor_result = secure_document_operation(
                operation="insert",
                doc=donor,
                justification=f"Automated donor creation for member {member.name}",
                required_permissions=["Donor:create"],
            )

            if not donor_result.success:
                return {
                    "success": False,
                    "error": "; ".join(donor_result.errors),
                    "message": _("Failed to create donor record: {0}").format("; ".join(donor_result.errors)),
                }

            # Link the customer record if it exists
            if member.customer:
                try:
                    # Update customer record to link to donor
                    customer_doc = frappe.get_doc("Customer", member.customer)
                    if hasattr(customer_doc, "donor"):
                        customer_doc.donor = donor.name

                        # Secure customer update with explicit permission validation
                        customer_result = secure_document_operation(
                            operation="save",
                            doc=customer_doc,
                            justification=f"Link customer {member.customer} to donor {donor.name}",
                            required_permissions=["Customer:write"],
                        )

                        if not customer_result.success:
                            self.logger.warning(
                                f"Could not link customer {member.customer} to donor {donor.name}: "
                                f"{'; '.join(customer_result.errors)}"
                            )
                except Exception as cust_e:
                    self.logger.warning(f"Could not link customer to donor: {str(cust_e)}")

            self.logger.info(f"Created donor record {donor.name} for member {member.name}")

            return {
                "success": True,
                "message": _("Donor record created successfully. Member can now receive donation receipts."),
                "donor_name": donor.name,
            }

        except Exception as e:
            # Very short error message to avoid log truncation
            self.logger.error(f"Donor creation failed: {str(e)[:50]}")
            return {
                "success": False,
                "error": str(e),
                "message": _("Failed to create donor record: {0}").format(str(e)),
            }


def get_member_donor_integration_service() -> MemberDonorIntegrationService:
    """Get singleton instance of MemberDonorIntegrationService"""
    return MemberDonorIntegrationService()
