import frappe

from verenigingen.utils.error_handling import validate_admin_access


def get_context(context):
    context.no_cache = 1
    context.show_sidebar = False

    # Modernized permission check
    validate_admin_access("You do not have permission to fix account types")

    return context
