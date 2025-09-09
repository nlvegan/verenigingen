#!/usr/bin/env python3
"""
Configurable Account Mapper

Abstracts hardcoded account number dependencies by providing a configurable
mapping system that can work with any chart of accounts structure.

This replaces hardcoded Dutch account numbers (10440, 10470, etc.) with
dynamic lookups based on account purpose/type.
"""

from typing import Dict, List, Optional

import frappe
from frappe.utils import cint


class ConfigurableAccountMapper:
    """
    Maps logical account purposes to actual account numbers/names.

    This allows the same code to work with different chart of accounts
    without hardcoding specific Dutch account numbers.
    """

    def __init__(self, company: str):
        self.company = company
        self._cache = {}

    def get_account_by_purpose(self, purpose: str) -> Optional[str]:
        """
        Get account by business purpose rather than hardcoded number.

        Args:
            purpose: Business purpose like "main_bank", "paypal", "cash", "triodos"

        Returns:
            Account name or None if not found
        """
        if purpose in self._cache:
            return self._cache[purpose]

        # First try configured mappings (future enhancement)
        # account = self._get_configured_mapping(purpose)
        # if account:
        #     self._cache[purpose] = account
        #     return account

        # Use smart detection
        account = self._detect_account_by_purpose(purpose)
        if account:
            self._cache[purpose] = account
            return account

        return None

    def _get_configured_mapping(self, purpose: str) -> Optional[str]:
        """Get account from configured mappings (future: DocType for configuration)."""
        # TODO: Create "Account Purpose Mapping" DocType for configuration
        # For now, return None to use smart detection
        return None

    def _detect_account_by_purpose(self, purpose: str) -> Optional[str]:
        """Detect account by analyzing account names and types."""
        detection_rules = {
            "main_bank": self._find_main_bank_account,
            "triodos": lambda: self._find_bank_by_name("triodos"),
            "paypal": lambda: self._find_bank_by_name("paypal"),
            "asn": lambda: self._find_bank_by_name("asn"),
            "cash": self._find_cash_account,
            "default_expense": self._find_default_expense_account,
            "default_income": self._find_default_income_account,
        }

        detector = detection_rules.get(purpose)
        if detector:
            return detector()

        return None

    def _find_main_bank_account(self) -> Optional[str]:
        """Find the main bank account (typically the first/primary one)."""
        # Look for account with "primary" or "main" in name first
        main_account = frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_type": "Bank",
                "is_group": 0,
                "disabled": 0,
            },
            "name",
            filters=[["name", "like", "%main%"], ["or"], ["name", "like", "%primary%"]],
            order_by="name",
        )

        if main_account:
            return main_account

        # Fallback to first bank account by account number
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Bank", "is_group": 0, "disabled": 0},
            "name",
            order_by="account_number",
        )

    def _find_bank_by_name(self, bank_name: str) -> Optional[str]:
        """Find bank account by name pattern."""
        return frappe.db.get_value(
            "Account",
            {
                "company": self.company,
                "account_type": "Bank",
                "is_group": 0,
                "disabled": 0,
            },
            "name",
            filters=[["name", "like", f"%{bank_name}%"]],
            order_by="name",
        )

    def _find_cash_account(self) -> Optional[str]:
        """Find cash account."""
        # First try by account type
        cash_account = frappe.db.get_value(
            "Account",
            {"company": self.company, "account_type": "Cash", "is_group": 0, "disabled": 0},
            "name",
            order_by="account_number",
        )

        if cash_account:
            return cash_account

        # Fallback to account with "kas" or "cash" in name
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "is_group": 0, "disabled": 0},
            "name",
            filters=[["name", "like", "%kas%"], ["or"], ["name", "like", "%cash%"]],
            order_by="name",
        )

    def _find_default_expense_account(self) -> Optional[str]:
        """Find default expense account for the company."""
        company_doc = frappe.get_doc("Company", self.company)
        if company_doc.default_expense_account:
            return company_doc.default_expense_account

        # Fallback to any expense account
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Expense", "is_group": 0, "disabled": 0},
            "name",
            order_by="account_number",
        )

    def _find_default_income_account(self) -> Optional[str]:
        """Find default income account for the company."""
        company_doc = frappe.get_doc("Company", self.company)
        if company_doc.default_income_account:
            return company_doc.default_income_account

        # Fallback to any income account
        return frappe.db.get_value(
            "Account",
            {"company": self.company, "root_type": "Income", "is_group": 0, "disabled": 0},
            "name",
            order_by="account_number",
        )

    def get_payment_account_mappings(self) -> Dict[str, str]:
        """Get all payment account mappings for this company."""
        mappings = {}
        purposes = ["main_bank", "triodos", "paypal", "asn", "cash"]

        for purpose in purposes:
            account = self.get_account_by_purpose(purpose)
            if account:
                mappings[purpose] = account

        return mappings

    def validate_required_accounts(self, required_purposes: List[str]) -> Dict[str, bool]:
        """Validate that required account purposes can be resolved."""
        results = {}
        for purpose in required_purposes:
            account = self.get_account_by_purpose(purpose)
            results[purpose] = bool(account)

        return results


def get_account_mapper(company: str) -> ConfigurableAccountMapper:
    """Get account mapper instance for a company."""
    return ConfigurableAccountMapper(company)


def validate_account_setup(company: str) -> Dict:
    """Validate that required accounts exist for eBoekhouden integration."""
    mapper = get_account_mapper(company)

    required_accounts = ["main_bank", "cash", "default_expense", "default_income"]
    results = mapper.validate_required_accounts(required_accounts)

    missing = [purpose for purpose, found in results.items() if not found]

    return {
        "valid": not missing,
        "missing_accounts": missing,
        "found_mappings": {k: v for k, v in results.items() if v},
        "recommendations": _generate_setup_recommendations(missing),
    }


def _generate_setup_recommendations(missing_accounts: List[str]) -> List[str]:
    """Generate setup recommendations for missing accounts."""
    recommendations = []

    if "main_bank" in missing_accounts:
        recommendations.append("Create at least one Bank account for payment processing")
    if "cash" in missing_accounts:
        recommendations.append("Create a Cash account for cash transactions")
    if "default_expense" in missing_accounts:
        recommendations.append("Set default expense account in Company settings")
    if "default_income" in missing_accounts:
        recommendations.append("Set default income account in Company settings")

    return recommendations
