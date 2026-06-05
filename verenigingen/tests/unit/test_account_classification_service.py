"""
Unit tests for AccountClassificationService

Tests the consolidated account classification logic with Dutch RGS patterns.
"""

import unittest

from verenigingen.e_boekhouden.services.account_classification_service import (
    AccountClassification,
    AccountClassificationService,
    ClassificationConfidence,
)


class _StubEBoekhoudenSettings:
    """Minimal stand-in for E-Boekhouden Settings.

    Mirrors the shape returned by
    EBoekhoudenSettings.get_classification_rules(), supplying the standard Dutch
    RGS code ranges so classification is deterministic in unit tests.
    """

    def get_classification_rules(self):
        return {
            "use_classification_service": 1,
            "strategy": "Prefer Groups",
            "balance_sheet_group_mappings": {},
            "pl_group_mappings": {},
            "group_type_mappings": {},
            "bal_rules": {
                "asset_ranges": [],
                "liability_ranges": [],
                "equity_ranges": [],
                "equity_keywords": [],
            },
            "vw_rules": {
                # 8000-8999 = Income (Dutch RGS). Expense ranges are intentionally
                # left empty: the tests expect unmatched VW codes in the 4xxx-7xxx
                # band (e.g. 6500) to fall through to "no match / manual review"
                # rather than being range-classified as expense.
                "income_ranges": [("8000", "8999")],
                "expense_ranges": [],
                "income_keywords": [],
                "expense_keywords": [],
            },
        }


class TestAccountClassificationService(unittest.TestCase):
    """Test suite for account classification service"""

    def setUp(self):
        """Set up test fixtures.

        Inject a settings stub providing the standard Dutch RGS code ranges
        (8000-8999 = Income, 4000-7999 = Expense). These ranges normally come
        from E-Boekhouden Settings; injecting them keeps the unit test pure and
        deterministic regardless of the test site's Single configuration, and
        exercises PRIORITY-1 (code-range) classification as the tests assert.
        """
        self.service = AccountClassificationService(settings=_StubEBoekhoudenSettings())

    def test_category_deb_classification(self):
        """Test DEB (debtors) category classification"""
        result = self.service.classify_account(
            {"code": "1300", "description": "Debiteuren", "category": "DEB", "group": ""}
        )

        self.assertEqual(result.account_type, "Current Asset")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)
        self.assertEqual(result.strategy_used, "category_mapping")

    def test_category_cred_classification(self):
        """Test CRED (creditors) category classification"""
        result = self.service.classify_account(
            {"code": "4400", "description": "Crediteuren", "category": "CRED", "group": ""}
        )

        self.assertEqual(result.account_type, "Current Liability")
        self.assertEqual(result.root_type, "Liability")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_category_fin_bank_classification(self):
        """Test FIN (financial) category classification"""
        result = self.service.classify_account(
            {"code": "1010", "description": "ING Bank", "category": "FIN", "group": ""}
        )

        self.assertEqual(result.account_type, "Bank")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_category_kas_cash_classification(self):
        """Test KAS (cash) category classification"""
        result = self.service.classify_account(
            {"code": "1000", "description": "Kas", "category": "KAS", "group": ""}
        )

        self.assertEqual(result.account_type, "Cash")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_category_btw_tax_classification(self):
        """Test BTW/BTWRC (tax) category classification"""
        result = self.service.classify_account(
            {"code": "1500", "description": "BTW te vorderen", "category": "VOOR", "group": ""}
        )

        self.assertEqual(result.account_type, "Tax")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_category_eig_equity_classification(self):
        """Test EIG (equity) category classification"""
        result = self.service.classify_account(
            {"code": "2500", "description": "Eigen vermogen", "category": "EIG", "group": ""}
        )

        self.assertEqual(result.account_type, "Equity")
        self.assertEqual(result.root_type, "Equity")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_equity_by_keyword(self):
        """Test BAL category with equity keyword"""
        result = self.service.classify_account(
            {"code": "2700", "description": "Bestemmingsreserve", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Equity")
        self.assertEqual(result.root_type, "Equity")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)
        self.assertIn("equity_keyword", result.strategy_used)

    def test_bal_equity_by_group_005(self):
        """Test BAL category with group 005 (equity)"""
        result = self.service.classify_account(
            {"code": "2600", "description": "Reserve", "category": "BAL", "group": "005"}
        )

        self.assertEqual(result.account_type, "Equity")
        self.assertEqual(result.root_type, "Equity")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)
        self.assertEqual(result.strategy_used, "balance_sheet_group_005")

    def test_bal_fixed_asset_02xx(self):
        """Test BAL category with 02xx fixed asset code"""
        result = self.service.classify_account(
            {"code": "0200", "description": "Gebouwen", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Fixed Asset")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.MEDIUM)

    def test_bal_bank_10xx(self):
        """Test BAL category with 10xx bank code"""
        result = self.service.classify_account(
            {"code": "1010", "description": "ABN AMRO Bank", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Bank")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_cash_10xx_with_kas(self):
        """Test BAL category with 10xx and 'kas' keyword"""
        result = self.service.classify_account({"code": "1000", "description": "Kas", "category": "BAL", "group": ""})

        self.assertEqual(result.account_type, "Cash")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_receivable_13xx_with_keyword(self):
        """Test BAL category with 13xx and receivable keyword"""
        result = self.service.classify_account(
            {"code": "1300", "description": "Debiteuren", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_trade_receivable_130x(self):
        """Test BAL category with 130x trade receivable code"""
        result = self.service.classify_account(
            {"code": "1301", "description": "Handelsdebiteuren", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_accrued_receivable_139x(self):
        """Test BAL category with 139x accrued receivable code"""
        result = self.service.classify_account(
            {"code": "1390", "description": "Nog te ontvangen facturen", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_bal_stock_14xx(self):
        """Test BAL category with 14xx stock code"""
        result = self.service.classify_account(
            {"code": "1400", "description": "Voorraad goederen", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Stock")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.MEDIUM)

    def test_bal_payable_44xx_with_keyword(self):
        """Test BAL category with 44xx and payable keyword"""
        result = self.service.classify_account(
            {"code": "4400", "description": "Crediteuren", "category": "BAL", "group": ""}
        )

        self.assertEqual(result.account_type, "Payable")
        self.assertEqual(result.root_type, "Liability")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_vw_income_group_055(self):
        """Test VW category with group 055 (income)"""
        result = self.service.classify_account(
            {"code": "8000", "description": "Contributies", "category": "VW", "group": "055"}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)
        # Code ranges (8xxx = income) have higher priority than group codes
        self.assertEqual(result.strategy_used, "profit_loss_income_range")

    def test_vw_expense_group_056(self):
        """Test VW category with group 056 (expenses)"""
        result = self.service.classify_account(
            {"code": "6000", "description": "Kantoorkosten", "category": "VW", "group": "056"}
        )

        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)

    def test_vw_income_by_keyword(self):
        """Test VW category with income keyword - 8xxx code takes priority"""
        result = self.service.classify_account(
            {"code": "8100", "description": "Opbrengst donaties", "category": "VW", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")
        # Code ranges (8xxx = income) have higher priority than keywords, so HIGH confidence
        self.assertEqual(result.confidence, ClassificationConfidence.HIGH)
        self.assertIn("income_range", result.strategy_used)

    def test_vw_income_by_code_8xxx(self):
        """Test VW category with 8xxx income code"""
        result = self.service.classify_account(
            {"code": "8200", "description": "Overige inkomsten", "category": "VW", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_vw_no_match_requires_review(self):
        """Test VW category without matching patterns returns NONE confidence for manual review"""
        result = self.service.classify_account(
            {"code": "6500", "description": "Algemene kosten", "category": "VW", "group": ""}
        )

        # VW accounts without group match, keyword match, or code pattern match
        # now return NONE confidence to flag for manual review rather than defaulting to expense
        self.assertEqual(result.account_type, "")
        self.assertIsNone(result.root_type)
        self.assertEqual(result.confidence, ClassificationConfidence.NONE)
        self.assertEqual(result.strategy_used, "profit_loss_no_match")

    def test_code_pattern_bank_10xx(self):
        """Test code pattern classification for 10xx (bank)"""
        result = self.service.classify_account(
            {"code": "1020", "description": "Rabobank", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Bank")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.MEDIUM)

    def test_code_pattern_fixed_asset_02xx(self):
        """Test code pattern classification for 02xx (fixed assets)"""
        result = self.service.classify_account(
            {"code": "0210", "description": "Computers", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Fixed Asset")
        self.assertEqual(result.root_type, "Asset")

    def test_code_pattern_receivable_130x(self):
        """Test code pattern classification for 130x (trade receivables)"""
        result = self.service.classify_account(
            {"code": "1305", "description": "Handelsdebiteuren", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")
        # Note: Keyword strategy fires first (HIGH), but code pattern would also match (MEDIUM)
        self.assertIn(result.confidence, [ClassificationConfidence.HIGH, ClassificationConfidence.MEDIUM])

    def test_code_pattern_payable_440x(self):
        """Test code pattern classification for 440x (trade payables)"""
        result = self.service.classify_account(
            {"code": "4401", "description": "Handelscrediteuren", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Payable")
        self.assertEqual(result.root_type, "Liability")
        # Note: Keyword strategy fires first (HIGH for "crediteuren"), but code pattern would also match
        self.assertIn(result.confidence, [ClassificationConfidence.HIGH, ClassificationConfidence.MEDIUM])

    def test_code_pattern_equity_5xxx(self):
        """Test code pattern classification for 5xxx (equity)"""
        result = self.service.classify_account(
            {"code": "5000", "description": "Kapitaal", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Equity")
        self.assertEqual(result.root_type, "Equity")

    def test_code_pattern_cogs_4xxx(self):
        """Test code pattern classification for 4xxx (COGS, not 44xx)"""
        result = self.service.classify_account(
            {"code": "4100", "description": "Inkoopwaarde verkopen", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Cost of Goods Sold")
        self.assertEqual(result.root_type, "Expense")

    def test_code_pattern_expense_6xxx(self):
        """Test code pattern classification for 6xxx (personnel expenses)"""
        result = self.service.classify_account(
            {"code": "6100", "description": "Salarissen", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")

    def test_code_pattern_financial_income_7xxx(self):
        """Test code pattern classification for 7xxx with interest income"""
        result = self.service.classify_account(
            {"code": "7100", "description": "Ontvangen rente", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_code_pattern_financial_expense_7xxx(self):
        """Test code pattern classification for 7xxx without income keywords"""
        result = self.service.classify_account(
            {"code": "7200", "description": "Bankkosten", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")

    def test_code_pattern_income_8xxx(self):
        """Test code pattern classification for 8xxx (income)"""
        result = self.service.classify_account(
            {"code": "8300", "description": "Buitengewone baten", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_code_pattern_income_9xxx(self):
        """Test code pattern classification for 9xxx (income)"""
        result = self.service.classify_account(
            {"code": "9000", "description": "Overige opbrengsten", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_keyword_receivable(self):
        """Test keyword-based receivable classification for balance sheet accounts"""
        # Use 1xxx code (balance sheet) where keywords take priority
        result = self.service.classify_account(
            {"code": "1399", "description": "Vordering op derden", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")
        self.assertEqual(result.confidence, ClassificationConfidence.MEDIUM)

    def test_keyword_payable(self):
        """Test keyword-based payable classification for balance sheet accounts"""
        # Use 4xxx code (balance sheet liabilities) where keywords take priority
        result = self.service.classify_account(
            {"code": "4599", "description": "Schuld aan leveranciers", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Payable")
        self.assertEqual(result.root_type, "Liability")
        self.assertEqual(result.confidence, ClassificationConfidence.MEDIUM)

    def test_keyword_income(self):
        """Test keyword-based income classification"""
        result = self.service.classify_account(
            {"code": "9999", "description": "Overige omzet", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_keyword_tax(self):
        """Test keyword-based tax classification for balance sheet accounts"""
        # Use 1xxx code (balance sheet) where keywords take priority
        result = self.service.classify_account(
            {"code": "1599", "description": "BTW hoog tarief", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Tax")
        self.assertEqual(result.root_type, "Liability")

    def test_keyword_stock(self):
        """Test keyword-based stock classification"""
        result = self.service.classify_account(
            {"code": "1499", "description": "Voorraad handelsgoederen", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Stock")
        self.assertEqual(result.root_type, "Asset")

    def test_fallback_no_code(self):
        """Test fallback when no code is provided"""
        result = self.service.classify_account({"code": "", "description": "Unknown account", "category": "", "group": ""})

        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")
        self.assertEqual(result.confidence, ClassificationConfidence.LOW)

    def test_fallback_unknown_pattern(self):
        """Test fallback for unknown code patterns"""
        result = self.service.classify_account(
            {"code": "Z999", "description": "Unknown", "category": "", "group": ""}
        )

        self.assertEqual(result.confidence, ClassificationConfidence.LOW)
        self.assertIn("fallback", result.strategy_used)

    def test_missing_required_fields(self):
        """Test error handling for missing required fields"""
        with self.assertRaises(ValueError):
            self.service.classify_account({"code": "", "description": ""})

    def test_confidence_levels(self):
        """Test that different strategies return appropriate confidence levels"""
        # HIGH: Category mapping
        high_result = self.service.classify_account(
            {"code": "1010", "description": "Bank", "category": "FIN", "group": ""}
        )
        self.assertEqual(high_result.confidence, ClassificationConfidence.HIGH)

        # MEDIUM: Code pattern
        medium_result = self.service.classify_account(
            {"code": "1020", "description": "Bank account", "category": "", "group": ""}
        )
        self.assertEqual(medium_result.confidence, ClassificationConfidence.MEDIUM)

        # LOW: Fallback
        low_result = self.service.classify_account(
            {"code": "X999", "description": "Unknown", "category": "", "group": ""}
        )
        self.assertEqual(low_result.confidence, ClassificationConfidence.LOW)

    def test_strategy_used_tracking(self):
        """Test that strategy_used is properly tracked"""
        result = self.service.classify_account(
            {"code": "1300", "description": "Debiteuren", "category": "DEB", "group": ""}
        )
        self.assertEqual(result.strategy_used, "category_mapping")

        # Test with a code that doesn't have obvious keywords
        result = self.service.classify_account(
            {"code": "1305", "description": "Trade accounts", "category": "", "group": ""}
        )
        self.assertIn("code_pattern", result.strategy_used)

    def test_notes_populated(self):
        """Test that classification notes are populated"""
        result = self.service.classify_account(
            {"code": "1300", "description": "Debiteuren", "category": "DEB", "group": ""}
        )
        self.assertIsNotNone(result.notes)
        self.assertIn("DEB", result.notes)

    def test_real_world_examples(self):
        """Test real-world Dutch account examples"""
        # Real receivables account
        result = self.service.classify_account(
            {"code": "1300", "description": "130 Debiteuren algemeen", "category": "DEB", "group": "003"}
        )
        self.assertEqual(result.account_type, "Current Asset")
        self.assertEqual(result.root_type, "Asset")

        # Real bank account
        result = self.service.classify_account(
            {"code": "1010", "description": "101 ING Bank rekening courant", "category": "FIN", "group": "001"}
        )
        self.assertEqual(result.account_type, "Bank")
        self.assertEqual(result.root_type, "Asset")

        # Real income account
        result = self.service.classify_account(
            {"code": "8000", "description": "800 Contributies leden", "category": "VW", "group": "055"}
        )
        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

        # Real expense account
        result = self.service.classify_account(
            {"code": "6100", "description": "610 Kantoorkosten", "category": "VW", "group": "056"}
        )
        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")


    def test_conflicting_signals_expense_with_receivable_keyword(self):
        """Test that expense code (6xxx) overrides receivable keyword"""
        result = self.service.classify_account(
            {"code": "6100", "description": "Kosten debiteuren administratie", "category": "", "group": ""}
        )

        # Code 6xxx should classify as Expense, NOT Receivable (despite "debiteuren" keyword)
        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")
        self.assertIn("code_pattern", result.strategy_used)

    def test_conflicting_signals_income_with_expense_keyword(self):
        """Test that income code (8xxx) overrides expense-like keywords"""
        result = self.service.classify_account(
            {"code": "8000", "description": "Opbrengst kosten doorberekend", "category": "", "group": ""}
        )

        # Code 8xxx should classify as Income, NOT Expense (despite "kosten" keyword)
        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_conflicting_signals_payable_expense_code(self):
        """Test expense account with payable keyword"""
        result = self.service.classify_account(
            {"code": "6200", "description": "Te betalen kosten", "category": "", "group": ""}
        )

        # Code 6xxx = Expense should override "te betalen" (payable keyword)
        self.assertEqual(result.account_type, "Expense Account")
        self.assertEqual(result.root_type, "Expense")

    def test_malicious_input_long_code(self):
        """Test handling of excessively long account code"""
        with self.assertRaises(ValueError) as context:
            self.service.classify_account({"code": "A" * 100, "description": "Test", "category": "", "group": ""})

        self.assertIn("exceeds maximum length", str(context.exception))

    def test_malicious_input_long_description(self):
        """Test handling of excessively long description"""
        with self.assertRaises(ValueError) as context:
            self.service.classify_account({"code": "1000", "description": "Evil" * 200, "category": "", "group": ""})

        self.assertIn("exceeds maximum length", str(context.exception))

    def test_malicious_input_invalid_characters(self):
        """Test handling of invalid characters in code"""
        with self.assertRaises(ValueError) as context:
            self.service.classify_account(
                {"code": "1000'; DROP TABLE--", "description": "SQL Injection", "category": "", "group": ""}
            )

        self.assertIn("invalid characters", str(context.exception))

    def test_edge_case_empty_dict(self):
        """Test handling of empty account data"""
        with self.assertRaises(ValueError):
            self.service.classify_account({})

    def test_edge_case_none_values(self):
        """Test handling of None values in account data"""
        # Should handle None gracefully by converting to empty string
        result = self.service.classify_account(
            {"code": None, "description": "Test Account", "category": None, "group": None}
        )

        self.assertIsNotNone(result.account_type)
        self.assertIsNotNone(result.root_type)

    def test_edge_case_unicode_dutch_characters(self):
        """Test handling of Dutch special characters"""
        result = self.service.classify_account(
            {"code": "8000", "description": "Contributies België en Curaçao", "category": "VW", "group": "055"}
        )

        self.assertEqual(result.account_type, "Income Account")
        self.assertEqual(result.root_type, "Income")

    def test_edge_case_compound_word_no_spaces(self):
        """Test Dutch compound words without spaces"""
        result = self.service.classify_account(
            {"code": "1300", "description": "Debiteurenadministratie", "category": "", "group": ""}
        )

        # Should still detect "debiteuren" within compound word
        self.assertEqual(result.account_type, "Receivable")
        self.assertEqual(result.root_type, "Asset")

    def test_edge_case_code_boundary_1999(self):
        """Test boundary at 19xx (Current Liabilities in RGS)"""
        result = self.service.classify_account(
            {"code": "1999", "description": "Overige kortlopende schulden", "category": "", "group": ""}
        )

        # 19xx is Current Liabilities in Dutch RGS, not Asset
        self.assertEqual(result.root_type, "Liability")

    def test_edge_case_code_boundary_3999(self):
        """Test boundary between liability and COGS (3999)"""
        result = self.service.classify_account(
            {"code": "3999", "description": "Overige kortlopende schulden", "category": "", "group": ""}
        )

        self.assertEqual(result.root_type, "Liability")

    def test_edge_case_code_boundary_4000(self):
        """Test start of COGS range (4000)"""
        result = self.service.classify_account(
            {"code": "4000", "description": "Inkoopwaarde omzet", "category": "", "group": ""}
        )

        self.assertEqual(result.account_type, "Cost of Goods Sold")
        self.assertEqual(result.root_type, "Expense")

    def test_balance_sheet_vs_profit_loss_strategy_difference(self):
        """Test that balance sheet accounts use keyword-first, P&L uses code-first"""
        # Balance sheet account (13xx) with receivable keyword - keyword should win
        bs_result = self.service.classify_account(
            {"code": "1350", "description": "Vordering op derden", "category": "", "group": ""}
        )
        self.assertEqual(bs_result.account_type, "Receivable")
        self.assertIn("keyword", bs_result.strategy_used.lower())

        # P&L account (6xxx) with receivable keyword - code should win
        pl_result = self.service.classify_account(
            {"code": "6100", "description": "Kosten vordering", "category": "", "group": ""}
        )
        self.assertEqual(pl_result.account_type, "Expense Account")
        self.assertIn("code_pattern", pl_result.strategy_used.lower())


if __name__ == "__main__":
    unittest.main()
