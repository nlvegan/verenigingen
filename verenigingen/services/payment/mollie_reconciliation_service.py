"""
Mollie Reconciliation Service

Provides member-centric reconciliation logic for matching Mollie subscription data
with Member records in the database.

This service handles:
- Grouping subscriptions by customer
- Building member reconciliation data with discrepancy detection
- Identifying status mismatches, missing subscriptions, and duplicate active subscriptions
"""

from typing import Any, Dict, List, Optional

import frappe

from verenigingen.utils.settings_utils import get_payments_settings
from verenigingen.verenigingen_payments.core.mollie_base_client import MollieBaseClient


class MollieReconciliationService:
    """
    Service for reconciling Mollie subscription data with Member records.

    This service provides member-centric reconciliation capabilities,
    identifying discrepancies between what Mollie reports and what's
    stored in Member records.
    """

    def __init__(self):
        self.client = MollieBaseClient(use_backend_api=False)
        self._dues_keywords: Optional[List[str]] = None

    @property
    def dues_keywords(self) -> List[str]:
        """Get membership dues keywords from settings (cached)."""
        if self._dues_keywords is None:
            settings = get_payments_settings()
            self._dues_keywords = [
                k.strip().lower() for k in (settings.dues_keywords or "contributie").split(",")
            ]
        return self._dues_keywords

    def get_reconciliation_data(
        self,
        progress_callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """
        Get complete member reconciliation data.

        Args:
            progress_callback: Optional callback(message, progress_percent) for progress updates

        Returns:
            Dict containing members list, totals, and test mode status
        """
        self._report_progress(progress_callback, "Fetching Mollie subscriptions...", 10)

        # Fetch all subscriptions from Mollie
        all_subscriptions = self._fetch_all_subscriptions()

        self._report_progress(
            progress_callback,
            f"Filtering {len(all_subscriptions)} subscriptions for membership dues...",
            30,
        )

        # Filter for membership dues subscriptions only
        dues_subscriptions = self._filter_dues_subscriptions(all_subscriptions)

        self._report_progress(
            progress_callback,
            f"Found {len(dues_subscriptions)} membership dues subscriptions. Loading members...",
            50,
        )

        # Fetch all members with Mollie data
        members = self._get_members_with_mollie_data()

        self._report_progress(
            progress_callback,
            f"Processing {len(members)} members with Mollie data...",
            70,
        )

        # Build reconciliation data
        member_data = self.build_member_reconciliation(members, dues_subscriptions)

        self._report_progress(progress_callback, "Reconciliation complete!", 100)

        return {
            "members": member_data,
            "total_members": len(member_data),
            "dues_keywords": self.dues_keywords,
            "test_mode": self.client.test_mode,
        }

    def build_member_reconciliation(
        self,
        members: List[Dict[str, Any]],
        mollie_subscriptions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Build member-centric reconciliation data with discrepancy detection.

        Args:
            members: List of Member records with Mollie data
            mollie_subscriptions: List of Mollie subscriptions (membership dues only)

        Returns:
            List of member reconciliation data with subscriptions and discrepancies
        """
        # Group subscriptions by customer ID
        subs_by_customer = self._group_subscriptions_by_customer(mollie_subscriptions)

        # Build member reconciliation data
        member_data = []
        for member in members:
            customer_id = member.get("mollie_customer_id")
            mollie_subs = subs_by_customer.get(customer_id, [])

            # Sort subscriptions: active first, then by creation date (newest first)
            mollie_subs.sort(
                key=lambda s: (s["status"] != "active", s.get("created_at", "")),
                reverse=True,
            )

            # Categorize subscriptions
            active_subs = [s for s in mollie_subs if s["status"] == "active"]
            inactive_subs = [s for s in mollie_subs if s["status"] != "active"]

            # Detect discrepancies and generate suggestions
            discrepancy_result = self._detect_discrepancies(member, active_subs)

            member_data.append(
                {
                    "member_id": member.get("name"),
                    "member_name": member.get("full_name"),
                    "member_status": member.get("status"),
                    "current_subscription_status": member.get("subscription_status"),
                    "current_subscription_id": member.get("mollie_subscription_id"),
                    "current_next_payment_date": member.get("next_payment_date"),
                    "current_mollie_next_invoice_date": member.get("mollie_subscription_next_invoice_date"),
                    "customer_id": customer_id,
                    "active_subscriptions": active_subs,
                    "inactive_subscriptions": inactive_subs,
                    "discrepancies": discrepancy_result["discrepancies"],
                    "has_issues": len(discrepancy_result["discrepancies"]) > 0,
                    "suggested_subscription_id": discrepancy_result["suggested_subscription_id"],
                    "suggested_status": discrepancy_result["suggested_status"],
                    "suggested_next_invoice_date": discrepancy_result["suggested_next_invoice_date"],
                }
            )

        # Sort: issues first, then by member name
        member_data.sort(key=lambda m: (not m["has_issues"], m["member_name"] or ""))

        return member_data

    def _fetch_all_subscriptions(self) -> List[Dict[str, Any]]:
        """Fetch all subscriptions from Mollie API with pagination."""
        return self.client.get("subscriptions", paginated=True)

    def _filter_dues_subscriptions(
        self,
        all_subscriptions: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Filter subscriptions for membership dues only."""
        dues_subscriptions = []
        for sub in all_subscriptions:
            description = (sub.get("description") or "").lower()
            if any(keyword in description for keyword in self.dues_keywords):
                dues_subscriptions.append(sub)
        return dues_subscriptions

    def _get_members_with_mollie_data(self) -> List[Dict[str, Any]]:
        """Fetch all members with Mollie customer IDs."""
        return frappe.get_all(
            "Member",
            filters={"mollie_customer_id": ["is", "set"]},
            fields=[
                "name",
                "full_name",
                "status",
                "subscription_status",
                "mollie_customer_id",
                "mollie_subscription_id",
                "next_payment_date",
                "mollie_subscription_next_invoice_date",
            ],
        )

    def _group_subscriptions_by_customer(
        self,
        subscriptions: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group subscriptions by customer ID."""
        subs_by_customer: Dict[str, List[Dict[str, Any]]] = {}

        for sub in subscriptions:
            customer_id = sub.get("customerId")
            if customer_id:
                if customer_id not in subs_by_customer:
                    subs_by_customer[customer_id] = []
                subs_by_customer[customer_id].append(
                    {
                        "subscription_id": sub.get("id"),
                        "status": sub.get("status"),
                        "description": sub.get("description"),
                        "amount": sub.get("amount", {}).get("value"),
                        "interval": sub.get("interval"),
                        "next_payment_date": sub.get("nextPaymentDate"),
                        "created_at": sub.get("createdAt"),
                        "cancelled_at": sub.get("canceledAt"),
                    }
                )

        return subs_by_customer

    def _detect_discrepancies(
        self,
        member: Dict[str, Any],
        active_subs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Detect discrepancies between member data and Mollie subscriptions.

        Args:
            member: Member record data
            active_subs: List of active subscriptions for this member

        Returns:
            Dict with discrepancies list and suggested values
        """
        discrepancies = []
        suggested_subscription_id = None
        suggested_status = None
        suggested_next_invoice_date = None

        member_subscription_status = member.get("subscription_status")
        member_subscription_id = member.get("mollie_subscription_id")

        if not active_subs and member_subscription_status in ["active", "pending"]:
            discrepancies.append("Member claims active subscription but no active subscription in Mollie")
            suggested_status = "canceled"

        elif len(active_subs) == 1:
            active_sub = active_subs[0]
            suggested_subscription_id = active_sub["subscription_id"]

            if member_subscription_id != active_sub["subscription_id"]:
                discrepancies.append(
                    f"Member subscription ID doesn't match Mollie "
                    f"({member_subscription_id} vs {active_sub['subscription_id']})"
                )

            if member_subscription_status != active_sub["status"]:
                discrepancies.append(
                    f"Status mismatch ({member_subscription_status} vs {active_sub['status']})"
                )
                suggested_status = active_sub["status"]

        elif len(active_subs) > 1:
            discrepancies.append(
                f"Multiple active subscriptions found ({len(active_subs)}) - manual review needed"
            )
            # Suggest the newest one by default
            suggested_subscription_id = active_subs[0]["subscription_id"]

        # Get next invoice date from active subscription if available
        if active_subs:
            suggested_next_invoice_date = active_subs[0].get("next_payment_date")

        return {
            "discrepancies": discrepancies,
            "suggested_subscription_id": suggested_subscription_id,
            "suggested_status": suggested_status,
            "suggested_next_invoice_date": suggested_next_invoice_date,
        }

    def _report_progress(
        self,
        callback: Optional[callable],
        message: str,
        progress: int,
    ) -> None:
        """Report progress via callback if provided."""
        if callback:
            callback(message, progress)


# Convenience function
def get_mollie_reconciliation_service() -> MollieReconciliationService:
    """Get a MollieReconciliationService instance."""
    return MollieReconciliationService()
