import frappe
from frappe import _


def setup_subscription_override():
    """Fix the Subscription doctype to allow updating date fields after submission"""
    frappe.logger().info("Setting up subscription date fields to be updatable after submission")

    try:
        # Get the Subscription doctype
        subscription_doctype = frappe.get_doc("DocType", "Subscription")

        # Get the fields we need to modify
        start_date_field = None
        end_date_field = None

        for field in subscription_doctype.fields:
            if field.fieldname == "current_invoice_start":
                start_date_field = field
            elif field.fieldname == "current_invoice_end":
                end_date_field = field

        # Set allow_on_submit = 1 for these fields
        modified = False

        if start_date_field and not start_date_field.allow_on_submit:
            start_date_field.allow_on_submit = 1
            modified = True
            frappe.logger().info("Set current_invoice_start to allow_on_submit=1")

        if end_date_field and not end_date_field.allow_on_submit:
            end_date_field.allow_on_submit = 1
            modified = True
            frappe.logger().info("Set current_invoice_end to allow_on_submit=1")

        # Save the doctype if we modified it
        if modified:
            subscription_doctype.save()
            frappe.clear_cache(doctype="Subscription")
            frappe.logger().info(
                "Successfully updated Subscription doctype to allow date updates after submission"
            )
            return True
        else:
            frappe.logger().info("Subscription doctype already allows date updates after submission")
            return True

    except Exception as e:
        frappe.log_error(f"Error updating Subscription doctype: {str(e)}", "Subscription Override Error")
        return False


def update_hooks():
    """
    Add our custom hooks to the app's hooks.py
    This is for documentation only - you'll need to manually add these to hooks.py
    """
    hooks_to_add = """
# Subscription handling
on_app_init = ["verenigingen.verenigingen.subscription_override.setup_subscription_override"]

# Schedule subscription processing
scheduler_events = {
    "daily": [
        # ... your existing daily jobs ...
        "verenigingen.verenigingen.subscription_handler.process_all_subscriptions"
    ]
}
"""
    return hooks_to_add


@frappe.whitelist()
def manual_override_setup():
    """
    Manually trigger the subscription override setup
    Useful for testing or if the app_init hook doesn't work
    """
    result = setup_subscription_override()
    if result:
        frappe.msgprint(_("Subscription override successfully set up"))
    else:
        frappe.msgprint(_("Failed to set up subscription override. Check error logs."))

    return result
