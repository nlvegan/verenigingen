import frappe
from frappe import _


def get_context(context):
    """Get campaign page context"""
    campaign_name = frappe.form_dict.campaign or frappe.form_dict.name

    if not campaign_name:
        frappe.throw(_("Campaign not specified"), frappe.DoesNotExistError)

    # Get campaign details
    campaign = frappe.get_doc("Donation Campaign", campaign_name)

    # Check if campaign is public
    if not campaign.is_public or not campaign.show_on_website:
        frappe.throw(_("This campaign is not available"), frappe.PermissionError)

    # Check if campaign is active
    if campaign.status not in ["Active", "Completed"]:
        frappe.throw(_("This campaign is not currently active"), frappe.ValidationError)

    context.campaign = campaign
    context.title = campaign.campaign_name

    # Get recent donations if enabled
    if campaign.show_recent_donations:
        context.recent_donations = campaign.get_recent_donations(limit=10)

    # Get top donors if enabled
    if campaign.show_donor_list:
        context.top_donors = campaign.get_top_donors(limit=10)

    # Calculate progress percentage for display
    context.progress_percentage = min(campaign.monetary_progress or 0, 100)
    context.donor_progress_percentage = min(campaign.donor_progress or 0, 100)

    # Parse suggested amounts
    if campaign.suggested_donation_amounts:
        context.suggested_amounts = [
            float(amt.strip()) for amt in campaign.suggested_donation_amounts.split(",")
        ]
    else:
        context.suggested_amounts = [25, 50, 100, 250]

    # Check if ANBI is enabled
    context.anbi_enabled = frappe.db.get_single_value("Verenigingen Settings", "enable_anbi_functionality")

    context.no_cache = 1
    return context
