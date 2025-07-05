import frappe
from erpnext.accounts.party import validate_due_date as original_validate_due_date


def validate_due_date_override(posting_date, due_date, bill_date=None, template_name=None, doctype=None):
    """Override of validate_due_date to allow due dates before posting date for Sales Invoice."""
    # For Sales Invoice, allow due date to be before posting date
    if doctype == "Sales Invoice":
        # Log for debugging
        frappe.logger().info(f"Sales Invoice: Allowing due date {due_date} (posting date: {posting_date})")
        # Skip validation - just return without error
        return

    # For other doctypes, use the original validation
    original_validate_due_date(posting_date, due_date, bill_date, template_name, doctype)


def custom_validate(doc, method):
    """Custom validation for Sales Invoice - not needed with monkey patch approach."""


def after_validate(doc, method):
    """After validation hook - not needed with monkey patch approach."""


# Monkey patch the validate_due_date function when this module is imported
def apply_patches():
    """Apply monkey patches to core functions."""
    import erpnext.accounts.party

    erpnext.accounts.party.validate_due_date = validate_due_date_override
    frappe.logger().info("Applied validate_due_date override for Sales Invoice")


# Apply patches when module is imported
apply_patches()
