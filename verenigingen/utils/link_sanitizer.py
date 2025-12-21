"""
Link field sanitization utilities.

Provides functions to clean up broken Link field references on documents
before saving, preventing validation errors from orphaned references.

Usage:
    from verenigingen.utils.link_sanitizer import sanitize_customer_links

    # Auto-fix mode (default): clears broken links with audit trail
    cleared = sanitize_customer_links(customer_doc)

    # Strict mode: raises exception instead of auto-fixing
    sanitize_customer_links(customer_doc, strict=True)
"""

import frappe


class BrokenLinkError(frappe.ValidationError):
    """Raised when a Link field points to a non-existent document in strict mode."""

    pass


def sanitize_document_link_fields(doc, fields_to_check=None, strict=False):
    """
    Clear Link fields that point to non-existent documents.

    This is useful when saving documents that may have stale references
    to deleted records, which would otherwise cause Frappe's _validate_links()
    to throw an error.

    Args:
        doc: The document to sanitize
        fields_to_check: Optional list of field names to check. If None, checks all Link fields.
        strict: If True, raises BrokenLinkError instead of auto-fixing. Default False.

    Returns:
        list: Field names that were cleared (empty list in strict mode if validation passes)

    Raises:
        BrokenLinkError: If strict=True and broken links are found
    """
    if not doc or not doc.doctype:
        return []

    meta = frappe.get_meta(doc.doctype)
    link_fields = [f for f in meta.fields if f.fieldtype == "Link"]

    if fields_to_check:
        link_fields = [f for f in link_fields if f.fieldname in fields_to_check]

    cleared_fields = []
    broken_links = []

    for field in link_fields:
        value = getattr(doc, field.fieldname, None)
        if value and not frappe.db.exists(field.options, value):
            broken_links.append({"field": field.fieldname, "target_doctype": field.options, "value": value})

            if strict:
                # Don't auto-fix in strict mode - collect all errors first
                continue

            # Auto-fix: clear the broken reference
            setattr(doc, field.fieldname, None)
            cleared_fields.append(field.fieldname)

            # Create audit trail in Error Log for visibility
            error_message = (
                f"Auto-cleared broken link on {doc.doctype} {doc.name}\n\n"
                f"Field: {field.fieldname}\n"
                f"Target DocType: {field.options}\n"
                f"Missing Value: {value}\n\n"
                "This broken reference was automatically cleared to prevent save errors. "
                "The original document may have been deleted."
            )
            frappe.log_error(error_message, "Link Sanitization - Auto-Cleared")

            # Also log to frappe.logger for operational monitoring
            frappe.logger().warning(
                f"Cleared broken {field.fieldname} link on {doc.doctype} {doc.name}: "
                f"{field.options} '{value}' does not exist"
            )

    # In strict mode, raise exception if any broken links found
    if strict and broken_links:
        error_details = "\n".join(
            f"  - {bl['field']}: {bl['target_doctype']} '{bl['value']}' does not exist" for bl in broken_links
        )
        raise BrokenLinkError(
            f"Document {doc.doctype} {doc.name} has broken link references:\n{error_details}"
        )

    return cleared_fields


def sanitize_member_links_on_customer(customer_doc, strict=False):
    """
    Specifically sanitize Member link fields on a Customer document.

    Customer documents may have `member` and `custom_member` fields that
    can become orphaned when Members are deleted.

    Args:
        customer_doc: Customer document to sanitize
        strict: If True, raises BrokenLinkError instead of auto-fixing

    Returns:
        list: Field names that were cleared
    """
    return sanitize_document_link_fields(
        customer_doc, fields_to_check=["member", "custom_member"], strict=strict
    )


def sanitize_customer_links(customer_doc, strict=False):
    """
    Sanitize all commonly orphaned Link fields on a Customer document.

    This handles:
    - Member links (member, custom_member)
    - Contact links (customer_primary_contact)
    - Address links (customer_primary_address)

    Args:
        customer_doc: Customer document to sanitize
        strict: If True, raises BrokenLinkError instead of auto-fixing

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
        strict=strict,
    )


def get_broken_links_summary(doctype=None, limit=100):
    """
    Get a summary of recently auto-cleared broken links from Error Log.

    Useful for administrators to identify patterns of data integrity issues.

    Args:
        doctype: Optional filter by doctype name in error message
        limit: Maximum number of entries to return

    Returns:
        list: Recent link sanitization error log entries
    """
    filters = {"error": "Link Sanitization - Auto-Cleared"}
    if doctype:
        filters["error"] = ["like", f"%{doctype}%"]

    return frappe.get_all(
        "Error Log",
        filters={"method": "Link Sanitization - Auto-Cleared"},
        fields=["name", "error", "creation", "seen"],
        order_by="creation desc",
        limit=limit,
    )
