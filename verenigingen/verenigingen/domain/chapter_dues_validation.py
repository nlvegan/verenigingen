"""
Validation Service for Chapter Dues Allocation

Centralizes business rule validation to ensure consistency across
settings, API endpoints, and hooks.

Architecture:
- Single source of truth for validation logic
- Consistent error messages
- Reusable validation methods
- Clear separation from business logic
"""

from datetime import date
from typing import Optional, Tuple

import frappe
from frappe import _


class DuesAllocationValidator:
    """Validates inputs and configuration for dues allocation"""

    @staticmethod
    def validate_date_range(from_date: date, to_date: date) -> None:
        """
        Validate date range is logical.

        Args:
            from_date: Start date
            to_date: End date

        Raises:
            frappe.ValidationError: If date range is invalid
        """
        if from_date > to_date:
            frappe.throw(
                _("From Date ({0}) cannot be after To Date ({1})").format(from_date, to_date),
                frappe.ValidationError,
            )

    @staticmethod
    def validate_account_configuration() -> Tuple[str, str, str]:
        """
        Validate account configuration is complete and correct.

        Returns:
            Tuple of (source_account, chapter_account, national_account)

        Raises:
            frappe.ValidationError: If configuration is invalid
        """
        settings = frappe.get_single("Verenigingen Settings")

        # Check all accounts configured
        source = getattr(settings, "dues_income_account", None)
        chapter = getattr(settings, "chapter_dues_income_account", None)
        national = getattr(settings, "national_dues_income_account", None)

        if not all([source, chapter, national]):
            missing = []
            if not source:
                missing.append("Dues Income Account")
            if not chapter:
                missing.append("Chapter Dues Income Account")
            if not national:
                missing.append("National Dues Income Account")

            frappe.throw(
                _(
                    "Please configure chapter dues allocation accounts in Verenigingen Settings. "
                    "Missing: {0}"
                ).format(", ".join(missing)),
                frappe.ValidationError,
            )

        # Validate accounts are different
        if len({source, chapter, national}) != 3:
            frappe.throw(
                _("Chapter dues allocation accounts must be different from each other"),
                frappe.ValidationError,
            )

        # Validate account types (cached query)
        for account_name, account_value in [
            ("Dues Income Account", source),
            ("Chapter Dues Income Account", chapter),
            ("National Dues Income Account", national),
        ]:
            account_type = frappe.db.get_value("Account", account_value, "account_type")
            if account_type != "Income Account":
                frappe.throw(
                    _("{0} must be an Income Account (currently: {1})").format(
                        account_name, account_type or "Not set"
                    ),
                    frappe.ValidationError,
                )

        return source, chapter, national

    @staticmethod
    def validate_chapter_exists(chapter_name: Optional[str]) -> None:
        """
        Validate chapter exists if provided.

        Args:
            chapter_name: Optional chapter name

        Raises:
            frappe.ValidationError: If chapter doesn't exist
        """
        if chapter_name and not frappe.db.exists("Chapter", chapter_name):
            frappe.throw(_("Chapter {0} does not exist").format(chapter_name), frappe.ValidationError)

    @staticmethod
    def validate_company_exists(company_name: Optional[str]) -> None:
        """
        Validate company exists if provided.

        Args:
            company_name: Optional company name

        Raises:
            frappe.ValidationError: If company doesn't exist
        """
        if company_name and not frappe.db.exists("Company", company_name):
            frappe.throw(_("Company {0} does not exist").format(company_name), frappe.ValidationError)
