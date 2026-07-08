"""
Unit tests for E-Boekhouden payment direction determination (real production path).

Previously this file reimplemented the `is_incoming` direction formula inline in every
test method, so it could never fail on a regression to the actual production logic in
`PaymentProcessor._process_money_transfer` (payment_processor.py). These tests now drive
the real method (mocking only the frappe/DB/account-resolution boundaries, following the
pattern established in test_payment_processor.py) and assert the resulting Journal Entry
debit/credit lines.

Covers the reversal/correction cases (a negative amount flips the direction implied by
the mutation type) including the historical mutation-9307 bug: a Type 5 (Money Received)
mutation recorded with a negative row amount must be treated as OUTGOING, not incoming.
"""

import unittest
from unittest.mock import MagicMock, patch

MODULE = "verenigingen.e_boekhouden.utils.processors.payment_processor"


def _make_mutation(**overrides):
    """Create a minimal mutation dict with sensible defaults."""
    mutation = {
        "id": 9307,
        "type": 5,
        "amount": 75.0,
        "ledgerId": 1,
        "date": "2025-01-15",
        "description": "Test payment",
        "rows": [{"amount": 75.0, "ledgerId": 2}],
    }
    mutation.update(overrides)
    return mutation


def _make_mock_je():
    """Create a mock Journal Entry document that records appended account rows."""
    je = MagicMock()
    je.name = "JV-2025-00001"
    je.accounts = []

    def append_account(table_name, entry_dict):
        account_entry = MagicMock()
        account_entry.party = None
        account_entry.party_type = None
        for k, v in entry_dict.items():
            setattr(account_entry, k, v)
        je.accounts.append(account_entry)

    je.append = append_account
    return je


class _DirectionTestBase(unittest.TestCase):
    """Shared harness: run the real _process_money_transfer with collaborator mocks."""

    def _run(self, mutation, account_type="Expense"):
        with (
            patch(f"{MODULE}.insert_with_duplicate_handling") as mock_insert,
            patch(f"{MODULE}.convert_gl_account_to_bank_account_or_raise") as mock_convert_bank,
            patch(f"{MODULE}.get_erpnext_account_from_ledger_id") as mock_get_account,
            patch(f"{MODULE}.frappe") as mock_frappe,
            patch(
                "verenigingen.e_boekhouden.utils.party_extractor.EBoekhoudenPartyExtractor"
            ) as mock_extractor_cls,
        ):
            mock_frappe.utils.flt.side_effect = lambda x, *a: float(x or 0)
            mock_get_account.return_value = "1100 - Bank - NVV"
            mock_convert_bank.return_value = "Bank Account 1"

            def side_effect_get_value(dt, name_or_filters, *args, **kwargs):
                if dt == "Account":
                    return account_type
                if dt == "Cost Center":
                    return "Main - NVV"
                return None

            mock_frappe.db.get_value.side_effect = side_effect_get_value

            extractor = MagicMock()
            mock_extractor_cls.return_value = extractor
            extractor.extract_party_from_mutation.return_value = None

            from verenigingen.e_boekhouden.utils.processors.payment_processor import (
                PaymentProcessor,
            )

            processor = PaymentProcessor(company="Test Company")
            processor.validate_row_amounts = MagicMock(return_value=(True, "", 0.0))
            processor._create_bank_transaction_for_journal_entry = MagicMock(return_value="BT-001")

            je = _make_mock_je()
            mock_frappe.new_doc.return_value = je
            mock_insert.return_value = (je, False)

            processor._process_money_transfer(mutation)
            return je


class TestPaymentDirectionReversal(_DirectionTestBase):
    """Negative amounts flip the direction implied by mutation type (correction/reversal)."""

    def test_type5_negative_amount_is_outgoing_not_incoming(self):
        """Type 5 (Money Received) with a NEGATIVE amount must be OUTGOING (bank credited)."""
        mutation = _make_mutation(type=5, amount=-75.0, rows=[{"amount": -75.0, "ledgerId": 2}])

        je = self._run(mutation)

        bank_entry = je.accounts[0]
        self.assertEqual(
            bank_entry.credit_in_account_currency,
            75.0,
            "Negative-amount Type 5 must credit (not debit) the bank account",
        )
        self.assertEqual(bank_entry.debit_in_account_currency, 0)

    def test_type6_negative_amount_is_incoming_not_outgoing(self):
        """Type 6 (Money Paid) with a NEGATIVE amount must be INCOMING (bank debited)."""
        mutation = _make_mutation(type=6, amount=-75.0, rows=[{"amount": -75.0, "ledgerId": 2}])

        je = self._run(mutation)

        bank_entry = je.accounts[0]
        self.assertEqual(
            bank_entry.debit_in_account_currency,
            75.0,
            "Negative-amount Type 6 must debit (not credit) the bank account",
        )
        self.assertEqual(bank_entry.credit_in_account_currency, 0)


class TestMutation9307RowFallbackRegression(_DirectionTestBase):
    """Regression: when the main `amount` is 0, direction is derived from the summed row
    amounts, and that sum must preserve sign (not be abs()'d) -- the historical mutation
    9307 bug (a Type 5 mutation with a negative row amount was mis-recorded as incoming)."""

    def test_zero_main_amount_falls_back_to_signed_row_sum(self):
        """Type 5 with amount=0 but a single -75 row must resolve to OUTGOING: the
        row-sum fallback must preserve sign, or real transactions silently get the
        wrong bank direction."""
        mutation = _make_mutation(type=5, amount=0.0, rows=[{"amount": -75.0, "ledgerId": 2}])

        je = self._run(mutation)

        bank_entry = je.accounts[0]
        self.assertEqual(bank_entry.credit_in_account_currency, 75.0)
        self.assertEqual(bank_entry.debit_in_account_currency, 0)


if __name__ == "__main__":
    unittest.main()
