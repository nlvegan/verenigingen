"""
Simple party handler for payment processing without custom fields.
"""

import frappe


def get_or_create_customer_simple(relation_id, debug_log=None):
    """Get or create customer without relying on custom fields."""
    if not relation_id:
        return None

    # Try to find by name pattern first
    customer_name_pattern = f"%{relation_id}%"
    existing = frappe.db.get_value("Customer", {"customer_name": ["like", customer_name_pattern]}, "name")

    if existing:
        if debug_log:
            debug_log.append(f"Found existing customer: {existing}")
        return existing

    # Create new customer
    try:
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"E-Boekhouden Customer {relation_id}"
        customer.customer_group = frappe.db.get_value("Customer Group", {}, "name")
        customer.territory = frappe.db.get_value("Territory", {}, "name")
        customer.save()

        if debug_log:
            debug_log.append(f"Created customer: {customer.name}")
        return customer.name

    except Exception as e:
        if debug_log:
            debug_log.append(f"Error creating customer: {str(e)}")
        return None


def get_or_create_supplier_simple(relation_id, description, debug_log=None):
    """Get or create supplier without relying on custom fields."""
    if not relation_id:
        return None

    # Try to find by name pattern first
    supplier_name_pattern = f"%{relation_id}%"
    existing = frappe.db.get_value("Supplier", {"supplier_name": ["like", supplier_name_pattern]}, "name")

    if existing:
        if debug_log:
            debug_log.append(f"Found existing supplier: {existing}")
        return existing

    # Create new supplier
    try:
        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = f"E-Boekhouden Supplier {relation_id}"
        supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
        supplier.save()

        if debug_log:
            debug_log.append(f"Created supplier: {supplier.name}")
        return supplier.name

    except Exception as e:
        if debug_log:
            debug_log.append(f"Error creating supplier: {str(e)}")
        return None
