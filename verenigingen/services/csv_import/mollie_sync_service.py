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
                member_doc.subscription_status = "active"

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
        """Update Customer document with Mollie fields."""
        customer = frappe.get_doc("Customer", customer_name)

        if mollie_data.get("custom_mollie_customer_id"):
            customer.custom_mollie_customer_id = mollie_data["custom_mollie_customer_id"]
        if mollie_data.get("custom_mollie_subscription_id"):
            customer.custom_mollie_subscription_id = mollie_data["custom_mollie_subscription_id"]
        if mollie_data.get("custom_subscription_status"):
            customer.custom_subscription_status = mollie_data["custom_subscription_status"]

        customer.save()

    def validate_mollie_data_preservation(
        self,
        member_names: List[str],
        auto_fix_payment_method: bool = True,
    ) -> Tuple[List[str], List[str]]:
        """Validate Mollie data on imported members.

        Checks that members with Mollie IDs have correct payment method settings
        and optionally auto-fixes inconsistencies.

        Args:
            member_names: List of member document names to validate
            auto_fix_payment_method: Whether to auto-fix payment method mismatches

        Returns:
            Tuple of (issues, auto_fixed) where:
            - issues: List of validation issue messages
            - auto_fixed: List of auto-fixed issue messages
        """
        issues = []
        auto_fixed = []

        for member_name in member_names:
            try:
                member = frappe.get_doc("Member", member_name)

                # Check for Mollie data without Mollie payment method
                has_mollie_data = member.mollie_customer_id or member.mollie_subscription_id
                is_mollie_payment = member.payment_method == "Mollie"

                if has_mollie_data and not is_mollie_payment:
                    if auto_fix_payment_method:
                        member.payment_method = "Mollie"
                        member._system_update = True
                        member.save()
                        auto_fixed.append(
                            f"Member {member_name}: Payment method set to Mollie "
                            "(had Mollie data but different payment method)"
                        )
                    else:
                        issues.append(
                            f"Member {member_name}: Has Mollie data but payment method "
                            f"is '{member.payment_method}'"
                        )

                # Check for Mollie payment method without Mollie data
                if is_mollie_payment and not has_mollie_data:
                    issues.append(f"Member {member_name}: Payment method is Mollie but no Mollie data")

            except Exception as e:
                issues.append(f"Member {member_name}: Validation failed - {str(e)}")

        return issues, auto_fixed


# Module-level singleton accessor
_service_instance: Optional[MollieSyncService] = None


def get_mollie_sync_service() -> MollieSyncService:
    """Get singleton instance of MollieSyncService."""
    global _service_instance
    if _service_instance is None:
        _service_instance = MollieSyncService()
    return _service_instance
