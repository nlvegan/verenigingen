"""
Subscription Audit Utility

Identifies orphaned or mismatched Mollie subscriptions that may exist
after member deletions or data inconsistencies.
"""

from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.integrations.mollie.core.mollie_client import MollieClient
from verenigingen.utils.security.api_security_framework import OperationType, critical_api


class SubscriptionAudit:
    """
    Audit tool for finding subscription data integrity issues.

    Identifies:
    - Active Mollie subscriptions without corresponding Member records
    - Members with subscription_status='active' but no Mollie subscription
    - Mismatches between Mollie data and Member records
    """

    def __init__(self):
        self.client = MollieClient()
        self.issues = {
            "orphaned_subscriptions": [],  # Mollie subscriptions without valid members
            "missing_mollie_data": [],  # Members claiming active subscription but no Mollie record
            "status_mismatches": [],  # Status conflicts between Mollie and Member
            "deleted_member_subscriptions": [],  # Subscriptions for deleted members
        }

    def run_full_audit(self) -> Dict[str, Any]:
        """
        Run comprehensive subscription audit.

        Returns:
            Audit report with all findings and statistics
        """
        frappe.msgprint(_("Starting subscription audit..."))

        # Step 1: Fetch all subscriptions from Mollie
        mollie_subscriptions = self._fetch_all_mollie_subscriptions()
        frappe.msgprint(_("Found {0} total subscriptions in Mollie").format(len(mollie_subscriptions)))

        # Step 2: Cross-reference with Member records
        self._cross_reference_with_members(mollie_subscriptions)

        # Step 3: Check for members claiming subscriptions that don't exist
        # Pass the subscription data we already have to avoid redundant API calls
        self._find_members_with_invalid_subscriptions(mollie_subscriptions)

        # Generate report
        report = self._generate_report(mollie_subscriptions)

        return report

    def _fetch_all_mollie_subscriptions(self) -> List[Dict[str, Any]]:
        """
        Fetch all subscriptions from Mollie using the global subscriptions endpoint.

        Note: The Mollie Python SDK doesn't have a direct subscriptions.list() method
        at the API root level, so we use direct REST API call.
        """
        all_subscriptions = []
        next_url = None
        page_count = 0

        try:
            # Use direct API call to list all subscriptions
            endpoint = "subscriptions?limit=250"  # Fetch 250 at a time for efficiency

            while True:
                page_count += 1

                # Publish progress
                frappe.publish_realtime(
                    "msgprint", f"Fetching page {page_count} from Mollie API...", user=frappe.session.user
                )

                if next_url:
                    # Pagination: use the next URL from previous response
                    response = self.client._make_request("GET", next_url.replace(self.client.BASE_URL, ""))
                else:
                    response = self.client._make_request("GET", endpoint)

                # Extract subscriptions from response
                subscriptions = response.get("_embedded", {}).get("subscriptions", [])
                all_subscriptions.extend(subscriptions)

                frappe.publish_realtime(
                    "msgprint",
                    f"Retrieved {len(all_subscriptions)} subscriptions so far...",
                    user=frappe.session.user,
                )

                # Check for pagination
                next_link = response.get("_links", {}).get("next", {})
                if next_link and next_link.get("href"):
                    next_url = next_link["href"]
                else:
                    break

            frappe.msgprint(
                _("Retrieved {0} total subscriptions from Mollie API").format(len(all_subscriptions))
            )

        except Exception as e:
            frappe.log_error(f"Failed to fetch Mollie subscriptions: {str(e)}", "Subscription Audit")
            frappe.throw(_("Failed to fetch subscriptions from Mollie: {0}").format(str(e)))

        return all_subscriptions

    def _cross_reference_with_members(self, mollie_subscriptions: List[Dict[str, Any]]):
        """
        Cross-reference Mollie subscriptions with Member records.
        """
        total = len(mollie_subscriptions)

        # Fetch all members with subscription IDs upfront to avoid N+1 queries
        frappe.publish_realtime("msgprint", "Loading member subscription data...", user=frappe.session.user)

        members_with_subs = frappe.get_all(
            "Member",
            filters={"mollie_subscription_id": ["is", "set"]},
            fields=[
                "name",
                "full_name",
                "status",
                "subscription_status",
                "mollie_customer_id",
                "mollie_subscription_id",
            ],
        )

        # Build lookup dict: subscription_id -> member data
        member_by_sub_id = {m.mollie_subscription_id: m for m in members_with_subs}

        # Fetch all deleted members upfront to avoid N+1 LIKE queries
        deleted_members_data = frappe.db.sql(
            """
            SELECT name, data
            FROM `tabDeleted Document`
            WHERE deleted_doctype = 'Member'
            """,
            as_dict=True,
        )

        # Build a set of subscription IDs from deleted members for fast lookup
        deleted_member_sub_ids = {}
        for deleted in deleted_members_data:
            # Extract subscription IDs from the JSON data field
            if deleted.data and "mollie_subscription_id" in deleted.data:
                # Simple string search for subscription ID pattern (sub_xxxx)
                import re

                sub_matches = re.findall(r"sub_[a-zA-Z0-9]+", deleted.data)
                for sub_id in sub_matches:
                    deleted_member_sub_ids[sub_id] = deleted.name

        frappe.publish_realtime(
            "msgprint",
            f"Loaded {len(member_by_sub_id)} member subscriptions and {len(deleted_member_sub_ids)} deleted member subscriptions. Cross-referencing...",
            user=frappe.session.user,
        )

        for idx, subscription in enumerate(mollie_subscriptions):
            # Publish progress every 50 subscriptions (less frequent since it's much faster now)
            if idx % 50 == 0:
                frappe.publish_realtime(
                    "msgprint", f"Cross-referencing subscriptions: {idx}/{total}", user=frappe.session.user
                )

            sub_id = subscription.get("id")
            customer_id = subscription.get("customerId")
            status = subscription.get("status")

            # Only audit active/pending subscriptions
            if status not in ["active", "pending"]:
                continue

            # Look up member by subscription ID using in-memory dict (O(1) instead of database query)
            member = member_by_sub_id.get(sub_id)

            if not member:
                # No member found - this is an orphaned subscription
                # Check if there's a deleted member using our pre-built lookup dict
                deleted_member_name = deleted_member_sub_ids.get(sub_id)

                if deleted_member_name:
                    self.issues["deleted_member_subscriptions"].append(
                        {
                            "subscription_id": sub_id,
                            "customer_id": customer_id,
                            "status": status,
                            "deleted_member": deleted_member_name,
                            "amount": subscription.get("amount", {}).get("value"),
                            "interval": subscription.get("interval"),
                            "description": subscription.get("description"),
                            "next_payment_date": subscription.get("nextPaymentDate"),
                        }
                    )
                else:
                    self.issues["orphaned_subscriptions"].append(
                        {
                            "subscription_id": sub_id,
                            "customer_id": customer_id,
                            "status": status,
                            "amount": subscription.get("amount", {}).get("value"),
                            "interval": subscription.get("interval"),
                            "description": subscription.get("description"),
                            "next_payment_date": subscription.get("nextPaymentDate"),
                        }
                    )
            else:
                # Member found - check for status mismatches
                if member.subscription_status != status:
                    self.issues["status_mismatches"].append(
                        {
                            "member_id": member.name,
                            "member_name": member.full_name,
                            "subscription_id": sub_id,
                            "mollie_status": status,
                            "member_status": member.subscription_status,
                            "member_overall_status": member.status,
                        }
                    )

                # Check if customer_id matches
                if member.mollie_customer_id != customer_id:
                    self.issues["status_mismatches"].append(
                        {
                            "member_id": member.name,
                            "member_name": member.full_name,
                            "subscription_id": sub_id,
                            "issue": "customer_id_mismatch",
                            "mollie_customer_id": customer_id,
                            "member_customer_id": member.mollie_customer_id,
                        }
                    )

    def _find_members_with_invalid_subscriptions(self, mollie_subscriptions: List[Dict[str, Any]]):
        """
        Find members claiming to have active subscriptions that don't exist in Mollie.
        Uses the already-fetched subscription data instead of making new API calls.
        """
        # Build a set of all subscription IDs we found in Mollie for fast lookup
        mollie_subscription_ids = {sub.get("id") for sub in mollie_subscriptions}

        frappe.publish_realtime(
            "msgprint",
            f"Checking member subscriptions against {len(mollie_subscription_ids)} Mollie subscriptions...",
            user=frappe.session.user,
        )

        # Find members with subscription_status = 'active' but no valid Mollie subscription
        members_with_subscriptions = frappe.get_all(
            "Member",
            filters={
                "subscription_status": ["in", ["active", "pending"]],
                "mollie_subscription_id": ["is", "set"],
            },
            fields=[
                "name",
                "full_name",
                "mollie_subscription_id",
                "mollie_customer_id",
                "subscription_status",
            ],
        )

        frappe.publish_realtime(
            "msgprint",
            f"Validating {len(members_with_subscriptions)} member subscriptions...",
            user=frappe.session.user,
        )

        for member in members_with_subscriptions:
            if not member.mollie_customer_id or not member.mollie_subscription_id:
                # Missing customer or subscription ID
                self.issues["missing_mollie_data"].append(
                    {
                        "member_id": member.name,
                        "member_name": member.full_name,
                        "issue": "incomplete_mollie_data",
                        "subscription_status": member.subscription_status,
                        "mollie_customer_id": member.mollie_customer_id,
                        "mollie_subscription_id": member.mollie_subscription_id,
                    }
                )
            elif member.mollie_subscription_id not in mollie_subscription_ids:
                # Subscription ID not found in Mollie's list
                self.issues["missing_mollie_data"].append(
                    {
                        "member_id": member.name,
                        "member_name": member.full_name,
                        "issue": "subscription_not_found_in_mollie",
                        "subscription_status": member.subscription_status,
                        "mollie_subscription_id": member.mollie_subscription_id,
                        "mollie_customer_id": member.mollie_customer_id,
                        "error": "Subscription not found in Mollie's active subscriptions",
                    }
                )

    def _generate_report(self, mollie_subscriptions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Generate comprehensive audit report.
        """
        total_mollie = len(mollie_subscriptions)
        active_mollie = len([s for s in mollie_subscriptions if s.get("status") == "active"])

        report = {
            "summary": {
                "total_mollie_subscriptions": total_mollie,
                "active_mollie_subscriptions": active_mollie,
                "orphaned_subscriptions": len(self.issues["orphaned_subscriptions"]),
                "deleted_member_subscriptions": len(self.issues["deleted_member_subscriptions"]),
                "status_mismatches": len(self.issues["status_mismatches"]),
                "missing_mollie_data": len(self.issues["missing_mollie_data"]),
            },
            "details": self.issues,
            "audit_timestamp": frappe.utils.now(),
            "test_mode": self.client.test_mode,
        }

        # Print summary
        frappe.msgprint(
            f"""
            <h3>Subscription Audit Summary</h3>
            <ul>
                <li>Total Mollie Subscriptions: {total_mollie}</li>
                <li>Active Mollie Subscriptions: {active_mollie}</li>
                <li><strong>Orphaned Subscriptions: {report['summary']['orphaned_subscriptions']}</strong></li>
                <li><strong>Deleted Member Subscriptions: {report['summary']['deleted_member_subscriptions']}</strong></li>
                <li>Status Mismatches: {report['summary']['status_mismatches']}</li>
                <li>Missing Mollie Data: {report['summary']['missing_mollie_data']}</li>
            </ul>
        """
        )

        return report


@frappe.whitelist()
@critical_api(operation_type=OperationType.FINANCIAL)
def run_subscription_audit():
    """
    Whitelisted method to run subscription audit from Desk.

    Security: Requires Member read, Mollie Settings read, and Payment Entry read permissions.

    Usage:
        In Desk Console:
        frappe.call('verenigingen.utils.admin_utilities.subscription_audit.run_subscription_audit')
    """
    auditor = SubscriptionAudit()
    report = auditor.run_full_audit()

    # Save report to file for review
    report_path = frappe.get_site_path("private", "files", "subscription_audit_report.json")
    import json

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    frappe.msgprint(_("Audit complete. Report saved to: {0}").format(report_path))

    return report
