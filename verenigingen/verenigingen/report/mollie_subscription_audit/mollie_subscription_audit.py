# Copyright (c) 2025, Partij voor de Dieren and contributors
# For license information, please see license.txt

import frappe
from frappe import _

from verenigingen.utils.admin_utilities.subscription_audit import SubscriptionAudit


def execute(filters=None):
    """
    Generate Mollie Subscription Audit report.

    Identifies:
    - Orphaned subscriptions (active in Mollie but no corresponding Member)
    - Subscriptions for deleted members
    - Status mismatches between Mollie and Member records
    - Members claiming subscriptions that don't exist in Mollie
    """
    columns = get_columns()
    data = get_data(filters)

    return columns, data


def get_columns():
    """Define report columns."""
    return [
        {"fieldname": "issue_type", "label": _("Issue Type"), "fieldtype": "Data", "width": 180},
        {"fieldname": "subscription_id", "label": _("Subscription ID"), "fieldtype": "Data", "width": 150},
        {"fieldname": "customer_id", "label": _("Customer ID"), "fieldtype": "Data", "width": 150},
        {
            "fieldname": "member_id",
            "label": _("Member ID"),
            "fieldtype": "Link",
            "options": "Member",
            "width": 150,
        },
        {"fieldname": "member_name", "label": _("Member Name"), "fieldtype": "Data", "width": 200},
        {"fieldname": "status", "label": _("Mollie Status"), "fieldtype": "Data", "width": 100},
        {"fieldname": "member_status", "label": _("Member Status"), "fieldtype": "Data", "width": 120},
        {"fieldname": "amount", "label": _("Amount"), "fieldtype": "Currency", "width": 100},
        {"fieldname": "interval", "label": _("Interval"), "fieldtype": "Data", "width": 100},
        {"fieldname": "next_payment_date", "label": _("Next Payment"), "fieldtype": "Date", "width": 120},
        {"fieldname": "description", "label": _("Description"), "fieldtype": "Data", "width": 250},
        {"fieldname": "details", "label": _("Details"), "fieldtype": "Text", "width": 200},
    ]


def get_data(filters=None):
    """Fetch audit data."""

    # Show progress message
    frappe.publish_realtime(
        "msgprint",
        "Running subscription audit... Fetching data from Mollie API (this may take 1-2 minutes)...",
        user=frappe.session.user,
    )

    # Commit before starting long operation to avoid timeout issues
    frappe.db.commit()

    # Run the audit
    auditor = SubscriptionAudit()
    report = auditor.run_full_audit(auto_cancel_orphans=False)

    data = []

    # Add orphaned subscriptions
    for orphan in report["details"]["orphaned_subscriptions"]:
        data.append(
            {
                "issue_type": "🔴 Orphaned Subscription",
                "subscription_id": orphan["subscription_id"],
                "customer_id": orphan["customer_id"],
                "member_id": None,
                "member_name": None,
                "status": orphan["status"],
                "member_status": None,
                "amount": float(orphan["amount"]) if orphan.get("amount") else 0.0,
                "interval": orphan.get("interval"),
                "next_payment_date": orphan.get("next_payment_date"),
                "description": orphan.get("description"),
                "details": "Active in Mollie but no corresponding Member record found",
            }
        )

    # Add deleted member subscriptions
    for deleted in report["details"]["deleted_member_subscriptions"]:
        data.append(
            {
                "issue_type": "🟠 Deleted Member Subscription",
                "subscription_id": deleted["subscription_id"],
                "customer_id": deleted["customer_id"],
                "member_id": deleted.get("deleted_member"),
                "member_name": None,
                "status": deleted["status"],
                "member_status": None,
                "amount": float(deleted["amount"]) if deleted.get("amount") else 0.0,
                "interval": deleted.get("interval"),
                "next_payment_date": deleted.get("next_payment_date"),
                "description": deleted.get("description"),
                "details": f"Member was deleted: {deleted.get('deleted_member')}",
            }
        )

    # Add status mismatches
    for mismatch in report["details"]["status_mismatches"]:
        if mismatch.get("issue") == "customer_id_mismatch":
            details = f"Customer ID mismatch - Mollie: {mismatch['mollie_customer_id']}, Member: {mismatch['member_customer_id']}"
        else:
            details = f"Status mismatch - Mollie: {mismatch.get('mollie_status')}, Member: {mismatch.get('member_status')}"

        data.append(
            {
                "issue_type": "🟡 Status Mismatch",
                "subscription_id": mismatch.get("subscription_id"),
                "customer_id": mismatch.get("customer_id"),
                "member_id": mismatch.get("member_id"),
                "member_name": mismatch.get("member_name"),
                "status": mismatch.get("mollie_status"),
                "member_status": mismatch.get("member_status") or mismatch.get("member_overall_status"),
                "amount": None,
                "interval": None,
                "next_payment_date": None,
                "description": None,
                "details": details,
            }
        )

    # Add missing Mollie data
    for missing in report["details"]["missing_mollie_data"]:
        data.append(
            {
                "issue_type": "🔵 Missing Mollie Data",
                "subscription_id": missing.get("mollie_subscription_id"),
                "customer_id": missing.get("mollie_customer_id"),
                "member_id": missing.get("member_id"),
                "member_name": missing.get("member_name"),
                "status": None,
                "member_status": missing.get("subscription_status"),
                "amount": None,
                "interval": None,
                "next_payment_date": None,
                "description": None,
                "details": f"Issue: {missing.get('issue')} - {missing.get('error', 'Subscription not found in Mollie')}",
            }
        )

    # Add summary row at the top
    summary_text = (
        f"Total: {report['summary']['total_mollie_subscriptions']} subscriptions | "
        f"Active: {report['summary']['active_mollie_subscriptions']} | "
        f"Orphaned: {report['summary']['orphaned_subscriptions']} | "
        f"Deleted Member: {report['summary']['deleted_member_subscriptions']} | "
        f"Mismatches: {report['summary']['status_mismatches']} | "
        f"Missing Data: {report['summary']['missing_mollie_data']} | "
        f"Test Mode: {'Yes' if report['test_mode'] else 'No'}"
    )

    data.insert(
        0,
        {
            "issue_type": "📊 SUMMARY",
            "subscription_id": None,
            "customer_id": None,
            "member_id": None,
            "member_name": None,
            "status": None,
            "member_status": None,
            "amount": None,
            "interval": None,
            "next_payment_date": None,
            "description": None,
            "details": summary_text,
        },
    )

    # Save detailed report to file
    import json

    report_path = frappe.get_site_path("private", "files", "subscription_audit_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Show completion message
    frappe.publish_realtime(
        "msgprint",
        f"Audit complete! Found {len(data)-1} issues. Detailed report saved to private/files/subscription_audit_report.json",
        user=frappe.session.user,
    )

    return data
