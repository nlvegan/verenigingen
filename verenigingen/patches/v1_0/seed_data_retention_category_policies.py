import frappe


def execute():
    """Seed Data Retention Settings with the 9 default category policies (once)."""
    if not frappe.db.exists("DocType", "Data Retention Settings"):
        return
    settings = frappe.get_single("Data Retention Settings")
    if settings.get("category_policies"):
        return  # already has rows; do not clobber admin edits
    settings.reset_category_policies()
