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
    """Get or create supplier using proper party resolver for accurate names."""
    if not relation_id:
        return None

    if debug_log is None:
        debug_log = []

    # Use the robust party resolver instead of creating generic names
    try:
        from verenigingen.e_boekhouden.utils.party_resolver import EBoekhoudenPartyResolver

        resolver = EBoekhoudenPartyResolver()
        supplier_name = resolver.resolve_supplier(relation_id, debug_log)

        if supplier_name:
            debug_log.append(f"Party resolver returned supplier: {supplier_name}")
            return supplier_name
        else:
            debug_log.append(f"Party resolver failed for relation {relation_id}, using description fallback")
            # Fallback to description-based naming if provided
            if description and description.strip():
                return _create_supplier_from_description(relation_id, description, debug_log)
            return None

    except Exception as e:
        debug_log.append(f"Error using party resolver for relation {relation_id}: {str(e)}")
        return None


def _create_supplier_from_description(relation_id, description, debug_log):
    """Create supplier using description when API data unavailable."""
    try:
        # Clean description for supplier name
        clean_desc = description.strip()[:80] if description else ""

        if clean_desc:
            supplier_name = f"{clean_desc} (EB-{relation_id})"
        else:
            supplier_name = f"EB Supplier {relation_id}"

        # Check if already exists
        existing = frappe.db.get_value("Supplier", {"supplier_name": supplier_name}, "name")
        if existing:
            debug_log.append(f"Found existing description-based supplier: {existing}")
            return existing

        supplier = frappe.new_doc("Supplier")
        supplier.supplier_name = supplier_name
        supplier.supplier_group = frappe.db.get_value("Supplier Group", {}, "name")
        if hasattr(supplier, "eboekhouden_relation_code"):
            supplier.eboekhouden_relation_code = str(relation_id)
        supplier.save()

        if debug_log:
            debug_log.append(f"Created supplier: {supplier.name}")
        return supplier.name

    except Exception as e:
        if debug_log:
            debug_log.append(f"Error creating supplier: {str(e)}")
        return None
