# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Donor Management Service

Handles donor record creation and linkage with members for donation tracking.

ERROR HANDLING PATTERN: Dict-Based Pattern
===============================================
All methods return {"success": bool, ...} dictionaries, never throw exceptions.

Rationale: Donor management is a financial utility where:
- Callers need detailed error messages for troubleshooting
- Operations should not abort workflows
- Results need to be displayed in UI
- Partial failures should be handled gracefully

Methods:
- check_donor_exists: Returns {"exists": bool, "donor_name": str}
- create_donor_from_member: Returns {"success": bool, "donor_name": str, "message": str}

See: docs/patterns/ERROR_HANDLING_PATTERNS.md
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.secure_operations import secure_document_operation


class DonorManagementService:
    """
    Donor Management Service

    Handles creation and management of donor records linked to members.
    Donors are required for members who want to receive donation receipts.

    Methods:
        - check_donor_exists: Check if donor exists for member
        - create_donor_from_member: Create donor from member data

    Security:
        - Uses secure_document_operation for all document operations
        - Validates permissions at API layer
        - Creates audit trail for donor creation

    Business Rules:
        - One donor per member email address
        - Donor linked via email (primary lookup)
        - Dutch phone numbers formatted with +31
        - Address copied from member's primary address
    """

    @staticmethod
    def check_donor_exists(member_name: str) -> Dict[str, Any]:
        """
        Check if a donor record exists for a member.

        Looks up donor by member's email address (primary method).

        Args:
            member_name: Name of the Member document

        Returns:
            Dict with check result:
                - exists: Boolean indicating if donor exists
                - donor_name: Document name (if exists)
                - donor_display_name: Display name (if exists)
                - error: Error message (if check failed)

        Example:
            >>> result = DonorManagementService.check_donor_exists("Member-001")
            >>> if result["exists"]:
            >>>     print(f"Donor: {result['donor_display_name']}")

        Note:
            - Never throws exceptions (returns {"exists": False, "error": str} on failure)
            - Email-based lookup is primary method
            - Returns False if member doesn't exist
        """
        try:
            # Validate member exists first
            if not frappe.db.exists("Member", member_name):
                return {"exists": False}

            member = frappe.get_doc("Member", member_name)

            # Lookup donor by email (primary method)
            existing_donor = frappe.db.get_value(
                "Donor", {"donor_email": member.email}, ["name", "donor_name"]
            )

            if existing_donor:
                return {
                    "exists": True,
                    "donor_name": existing_donor[0],
                    "donor_display_name": existing_donor[1],
                }

            # No donor found
            return {"exists": False}

        except Exception as e:
            frappe.log_error(
                f"Error checking donor existence for member {member_name}: {str(e)}", "DonorManagementService"
            )
            return {"exists": False, "error": str(e)}

    @staticmethod
    def create_donor_from_member(member_name: str) -> Dict[str, Any]:
        """
        Create a donor record from member information.

        Copies member data to new donor record, including:
        - Basic information (name, email)
        - Dutch-formatted phone number
        - Address from primary_address
        - Links to member and customer

        Args:
            member_name: Name of the Member document

        Returns:
            Dict with creation result:
                - success: Boolean indicating if creation succeeded
                - donor_name: Created donor document name (if successful)
                - message: Human-readable result message
                - error: Error details (if failed)

        Security:
            - Uses secure_document_operation for donor.insert()
            - Uses secure_document_operation for customer linking
            - Creates audit trail for all operations
            - Requires Donor:create permission

        Example:
            >>> result = DonorManagementService.create_donor_from_member("Member-001")
            >>> if result["success"]:
            >>>     print(f"Created donor: {result['donor_name']}")
            >>> else:
            >>>     print(f"Error: {result['message']}")

        Business Rules:
            - One donor per member (checked via email)
            - Donor type always "Individual"
            - Category set to "Regular Donor"
            - Phone numbers formatted for Netherlands (+31)
            - Address copied from primary_address if available
            - Customer linked if exists

        Note:
            - Never throws exceptions
            - Returns {"success": False, "message": str} on failure
            - Partial success (donor created but customer link failed) logs warning
        """
        try:
            # Get member document
            member = frappe.get_doc("Member", member_name)

            # Check if donor already exists
            existing_check = DonorManagementService.check_donor_exists(member_name)
            if existing_check.get("exists"):
                return {
                    "success": False,
                    "message": _("Donor record already exists for this member"),
                    "donor_name": existing_check.get("donor_name"),
                }

            # Prepare donor data
            donor_data = DonorManagementService._prepare_donor_basic_data(member)

            # Create donor document
            donor = frappe.new_doc("Donor")
            for field, value in donor_data.items():
                setattr(donor, field, value)

            # Copy address if available
            if member.primary_address:
                address_result = DonorManagementService._copy_address_from_member(member)
                if address_result["success"]:
                    donor.address = address_result["address"]

            # Link to member record
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

            # Link customer if exists (non-critical, log warning on failure)
            if member.customer:
                DonorManagementService._link_customer_to_donor(member.customer, donor.name)

            frappe.logger().info(
                f"DonorManagementService: Created donor {donor.name} for member {member.name}"
            )

            return {
                "success": True,
                "message": _("Donor record created successfully. Member can now receive donation receipts."),
                "donor_name": donor.name,
            }

        except Exception as e:
            frappe.log_error(
                f"Donor creation failed for {member_name}: {str(e)[:100]}", "DonorManagementService"
            )
            return {
                "success": False,
                "error": str(e),
                "message": _("Failed to create donor record: {0}").format(str(e)),
            }

    @staticmethod
    def _prepare_donor_basic_data(member) -> Dict[str, Any]:
        """
        Prepare basic donor data from member document.

        Extracts and formats basic donor fields including Dutch phone number formatting.

        Args:
            member: Member document

        Returns:
            Dict with donor field values:
                - donor_name: Full name
                - donor_email: Email address
                - donor_type: Always "Individual"
                - contact_person: Full name
                - phone: Formatted phone number (if available)
                - donor_category: Always "Regular Donor"

        Business Rules:
            - Phone numbers formatted with Dutch +31 prefix
            - Empty phone if member has no contact_number
            - All fields use member data as source
        """
        donor_data = {
            "donor_name": member.full_name,
            "donor_email": member.email,
            "donor_type": "Individual",
            "donor_category": "Regular Donor",
        }

        # Set contact person if available
        if member.full_name:
            donor_data["contact_person"] = member.full_name

        # Format Dutch phone number if available
        if member.contact_number and member.contact_number.strip():
            phone_result = DonorManagementService._format_dutch_phone_number(member.contact_number)
            if phone_result["success"]:
                donor_data["phone"] = phone_result["formatted_number"]

        return donor_data

    @staticmethod
    def _format_dutch_phone_number(phone: str) -> Dict[str, Any]:
        """
        Format Dutch phone numbers with +31 country code.

        Handles various input formats:
        - 06XXXXXXXX (Dutch mobile) → +316XXXXXXXX
        - 0XXXXXXXXX (Dutch landline) → +31XXXXXXXXX
        - Already formatted numbers passed through

        Args:
            phone: Raw phone number string

        Returns:
            Dict with formatting result:
                - success: Boolean
                - formatted_number: Formatted number with +31 (if successful)
                - error: Error message (if failed)

        Examples:
            >>> result = DonorManagementService._format_dutch_phone_number("0612345678")
            >>> result["formatted_number"]  # "+31612345678"

            >>> result = DonorManagementService._format_dutch_phone_number("+31612345678")
            >>> result["formatted_number"]  # "+31612345678" (unchanged)

        Note:
            - Never throws exceptions
            - Returns {"success": False, "error": str} on failure
            - Strips spaces before processing
        """
        try:
            # Remove spaces for validation
            phone_number = phone.replace(" ", "")

            # If already has country code, return as-is
            if phone_number.startswith("+"):
                return {"success": True, "formatted_number": phone_number}

            # Add Dutch country code
            if phone_number.startswith("06") or phone_number.startswith("0"):
                # Replace leading 0 with +31
                formatted = "+31" + phone_number[1:]
            else:
                # Add +31 prefix
                formatted = "+31" + phone_number

            return {"success": True, "formatted_number": formatted}

        except Exception as e:
            frappe.logger().warning(
                f"DonorManagementService: Error formatting phone number '{phone}': {str(e)}"
            )
            return {"success": False, "error": str(e)}

    @staticmethod
    def _copy_address_from_member(member) -> Dict[str, Any]:
        """
        Copy and format address from member's primary address.

        Combines address components into single formatted string for donor record.

        Args:
            member: Member document with primary_address field

        Returns:
            Dict with copy result:
                - success: Boolean
                - address: Formatted address string (if successful)
                - error: Error message (if failed)

        Format:
            "Street, City, Postal Code, Country"

        Example:
            >>> result = DonorManagementService._copy_address_from_member(member)
            >>> if result["success"]:
            >>>     print(result["address"])
            # "Main Street 123, Amsterdam, 1012 AB, Netherlands"

        Note:
            - Never throws exceptions
            - Returns {"success": False} if address can't be copied
            - Logs warning on failure (non-critical operation)
        """
        try:
            if not member.primary_address:
                return {"success": False, "error": "No primary address set"}

            address_doc = frappe.get_doc("Address", member.primary_address)

            # Build address parts
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

            if not address_parts:
                return {"success": False, "error": "Address has no data"}

            formatted_address = ", ".join(address_parts)

            return {"success": True, "address": formatted_address}

        except Exception as e:
            frappe.logger().warning(
                f"DonorManagementService: Could not copy address from member {member.name}: {str(e)}"
            )
            return {"success": False, "error": str(e)}

    @staticmethod
    def _link_customer_to_donor(customer_name: str, donor_name: str) -> Dict[str, Any]:
        """
        Link customer record to donor record.

        Updates customer's donor field to create bidirectional link.
        This is a non-critical operation - failure is logged but doesn't abort donor creation.

        Args:
            customer_name: Name of Customer document
            donor_name: Name of Donor document

        Returns:
            Dict with link result:
                - success: Boolean
                - message: Result message
                - error: Error details (if failed)

        Security:
            - Uses secure_document_operation for customer update
            - Requires Customer:write permission

        Note:
            - Never throws exceptions
            - Returns {"success": False} on failure
            - Logs warning on failure (non-critical)
        """
        try:
            customer_doc = frappe.get_doc("Customer", customer_name)

            # Check if customer has donor field
            if not hasattr(customer_doc, "donor"):
                return {"success": False, "error": "Customer DocType does not have donor field"}

            customer_doc.donor = donor_name

            # Secure customer update with explicit permission validation
            customer_result = secure_document_operation(
                operation="save",
                doc=customer_doc,
                justification=f"Link customer {customer_name} to donor {donor_name}",
                required_permissions=["Customer:write"],
            )

            if not customer_result.success:
                error_msg = "; ".join(customer_result.errors)
                frappe.logger().warning(
                    f"DonorManagementService: Could not link customer {customer_name} to donor {donor_name}: {error_msg}"
                )
                return {"success": False, "error": error_msg}

            frappe.logger().info(
                f"DonorManagementService: Linked customer {customer_name} to donor {donor_name}"
            )

            return {"success": True, "message": "Customer linked to donor successfully"}

        except Exception as e:
            frappe.logger().warning(f"DonorManagementService: Could not link customer to donor: {str(e)}")
            return {"success": False, "error": str(e)}


# Convenience function for backward compatibility
def get_donor_management_service():
    """
    Get DonorManagementService instance.

    Returns:
        DonorManagementService class (stateless service)

    Example:
        >>> service = get_donor_management_service()
        >>> result = service.create_donor_from_member("Member-001")
    """
    return DonorManagementService
