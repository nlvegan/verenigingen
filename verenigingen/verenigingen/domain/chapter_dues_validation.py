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

        Uses fallback logic: if chapter_dues_income_account or national_dues_income_account
        are not set, uses dues_income_account for both.

        Returns:
            Tuple of (source_account, chapter_account, national_account)

        Raises:
            frappe.ValidationError: If configuration is invalid
        """
        settings = frappe.get_single("Verenigingen Settings")

        # Source account is always required
        source = getattr(settings, "dues_income_account", None)
        if not source:
            frappe.throw(
                _("Please configure Dues Income Account in Verenigingen Settings"),
                frappe.ValidationError,
            )

        # Chapter and national accounts are optional - use source as fallback
        chapter = getattr(settings, "chapter_dues_income_account", None) or source
        national = getattr(settings, "national_dues_income_account", None) or source

        # Validate accounts are different if both chapter and national are explicitly configured
        has_chapter = getattr(settings, "chapter_dues_income_account", None)
        has_national = getattr(settings, "national_dues_income_account", None)

        if has_chapter and has_national and has_chapter == has_national:
            frappe.throw(
                _(
                    "Chapter Dues Income Account and National Dues Income Account "
                    "cannot be the same account ({0})"
                ).format(has_chapter),
                frappe.ValidationError,
            )

        # Validate account types (cached query) - only for explicitly configured accounts
        accounts_to_validate = [("Dues Income Account", source)]
        if has_chapter:
            accounts_to_validate.append(("Chapter Dues Income Account", has_chapter))
        if has_national:
            accounts_to_validate.append(("National Dues Income Account", has_national))

        for account_name, account_value in accounts_to_validate:
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
