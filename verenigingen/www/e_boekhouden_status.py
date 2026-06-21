import frappe
from frappe import _


def get_context(context):
    """Get context for simple dashboard page"""
    context.title = _("E-Boekhouden Migration Status")

    # Check permissions
    if frappe.session.user == "Guest":
        frappe.throw(_("Please login to view dashboard"))

    # Get data using direct API call to avoid import issues
    try:
        dashboard_data = frappe.call("verenigingen.e_boekhouden.utils.eboekhouden_api.get_dashboard_data_api")

        # get_dashboard_data() returns the data keys directly (connection_status,
        # migration_stats, ...) and only carries an "error" key on failure — it
        # never returns "success". The old `if dashboard_data.get("success")`
        # was therefore always falsy, so the page always showed "Unknown error"
        # and dropped the real stats. Treat absence of "error" as success.
        if "error" not in dashboard_data:
            context.update(dashboard_data)
        else:
            context.error = dashboard_data.get("error", "Unknown error")

    except Exception as e:
        frappe.log_error(f"Dashboard error: {str(e)}")
        context.error = str(e)

    # Add recent migrations
    try:
        context.recent_migrations = frappe.get_all(
            "E-Boekhouden Migration",
            fields=["name", "migration_name", "migration_status", "progress_percentage", "start_time"],
            order_by="start_time desc",
            limit=5,
        )
    except Exception as e:
        context.recent_migrations = []
        frappe.log_error(f"Error getting recent migrations: {str(e)}")
