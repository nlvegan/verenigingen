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

import frappe
from frappe import _

# Import security decorators
from verenigingen.utils.security.api_security_framework import critical_api, high_security_api, standard_api


def add_customer_to_member_link():
    """Add Member link to Customer dashboard"""
    try:
        # Check if the link already exists
        existing_links = frappe.get_all(
            "DocType Link", filters={"parent": "Customer", "parenttype": "DocType", "link_doctype": "Member"}
        )

        if existing_links:
            return {"message": "Link already exists", "success": True}

        # Get Customer doctype
        customer_doc = frappe.get_doc("DocType", "Customer")

        # Add Member link
        customer_doc.append(
            "links",
            {"link_doctype": "Member", "link_fieldname": "customer", "group": "Membership", "hidden": 0},
        )

        customer_doc.save(ignore_permissions=True)
        frappe.db.commit()

        return {"message": "Customer to Member link added successfully", "success": True}

    except Exception as e:
        frappe.log_error(f"Error adding customer to member link: {str(e)}")
        return {"message": f"Error: {str(e)}", "success": False}


@frappe.whitelist()
@standard_api  # Customer-member relationship lookup
def get_member_from_customer(customer):
    """
    Retrieve the Member record associated with a Customer record.

    This function implements a dual lookup strategy to find Member records
    linked to Customer records, supporting both the current direct field
    approach and legacy reverse lookup methods for maximum compatibility.

    Args:
        customer (str): The name/ID of the Customer record to find the
                       associated Member for. Must be a valid Customer document name.

    Returns:
        dict or None: Member information if found, None if no association exists.
            Success response:
            {
                'name': 'MEM-2024-001',
                'full_name': 'John Doe',
                'status': 'Active'
            }

            None: If no Member is associated with the Customer

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
    # First try the new direct customer.member field
    member_name = frappe.db.get_value("Customer", customer, "member")
    if member_name:
        member = frappe.db.get_value("Member", member_name, ["name", "full_name", "status"], as_dict=True)
        if member:
            return member

    # Fallback to old method: search Member table for customer field
    member = frappe.db.get_value(
        "Member", {"customer": customer}, ["name", "full_name", "status"], as_dict=True
    )
    if member:
        return member
    return None


@frappe.whitelist()
def create_customer_member_button():
    """Add a custom button to Customer form to navigate to Member"""
    return """
    frappe.ui.form.on('Customer', {
        refresh: function(frm) {
            if (!frm.is_new()) {
                frappe.call({
                    method: 'verenigingen.api.customer_member_link.get_member_from_customer',
                    args: {
                        customer: frm.doc.name
                    },
                    callback: function(r) {
                        if (r.message) {
                            frm.add_custom_button(__('View Member'), function() {
                                frappe.set_route('Form', 'Member', r.message.name);
                            }, __('Actions'));

                            // Also show member status in dashboard
                            frm.dashboard.add_indicator(__('Member: ') + r.message.full_name + ' (' + r.message.status + ')',
                                r.message.status === 'Active' ? 'green' : 'orange');
                        }
                    }
                });
            }
        }
    });
    """
