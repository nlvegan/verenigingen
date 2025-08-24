# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

import frappe


def execute():
    """Add membership analytics doctypes and permissions"""

    # Create default Brand Settings if not exists (for analytics CSS)
    if not frappe.db.exists("Brand Settings", "Default"):
        from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
            create_default_brand_settings,
        )

        create_default_brand_settings()

    # Add permissions for analytics page
    if not frappe.db.exists("Page", "membership-analytics"):
        # Page should be created through JSON files
        pass
    else:
        # Set page permissions
        page = frappe.get_doc("Page", "membership-analytics")

        # Clear existing permissions
        page.roles = []

        # Add roles
        for role in [
            "Verenigingen Administrator",
            "Verenigingen Manager",
            "Verenigingen National Board Member",
        ]:
            page.append("roles", {"role": role})

        page.flags.ignore_permissions = True
        page.save()

    # Create initial snapshot
    try:
        from verenigingen.verenigingen.doctype.membership_analytics_snapshot.membership_analytics_snapshot import (
            create_snapshot,
        )

        create_snapshot("Manual", frappe.utils.today())
    except Exception as e:
        # Snapshot creation might fail if no data exists
        frappe.log_error(f"Could not create initial analytics snapshot: {str(e)}")

    # Create default alert rules
    create_default_alert_rules()

    frappe.db.commit()


def create_default_alert_rules():
    """Create some default alert rules as examples"""
    default_rules = [
        {
            "rule_name": "High Churn Rate Alert",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Churn Rate",
            "condition": "Greater Than",
            "threshold_value": 15,
            "check_frequency": "Daily",
            "send_email": 1,
            "send_system_notification": 1,
            "alert_message_template": "Alert: Monthly churn rate has reached {value:.1f}% (threshold: {threshold}%)",
        },
        {
            "rule_name": "Low Growth Alert",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Growth Rate",
            "condition": "Less Than",
            "threshold_value": 2,
            "check_frequency": "Weekly",
            "send_email": 1,
            "send_system_notification": 1,
            "alert_message_template": "Alert: Growth rate has dropped to {value:.1f}% (threshold: {threshold}%)",
        },
        {
            "rule_name": "Revenue Drop Alert",
            "is_active": 1,
            "alert_type": "Trend",
            "metric": "Revenue",
            "condition": "Decreases By",
            "threshold_value": 10,
            "check_frequency": "Daily",
            "send_email": 1,
            "send_system_notification": 1,
            "alert_message_template": "Alert: Revenue has decreased by {change} compared to previous period",
        },
        {
            "rule_name": "High Payment Failure Rate",
            "is_active": 1,
            "alert_type": "Threshold",
            "metric": "Payment Failure Rate",
            "condition": "Greater Than",
            "threshold_value": 10,
            "check_frequency": "Daily",
            "send_email": 1,
            "send_system_notification": 1,
            "alert_message_template": "Alert: Payment failure rate is {value:.1f}% (threshold: {threshold}%)",
        },
    ]

    for rule_data in default_rules:
        if not frappe.db.exists("Analytics Alert Rule", rule_data["rule_name"]):
            try:
                rule = frappe.get_doc({"doctype": "Analytics Alert Rule", **rule_data})

                # Add default recipients (administrators)
                admins = frappe.get_all(
                    "User",
                    filters={"enabled": 1},
                    or_filters=[
                        ["User Role", "role", "=", "Verenigingen Administrator"],
                        ["User Role", "role", "=", "Verenigingen National Board Member"],
                    ],
                    fields=["name"],
                    distinct=True,
                    limit=5,
                )

                for admin in admins:
                    rule.append("alert_recipients", {"recipient_type": "User", "recipient": admin.name})

                rule.insert(ignore_permissions=True)
            except Exception as e:
                frappe.log_error(f"Could not create alert rule {rule_data['rule_name']}: {str(e)}")
