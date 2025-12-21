"""
Subscription Audit Utility

Identifies orphaned or mismatched Mollie subscriptions that may exist
after member deletions or data inconsistencies.
"""

from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import OperationType, critical_api
from verenigingen.verenigingen_payments.mollie.core.mollie_client import MollieClient


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
            # Mollie-side issues (subscriptions in Mollie we need to address)
            "subscription_no_member_match": [],  # Subscription exists but no Member with that subscription_id
            "subscription_customer_no_member": [],  # Customer exists in Mollie but no Member with that customer_id
            "subscription_for_deleted_member": [],  # Subscription for a Member that was deleted from our database
            "subscription_status_mismatch": [],  # Member exists but status doesn't match Mollie
            # Database-side issues (Members claiming subscriptions that don't exist in Mollie)
            "member_subscription_not_in_mollie": [],  # Member claims active subscription but it's not in Mollie
            "member_incomplete_mollie_data": [],  # Member has subscription_status='active' but missing customer/subscription IDs
        }

    def run_full_audit(self) -> Dict[str, Any]:
        """
        Run comprehensive subscription audit.

        Returns:
            Audit report with all findings and statistics
        """
        # Step 1: Fetch all subscriptions from Mollie
        mollie_subscriptions = self._fetch_all_mollie_subscriptions()

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

        except Exception as e:
            frappe.log_error(f"Failed to fetch Mollie subscriptions: {str(e)}", "Subscription Audit")
            frappe.throw(_("Failed to fetch subscriptions from Mollie: {0}").format(str(e)))

        return all_subscriptions

    def _cross_reference_with_members(self, mollie_subscriptions: List[Dict[str, Any]]):
        """
        Cross-reference Mollie subscriptions with Member records.
        """
        total = len(mollie_subscriptions)

        # Fetch all members with Mollie data upfront to avoid N+1 queries
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

        # Also fetch members with customer IDs (might not have subscription IDs yet)
        members_with_customers = frappe.get_all(
            "Member",
            filters={"mollie_customer_id": ["is", "set"]},
            fields=[
                "name",
                "full_name",
                "status",
                "subscription_status",
                "mollie_customer_id",
                "mollie_subscription_id",
            ],
        )

        # Build lookup dicts
        member_by_sub_id = {
            m.mollie_subscription_id: m for m in members_with_subs if m.mollie_subscription_id
        }
        member_by_customer_id = {
            m.mollie_customer_id: m for m in members_with_customers if m.mollie_customer_id
        }

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
        import json

        for deleted in deleted_members_data:
            # Extract subscription IDs from the JSON data field using proper JSON parsing
            if deleted.data:
                try:
                    data_dict = json.loads(deleted.data)
                    if isinstance(data_dict, dict) and "mollie_subscription_id" in data_dict:
                        sub_id = data_dict["mollie_subscription_id"]
                        if sub_id:  # Only add if not None or empty
                            deleted_member_sub_ids[sub_id] = deleted.name
                except (json.JSONDecodeError, ValueError, TypeError):
                    # Skip invalid JSON data
                    continue

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

            # Extract customer name from Mollie subscription metadata (handle None)
            metadata = subscription.get("metadata") or {}
            customer_name = metadata.get("name", "Unknown")

            # Build base subscription info (handle None for nested gets)
            amount_obj = subscription.get("amount") or {}
            sub_info = {
                "subscription_id": sub_id,
                "customer_id": customer_id,
                "customer_name_mollie": customer_name,
                "status": status,
                "amount": amount_obj.get("value"),
                "interval": subscription.get("interval"),
                "description": subscription.get("description"),
                "next_payment_date": subscription.get("nextPaymentDate"),
            }

            # Look up member by subscription ID
            member_by_sub = member_by_sub_id.get(sub_id)
            # Also look up member by customer ID (might be different member or no subscription ID match)
            member_by_cust = member_by_customer_id.get(customer_id)

            if member_by_sub:
                # Member found by subscription ID - check for status mismatches
                if member_by_sub.subscription_status != status:
                    self.issues["subscription_status_mismatch"].append(
                        {
                            **sub_info,
                            "member_id": member_by_sub.name,
                            "member_name_db": member_by_sub.full_name,
                            "member_status": member_by_sub.status,
                            "member_subscription_status": member_by_sub.subscription_status,
                            "mollie_status": status,
                        }
                    )

                # Check if customer_id matches
                if member_by_sub.mollie_customer_id != customer_id:
                    self.issues["subscription_status_mismatch"].append(
                        {
                            **sub_info,
                            "member_id": member_by_sub.name,
                            "member_name_db": member_by_sub.full_name,
                            "issue": "customer_id_mismatch",
                            "member_customer_id": member_by_sub.mollie_customer_id,
                        }
                    )
            else:
                # No member found by subscription ID - check customer ID first (live members take priority)
                if member_by_cust:
                    # Customer ID exists in our database but subscription ID doesn't match
                    self.issues["subscription_customer_no_member"].append(
                        {
                            **sub_info,
                            "member_id": member_by_cust.name,
                            "member_name_db": member_by_cust.full_name,
                            "member_status": member_by_cust.status,
                            "member_subscription_id": member_by_cust.mollie_subscription_id,
                            "note": "Customer ID matches a Member, but subscription ID doesn't match our records",
                        }
                    )
                else:
                    # No live member found - check if this was a deleted member
                    deleted_member_name = deleted_member_sub_ids.get(sub_id)

                    if deleted_member_name:
                        # Subscription belongs to deleted member
                        self.issues["subscription_for_deleted_member"].append(
                            {
                                **sub_info,
                                "deleted_member_id": deleted_member_name,
                                "note": "Member was deleted from database but Mollie subscription still active",
                            }
                        )
                    else:
                        # No member found by either subscription ID or customer ID
                        self.issues["subscription_no_member_match"].append(
                            {
                                **sub_info,
                                "note": "No Member found with this subscription ID or customer ID",
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
                self.issues["member_incomplete_mollie_data"].append(
                    {
                        "member_id": member.name,
                        "member_name_db": member.full_name,
                        "subscription_status": member.subscription_status,
                        "mollie_customer_id": member.mollie_customer_id or "Missing",
                        "mollie_subscription_id": member.mollie_subscription_id or "Missing",
                        "note": "Member claims active subscription but has incomplete Mollie data",
                    }
                )
            elif member.mollie_subscription_id not in mollie_subscription_ids:
                # Subscription ID not found in Mollie's list
                self.issues["member_subscription_not_in_mollie"].append(
                    {
                        "member_id": member.name,
                        "member_name_db": member.full_name,
                        "subscription_status": member.subscription_status,
                        "mollie_subscription_id": member.mollie_subscription_id,
                        "mollie_customer_id": member.mollie_customer_id,
                        "note": "Member's subscription ID not found in Mollie (may have been cancelled/expired)",
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
                # Mollie-side issues
                "subscription_no_member_match": len(self.issues["subscription_no_member_match"]),
                "subscription_customer_no_member": len(self.issues["subscription_customer_no_member"]),
                "subscription_for_deleted_member": len(self.issues["subscription_for_deleted_member"]),
                "subscription_status_mismatch": len(self.issues["subscription_status_mismatch"]),
                # Database-side issues
                "member_subscription_not_in_mollie": len(self.issues["member_subscription_not_in_mollie"]),
                "member_incomplete_mollie_data": len(self.issues["member_incomplete_mollie_data"]),
            },
            "details": self.issues,
            "audit_timestamp": frappe.utils.now(),
            "test_mode": self.client.test_mode,
        }

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
