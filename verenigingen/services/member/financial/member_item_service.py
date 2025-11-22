# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MemberItemService - Membership billing item management

This service handles creation and retrieval of ERPNext Items used for
membership billing and invoicing operations.

Extracted from member.py:
- get_or_create_membership_item() - lines 984-1023 (40 LOC)

Architecture:
- Static methods for item operations
- Proper error handling and logging
- Uses secure_document_operation for permission-aware creation
- Singleton pattern for membership fee item

Business Logic:
- Creates standardized "MEMBERSHIP-FEE" item for billing
- Configures as service item (non-stock)
- Returns existing item if already created
- Handles creation failures gracefully

Security:
- Uses secure_document_operation for proper permission validation
- Justification logging for audit trail
- No permission bypasses

Dependencies:
- frappe.model.document for Item management
- secure_document_operation for permission-aware operations
"""

from typing import TYPE_CHECKING, Optional

import frappe

from verenigingen.utils.secure_operations import secure_document_operation

if TYPE_CHECKING:
    from frappe.model.document import Document


class MemberItemService:
    """
    Service for managing membership billing items.

    This service handles:
    - Membership fee item creation and retrieval
    - ERPNext Item configuration for membership billing
    - Singleton pattern for standardized membership item
    """

    @staticmethod
    def get_or_create_membership_item(member_doc: "Document") -> Optional["Document"]:
        """
        Get or create the standardized membership fee item.

        This method ensures a singleton "MEMBERSHIP-FEE" Item exists in ERPNext
        for use in membership billing and invoicing operations.

        Args:
            member_doc: Member document instance (for logging/justification)

        Returns:
            Item document if found or created successfully, None on error

        Business Logic:
            - Item Code: "MEMBERSHIP-FEE" (standardized)
            - Item Name: "Membership Fee"
            - Item Group: "Services" (default)
            - Service Item: Yes (non-stock)
            - Sales Item: Yes (for invoicing)
            - Purchase Item: No (not for procurement)

        Example:
            >>> item = MemberItemService.get_or_create_membership_item(member_doc)
            >>> if item:
            ...     print(f"Using item: {item.name}")
        """
        try:
            item_code = "MEMBERSHIP-FEE"

            # Check if item already exists
            existing_item = frappe.db.exists("Item", item_code)
            if existing_item:
                return frappe.get_doc("Item", existing_item)

            # Create membership fee item with standardized configuration
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": item_code,
                    "item_name": "Membership Fee",
                    "item_group": MemberItemService._get_default_item_group(),
                    "is_service_item": 1,
                    "maintain_stock": 0,
                    "include_item_in_manufacturing": 0,
                    "is_purchase_item": 0,
                    "is_sales_item": 1,
                }
            )

            # Use secure operation for permission-aware creation
            item_result = secure_document_operation(
                operation="insert",
                doc=item,
                justification=f"Automated membership item creation for member {member_doc.name}",
                required_permissions=["Item:create"],
            )

            if not item_result.success:
                frappe.logger().error(f"Failed to create membership item: {'; '.join(item_result.errors)}")
                return None

            frappe.logger().info(f"Created membership item {item.name}")
            return item

        except Exception as e:
            frappe.log_error(f"Error creating membership item: {str(e)}", "Member Item Service")
            return None

    @staticmethod
    def _get_default_item_group() -> str:
        """
        Get the default item group for membership items.

        Returns "Services" as the default item group. Falls back to "Products"
        if "Services" doesn't exist.

        Returns:
            Item group name for membership items
        """
        # Try to use "Services" as default item group
        if frappe.db.exists("Item Group", "Services"):
            return "Services"

        # Fallback to "Products" which should exist in standard ERPNext
        if frappe.db.exists("Item Group", "Products"):
            return "Products"

        # Last resort: use "All Item Groups" which is root in ERPNext
        return "All Item Groups"


def get_member_item_service() -> MemberItemService:
    """Get singleton instance of MemberItemService"""
    return MemberItemService()
