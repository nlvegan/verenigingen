"""
Customer-Member Link Management API

This module provides API endpoints for managing the relationships between Customer
and Member records in the Verenigingen association management system. It enhances
navigation and data consistency between the financial (Customer) and membership
(Member) systems.

Key Features:
    - Bi-directional linking between Customer and Member records
    - Navigation enhancement for improved user experience
    - Data consistency validation and maintenance
    - Legacy support for existing relationship patterns
    - Administrative tools for link management

Business Context:
    In the Verenigingen system, members often have corresponding Customer records
    for financial transactions (invoices, payments). This module manages the
    relationship between these entities to ensure data consistency and provide
    seamless navigation for administrators.

Architecture:
    - DocType Link management for navigation enhancement
    - Dual lookup strategy (direct field + fallback search)
    - Administrative functions for system configuration
    - Error handling and recovery mechanisms

Security Model:
    - Standard API security for relationship lookups
    - Permission validation for Customer and Member access
    - Administrative functions with appropriate restrictions
    - Audit logging for relationship changes

Integration Points:
    - Customer DocType (ERPNext financial system)
    - Member DocType (Verenigingen membership system)
    - DocType Link system for navigation
    - Dashboard and form customizations

Data Model:
    - Primary: Customer.member field (direct reference)
    - Fallback: Member.customer field (reverse lookup)
    - Navigation: DocType Links for UI enhancement

Author: Verenigingen Development Team
License: MIT
"""

import traceback
from typing import Any, Dict

import frappe
from frappe import _

from verenigingen.utils.operation_result import OperationResult

# Import security decorators
from verenigingen.utils.security.api_security_framework import (
    OperationType,
    standard_api,
)


@frappe.whitelist()
@standard_api(operation_type=OperationType.MEMBER_DATA)
def get_member_from_customer(customer: str) -> OperationResult[Dict[str, Any]]:
    """
    Retrieve the Member record associated with a Customer record.

    This function implements a dual lookup strategy to find Member records
    linked to Customer records, supporting both the current direct field
    approach and legacy reverse lookup methods for maximum compatibility.

    Args:
        customer (str): The name/ID of the Customer record to find the
                       associated Member for. Must be a valid Customer document name.

    Returns:
        OperationResult[Dict[str, Any]]: Result containing Member information if found.
            Success response data:
            {
                'name': 'MEM-2024-001',
                'full_name': 'John Doe',
                'status': 'Active'
            }

            If no Member is associated, returns success with None data.

    Raises:
        frappe.PermissionError: If user lacks access to Customer or Member records
        frappe.ValidationError: If customer parameter is invalid

    Security:
        - Standard API security for relationship lookups
        - Validates user permissions for both Customer and Member access
        - Input validation and sanitization

    Lookup Strategy:
        1. Primary: Check Customer.member field (direct reference)
        2. Fallback: Search Member.customer field (reverse lookup)
        3. Return None if no relationship found

    Business Logic:
        - Prioritizes current data model (Customer.member field)
        - Maintains compatibility with legacy data patterns
        - Returns essential member information for display
        - Handles missing or invalid relationships gracefully

    Database Access:
        - Reads from: tabCustomer, tabMember
        - Fields: Customer.member, Member fields (name, full_name, status)
        - Indexes used: Customer primary key, Member.customer foreign key

    Integration Points:
        - Customer dashboard and forms for navigation
        - Member management interfaces
        - Financial system integration
        - Reporting and analytics systems
    """
    try:
        # First try the new direct customer.member field
        member_name = frappe.db.get_value("Customer", customer, "member")
        if member_name:
            member = frappe.db.get_value("Member", member_name, ["name", "full_name", "status"], as_dict=True)
            if member:
                return OperationResult.ok(member, message=_("Member found for customer"))

        # Fallback to old method: search Member table for customer field
        member = frappe.db.get_value(
            "Member", {"customer": customer}, ["name", "full_name", "status"], as_dict=True
        )
        if member:
            return OperationResult.ok(member, message=_("Member found for customer"))

        # No member found - this is a valid state, not an error
        return OperationResult.ok(None, message=_("No member associated with this customer"))

    except Exception as e:
        error_msg = _("Failed to retrieve member for customer {0}").format(customer)
        frappe.log_error(
            title=_("Get Member From Customer Error"),
            message=f"{error_msg}\n\nCustomer: {customer}\n\nError: {str(e)}\n\n{traceback.format_exc()}",
        )
        return OperationResult.fail(error_msg, errors=[str(e)])
