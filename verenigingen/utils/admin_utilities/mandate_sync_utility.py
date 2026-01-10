"""
Mandate Sync Utility

Fetches mandate information from Mollie for all members with customer IDs
and populates missing mollie_mandate_id fields.
"""

from typing import Any, Dict, List

import frappe
from frappe import _

from verenigingen.utils.security.api_security_framework import critical_api
from verenigingen.verenigingen_payments.mollie.core.client import MollieClient


class MandateSyncUtility:
    """
    Utility for syncing mandate data from Mollie to Member records.

    Finds members with mollie_customer_id but missing mollie_mandate_id,
    fetches mandate data from Mollie, and populates the field.
    """

    def __init__(self):
        self.client = MollieClient()
        self.results = {
            "updated": [],  # Members where we set mandate_id
            "already_set": [],  # Members who already had mandate_id
            "no_mandates": [],  # Members with no mandates in Mollie
            "multiple_mandates": [],  # Members with multiple mandates (needs manual review)
            "invalid_mandates": [],  # Members with only invalid/pending mandates
            "errors": [],  # Errors during processing
        }

    def run_sync(self, dry_run=False) -> Dict[str, Any]:
        """
        Run mandate sync for all members with Mollie customer IDs.

        Args:
            dry_run: If True, don't actually update records, just report what would be done

        Returns:
            dict: Sync results with statistics and details
        """
        frappe.msgprint(_("Starting mandate sync..."))

        # Fetch all members with Mollie customer IDs
        members = frappe.get_all(
            "Member",
            filters={"mollie_customer_id": ["is", "set"]},
            fields=[
                "name",
                "full_name",
                "mollie_customer_id",
                "mollie_mandate_id",
                "subscription_status",
            ],
        )

        frappe.msgprint(_("Found {0} members with Mollie customer IDs").format(len(members)))

        total = len(members)
        for idx, member in enumerate(members):
            if idx % 50 == 0:
                frappe.publish_realtime(
                    "msgprint",
                    f"Processing member {idx + 1}/{total}...",
                    user=frappe.session.user,
                )

            self._process_member(member, dry_run)

        # Generate report
        report = self._generate_report(dry_run)

        return report

    def _process_member(self, member: Dict[str, Any], dry_run: bool):
        """
        Process a single member's mandate data.

        Args:
            member: Member data dict
            dry_run: If True, don't actually update the record
        """
        member_id = member.name
        customer_id = member.mollie_customer_id
        existing_mandate_id = member.mollie_mandate_id

        # Skip if already has mandate ID set
        if existing_mandate_id:
            self.results["already_set"].append(
                {
                    "member_id": member_id,
                    "member_name": member.full_name,
                    "mandate_id": existing_mandate_id,
                }
            )
            return

        # Fetch mandates from Mollie
        try:
            if not self.client.sdk_client:
                raise Exception("Mollie SDK client not available")

            customer = self.client.sdk_client.customers.get(customer_id)
            mandates = list(customer.mandates.list())

            if len(mandates) == 0:
                self.results["no_mandates"].append(
                    {
                        "member_id": member_id,
                        "member_name": member.full_name,
                        "customer_id": customer_id,
                        "note": "Customer has no mandates in Mollie",
                    }
                )
                return

            # Filter for valid mandates
            valid_mandates = [m for m in mandates if m.status == "valid"]
            pending_mandates = [m for m in mandates if m.status == "pending"]

            if len(valid_mandates) == 0 and len(pending_mandates) == 0:
                # Only invalid mandates
                self.results["invalid_mandates"].append(
                    {
                        "member_id": member_id,
                        "member_name": member.full_name,
                        "customer_id": customer_id,
                        "mandate_count": len(mandates),
                        "invalid_statuses": [m.status for m in mandates],
                        "note": "All mandates are invalid",
                    }
                )
                return

            # Prefer valid mandates, fall back to pending
            preferred_mandates = valid_mandates if valid_mandates else pending_mandates

            if len(preferred_mandates) > 1:
                # Multiple valid/pending mandates - needs manual review
                self.results["multiple_mandates"].append(
                    {
                        "member_id": member_id,
                        "member_name": member.full_name,
                        "customer_id": customer_id,
                        "mandates": [
                            {
                                "id": m.id,
                                "status": m.status,
                                "method": m.method,
                                "created_at": m.created_at,
                                "signature_date": m.signature_date,
                            }
                            for m in preferred_mandates
                        ],
                        "note": "Multiple valid/pending mandates found - manual review needed",
                    }
                )
                return

            # Single valid/pending mandate - use it
            mandate = preferred_mandates[0]

            if not dry_run:
                # Update the member record
                frappe.db.set_value("Member", member_id, "mollie_mandate_id", mandate.id)
                frappe.db.commit()

            self.results["updated"].append(
                {
                    "member_id": member_id,
                    "member_name": member.full_name,
                    "customer_id": customer_id,
                    "mandate_id": mandate.id,
                    "mandate_status": mandate.status,
                    "mandate_method": mandate.method,
                    "created_at": mandate.created_at,
                    "signature_date": mandate.signature_date,
                    "dry_run": dry_run,
                }
            )

        except Exception as e:
            error_msg = str(e)
            frappe.log_error(
                f"Failed to fetch mandates for member {member_id}: {error_msg}",
                "Mandate Sync Error",
            )
            self.results["errors"].append(
                {
                    "member_id": member_id,
                    "member_name": member.full_name,
                    "customer_id": customer_id,
                    "error": error_msg,
                }
            )

    def _generate_report(self, dry_run: bool) -> Dict[str, Any]:
        """
        Generate comprehensive sync report.

        Args:
            dry_run: Whether this was a dry run

        Returns:
            dict: Complete sync report
        """
        report = {
            "summary": {
                "updated": len(self.results["updated"]),
                "already_set": len(self.results["already_set"]),
                "no_mandates": len(self.results["no_mandates"]),
                "multiple_mandates": len(self.results["multiple_mandates"]),
                "invalid_mandates": len(self.results["invalid_mandates"]),
                "errors": len(self.results["errors"]),
            },
            "details": self.results,
            "dry_run": dry_run,
            "timestamp": frappe.utils.now(),
        }

        # Print summary
        mode_str = "DRY RUN" if dry_run else "LIVE RUN"
        frappe.msgprint(
            f"""
            <h3>Mandate Sync Summary ({mode_str})</h3>
            <ul>
                <li><strong>{"Would Update" if dry_run else "Updated"}:</strong> {report['summary']['updated']} members</li>
                <li>Already Had Mandate ID: {report['summary']['already_set']} members</li>
                <li>No Mandates in Mollie: {report['summary']['no_mandates']} members</li>
                <li>Multiple Mandates (Manual Review): {report['summary']['multiple_mandates']} members</li>
                <li>Invalid Mandates Only: {report['summary']['invalid_mandates']} members</li>
                <li>Errors: {report['summary']['errors']}</li>
            </ul>
        """
        )

        return report


@frappe.whitelist()
@critical_api()  # Member data updates
def run_mandate_sync(dry_run=True):
    """
    Whitelisted method to run mandate sync from Desk.

    Args:
        dry_run: If True (default), don't actually update records

    Security: Requires Member write permission and Mollie Settings read permission.

    Usage:
        In Desk Console:
        frappe.call('verenigingen.utils.admin_utilities.mandate_sync_utility.run_mandate_sync', args={'dry_run': True})
    """
    # Validate permissions
    required_permissions = [
        ("Member", "write"),
        ("Mollie Settings", "read"),
    ]

    for doctype, ptype in required_permissions:
        if not frappe.has_permission(doctype, ptype):
            frappe.throw(
                f"Insufficient permissions: {doctype} {ptype} access required for mandate sync",
                frappe.PermissionError,
            )

    # Convert string to boolean (frappe.whitelist converts all args to strings)
    dry_run_bool = dry_run in [True, "True", "true", 1, "1"]

    utility = MandateSyncUtility()
    report = utility.run_sync(dry_run=dry_run_bool)

    # Save report to file for review
    report_filename = f"mandate_sync_report_{'dry_run' if dry_run_bool else 'live'}_{frappe.utils.now().replace(' ', '_').replace(':', '-')}.json"
    report_path = frappe.get_site_path("private", "files", report_filename)

    import json

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    frappe.msgprint(_("Sync complete. Report saved to: {0}").format(report_path))

    return report
