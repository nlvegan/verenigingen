# Copyright (c) 2025, Frappe Technologies and contributors
# For license information, please see license.txt

"""
MollieSyncService - Service for syncing Mollie data during CSV import.

Extracts Mollie data validation and Customer record update logic from
MijnRood CSV Import DocType into a dedicated service.
"""

from typing import Any, Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.model.document import Document

from verenigingen.services.infrastructure.base_service import StatelessService


class MollieSyncService(StatelessService):
    """Service for syncing Mollie subscription data during CSV import.

    Handles validation and synchronization of Mollie customer and subscription
    IDs to both Member and Customer records during bulk import operations.
    """

    def __init__(self):
        """Initialize the MollieSyncService."""
        super().__init__(service_name="MollieSyncService")

    def sync_mollie_data(
        self,
        member_doc: Document,
        mollie_data: Dict[str, Any],
    ) -> None:
        """Sync Mollie customer/subscription IDs to Member and Customer records.

        Updates both the Member record (for PaymentClassifier matching) and
        the Customer record (for relationship management) with Mollie data.

        Args:
            member_doc: Member document to sync Mollie data to
            mollie_data: Dictionary containing Mollie fields:
                - custom_mollie_customer_id: Mollie customer ID
                - custom_mollie_subscription_id: Mollie subscription ID
                - custom_subscription_status: Subscription status

        Raises:
            frappe.ValidationError: If Mollie data format is invalid
        """
        try:
            # Validate Mollie data before processing
            self._validate_mollie_data(mollie_data)

            # Ensure customer exists
            if not member_doc.customer:
                member_doc._suppress_customer_messages = True
                customer_name = member_doc.create_customer()
                member_doc.customer = customer_name

            # Update Member record with Mollie data
            if mollie_data.get("custom_mollie_customer_id"):
                member_doc.mollie_customer_id = mollie_data["custom_mollie_customer_id"]
            if mollie_data.get("custom_mollie_subscription_id"):
                member_doc.mollie_subscription_id = mollie_data["custom_mollie_subscription_id"]
                # Honor caller-supplied status (e.g. "canceled" for terminated members);
                # default to "active" if no status given but a subscription exists.
                member_doc.subscription_status = mollie_data.get("custom_subscription_status") or "active"

            member_doc.save()

            # Update Customer record with Mollie data
            if member_doc.customer:
                self._update_customer_mollie_fields(member_doc.customer, mollie_data)
                self.logger.info(
                    f"Updated Member {member_doc.name} and Customer {member_doc.customer} " "with Mollie data"
                )

        except Exception as e:
            self.logger.error(
                f"Failed to update Customer with Mollie data for Member {member_doc.name}: {str(e)}"
            )
            raise

    def _validate_mollie_data(self, mollie_data: Dict[str, Any]) -> None:
        """Validate Mollie data format.

        Args:
            mollie_data: Dictionary containing Mollie fields

        Raises:
            frappe.ValidationError: If data is invalid
        """
        try:
            from verenigingen.verenigingen_payments.mollie.utils.data_validator import (
                get_mollie_validator,
            )

            validator = get_mollie_validator()
            is_valid, errors, warnings = validator.validate_customer_data(mollie_data)

            if not is_valid:
                frappe.throw(f"Invalid Mollie data in CSV import: {'; '.join(errors)}")

            for warning in warnings:
                self.logger.warning("CSV import Mollie data warning: %s", warning)

        except ImportError:
            # Mollie validator not available, do basic validation
            customer_id = mollie_data.get("custom_mollie_customer_id")
            if customer_id and not str(customer_id).startswith("cst_"):
                self.logger.warning(
                    f"Mollie customer ID '{customer_id}' doesn't match expected format (cst_*)"
                )

    def _update_customer_mollie_fields(
        self,
        customer_name: str,
        mollie_data: Dict[str, Any],
    ) -> None:
        """Update Customer document with Mollie fields.

        Uses frappe.db.set_value (direct DB write) rather than customer.save()
        because the Mollie fields are pure data with no downstream hooks. A full
        save fires Customer.on_update -> create_primary_contact() ->
        frappe.set_value("Contact", ..., "is_primary_contact", 1), which can
        raise TimestampMismatchError when the Contact was modified earlier in
        the same request (e.g., name propagation) and the doc cache serves a
        stale copy.

        Note: subscription status is stored on Member.subscription_status — Customer
        has no equivalent column, so custom_subscription_status is intentionally
        ignored here.
        """
        values = {}
        if mollie_data.get("custom_mollie_customer_id"):
            values["custom_mollie_customer_id"] = mollie_data["custom_mollie_customer_id"]
        if mollie_data.get("custom_mollie_subscription_id"):
            values["custom_mollie_subscription_id"] = mollie_data["custom_mollie_subscription_id"]

        if values:
            frappe.db.set_value("Customer", customer_name, values)

    def validate_mollie_data_preservation(
        self,
        member_names: List[str],
        auto_fix_payment_method: bool = True,
    ) -> Tuple[List[str], List[str], List[str]]:
        """Validate Mollie subscription data with issue categorization and optional auto-fix.

        Performs comprehensive validation of Mollie data on both Member and Customer records:
        - Validates Mollie ID formats (cst_*, sub_*)
        - Checks payment method consistency
        - Detects CRITICAL issues (active subscriptions on terminated/banned/deceased members)

        Args:
            member_names: List of member document names to validate
            auto_fix_payment_method: Whether to auto-fix payment method mismatches

        Returns:
            Tuple of (issues, auto_fixed, critical_issues) where:
            - issues: List of validation issue messages
            - auto_fixed: List of auto-fixed issue messages
            - critical_issues: List of critical issues requiring manual intervention
        """
        issues = []
        auto_fixed = []
        critical_issues = []

        for member_name in member_names:
            try:
                member = frappe.get_doc("Member", member_name)

                if not member.customer:
                    continue

                customer = frappe.get_doc("Customer", member.customer)
                if not (customer.custom_mollie_customer_id or customer.custom_mollie_subscription_id):
                    continue

                member_issues = []

                # Validate Mollie Customer ID format
                if customer.custom_mollie_customer_id:
                    if not customer.custom_mollie_customer_id.startswith("cst_"):
                        member_issues.append(
                            f"Invalid Mollie Customer ID format: {customer.custom_mollie_customer_id}"
                        )

                # Validate Mollie Subscription ID format
                if customer.custom_mollie_subscription_id:
                    if not customer.custom_mollie_subscription_id.startswith("sub_"):
                        member_issues.append(
                            f"Invalid Mollie Subscription ID format: {customer.custom_mollie_subscription_id}"
                        )

                # Check payment method consistency
                if (
                    customer.custom_mollie_customer_id or customer.custom_mollie_subscription_id
                ) and member.payment_method != "Mollie":
                    if auto_fix_payment_method:
                        old_method = member.payment_method
                        frappe.db.set_value(
                            "Member", member_name, "payment_method", "Mollie", update_modified=False
                        )
                        auto_fixed.append(f"{member_name}: payment_method {old_method} → Mollie")
                    else:
                        member_issues.append(
                            f"Payment method should be 'Mollie', found: {member.payment_method}"
                        )

                # CRITICAL: Active subscriptions on terminated/banned/deceased members
                # These represent potential ongoing charges that need manual intervention
                if customer.custom_mollie_subscription_id and member.status in [
                    "Quit",
                    "Banned",
                    "Deceased",
                ]:
                    critical_msg = (
                        f"[CRITICAL] Member {member_name}: Active Mollie subscription "
                        f"{customer.custom_mollie_subscription_id} on {member.status} member - "
                        "MANUAL CANCELLATION REQUIRED to prevent ongoing charges"
                    )
                    critical_issues.append(critical_msg)
                    member_issues.append(critical_msg)

                if member_issues:
                    issues.append(f"Member {member_name}: {'; '.join(member_issues)}")

            except Exception as e:
                self.logger.error(f"Error validating Mollie data for {member_name}: {str(e)}")
                issues.append(f"Member {member_name}: Validation failed - {str(e)}")

        # Commit auto-fixes
        if auto_fixed:
            self.logger.info(f"Mollie validation auto-fixed {len(auto_fixed)} payment method mismatches")
            frappe.db.commit()

        return issues, auto_fixed, critical_issues


# Module-level singleton accessor
_service_instance: Optional[MollieSyncService] = None


def get_mollie_sync_service() -> MollieSyncService:
    """Get singleton instance of MollieSyncService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MollieSyncService()
    return _service_instance
