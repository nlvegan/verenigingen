"""
Link field sanitization utilities.

Provides functions to clean up broken Link field references on documents
before saving, preventing validation errors from orphaned references.
"""

import frappe


def sanitize_document_link_fields(doc, fields_to_check=None):
    """
    Clear Link fields that point to non-existent documents.

    This is useful when saving documents that may have stale references
    to deleted records, which would otherwise cause Frappe's _validate_links()
    to throw an error.

    Args:
        doc: The document to sanitize
        fields_to_check: Optional list of field names to check. If None, checks all Link fields.

    Returns:
        list: Field names that were cleared
    """
    if not doc or not doc.doctype:
        return []

    meta = frappe.get_meta(doc.doctype)
    link_fields = [f for f in meta.fields if f.fieldtype == "Link"]

    if fields_to_check:
        link_fields = [f for f in link_fields if f.fieldname in fields_to_check]

    cleared_fields = []

    for field in link_fields:
        value = getattr(doc, field.fieldname, None)
        if value and not frappe.db.exists(field.options, value):
            setattr(doc, field.fieldname, None)
            cleared_fields.append(field.fieldname)
            frappe.logger().warning(
                f"Cleared broken {field.fieldname} link on {doc.doctype} {doc.name}: "
                f"{field.options} '{value}' does not exist"
            )

    return cleared_fields


def sanitize_member_links_on_customer(customer_doc):
    """
    Specifically sanitize Member link fields on a Customer document.

    Customer documents may have `member` and `custom_member` fields that
    can become orphaned when Members are deleted.

    Args:
        customer_doc: Customer document to sanitize

    Returns:
        list: Field names that were cleared
    """
    return sanitize_document_link_fields(customer_doc, fields_to_check=["member", "custom_member"])


def sanitize_customer_links(customer_doc):
    """
    Sanitize all commonly orphaned Link fields on a Customer document.

    This handles:
    - Member links (member, custom_member)
    - Contact links (customer_primary_contact)
    - Address links (customer_primary_address)

    Args:
        customer_doc: Customer document to sanitize

    Returns:
        list: Field names that were cleared
    """
    return sanitize_document_link_fields(
        customer_doc,
        fields_to_check=[
            "member",
            "custom_member",
            "customer_primary_contact",
            "customer_primary_address",
        ],
    )
