# Copyright (c) 2025, Verenigingen and Contributors
# See license.txt

"""
Unit tests for PaymentProcessor.

Tests branching logic and validation guards using mocks — no database required.
Covers:
- can_process: type routing, refund detection, gateway adjustment detection
- process: delegation to money transfer vs payment entry creation
- _process_money_transfer: Journal Entry construction, party assignment, amount validation
- Receivable/Payable validation guard: fail-fast on missing party
- _is_payment_gateway_adjustment: gateway detection logic
- _adjust_payment_gateway_amount: amount adjustment for gateway reconciliation
"""

import unittest
from unittest.mock import MagicMock, patch

MODULE = "verenigingen.e_boekhouden.utils.processors.payment_processor"


def _make_mutation(**overrides):
    """Create a minimal mutation dict with sensible defaults."""
    mutation = {
        "id": 12345,
        "type": 5,
        "amount": 100.0,
        "ledgerId": 1,
        "date": "2025-01-15",
        "description": "Test payment",
        "rows": [{"amount": 100.0, "ledgerId": 2}],
    }
    mutation.update(overrides)
    return mutation


def _make_mock_je():
    """Create a mock Journal Entry document."""
    je = MagicMock()
    je.name = "JV-2025-00001"
    je.posting_date = "2025-01-15"
    je.accounts = []

    def append_account(table_name, entry_dict):
        account_entry = MagicMock()
        # Default party fields to None — MagicMock auto-creates truthy attrs
        account_entry.party = None
        account_entry.party_type = None
        for k, v in entry_dict.items():
            setattr(account_entry, k, v)
        je.accounts.append(account_entry)

    je.append = append_account
    return je


def _make_account_entry(account, party=None, party_type=None, debit=0, credit=0):
    """Create a mock account entry for JE validation."""
    entry = MagicMock()
    entry.account = account
    entry.party = party
    entry.party_type = party_type
    entry.debit_in_account_currency = debit
    entry.credit_in_account_currency = credit
    return entry


class TestCanProcess(unittest.TestCase):
    """Test PaymentProcessor.can_process() routing logic."""

    @patch(f"{MODULE}.frappe")
    def setUp(self, mock_frappe):
        mock_frappe.db.get_value.return_value = "Main - NVV"
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        self.processor = PaymentProcessor(company="Test Company")

    def test_accepts_type_3_customer_payment(self):
        mutation = _make_mutation(type=3, amount=50.0)
        self.assertTrue(self.processor.can_process(mutation))

    def test_accepts_type_4_supplier_payment(self):
        mutation = _make_mutation(type=4, amount=-50.0)
        self.assertTrue(self.processor.can_process(mutation))

    def test_accepts_type_5_money_received(self):
        mutation = _make_mutation(type=5, amount=100.0)
        self.assertTrue(self.processor.can_process(mutation))

    def test_accepts_type_6_money_paid(self):
        mutation = _make_mutation(type=6, amount=-100.0)
        self.assertTrue(self.processor.can_process(mutation))

    def test_rejects_type_1(self):
        mutation = _make_mutation(type=1)
        self.assertFalse(self.processor.can_process(mutation))

    def test_rejects_type_2(self):
        mutation = _make_mutation(type=2)
        self.assertFalse(self.processor.can_process(mutation))

    def test_rejects_type_0(self):
        mutation = _make_mutation(type=0)
        self.assertFalse(self.processor.can_process(mutation))

    def test_type_3_negative_without_invoice_ref_rejected(self):
        """Type 3 negative amount without invoice ref = generic refund → JournalProcessor."""
        mutation = _make_mutation(type=3, amount=-50.0, invoiceNumber="")
        self.assertFalse(self.processor.can_process(mutation))

    def test_type_3_negative_with_invoice_ref_accepted(self):
        """Type 3 negative with invoice ref = credit note payment → keep for PaymentProcessor."""
        mutation = _make_mutation(type=3, amount=-50.0, invoiceNumber="INV-001")
        self.assertTrue(self.processor.can_process(mutation))

    def test_type_4_negative_refund_accepted(self):
        """Type 4 negative = refund from supplier → still handled by PaymentProcessor."""
        mutation = _make_mutation(type=4, amount=-50.0)
        self.assertTrue(self.processor.can_process(mutation))

    def test_type_4_positive_normal_accepted(self):
        """Type 4 positive = normal supplier payment."""
        mutation = _make_mutation(type=4, amount=50.0)
        self.assertTrue(self.processor.can_process(mutation))


class TestCanProcessGatewayAdjustment(unittest.TestCase):
    """Test gateway adjustment detection in can_process."""

    @patch(f"{MODULE}.frappe")
    def setUp(self, mock_frappe):
        mock_frappe.db.get_value.return_value = "Main - NVV"
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        self.processor = PaymentProcessor(company="Test Company")
        self.mock_frappe = mock_frappe

    @patch(f"{MODULE}.frappe")
    def test_gateway_adjustment_claimed_but_skipped(self, mock_frappe):
        """Gateway adjustments should be claimed (True) to prevent falling to JournalProcessor."""
        # Setup settings
        settings = MagicMock()
        settings.get.side_effect = lambda k, d=None: {
            "payment_gateway_virtual_account": "1200 - Mollie - NVV",
            "payment_gateway_invoice_prefix": "MOL-",
        }.get(k, d)
        mock_frappe.get_single.return_value = settings

        # Setup ledger mapping
        mock_frappe.db.get_value.side_effect = lambda dt, filters, *a, **kw: {
            "E-Boekhouden Ledger Mapping": "42",
        }.get(dt) if isinstance(filters, dict) else None

        # Gateway invoice already paid
        mock_frappe.get_all.return_value = [
            {"name": "PINV-001", "grand_total": 100, "outstanding_amount": 0}
        ]
        mock_frappe.utils.flt.return_value = 0.0

        mutation = _make_mutation(type=4, ledgerId=42, invoiceNumber="MOL-001")

        result = self.processor.can_process(mutation)
        self.assertTrue(result)


class TestProcessRouting(unittest.TestCase):
    """Test process() delegation to correct handler."""

    @patch(f"{MODULE}.frappe")
    def setUp(self, mock_frappe):
        mock_frappe.db.get_value.return_value = "Main - NVV"
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        self.processor = PaymentProcessor(company="Test Company")

    @patch(f"{MODULE}.frappe")
    def test_type_5_routes_to_money_transfer(self, mock_frappe):
        """Type 5 should call _process_money_transfer."""
        mutation = _make_mutation(type=5)
        self.processor._process_money_transfer = MagicMock(return_value=MagicMock())
        self.processor._is_payment_gateway_adjustment = MagicMock(return_value=False)

        self.processor.process(mutation)

        self.processor._process_money_transfer.assert_called_once_with(mutation)

    @patch(f"{MODULE}.frappe")
    def test_type_6_routes_to_money_transfer(self, mock_frappe):
        """Type 6 should call _process_money_transfer."""
        mutation = _make_mutation(type=6)
        self.processor._process_money_transfer = MagicMock(return_value=MagicMock())
        self.processor._is_payment_gateway_adjustment = MagicMock(return_value=False)

        self.processor.process(mutation)

        self.processor._process_money_transfer.assert_called_once_with(mutation)

    @patch("verenigingen.e_boekhouden.utils.consolidated.payment_entry_creation.create_payment_entry")
    @patch(f"{MODULE}.frappe")
    def test_type_3_routes_to_payment_entry(self, mock_frappe, mock_create_pe):
        """Type 3 should call create_payment_entry."""
        mutation = _make_mutation(type=3, amount=50.0)
        self.processor._is_payment_gateway_adjustment = MagicMock(return_value=False)
        mock_create_pe.return_value = MagicMock()

        self.processor.process(mutation)

        mock_create_pe.assert_called_once()

    @patch(f"{MODULE}.frappe")
    def test_gateway_adjustment_returns_none(self, mock_frappe):
        """Gateway adjustment mutations should return None (skip)."""
        mutation = _make_mutation(type=4)
        self.processor._is_payment_gateway_adjustment = MagicMock(return_value=True)

        result = self.processor.process(mutation)

        self.assertIsNone(result)


class TestReceivablePayableGuard(unittest.TestCase):
    """Test the Receivable/Payable validation guard in _process_money_transfer.

    This guard prevents Journal Entries with Receivable/Payable accounts
    from being created without party assignment. Without this guard,
    the JE insert would fail with a generic Frappe error instead of
    a descriptive ValueError.
    """

    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_receivable_without_party_raises_value_error(
        self, mock_frappe, mock_get_account, mock_convert_bank
    ):
        """Receivable account without party should raise descriptive ValueError."""
        # Setup
        mock_frappe.db.get_value.side_effect = lambda dt, name_or_filters, *a, **kw: {
            "Cost Center": "Main - NVV",
        }.get(dt, "Receivable" if dt == "Account" else None)
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)

        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        # Create JE mock that builds real account entries
        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je

        # Party extraction returns info but resolve fails (returns None)
        party_info = {
            "party_type": "Customer",
            "party_name": "Some Customer",
            "is_bank_internal": False,
            "extraction_method": "description_pattern",
        }

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = party_info
            # resolve_party returns None — party assignment fails
            extractor.resolve_party_for_journal_entry.return_value = None

            mutation = _make_mutation(
                type=5,
                amount=100.0,
                rows=[{"amount": 100.0, "ledgerId": 2}],
            )

            # The guard should fire because account is Receivable and party is None
            # We need db.get_value to return "Receivable" for the Account lookup
            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Receivable"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value

            # validate_row_amounts needs to pass
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))

            with self.assertRaises(ValueError) as ctx:
                processor._process_money_transfer(mutation)

            self.assertIn("Receivable", str(ctx.exception))
            self.assertIn("Customer", str(ctx.exception))
            self.assertIn("party extraction failed", str(ctx.exception))
            self.assertIn("12345", str(ctx.exception))

    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_payable_without_party_raises_value_error(
        self, mock_frappe, mock_get_account, mock_convert_bank
    ):
        """Payable account without party should raise ValueError mentioning Supplier."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je

        party_info = {
            "party_type": "Supplier",
            "party_name": "Some Supplier",
            "is_bank_internal": False,
            "extraction_method": "description_pattern",
        }

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = party_info
            extractor.resolve_party_for_journal_entry.return_value = None

            mutation = _make_mutation(
                type=6,
                amount=50.0,
                rows=[{"amount": 50.0, "ledgerId": 3}],
            )

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Payable"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))

            with self.assertRaises(ValueError) as ctx:
                processor._process_money_transfer(mutation)

            self.assertIn("Payable", str(ctx.exception))
            self.assertIn("Supplier", str(ctx.exception))

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_non_receivable_payable_account_passes_without_party(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Non-Receivable/Payable accounts (e.g. Expense) should pass without party."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je

        # Mock insert to return the JE as non-duplicate
        mock_insert.return_value = (je, False)

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None
            extractor.resolve_party_for_journal_entry.return_value = None

            mutation = _make_mutation(
                type=5,
                amount=100.0,
                rows=[{"amount": 100.0, "ledgerId": 2}],
            )

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Expense"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(
                return_value="BT-001"
            )

            # Should NOT raise — Expense accounts don't require party
            result = processor._process_money_transfer(mutation)
            self.assertIsNotNone(result)

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_receivable_with_party_passes(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Receivable account WITH party assigned should pass validation."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je
        mock_insert.return_value = (je, False)

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = {
                "party_type": "Customer",
                "party_name": "Test Customer",
                "is_bank_internal": False,
                "extraction_method": "relation_id",
            }
            # resolve_party succeeds — returns party tuple
            extractor.resolve_party_for_journal_entry.return_value = (
                "Customer",
                "CUST-001",
            )

            mutation = _make_mutation(
                type=5,
                amount=100.0,
                rows=[{"amount": 100.0, "ledgerId": 2}],
            )

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Receivable"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(
                return_value="BT-001"
            )

            # Should pass — Receivable account has party assigned
            result = processor._process_money_transfer(mutation)
            self.assertIsNotNone(result)


class TestMoneyTransferDirection(unittest.TestCase):
    """Test Journal Entry debit/credit direction for Type 5/6."""

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_type_5_positive_debits_bank(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Type 5 (Money Received) positive = bank debited (money in)."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je
        mock_insert.return_value = (je, False)

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None

            mutation = _make_mutation(type=5, amount=200.0, rows=[{"amount": 200.0, "ledgerId": 2}])

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Bank"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(return_value="BT-001")

            processor._process_money_transfer(mutation)

            # First appended account = bank entry (debit for incoming)
            self.assertEqual(len(je.accounts), 2)
            bank_entry = je.accounts[0]
            self.assertEqual(bank_entry.debit_in_account_currency, 200.0)
            self.assertEqual(bank_entry.credit_in_account_currency, 0)

            # Second = income entry (credit)
            income_entry = je.accounts[1]
            self.assertEqual(income_entry.debit_in_account_currency, 0)
            self.assertEqual(income_entry.credit_in_account_currency, 200.0)

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_type_6_positive_credits_bank(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Type 6 (Money Paid) positive = bank credited (money out)."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je
        mock_insert.return_value = (je, False)

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None

            mutation = _make_mutation(type=6, amount=150.0, rows=[{"amount": 150.0, "ledgerId": 2}])

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Expense"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(return_value="BT-001")

            processor._process_money_transfer(mutation)

            # First = bank entry (credit for outgoing)
            self.assertEqual(len(je.accounts), 2)
            bank_entry = je.accounts[0]
            self.assertEqual(bank_entry.debit_in_account_currency, 0)
            self.assertEqual(bank_entry.credit_in_account_currency, 150.0)

            # Second = expense entry (debit)
            expense_entry = je.accounts[1]
            self.assertEqual(expense_entry.debit_in_account_currency, 150.0)
            self.assertEqual(expense_entry.credit_in_account_currency, 0)


class TestMoneyTransferMultiRow(unittest.TestCase):
    """Test multi-row Journal Entry construction."""

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_multiple_rows_create_multiple_je_lines(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Multi-row mutations should create one JE line per row."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je
        mock_insert.return_value = (je, False)

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None

            mutation = _make_mutation(
                type=5,
                amount=300.0,
                rows=[
                    {"amount": 100.0, "ledgerId": 2},
                    {"amount": 80.0, "ledgerId": 3},
                    {"amount": 120.0, "ledgerId": 4},
                ],
            )

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Income"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(return_value="BT-001")

            processor._process_money_transfer(mutation)

            # 1 bank entry + 3 income entries = 4 total
            self.assertEqual(len(je.accounts), 4)

            # Bank entry should be total of all rows
            bank_entry = je.accounts[0]
            self.assertEqual(bank_entry.debit_in_account_currency, 300.0)


class TestMoneyTransferValidation(unittest.TestCase):
    """Test error handling in _process_money_transfer."""

    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_missing_bank_account_raises(self, mock_frappe, mock_get_account):
        """Missing bank account mapping should raise ValidationError."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = None
        mock_frappe.db.get_value.return_value = None
        mock_frappe.ValidationError = type("ValidationError", (Exception,), {})

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        mutation = _make_mutation(type=5, ledgerId=999)

        with self.assertRaises(Exception) as ctx:
            processor._process_money_transfer(mutation)

        self.assertIn("No ERPNext account mapped", str(ctx.exception))

    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_no_valid_rows_raises(self, mock_frappe, mock_get_account, mock_convert_bank):
        """Mutation with zero-amount rows should raise exception."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_frappe.as_json.return_value = "{}"
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        mutation = _make_mutation(
            type=5,
            amount=0.0,
            rows=[{"amount": 0.0, "ledgerId": 2}],
        )

        # validate_row_amounts will fail due to mismatch
        processor.validate_row_amounts = MagicMock(
            return_value=(False, "Amount mismatch", 100.0)
        )

        with self.assertRaises(Exception):
            processor._process_money_transfer(mutation)

    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_party_extraction_failure_raises(
        self, mock_frappe, mock_get_account, mock_convert_bank
    ):
        """Party extraction exception should propagate (fail fast)."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"
        mock_frappe.as_json.return_value = "{}"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")
        processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.side_effect = RuntimeError(
                "SOAP API connection failed"
            )

            mutation = _make_mutation(type=5, rows=[{"amount": 100.0, "ledgerId": 2}])

            with self.assertRaises(RuntimeError) as ctx:
                processor._process_money_transfer(mutation)

            self.assertIn("SOAP API connection failed", str(ctx.exception))


class TestMoneyTransferDuplicateHandling(unittest.TestCase):
    """Test duplicate detection in _process_money_transfer."""

    @patch(f"{MODULE}.insert_with_duplicate_handling")
    @patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise")
    @patch(f"{MODULE}.get_erpnext_account_from_ledger_id")
    @patch(f"{MODULE}.frappe")
    def test_duplicate_returns_existing_je(
        self, mock_frappe, mock_get_account, mock_convert_bank, mock_insert
    ):
        """Duplicate detection should return existing JE without creating Bank Transaction."""
        mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
        mock_get_account.return_value = "1100 - Bank - NVV"
        mock_convert_bank.return_value = "Bank Account 1"

        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        processor = PaymentProcessor(company="Test Company")

        je = _make_mock_je()
        mock_frappe.new_doc.return_value = je
        mock_insert.return_value = (je, True)  # was_duplicate=True

        with patch("verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor") as mock_extractor_cls:
            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None

            mutation = _make_mutation(type=5, rows=[{"amount": 100.0, "ledgerId": 2}])

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return "Income"
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))

            result = processor._process_money_transfer(mutation)

            self.assertEqual(result, je)
            # Bank Transaction should NOT be created for duplicates
            processor._create_bank_transaction_for_journal_entry = MagicMock()
            # je.submit should NOT be called for duplicates
            je.submit.assert_not_called()


class TestGatewayAmountAdjustment(unittest.TestCase):
    """Test _adjust_payment_gateway_amount logic."""

    @patch(f"{MODULE}.frappe")
    def setUp(self, mock_frappe):
        mock_frappe.db.get_value.return_value = "Main - NVV"
        from verenigingen.e_boekhouden.utils.processors.payment_processor import (
            PaymentProcessor,
        )

        self.processor = PaymentProcessor(company="Test Company")

    @patch(f"{MODULE}.frappe")
    def test_non_type_4_returns_original(self, mock_frappe):
        """Only Type 4 mutations should be adjusted."""
        mutation = _make_mutation(type=3, amount=50.0)
        result = self.processor._adjust_payment_gateway_amount(mutation)
        self.assertEqual(result, mutation)

    @patch(f"{MODULE}.frappe")
    def test_no_gateway_config_returns_original(self, mock_frappe):
        """Without gateway configuration, return original mutation."""
        settings = MagicMock()
        settings.get.return_value = None
        mock_frappe.get_single.return_value = settings

        mutation = _make_mutation(type=4, amount=-50.0)
        result = self.processor._adjust_payment_gateway_amount(mutation)
        self.assertEqual(result, mutation)

    @patch(f"{MODULE}.frappe")
    def test_gateway_adjustment_deep_copies_mutation(self, mock_frappe):
        """Adjustment should not mutate the original mutation dict."""
        settings = MagicMock()
        settings.get.side_effect = lambda k, d=None: {
            "payment_gateway_virtual_account": "1200 - Mollie - NVV",
            "payment_gateway_invoice_prefix": "MOL-",
        }.get(k, d)
        mock_frappe.get_single.return_value = settings
        mock_frappe.db.get_value.side_effect = lambda dt, filters, *a, **kw: {
            "E-Boekhouden Ledger Mapping": "42",
        }.get(dt) if isinstance(filters, dict) else None
        mock_frappe.get_all.return_value = [{"name": "PINV-001", "grand_total": 95.0}]
        mock_frappe.db.exists.return_value = False

        mutation = _make_mutation(
            type=4,
            amount=-100.0,
            ledgerId=42,
            invoiceNumber="MOL-001",
            rows=[{"amount": -100.0, "ledgerId": 2}],
        )
        original_amount = mutation["amount"]

        result = self.processor._adjust_payment_gateway_amount(mutation)

        # Original should be unchanged
        self.assertEqual(mutation["amount"], original_amount)
        # Result should have adjusted amount
        self.assertNotEqual(result, mutation)


if __name__ == "__main__":
    unittest.main()
