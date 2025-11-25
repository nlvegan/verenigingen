# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Donor Management Service

Handles donor record creation and linkage with members for donation tracking.

ERROR HANDLING PATTERN: OperationResult Pattern
===============================================
All methods return OperationResult[T] with type-safe error handling.
Never throws exceptions - all errors returned as OperationResult.fail().

Rationale: Donor management is a financial utility where:
- Callers need detailed error messages for troubleshooting
- Operations should not abort workflows
- Type safety prevents runtime errors
- Partial failures should be handled gracefully
- Error chaining provides clear context

Public Methods:
- check_donor_exists: Returns OperationResult[Optional[Dict[str, str]]]
- create_donor_from_member: Returns OperationResult[str] (donor_name)

Private Helper Methods:
- _prepare_donor_basic_data: Returns OperationResult[Dict[str, Any]]
- _format_dutch_phone_number: Returns OperationResult[str]
- _copy_address_from_member: Returns OperationResult[str]
- _link_customer_to_donor: Returns OperationResult[None]

Migration Status: ✅ COMPLETE (2025-11-24)
- All 6 methods migrated from dict-based to OperationResult pattern
- Proper error chaining with .chain() for context propagation
- Type-safe generic return types

See: docs/patterns/OPERATION_RESULT_PATTERN.md
"""

from typing import Any, Dict, Optional

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult
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
    def check_donor_exists(member_name: str) -> OperationResult[Optional[Dict[str, str]]]:
        """
        Check if a donor record exists for a member.

        Looks up donor by member's email address (primary method).

        Args:
            member_name: Name of the Member document

        Returns:
            OperationResult[Optional[Dict[str, str]]]:
                - If donor exists: Returns dict with {"donor_name": str, "donor_display_name": str}
                - If donor doesn't exist: Returns None
                - On error: Returns failed OperationResult

        Example:
            >>> result = DonorManagementService.check_donor_exists("Member-001")
            >>> if result.success and result.data:
            >>>     print(f"Donor: {result.data['donor_display_name']}")
            >>> elif result.success:
            >>>     print("No donor found")

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Email-based lookup is primary method
            - Returns success with None if member doesn't exist (not an error)
        """
        try:
            # Validate member exists first
            if not frappe.db.exists("Member", member_name):
                return OperationResult.ok(None, member_not_found=True)

            member = frappe.get_doc("Member", member_name)

            # Lookup donor by email (primary method)
            existing_donor = frappe.db.get_value(
                "Donor", {"donor_email": member.email}, ["name", "donor_name"]
            )

            if existing_donor:
                return OperationResult.ok(
                    {
                        "donor_name": existing_donor[0],
                        "donor_display_name": existing_donor[1],
                    },
                    exists=True,
                )

            # No donor found (not an error)
            return OperationResult.ok(None, exists=False)

        except Exception as e:
            frappe.log_error(
                f"Error checking donor existence for member {member_name}: {str(e)}", "DonorManagementService"
            )
            return OperationResult.fail(
                f"Failed to check donor existence: {str(e)}", errors=[str(e)], member=member_name
            )

    @staticmethod
    def create_donor_from_member(member_name: str) -> OperationResult[str]:
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
            OperationResult[str]: Created donor document name (donor.name) on success

        Security:
            - Uses secure_document_operation for donor.insert()
            - Uses secure_document_operation for customer linking
            - Creates audit trail for all operations
            - Requires Donor:create permission

        Example:
            >>> result = DonorManagementService.create_donor_from_member("Member-001")
            >>> if result.success:
            >>>     print(f"Created donor: {result.data}")
            >>> else:
            >>>     print(f"Error: {result.error_message}")

        Business Rules:
            - One donor per member (checked via email)
            - Donor type always "Individual"
            - Category set to "Regular Donor"
            - Phone numbers formatted for Netherlands (+31)
            - Address copied from primary_address if available
            - Customer linked if exists

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Partial success (donor created but customer link failed) logs warning
        """
        try:
            # Get member document
            member = frappe.get_doc("Member", member_name)

            # Check if donor already exists
            existing_check = DonorManagementService.check_donor_exists(member_name)
            if not existing_check.success:
                return existing_check.chain("Failed to check for existing donor")

            if existing_check.data:
                # Donor already exists
                return OperationResult.fail(
                    _("Donor record already exists for this member"),
                    errors=["Donor already exists"],
                    donor_name=existing_check.data.get("donor_name"),
                )

            # Prepare donor data
            donor_data_result = DonorManagementService._prepare_donor_basic_data(member)
            if not donor_data_result.success:
                return donor_data_result.chain("Failed to prepare donor data")

            # Create donor document
            donor = frappe.new_doc("Donor")
            for field, value in donor_data_result.data.items():
                setattr(donor, field, value)

            # Copy address if available (non-critical)
            if member.primary_address:
                address_result = DonorManagementService._copy_address_from_member(member)
                if address_result.success:
                    donor.address = address_result.data
                else:
                    # Address copy failed - log warning but continue (non-critical)
                    frappe.logger().warning(
                        f"DonorManagementService: Could not copy address for member {member.name}: {address_result.error_message}"
                    )

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
                return OperationResult.fail(
                    _("Failed to create donor record: {0}").format("; ".join(donor_result.errors)),
                    errors=donor_result.errors,
                )

            # Link customer if exists (non-critical, log warning on failure)
            if member.customer:
                customer_link_result = DonorManagementService._link_customer_to_donor(
                    member.customer, donor.name
                )
                if not customer_link_result.success:
                    # Customer linking failed - log warning but continue (non-critical)
                    frappe.logger().warning(
                        f"DonorManagementService: Donor created but customer link failed: {customer_link_result.error_message}"
                    )

            frappe.logger().info(
                f"DonorManagementService: Created donor {donor.name} for member {member.name}"
            )

            return OperationResult.ok(
                donor.name,
                message=_("Donor record created successfully. Member can now receive donation receipts."),
            )

        except Exception as e:
            frappe.log_error(
                f"Donor creation failed for {member_name}: {str(e)[:100]}", "DonorManagementService"
            )
            return OperationResult.fail(
                _("Failed to create donor record: {0}").format(str(e)), errors=[str(e)], member=member_name
            )

    @staticmethod
    def _prepare_donor_basic_data(member) -> OperationResult[Dict[str, Any]]:
        """
        Prepare basic donor data from member document.

        Extracts and formats basic donor fields including Dutch phone number formatting.

        Args:
            member: Member document

        Returns:
            OperationResult[Dict[str, Any]]: Dictionary with donor field values:
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

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Phone formatting errors are non-fatal (phone field omitted)
        """
        try:
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
                if phone_result.success:
                    donor_data["phone"] = phone_result.data
                else:
                    # Phone formatting failed - log warning but continue (non-fatal)
                    frappe.logger().warning(
                        f"DonorManagementService: Could not format phone for member {member.name}: {phone_result.error_message}"
                    )

            return OperationResult.ok(donor_data)

        except Exception as e:
            frappe.logger().error(
                f"DonorManagementService: Error preparing donor data for member {member.name}: {str(e)}"
            )
            return OperationResult.fail(f"Failed to prepare donor data: {str(e)}", errors=[str(e)])

    @staticmethod
    def _format_dutch_phone_number(phone: str) -> OperationResult[str]:
        """
        Format Dutch phone numbers with +31 country code.

        Handles various input formats:
        - 06XXXXXXXX (Dutch mobile) → +316XXXXXXXX
        - 0XXXXXXXXX (Dutch landline) → +31XXXXXXXXX
        - Already formatted numbers passed through

        Args:
            phone: Raw phone number string

        Returns:
            OperationResult[str]: Formatted phone number with +31 country code

        Examples:
            >>> result = DonorManagementService._format_dutch_phone_number("0612345678")
            >>> result.data  # "+31612345678"

            >>> result = DonorManagementService._format_dutch_phone_number("+31612345678")
            >>> result.data  # "+31612345678" (unchanged)

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Strips spaces before processing
        """
        try:
            # Remove spaces for validation
            phone_number = phone.replace(" ", "")

            # If already has country code, return as-is
            if phone_number.startswith("+"):
                return OperationResult.ok(phone_number)

            # Add Dutch country code
            if phone_number.startswith("06") or phone_number.startswith("0"):
                # Replace leading 0 with +31
                formatted = "+31" + phone_number[1:]
            else:
                # Add +31 prefix
                formatted = "+31" + phone_number

            return OperationResult.ok(formatted)

        except Exception as e:
            frappe.logger().warning(
                f"DonorManagementService: Error formatting phone number '{phone}': {str(e)}"
            )
            return OperationResult.fail(f"Failed to format phone number: {str(e)}", errors=[str(e)])

    @staticmethod
    def _copy_address_from_member(member) -> OperationResult[str]:
        """
        Copy and format address from member's primary address.

        Combines address components into single formatted string for donor record.

        Args:
            member: Member document with primary_address field

        Returns:
            OperationResult[str]: Formatted address string in format "Street, City, Postal Code, Country"

        Example:
            >>> result = DonorManagementService._copy_address_from_member(member)
            >>> if result.success:
            >>>     print(result.data)
            # "Main Street 123, Amsterdam, 1012 AB, Netherlands"

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Logs warning on failure (non-critical operation)
        """
        try:
            if not member.primary_address:
                return OperationResult.fail(
                    "No primary address set", errors=["Member has no primary_address"]
                )

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
                return OperationResult.fail(
                    "Address has no data", errors=["Address document contains no data"]
                )

            formatted_address = ", ".join(address_parts)

            return OperationResult.ok(formatted_address)

        except Exception as e:
            frappe.logger().warning(
                f"DonorManagementService: Could not copy address from member {member.name}: {str(e)}"
            )
            return OperationResult.fail(f"Failed to copy address: {str(e)}", errors=[str(e)])

    @staticmethod
    def _link_customer_to_donor(customer_name: str, donor_name: str) -> OperationResult[None]:
        """
        Link customer record to donor record.

        Updates customer's donor field to create bidirectional link.
        This is a non-critical operation - failure is logged but doesn't abort donor creation.

        Args:
            customer_name: Name of Customer document
            donor_name: Name of Donor document

        Returns:
            OperationResult[None]: Success with no data, or failure with error details

        Security:
            - Uses secure_document_operation for customer update
            - Requires Customer:write permission

        Note:
            - Never throws exceptions (returns failed OperationResult)
            - Logs warning on failure (non-critical)
        """
        try:
            customer_doc = frappe.get_doc("Customer", customer_name)

            # Check if customer has donor field
            if not hasattr(customer_doc, "donor"):
                return OperationResult.fail(
                    "Customer DocType does not have donor field",
                    errors=["Customer DocType missing donor field"],
                )

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
                return OperationResult.fail(
                    f"Failed to link customer to donor: {error_msg}", errors=customer_result.errors
                )

            frappe.logger().info(
                f"DonorManagementService: Linked customer {customer_name} to donor {donor_name}"
            )

            return OperationResult.ok(None, customer=customer_name, donor=donor_name)

        except Exception as e:
            frappe.logger().warning(f"DonorManagementService: Could not link customer to donor: {str(e)}")
            return OperationResult.fail(f"Failed to link customer to donor: {str(e)}", errors=[str(e)])


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
