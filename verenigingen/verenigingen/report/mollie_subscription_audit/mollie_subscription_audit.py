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
    report = auditor.run_full_audit()

    data = []

    # Add Mollie-side issues: subscriptions without member match
    for issue in report["details"]["subscription_no_member_match"]:
        data.append(
            {
                "issue_type": "🔴 No Member Match",
                "subscription_id": issue["subscription_id"],
                "customer_id": issue["customer_id"],
                "member_id": None,
                "member_name": issue.get("customer_name_mollie"),
                "status": issue["status"],
                "member_status": None,
                "amount": float(issue["amount"]) if issue.get("amount") else 0.0,
                "interval": issue.get("interval"),
                "next_payment_date": issue.get("next_payment_date"),
                "description": issue.get("description"),
                "details": issue.get("note", "No Member found with this subscription ID or customer ID"),
            }
        )

    # Add Mollie-side issues: customer exists but subscription mismatch
    for issue in report["details"]["subscription_customer_no_member"]:
        data.append(
            {
                "issue_type": "🟠 Customer but Wrong Subscription",
                "subscription_id": issue["subscription_id"],
                "customer_id": issue["customer_id"],
                "member_id": issue.get("member_id"),
                "member_name": issue.get("member_name_db"),
                "status": issue["status"],
                "member_status": issue.get("member_status"),
                "amount": float(issue["amount"]) if issue.get("amount") else 0.0,
                "interval": issue.get("interval"),
                "next_payment_date": issue.get("next_payment_date"),
                "description": issue.get("description"),
                "details": issue.get("note", "Customer ID matches but subscription ID doesn't"),
            }
        )

    # Add Mollie-side issues: subscriptions for deleted members
    for issue in report["details"]["subscription_for_deleted_member"]:
        data.append(
            {
                "issue_type": "⚫ Deleted Member",
                "subscription_id": issue["subscription_id"],
                "customer_id": issue["customer_id"],
                "member_id": issue.get("deleted_member_id"),
                "member_name": issue.get("customer_name_mollie"),
                "status": issue["status"],
                "member_status": None,
                "amount": float(issue["amount"]) if issue.get("amount") else 0.0,
                "interval": issue.get("interval"),
                "next_payment_date": issue.get("next_payment_date"),
                "description": issue.get("description"),
                "details": issue.get("note", "Member was deleted but subscription still active"),
            }
        )

    # Add Mollie-side issues: status mismatches
    for issue in report["details"]["subscription_status_mismatch"]:
        if issue.get("issue") == "customer_id_mismatch":
            details = f"Customer ID mismatch - Mollie: {issue.get('customer_id')}, Member: {issue.get('member_customer_id')}"
        else:
            details = f"Status mismatch - Mollie: {issue.get('mollie_status')}, Member: {issue.get('member_subscription_status')}"

        data.append(
            {
                "issue_type": "🟡 Status Mismatch",
                "subscription_id": issue.get("subscription_id"),
                "customer_id": issue.get("customer_id"),
                "member_id": issue.get("member_id"),
                "member_name": issue.get("member_name_db"),
                "status": issue.get("mollie_status") or issue.get("status"),
                "member_status": issue.get("member_subscription_status"),
                "amount": float(issue["amount"]) if issue.get("amount") else 0.0,
                "interval": issue.get("interval"),
                "next_payment_date": issue.get("next_payment_date"),
                "description": issue.get("description"),
                "details": details,
            }
        )

    # Add Database-side issues: members claiming subscriptions not in Mollie
    for issue in report["details"]["member_subscription_not_in_mollie"]:
        data.append(
            {
                "issue_type": "🔵 Subscription Not in Mollie",
                "subscription_id": issue.get("mollie_subscription_id"),
                "customer_id": issue.get("mollie_customer_id"),
                "member_id": issue.get("member_id"),
                "member_name": issue.get("member_name_db"),
                "status": None,
                "member_status": issue.get("subscription_status"),
                "amount": None,
                "interval": None,
                "next_payment_date": None,
                "description": None,
                "details": issue.get("note", "Member's subscription ID not found in Mollie"),
            }
        )

    # Add Database-side issues: members with incomplete Mollie data
    for issue in report["details"]["member_incomplete_mollie_data"]:
        data.append(
            {
                "issue_type": "🔷 Incomplete Mollie Data",
                "subscription_id": issue.get("mollie_subscription_id"),
                "customer_id": issue.get("mollie_customer_id"),
                "member_id": issue.get("member_id"),
                "member_name": issue.get("member_name_db"),
                "status": None,
                "member_status": issue.get("subscription_status"),
                "amount": None,
                "interval": None,
                "next_payment_date": None,
                "description": None,
                "details": issue.get("note", "Member has incomplete Mollie data"),
            }
        )

    # Add summary row at the top
    summary_text = (
        f"Total: {report['summary']['total_mollie_subscriptions']} subscriptions | "
        f"Active: {report['summary']['active_mollie_subscriptions']} | "
        f"No Match: {report['summary']['subscription_no_member_match']} | "
        f"Customer Wrong Sub: {report['summary']['subscription_customer_no_member']} | "
        f"Deleted Members: {report['summary']['subscription_for_deleted_member']} | "
        f"Status Mismatches: {report['summary']['subscription_status_mismatch']} | "
        f"Not in Mollie: {report['summary']['member_subscription_not_in_mollie']} | "
        f"Incomplete Data: {report['summary']['member_incomplete_mollie_data']} | "
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
