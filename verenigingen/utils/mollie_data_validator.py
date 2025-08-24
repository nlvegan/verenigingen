"""
Centralized Mollie Data Validation Service

This module provides centralized validation for Mollie subscription and customer data
to ensure consistency across all integration points.
"""

import re
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _


class MollieDataValidator:
    """Centralized validator for Mollie subscription data"""

    # Valid Mollie ID patterns
    CUSTOMER_ID_PATTERN = re.compile(r"^cst_[a-zA-Z0-9]{14}$")
    SUBSCRIPTION_ID_PATTERN = re.compile(r"^sub_[a-zA-Z0-9]{14}$")
    PAYMENT_ID_PATTERN = re.compile(r"^tr_[a-zA-Z0-9]{10}$")

    # Valid status transitions
    VALID_STATUS_TRANSITIONS = {
        "pending": ["active", "canceled"],
        "active": ["canceled", "suspended", "completed"],
        "suspended": ["active", "canceled"],
        "canceled": [],  # Terminal state
        "completed": [],  # Terminal state
    }

    def __init__(self):
        self.errors = []
        self.warnings = []

    def validate_customer_data(self, data: Dict) -> Tuple[bool, List[str], List[str]]:
        """
        Validate complete Mollie customer data

        Args:
            data: Dictionary containing Mollie customer data

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []

        # Validate Mollie customer ID
        if data.get("custom_mollie_customer_id"):
            self._validate_customer_id(data["custom_mollie_customer_id"])

        # Validate subscription data if present
        if data.get("custom_mollie_subscription_id"):
            self._validate_subscription_id(data["custom_mollie_subscription_id"])

        # Validate subscription status
        if data.get("subscription_status"):
            self._validate_subscription_status(data["custom_subscription_status"])

        # Validate next payment date logic
        if data.get("custom_next_payment_date") and data.get("subscription_status"):
            self._validate_payment_date_logic(
                data["custom_subscription_status"], data["custom_next_payment_date"]
            )

        return len(self.errors) == 0, self.errors, self.warnings

    def validate_status_transition(self, from_status: str, to_status: str) -> bool:
        """
        Validate if a subscription status transition is allowed

        Args:
            from_status: Current subscription status
            to_status: Target subscription status

        Returns:
            bool: True if transition is valid
        """
        if not from_status or not to_status:
            return True  # Allow initial status setting

        valid_transitions = self.VALID_STATUS_TRANSITIONS.get(from_status, [])
        is_valid = to_status in valid_transitions

        if not is_valid:
            self.errors.append(
                _("Invalid subscription status transition from '{0}' to '{1}'").format(from_status, to_status)
            )

        return is_valid

    def _validate_customer_id(self, customer_id: str):
        """Validate Mollie customer ID format"""
        if not self.CUSTOMER_ID_PATTERN.match(customer_id):
            self.errors.append(
                _("Invalid Mollie customer ID format: {0}. Expected format: cst_xxxxxxxxxxxxxx").format(
                    customer_id
                )
            )

    def _validate_subscription_id(self, subscription_id: str):
        """Validate Mollie subscription ID format"""
        if not self.SUBSCRIPTION_ID_PATTERN.match(subscription_id):
            self.errors.append(
                _("Invalid Mollie subscription ID format: {0}. Expected format: sub_xxxxxxxxxxxxxx").format(
                    subscription_id
                )
            )

    def _validate_subscription_status(self, status: str):
        """Validate subscription status value"""
        valid_statuses = ["pending", "active", "suspended", "canceled", "completed"]
        if status not in valid_statuses:
            self.errors.append(
                _("Invalid subscription status: {0}. Valid values: {1}").format(
                    status, ", ".join(valid_statuses)
                )
            )

    def _validate_payment_date_logic(self, status: str, next_payment_date: str):
        """Validate payment date makes sense for subscription status"""
        from frappe.utils import getdate, nowdate

        if status in ["canceled", "completed"]:
            self.warnings.append(
                _(
                    "Subscription status is '{0}' but next_payment_date is set. Consider clearing the date."
                ).format(status)
            )
        elif status == "active":
            try:
                payment_date = getdate(next_payment_date)
                today = getdate(nowdate())

                if payment_date < today:
                    self.warnings.append(
                        _("Next payment date {0} is in the past for active subscription").format(
                            next_payment_date
                        )
                    )
            except Exception:
                self.errors.append(_("Invalid next payment date format: {0}").format(next_payment_date))


def validate_mollie_customer_data(customer_doc, method=None):
    """
    Validation hook for Customer DocType with Mollie data

    Args:
        customer_doc: Customer document
        method: Hook method name
    """
    # Only validate if Mollie fields are present
    has_mollie_data = any(
        [
            customer_doc.get("custom_mollie_customer_id"),
            customer_doc.get("custom_mollie_subscription_id"),
            customer_doc.get("custom_subscription_status"),
            customer_doc.get("custom_next_payment_date"),
        ]
    )

    if not has_mollie_data:
        return

    validator = MollieDataValidator()
    mollie_data = {
        "custom_mollie_customer_id": customer_doc.get("custom_mollie_customer_id"),
        "custom_mollie_subscription_id": customer_doc.get("custom_mollie_subscription_id"),
        "custom_subscription_status": customer_doc.get("custom_subscription_status"),
        "custom_next_payment_date": customer_doc.get("custom_next_payment_date"),
    }

    is_valid, errors, warnings = validator.validate_customer_data(mollie_data)

    # Check status transition if this is an update
    if not customer_doc.is_new():
        old_doc = customer_doc.get_doc_before_save()
        if old_doc and old_doc.get("custom_subscription_status"):
            validator.validate_status_transition(
                old_doc.get("custom_subscription_status"), customer_doc.get("custom_subscription_status")
            )

    # Report errors
    if errors:
        frappe.throw(_("Mollie data validation failed: {0}").format("; ".join(errors)))

    # Log warnings
    for warning in warnings:
        frappe.logger().warning(f"Mollie validation warning: {warning}")


def get_mollie_validator():
    """Factory function to get a new validator instance"""
    return MollieDataValidator()
