"""
Account Classification Service

Centralized service for classifying E-Boekhouden accounts into ERPNext account types.
Consolidates logic from multiple scattered implementations into a single, testable service.

Architecture:
- Strategy pattern for multiple classification approaches
- Confidence-based classification with fallbacks
- Dutch RGS (Reference Code System) patterns
- E-Boekhouden category codes integration
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

import frappe

from verenigingen.services.infrastructure.base_service import StatelessService


class ClassificationConfidence(Enum):
    """Confidence level for account classification"""

    HIGH = "high"  # Category + code pattern match
    MEDIUM = "medium"  # Code pattern or keyword match
    LOW = "low"  # Fallback classification
    NONE = "none"  # Could not classify - requires manual intervention


@dataclass
class AccountClassification:
    """Result of account classification"""

    account_type: str  # ERPNext account type (e.g., "Receivable", "Bank")
    root_type: str  # ERPNext root type (e.g., "Asset", "Liability", "Income", "Expense", "Equity")
    confidence: ClassificationConfidence
    strategy_used: str  # Which strategy produced this classification
    notes: Optional[str] = None  # Additional context or warnings


class AccountClassificationService(StatelessService):
    """
    Service for classifying E-Boekhouden accounts into ERPNext account types.

    Uses multiple classification strategies in priority order:
    1. E-Boekhouden category codes (highest confidence)
    2. Dutch RGS code patterns (medium confidence)
    3. Dutch accounting keywords (medium confidence)
    4. Fallback defaults (lowest confidence)

    Example:
        service = AccountClassificationService()
        result = service.classify_account({
            "code": "1300",
            "description": "Debiteuren",
            "category": "DEB",
            "group": "005"
        })
        # result.account_type = "Receivable"
        # result.root_type = "Asset"
        # result.confidence = ClassificationConfidence.HIGH
    """

    def __init__(self):
        """Initialize the classification service"""
        super().__init__()

        # E-Boekhouden category to ERPNext type mapping
        # NOTE: DEB/CRED mapped to Current Asset/Liability instead of Receivable/Payable
        # REASON: ERPNext requires "party" linking for Receivable/Payable types
        # This avoids ERPNext validation errors during account creation
        # Actual receivable/payable classification happens via code patterns (130x, 440x)
        self.category_mapping = {
            # Tax-related categories
            "BTWRC": ("Tax", "Liability"),  # VAT current account
            "AF6": ("Tax", "Liability"),  # Turnover tax low rate (6%)
            "AF9": ("Tax", "Liability"),  # Turnover tax standard rate (9%)
            "AF19": ("Tax", "Liability"),  # Turnover tax high rate (19%)
            "AF21": ("Tax", "Liability"),  # Turnover tax high rate (21%)
            "AFOVERIG": ("Tax", "Liability"),  # Turnover tax other
            "AF": ("Tax", "Liability"),  # Turnover tax general
            "VOOR": ("Tax", "Asset"),  # Input tax (VAT receivable)
            "BTW": ("Tax", "Liability"),  # Generic VAT
            # Financial accounts
            "FIN": ("Bank", "Asset"),  # Financial/Liquid Assets
            "KAS": ("Cash", "Asset"),  # Cash accounts
            # Debtors/Creditors - mapped to generic types to avoid ERPNext party requirements
            "DEB": ("Current Asset", "Asset"),  # Debtors → Current Asset (not Receivable)
            "CRED": ("Current Liability", "Liability"),  # Creditors → Current Liability (not Payable)
            # Equity
            "EIG": ("Equity", "Equity"),  # Eigen vermogen (equity)
            # Balance sheet - requires further analysis
            "BAL": (None, None),  # Balance sheet - needs code/name analysis
            # Profit & Loss - requires further analysis
            "VW": (None, None),  # Verbruiksrekeningen - needs code/group analysis
        }

        # Dutch accounting keywords for receivables
        self.receivable_keywords = [
            "debiteuren",
            "debiteur",
            "te ontvangen",
            "te vorderen",
            "vordering op",
            "nog te factureren",
            "nog te ontvangen",
            "handelsdebiteuren",
        ]

        # Dutch accounting keywords for payables
        self.payable_keywords = [
            "crediteuren",
            "crediteur",
            "te betalen",
            "schuld aan",
            "nog te betalen",
            "nog te ontvangen facturen",
            "handelscrediteuren",
        ]

        # Dutch accounting keywords for income
        self.income_keywords = [
            "opbrengst",
            "omzet",
            "inkomst",
            "contributie",
            "donatie",
            "verkoop",
            "baten",
            "winst",
            "ontvangen",
        ]

        # Dutch equity keywords
        self.equity_keywords = [
            "eigen vermogen",
            "reserve",
            "reservering",
            "bestemmingsreserve",
            "continuiteitsreserve",
            "kapitaal",
        ]

    def classify_account(self, account_data: Dict) -> AccountClassification:
        """
        Classify an E-Boekhouden account into ERPNext account type.

        Args:
            account_data: Dictionary containing:
                - code: Account code (required)
                - description: Account name/description (required)
                - category: E-Boekhouden category code (optional)
                - group: E-Boekhouden group code (optional)

        Returns:
            AccountClassification with type, root_type, and confidence level

        Raises:
            ValueError: If required fields are missing
        """
        # Input validation: Prevent malicious/malformed data
        raw_code = account_data.get("code", "")
        raw_description = account_data.get("description", "")
        raw_category = account_data.get("category", "")
        raw_group = account_data.get("group", "")

        # Length validation to prevent DoS attacks
        if len(str(raw_code)) > 20:
            raise ValueError(f"Account code exceeds maximum length (20 chars): {len(str(raw_code))}")
        if len(str(raw_description)) > 500:
            raise ValueError(
                f"Account description exceeds maximum length (500 chars): {len(str(raw_description))}"
            )
        if len(str(raw_category)) > 20:
            raise ValueError(f"Account category exceeds maximum length (20 chars): {len(str(raw_category))}")
        if len(str(raw_group)) > 10:
            raise ValueError(f"Account group exceeds maximum length (10 chars): {len(str(raw_group))}")

        # Sanitize and normalize input
        code = str(raw_code).strip()
        description = str(raw_description).strip()
        category = str(raw_category).strip().upper()
        group = str(raw_group).strip()

        # Validate required fields
        if not description:
            raise ValueError(f"Account description is required. Got description={description}")

        # Validate code format if provided (should be alphanumeric for Dutch RGS)
        if code and not code.replace(" ", "").replace("-", "").isalnum():
            raise ValueError(f"Account code contains invalid characters: {code}")

        # Strategy 1: Category-based classification (highest confidence)
        result = self._classify_by_category(code, description, category, group)
        if result:
            return result

        # Strategy 2: Dutch RGS code patterns for P&L accounts (4xxx-9xxx)
        # For profit/loss accounts, code patterns are MORE reliable than keywords
        # Example: "6100 - Kosten debiteuren" should be Expense (6xxx), not Receivable (keyword)
        if code and code[0] in ["4", "5", "6", "7", "8", "9"]:
            result = self._classify_by_code_pattern(code, description, group)
            if result:
                return result
            # If code pattern didn't match P&L ranges, try keywords as fallback
            result = self._classify_by_keywords(code, description)
            if result:
                return result
        else:
            # Strategy 3: For balance sheet accounts (0xxx-3xxx), keywords first
            # Keyword-based classification (high confidence for specific terms)
            result = self._classify_by_keywords(code, description)
            if result:
                return result

            # Strategy 4: Dutch RGS code patterns (medium confidence)
            result = self._classify_by_code_pattern(code, description, group)
            if result:
                return result

        # Strategy 5: Ultimate fallback (low confidence)
        return self._fallback_classification(code, description)

    def _classify_by_category(
        self, code: str, description: str, category: str, group: str
    ) -> Optional[AccountClassification]:
        """
        Classify using E-Boekhouden category codes.

        This is the highest confidence classification method when category is available.
        """
        if not category:
            return None

        if category not in self.category_mapping:
            frappe.logger().warning(f"Unknown E-Boekhouden category: {category} for account {code}")
            return None

        account_type, root_type = self.category_mapping[category]

        # Special handling for BAL (Balance Sheet) accounts
        if category == "BAL":
            return self._classify_balance_sheet_account(code, description, group)

        # Special handling for VW (Profit & Loss) accounts
        if category == "VW":
            return self._classify_profit_loss_account(code, description, group)

        # Direct category mapping available
        if account_type and root_type:
            return AccountClassification(
                account_type=account_type,
                root_type=root_type,
                confidence=ClassificationConfidence.HIGH,
                strategy_used="category_mapping",
                notes=f"E-Boekhouden category: {category}",
            )

        return None

    def _classify_balance_sheet_account(
        self, code: str, description: str, group: str
    ) -> Optional[AccountClassification]:
        """
        Classify BAL (Balance Sheet) category accounts using code patterns and keywords.

        Dutch RGS patterns:
        - 0xxx-1xxx: Assets
        - 2xxx: Equity (reserves, capital)
        - 3xxx-4xxx: Liabilities
        - 5xxx: Special case - could be equity or expenses
        """
        description_lower = description.lower()

        # Check group code for equity first (group 005 is typically equity) - more reliable than keywords
        if group == "005":
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.HIGH,
                strategy_used="balance_sheet_group_005",
                notes="Group 005 indicates equity",
            )

        # Check for equity patterns (name-based)
        if any(keyword in description_lower for keyword in self.equity_keywords):
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.HIGH,
                strategy_used="balance_sheet_equity_keyword",
                notes=f"Equity identified by keyword in: {description}",
            )

        # Code-based classification for BAL accounts
        if code.startswith(("0", "1")):
            # Assets range
            if code.startswith("02"):
                return AccountClassification(
                    account_type="Fixed Asset",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="balance_sheet_code_pattern",
                    notes="02xx = Fixed Assets (RGS)",
                )
            elif code.startswith("10"):
                if "kas" in description_lower:
                    return AccountClassification(
                        account_type="Cash",
                        root_type="Asset",
                        confidence=ClassificationConfidence.HIGH,
                        strategy_used="balance_sheet_cash_keyword",
                        notes="10xx with 'kas' = Cash",
                    )
                else:
                    return AccountClassification(
                        account_type="Bank",
                        root_type="Asset",
                        confidence=ClassificationConfidence.HIGH,
                        strategy_used="balance_sheet_code_pattern",
                        notes="10xx = Bank accounts (RGS)",
                    )
            elif code.startswith("13"):
                # Special handling for 13xx range (receivables or current assets)
                if any(keyword in description_lower for keyword in self.receivable_keywords):
                    return AccountClassification(
                        account_type="Receivable",
                        root_type="Asset",
                        confidence=ClassificationConfidence.HIGH,
                        strategy_used="balance_sheet_receivable_keyword",
                        notes="13xx with receivable keyword",
                    )
                else:
                    return AccountClassification(
                        account_type="Current Asset",
                        root_type="Asset",
                        confidence=ClassificationConfidence.MEDIUM,
                        strategy_used="balance_sheet_code_pattern",
                        notes="13xx = Current Assets (RGS)",
                    )
            elif code.startswith("14"):
                return AccountClassification(
                    account_type="Stock",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="balance_sheet_code_pattern",
                    notes="14xx = Stock/Inventory (RGS)",
                )
            else:
                return AccountClassification(
                    account_type="Current Asset",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="balance_sheet_code_pattern",
                    notes="0xxx/1xxx = Assets (RGS)",
                )

        elif code.startswith(("3", "4")):
            # Liabilities range
            if code.startswith("44"):
                # Special handling for 44xx range (payables or current liabilities)
                if any(keyword in description_lower for keyword in self.payable_keywords):
                    return AccountClassification(
                        account_type="Payable",
                        root_type="Liability",
                        confidence=ClassificationConfidence.HIGH,
                        strategy_used="balance_sheet_payable_keyword",
                        notes="44xx with payable keyword",
                    )
                else:
                    return AccountClassification(
                        account_type="Current Liability",
                        root_type="Liability",
                        confidence=ClassificationConfidence.MEDIUM,
                        strategy_used="balance_sheet_code_pattern",
                        notes="44xx = Current Liabilities (RGS)",
                    )
            else:
                return AccountClassification(
                    account_type="Current Liability",
                    root_type="Liability",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="balance_sheet_code_pattern",
                    notes="3xxx/4xxx = Liabilities (RGS)",
                )

        elif code.startswith("5") and not group:
            # 5xxx without group code suggests equity
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.LOW,
                strategy_used="balance_sheet_5xxx_fallback",
                notes="5xxx without group = Equity (tentative)",
            )

        # Default for unclassified BAL accounts
        return AccountClassification(
            account_type="Current Asset",
            root_type="Asset",
            confidence=ClassificationConfidence.LOW,
            strategy_used="balance_sheet_fallback",
            notes="BAL category with unknown pattern",
        )

    def _classify_profit_loss_account(
        self, code: str, description: str, group: str
    ) -> Optional[AccountClassification]:
        """
        Classify VW (Verbruiksrekeningen - Profit & Loss) category accounts.

        Uses E-Boekhouden group codes as primary classifier:
        - Group 055: Income (Opbrengsten)
        - Groups 056-059: Expenses (various cost types)

        Fallback to keywords and code patterns if group unavailable.
        """
        description_lower = description.lower()

        # Strategy 1: Use group code (most reliable for VW accounts)
        if group == "055":
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.HIGH,
                strategy_used="profit_loss_group_055",
                notes="Group 055 = Income (Opbrengsten)",
            )
        elif group in ["056", "057", "058", "059"]:
            return AccountClassification(
                account_type="Expense Account",
                root_type="Expense",
                confidence=ClassificationConfidence.HIGH,
                strategy_used=f"profit_loss_group_{group}",
                notes=f"Group {group} = Expenses",
            )

        # Strategy 2: Keyword-based classification
        if any(keyword in description_lower for keyword in self.income_keywords):
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="profit_loss_income_keyword",
                notes=f"Income keyword detected in: {description}",
            )

        # Strategy 3: Code pattern fallback (8xxx, 9xxx typically income)
        if code.startswith(("8", "9")):
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="profit_loss_code_pattern",
                notes="8xxx/9xxx = Income (RGS)",
            )

        # VW account with no matches - cannot classify confidently
        # Return None to indicate no classification rather than defaulting to Expense
        frappe.logger().warning(
            f"VW account {code} ({description}) could not be classified - "
            f"no group match, no keyword match, no code pattern match (group: {group})"
        )
        return AccountClassification(
            account_type="",
            root_type=None,
            confidence=ClassificationConfidence.NONE,
            strategy_used="profit_loss_no_match",
            notes="VW account could not be classified - requires manual review or additional configuration",
        )

    def _classify_by_code_pattern(
        self, code: str, description: str, group: str
    ) -> Optional[AccountClassification]:
        """
        Classify using Dutch RGS (Reference Code System) code patterns.

        This method handles accounts without category codes.
        """
        description_lower = description.lower()

        # Bank and Cash accounts (10xx, 11xx, 12xx)
        if code.startswith("10"):
            if "kas" in description_lower:
                return AccountClassification(
                    account_type="Cash",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_cash",
                    notes="10xx with 'kas' keyword",
                )
            elif "bank" in description_lower or "giro" in description_lower:
                return AccountClassification(
                    account_type="Bank",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_bank",
                    notes="10xx with bank keyword",
                )
            else:
                return AccountClassification(
                    account_type="Bank",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_10xx",
                    notes="10xx = Bank (RGS default)",
                )

        # Fixed Assets (02xx, 04xx-09xx)
        if code.startswith(("02", "04", "05", "06", "07", "08", "09")):
            return AccountClassification(
                account_type="Fixed Asset",
                root_type="Asset",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_fixed_asset",
                notes="0xxx range = Fixed Assets (RGS)",
            )

        # Current Assets including Receivables (11xx-14xx)
        if code.startswith("11") or code.startswith("12"):
            if any(keyword in description_lower for keyword in self.receivable_keywords):
                return AccountClassification(
                    account_type="Receivable",
                    root_type="Asset",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_receivable",
                    notes="11xx/12xx with receivable keyword",
                )
            else:
                return AccountClassification(
                    account_type="Current Asset",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_current_asset",
                    notes="11xx/12xx = Current Assets (RGS)",
                )

        # Receivables (13xx)
        if code.startswith("13"):
            if code.startswith("130") or "handelsdebiteuren" in description_lower:
                return AccountClassification(
                    account_type="Receivable",
                    root_type="Asset",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_trade_receivable",
                    notes="130xx = Trade Receivables (RGS)",
                )
            elif code.startswith("139") or "te ontvangen" in description_lower:
                return AccountClassification(
                    account_type="Receivable",
                    root_type="Asset",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_accrued_receivable",
                    notes="139xx = Accrued Receivables (RGS)",
                )
            elif any(keyword in description_lower for keyword in self.receivable_keywords):
                return AccountClassification(
                    account_type="Receivable",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_receivable_keyword",
                    notes="13xx with receivable keyword",
                )
            else:
                return AccountClassification(
                    account_type="Current Asset",
                    root_type="Asset",
                    confidence=ClassificationConfidence.LOW,
                    strategy_used="code_pattern_13xx_fallback",
                    notes="13xx fallback to Current Asset",
                )

        # Stock/Inventory (14xx)
        if code.startswith("14") or "voorraad" in description_lower:
            return AccountClassification(
                account_type="Stock",
                root_type="Asset",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_stock",
                notes="14xx = Stock/Inventory (RGS)",
            )

        # Tax accounts (15xx)
        if code.startswith("15"):
            if "btw" in description_lower or "belasting" in description_lower:
                return AccountClassification(
                    account_type="Tax",
                    root_type="Liability",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_tax",
                    notes="15xx with tax keyword",
                )
            else:
                return AccountClassification(
                    account_type="Current Liability",
                    root_type="Liability",
                    confidence=ClassificationConfidence.LOW,
                    strategy_used="code_pattern_15xx",
                    notes="15xx = Current Liability (RGS)",
                )

        # Other Current Liabilities (16xx-19xx)
        if code.startswith(("16", "17", "18", "19")):
            return AccountClassification(
                account_type="Current Liability",
                root_type="Liability",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_current_liability",
                notes="16xx-19xx = Current Liabilities (RGS)",
            )

        # Payables (20xx, 21xx, 44xx)
        if code.startswith("20") or code.startswith("21") or code.startswith("44"):
            if code.startswith("440") or "handelscrediteuren" in description_lower:
                return AccountClassification(
                    account_type="Payable",
                    root_type="Liability",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_trade_payable",
                    notes="440xx = Trade Payables (RGS)",
                )
            elif code.startswith("449") or "te betalen" in description_lower:
                return AccountClassification(
                    account_type="Payable",
                    root_type="Liability",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_accrued_payable",
                    notes="449xx = Accrued Payables (RGS)",
                )
            elif any(keyword in description_lower for keyword in self.payable_keywords):
                return AccountClassification(
                    account_type="Payable",
                    root_type="Liability",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_payable_keyword",
                    notes="20xx/21xx/44xx with payable keyword",
                )
            else:
                return AccountClassification(
                    account_type="Current Liability",
                    root_type="Liability",
                    confidence=ClassificationConfidence.LOW,
                    strategy_used="code_pattern_payable_fallback",
                    notes="20xx/21xx/44xx fallback to Current Liability",
                )

        # Cost of Goods Sold (40xx-43xx, not 44xx which is payables)
        if code.startswith(("40", "41", "42", "43")):
            return AccountClassification(
                account_type="Cost of Goods Sold",
                root_type="Expense",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_cogs",
                notes="40xx-43xx = Cost of Goods Sold (RGS)",
            )

        # Other Liabilities (22xx-29xx, 3xxx, 45xx-46xx)
        if code.startswith(("22", "23", "24", "25", "26", "27", "28", "29", "3", "45", "46")):
            if code.startswith(("45", "46")):
                if any(keyword in description_lower for keyword in self.payable_keywords):
                    return AccountClassification(
                        account_type="Payable",
                        root_type="Liability",
                        confidence=ClassificationConfidence.MEDIUM,
                        strategy_used="code_pattern_45_46_payable",
                        notes="45xx/46xx with payable keyword",
                    )
            return AccountClassification(
                account_type="Current Liability",
                root_type="Liability",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_liability_range",
                notes="2xxx-3xxx/45xx-46xx = Liabilities (RGS)",
            )

        # Equity (5xxx, 24xx-27xx)
        if code.startswith("5") or code.startswith(("24", "25", "26", "27")):
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_equity",
                notes="5xxx or 24xx-27xx = Equity (RGS)",
            )

        # Personnel costs (6xxx)
        if code.startswith("6"):
            return AccountClassification(
                account_type="Expense Account",
                root_type="Expense",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_personnel_expense",
                notes="6xxx = Personnel Expenses (RGS)",
            )

        # Financial income/costs (7xxx)
        if code.startswith("7"):
            if "rente" in description_lower and (
                "ontvangen" in description_lower or "baten" in description_lower
            ):
                return AccountClassification(
                    account_type="Income Account",
                    root_type="Income",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_financial_income",
                    notes="7xxx with interest income keywords",
                )
            else:
                return AccountClassification(
                    account_type="Expense Account",
                    root_type="Expense",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="code_pattern_financial_expense",
                    notes="7xxx = Financial Expenses (RGS)",
                )

        # Revenue (8xxx)
        if code.startswith("8"):
            if any(word in description_lower for word in ["opbrengst", "baten", "winst", "ontvangen"]):
                return AccountClassification(
                    account_type="Income Account",
                    root_type="Income",
                    confidence=ClassificationConfidence.HIGH,
                    strategy_used="code_pattern_revenue",
                    notes="8xxx with income keywords",
                )
            else:
                # Some 8xxx might be extraordinary expenses
                return AccountClassification(
                    account_type="Expense Account",
                    root_type="Expense",
                    confidence=ClassificationConfidence.LOW,
                    strategy_used="code_pattern_8xxx_fallback",
                    notes="8xxx without clear income keyword",
                )

        # Revenue (9xxx)
        if code.startswith("9"):
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="code_pattern_income",
                notes="9xxx = Income (RGS)",
            )

        return None

    def _classify_by_keywords(self, code: str, description: str) -> Optional[AccountClassification]:
        """
        Classify using Dutch accounting keywords.

        This is a fallback when category and code patterns don't give clear results.
        """
        description_lower = description.lower()

        # Check for receivable keywords
        if any(keyword in description_lower for keyword in self.receivable_keywords):
            return AccountClassification(
                account_type="Receivable",
                root_type="Asset",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_receivable",
                notes=f"Receivable keyword found in: {description}",
            )

        # Check for payable keywords
        if any(keyword in description_lower for keyword in self.payable_keywords):
            return AccountClassification(
                account_type="Payable",
                root_type="Liability",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_payable",
                notes=f"Payable keyword found in: {description}",
            )

        # Check for income keywords
        if any(keyword in description_lower for keyword in self.income_keywords):
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_income",
                notes=f"Income keyword found in: {description}",
            )

        # Check for equity keywords
        if any(keyword in description_lower for keyword in self.equity_keywords):
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_equity",
                notes=f"Equity keyword found in: {description}",
            )

        # Check for tax keywords
        if "btw" in description_lower or "belasting" in description_lower:
            return AccountClassification(
                account_type="Tax",
                root_type="Liability",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_tax",
                notes=f"Tax keyword found in: {description}",
            )

        # Check for stock/inventory keywords
        if "voorraad" in description_lower or "stock" in description_lower:
            return AccountClassification(
                account_type="Stock",
                root_type="Asset",
                confidence=ClassificationConfidence.MEDIUM,
                strategy_used="keyword_stock",
                notes=f"Stock keyword found in: {description}",
            )

        # Check for bank/cash keywords (only for asset range codes to avoid false positives like "Bankkosten")
        if code.startswith(("10", "11", "12", "1")):
            if "bank" in description_lower or "giro" in description_lower:
                return AccountClassification(
                    account_type="Bank",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="keyword_bank",
                    notes=f"Bank keyword found in asset range: {description}",
                )

            if "kas" in description_lower:
                return AccountClassification(
                    account_type="Cash",
                    root_type="Asset",
                    confidence=ClassificationConfidence.MEDIUM,
                    strategy_used="keyword_cash",
                    notes=f"Cash keyword found in asset range: {description}",
                )

        return None

    def _fallback_classification(self, code: str, description: str) -> AccountClassification:
        """
        Ultimate fallback classification based on first digit of code.

        This ensures we always return a classification, even if confidence is low.
        """
        if not code:
            return AccountClassification(
                account_type="Expense Account",
                root_type="Expense",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_no_code",
                notes="No code available - defaulted to Expense",
            )

        first_digit = code[0] if code else ""

        if first_digit in ["0", "1", "2", "3"]:
            return AccountClassification(
                account_type="Current Asset",
                root_type="Asset",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_first_digit",
                notes=f"First digit {first_digit} suggests Asset",
            )
        elif first_digit == "4":
            return AccountClassification(
                account_type="Current Liability",
                root_type="Liability",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_first_digit",
                notes=f"First digit {first_digit} suggests Liability",
            )
        elif first_digit == "5":
            return AccountClassification(
                account_type="Equity",
                root_type="Equity",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_first_digit",
                notes=f"First digit {first_digit} suggests Equity",
            )
        elif first_digit in ["6", "7"]:
            return AccountClassification(
                account_type="Expense Account",
                root_type="Expense",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_first_digit",
                notes=f"First digit {first_digit} suggests Expense",
            )
        elif first_digit in ["8", "9"]:
            return AccountClassification(
                account_type="Income Account",
                root_type="Income",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_first_digit",
                notes=f"First digit {first_digit} suggests Income",
            )
        else:
            return AccountClassification(
                account_type="Expense Account",
                root_type="Expense",
                confidence=ClassificationConfidence.LOW,
                strategy_used="fallback_ultimate",
                notes="Unknown pattern - defaulted to Expense",
            )

    def get_service_name(self) -> str:
        """Return the service name for logging"""
        return "AccountClassificationService"
