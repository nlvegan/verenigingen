"""
Tests for Data Integrity Utilities

Tests for the data integrity utilities module including:
- insert_with_duplicate_handling() - race condition protection
- submit_with_duplicate_handling() - submittable document protection
- mask_pii_in_mutation() - PII masking for privacy compliance
- normalize_date() - date format normalization
- safe_log_mutation_error() - PII-safe error logging
"""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.e_boekhouden.utils.data_integrity import (
    _mask_value,
    _should_mask_field,
    insert_with_duplicate_handling,
    mask_pii_in_mutation,
    normalize_date,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestNormalizeDate(unittest.TestCase):
    """Tests for normalize_date() function"""

    def test_yyyymmdd_format(self):
        """Test E-Boekhouden YYYYMMDD format"""
        self.assertEqual(normalize_date("20250110"), "2025-01-10")
        self.assertEqual(normalize_date("20231231"), "2023-12-31")
        self.assertEqual(normalize_date("20240101"), "2024-01-01")

    def test_iso_datetime_format(self):
        """Test ISO datetime format with time component"""
        self.assertEqual(normalize_date("2025-01-10T00:00:00"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T12:30:45"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T23:59:59.999"), "2025-01-10")

    def test_iso_datetime_with_timezone(self):
        """Test ISO datetime format with timezone"""
        self.assertEqual(normalize_date("2025-01-10T00:00:00+01:00"), "2025-01-10")
        self.assertEqual(normalize_date("2025-01-10T00:00:00Z"), "2025-01-10")

    def test_already_correct_format(self):
        """Test already correct YYYY-MM-DD format"""
        self.assertEqual(normalize_date("2025-01-10"), "2025-01-10")
        self.assertEqual(normalize_date("2023-12-31"), "2023-12-31")

    def test_european_dash_format(self):
        """Test European DD-MM-YYYY format"""
        self.assertEqual(normalize_date("10-01-2025"), "2025-01-10")
        self.assertEqual(normalize_date("31-12-2023"), "2023-12-31")
        self.assertEqual(normalize_date("1-1-2024"), "2024-01-01")

    def test_european_slash_format(self):
        """Test European DD/MM/YYYY format"""
        self.assertEqual(normalize_date("10/01/2025"), "2025-01-10")
        self.assertEqual(normalize_date("31/12/2023"), "2023-12-31")

    def test_empty_and_none_values(self):
        """Test handling of empty and None values"""
        self.assertIsNone(normalize_date(None))
        self.assertIsNone(normalize_date(""))
        self.assertIsNone(normalize_date("   "))

    def test_string_conversion(self):
        """Test that non-string values are converted"""
        # Integer date representation
        result = normalize_date(20250110)
        self.assertEqual(result, "2025-01-10")


class TestMaskValue(unittest.TestCase):
    """Tests for _mask_value() internal function"""

    def test_none_value(self):
        """Test None value handling"""
        self.assertIsNone(_mask_value(None))

    def test_short_values(self):
        """Test values 4 characters or shorter"""
        self.assertEqual(_mask_value("ab"), "***")
        self.assertEqual(_mask_value("abc"), "***")
        self.assertEqual(_mask_value("abcd"), "***")

    def test_longer_values(self):
        """Test values longer than 4 characters"""
        # Preserves first 2 and last 2 characters
        self.assertEqual(_mask_value("john@example.com"), "jo***om")
        self.assertEqual(_mask_value("0612345678"), "06***78")
        self.assertEqual(_mask_value("NL91ABNA0417164300"), "NL***00")

    def test_non_string_values(self):
        """Test that non-string values are converted"""
        self.assertEqual(_mask_value(12345), "12***45")

    def test_whitespace_trimming(self):
        """Test that whitespace is trimmed before masking"""
        self.assertEqual(_mask_value("  ab  "), "***")
        self.assertEqual(_mask_value("  abcdef  "), "ab***ef")


class TestShouldMaskField(unittest.TestCase):
    """Tests for _should_mask_field() internal function"""

    def test_exact_matches(self):
        """Test exact field name matches"""
        # Contact info
        self.assertTrue(_should_mask_field("email"))
        self.assertTrue(_should_mask_field("phone"))
        self.assertTrue(_should_mask_field("mobile"))
        self.assertTrue(_should_mask_field("fax"))

        # Address info
        self.assertTrue(_should_mask_field("address"))
        self.assertTrue(_should_mask_field("city"))
        self.assertTrue(_should_mask_field("postcode"))

        # Personal info
        self.assertTrue(_should_mask_field("name"))
        self.assertTrue(_should_mask_field("firstname"))
        self.assertTrue(_should_mask_field("lastname"))

        # Financial info
        self.assertTrue(_should_mask_field("iban"))
        self.assertTrue(_should_mask_field("bsn"))
        self.assertTrue(_should_mask_field("kvknummer"))

    def test_dutch_field_names(self):
        """Test Dutch field name variations"""
        self.assertTrue(_should_mask_field("emailadres"))
        self.assertTrue(_should_mask_field("telefoon"))
        self.assertTrue(_should_mask_field("telefoonnummer"))
        self.assertTrue(_should_mask_field("adres"))
        self.assertTrue(_should_mask_field("straat"))
        self.assertTrue(_should_mask_field("woonplaats"))
        self.assertTrue(_should_mask_field("voornaam"))
        self.assertTrue(_should_mask_field("achternaam"))
        self.assertTrue(_should_mask_field("bankrekeningnummer"))
        self.assertTrue(_should_mask_field("btwnummer"))

    def test_case_insensitivity(self):
        """Test case-insensitive matching"""
        self.assertTrue(_should_mask_field("EMAIL"))
        self.assertTrue(_should_mask_field("Email"))
        self.assertTrue(_should_mask_field("PHONE"))
        self.assertTrue(_should_mask_field("IBAN"))

    def test_partial_matches(self):
        """Test that partial matches work (field contains PII keyword)"""
        self.assertTrue(_should_mask_field("customer_email"))
        self.assertTrue(_should_mask_field("contact_phone"))
        self.assertTrue(_should_mask_field("billing_address"))

    def test_non_pii_fields(self):
        """Test that non-PII fields are not masked"""
        self.assertFalse(_should_mask_field("amount"))
        self.assertFalse(_should_mask_field("date"))
        self.assertFalse(_should_mask_field("id"))
        self.assertFalse(_should_mask_field("description"))
        self.assertFalse(_should_mask_field("type"))
        self.assertFalse(_should_mask_field("ledgerId"))

    def test_underscore_and_dash_handling(self):
        """Test that underscores and dashes are normalized"""
        self.assertTrue(_should_mask_field("e_mail"))
        self.assertTrue(_should_mask_field("e-mail"))
        self.assertTrue(_should_mask_field("phone_number"))
        self.assertTrue(_should_mask_field("phone-number"))


class TestMaskPiiInMutation(unittest.TestCase):
    """Tests for mask_pii_in_mutation() function"""

    def test_simple_mutation(self):
        """Test masking simple mutation with PII fields"""
        mutation = {
            "id": 12345,
            "amount": 100.50,
            "email": "john@example.com",
            "phone": "0612345678",
            "description": "Test transaction",
        }

        masked = mask_pii_in_mutation(mutation)

        # Non-PII fields unchanged
        self.assertEqual(masked["id"], 12345)
        self.assertEqual(masked["amount"], 100.50)
        self.assertEqual(masked["description"], "Test transaction")

        # PII fields masked
        self.assertEqual(masked["email"], "jo***om")
        self.assertEqual(masked["phone"], "06***78")

    def test_nested_mutation(self):
        """Test masking nested mutation structures"""
        mutation = {
            "id": 12345,
            "relation": {
                "name": "John Doe",
                "email": "john@example.com",
                "address": "123 Main Street",
            },
        }

        masked = mask_pii_in_mutation(mutation)

        # Nested PII fields masked
        self.assertEqual(masked["relation"]["name"], "Jo***oe")
        self.assertEqual(masked["relation"]["email"], "jo***om")
        self.assertEqual(masked["relation"]["address"], "12***et")

    def test_list_in_mutation(self):
        """Test masking mutation with list of nested dicts"""
        mutation = {
            "id": 12345,
            "rows": [
                {"ledgerId": 1000, "name": "John Doe"},
                {"ledgerId": 2000, "name": "Jane Smith"},
            ],
        }

        masked = mask_pii_in_mutation(mutation)

        # List items masked
        self.assertEqual(masked["rows"][0]["ledgerId"], 1000)  # Non-PII preserved
        self.assertEqual(masked["rows"][0]["name"], "Jo***oe")  # PII masked
        self.assertEqual(masked["rows"][1]["name"], "Ja***th")  # PII masked

    def test_original_not_modified(self):
        """Test that original mutation is not modified"""
        mutation = {
            "id": 12345,
            "email": "john@example.com",
        }

        masked = mask_pii_in_mutation(mutation)

        # Original unchanged
        self.assertEqual(mutation["email"], "john@example.com")

        # Masked version changed
        self.assertEqual(masked["email"], "jo***om")

    def test_empty_mutation(self):
        """Test empty and None mutation handling"""
        self.assertEqual(mask_pii_in_mutation({}), {})
        self.assertIsNone(mask_pii_in_mutation(None))

    def test_deep_nesting(self):
        """Test deeply nested structures"""
        mutation = {
            "level1": {
                "level2": {
                    "level3": {
                        "email": "deep@example.com",
                    }
                }
            }
        }

        masked = mask_pii_in_mutation(mutation)
        self.assertEqual(masked["level1"]["level2"]["level3"]["email"], "de***om")


class TestDuplicateHandling(unittest.TestCase):
    """Tests for duplicate handling functions"""

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_insert_with_duplicate_handling_success(self, mock_frappe):
        """Test successful insert (no duplicate)"""
        from verenigingen.e_boekhouden.utils.data_integrity import insert_with_duplicate_handling

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        # insert() succeeds
        result_doc, was_duplicate = insert_with_duplicate_handling(mock_doc)

        # Verify insert was called
        mock_doc.insert.assert_called_once()

        # Verify result
        self.assertEqual(result_doc, mock_doc)
        self.assertFalse(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_insert_with_duplicate_handling_race_condition(self, mock_frappe):
        """Test duplicate insert handling (race condition)"""
        from frappe.exceptions import DuplicateEntryError

        from verenigingen.e_boekhouden.utils.data_integrity import insert_with_duplicate_handling

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        # insert() raises DuplicateEntryError
        mock_doc.insert.side_effect = DuplicateEntryError()

        # Set up mock to find existing document
        mock_frappe.db.get_value.return_value = "JE-00001"
        mock_existing = MagicMock()
        mock_frappe.get_doc.return_value = mock_existing

        # Call function
        result_doc, was_duplicate = insert_with_duplicate_handling(mock_doc)

        # Verify existing doc lookup
        mock_frappe.db.get_value.assert_called_once_with(
            "Journal Entry",
            {"eboekhouden_mutation_nr": "12345"},
            "name",
        )

        # Verify result
        self.assertEqual(result_doc, mock_existing)
        self.assertTrue(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_submit_with_duplicate_handling_new_doc(self, mock_frappe):
        """Test submit_with_duplicate_handling for new document"""
        from verenigingen.e_boekhouden.utils.data_integrity import submit_with_duplicate_handling

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        # Call function
        result_doc, was_duplicate = submit_with_duplicate_handling(mock_doc)

        # Verify insert and submit were called
        mock_doc.insert.assert_called_once()
        mock_doc.submit.assert_called_once()

        # Verify result
        self.assertEqual(result_doc, mock_doc)
        self.assertFalse(was_duplicate)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_submit_with_duplicate_handling_existing_doc(self, mock_frappe):
        """Test submit_with_duplicate_handling for existing document (race condition)"""
        from frappe.exceptions import DuplicateEntryError

        from verenigingen.e_boekhouden.utils.data_integrity import submit_with_duplicate_handling

        # Create mock document
        mock_doc = MagicMock()
        mock_doc.doctype = "Journal Entry"
        mock_doc.eboekhouden_mutation_nr = "12345"

        # insert() raises DuplicateEntryError
        mock_doc.insert.side_effect = DuplicateEntryError()

        # Set up mock to find existing document
        mock_frappe.db.get_value.return_value = "JE-00001"
        mock_existing = MagicMock()
        mock_frappe.get_doc.return_value = mock_existing

        # Call function
        result_doc, was_duplicate = submit_with_duplicate_handling(mock_doc)

        # Verify submit was NOT called (existing doc already submitted)
        mock_doc.submit.assert_not_called()

        # Verify result
        self.assertEqual(result_doc, mock_existing)
        self.assertTrue(was_duplicate)


class TestDuplicateHandlingRealUniqueFieldCollision(EnhancedTestCase):
    """`insert_with_duplicate_handling` against a REAL unique-field collision (#699).

    `eboekhouden_mutation_nr` is a custom field marked `unique: 1` on Journal
    Entry (and Purchase/Sales Invoice, Payment Entry, Stock Reconciliation) --
    it is not the doctype's autoname/primary key, which is a naming series
    (``ACC-JV-...``). So a second insert with the same mutation number collides
    on that unique FIELD and frappe raises `UniqueValidationError`, not
    `DuplicateEntryError` (unrelated classes: the former derives from
    ValidationError, the latter from NameError). The mocked tests above only
    ever exercise `DuplicateEntryError`, so they could not catch this.

    Before the #699 fix, `insert_with_duplicate_handling` caught only
    `DuplicateEntryError`, so the intended "graceful duplicate handling for
    race conditions" this function exists for did not fire at all for its own
    documented example (Journal Entry / Payment Entry with
    `eboekhouden_mutation_nr` set) -- the `UniqueValidationError` propagated
    straight past the `except DuplicateEntryError` clause to the caller.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = "_Test Company"
        # Pinned by account_type, not just root_type: `_Test Company` carries
        # ~37 Asset accounts and the plain "newest" one under
        # `frappe.db.get_value`'s creation-DESC ordering is fixture-order
        # dependent across this shard (e.g. a Payable/Receivable account here
        # would need a party_type/party and error the JE). Bank/Income Account
        # types need neither.
        cls.debit_account = frappe.db.get_value(
            "Account",
            {"company": cls.company, "is_group": 0, "account_type": "Bank"},
            "name",
        )
        cls.credit_account = frappe.db.get_value(
            "Account",
            {"company": cls.company, "is_group": 0, "account_type": "Income Account"},
            "name",
        )
        assert cls.debit_account and cls.credit_account, (
            f"_Test Company is missing a Bank or Income Account account "
            f"(debit={cls.debit_account!r}, credit={cls.credit_account!r})"
        )

    def _make_je(self, mutation_nr):
        je = frappe.new_doc("Journal Entry")
        je.company = self.company
        je.posting_date = frappe.utils.today()
        je.eboekhouden_mutation_nr = mutation_nr
        je.append(
            "accounts",
            {"account": self.debit_account, "debit_in_account_currency": 10, "credit_in_account_currency": 0},
        )
        je.append(
            "accounts",
            {"account": self.credit_account, "debit_in_account_currency": 0, "credit_in_account_currency": 10},
        )
        return je

    def test_unique_mutation_nr_collision_is_handled_gracefully(self):
        """A second JE with the same mutation number must resolve to the first,
        not raise an uncaught UniqueValidationError."""
        mutation_nr = f"PROBE699-{frappe.generate_hash(length=8)}"

        first_doc, first_was_duplicate = insert_with_duplicate_handling(self._make_je(mutation_nr))
        self.track_doc("Journal Entry", first_doc.name)
        self.assertFalse(first_was_duplicate)

        second_doc, second_was_duplicate = insert_with_duplicate_handling(self._make_je(mutation_nr))

        self.assertTrue(second_was_duplicate)
        self.assertEqual(second_doc.name, first_doc.name)
        # Exactly one Journal Entry carries this mutation number.
        self.assertEqual(
            frappe.db.count("Journal Entry", {"eboekhouden_mutation_nr": mutation_nr}),
            1,
        )


class TestSafeLogMutationError(unittest.TestCase):
    """Tests for safe_log_mutation_error() function"""

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_logs_with_masked_mutation(self, mock_frappe):
        """Test that mutation data is masked in error log"""
        import json

        from verenigingen.e_boekhouden.utils.data_integrity import safe_log_mutation_error

        # Make as_json return actual JSON
        mock_frappe.as_json.side_effect = lambda x, **kwargs: json.dumps(x, **kwargs)

        mutation = {
            "id": 12345,
            "email": "john@example.com",
            "amount": 100.0,
        }

        safe_log_mutation_error(
            title="Test Error",
            mutation=mutation,
            additional_context="Test context",
        )

        # Verify log_error was called
        mock_frappe.log_error.assert_called_once()

        # Get the message argument
        call_args = mock_frappe.log_error.call_args
        message = call_args[1]["message"]

        # Verify masked email in message
        self.assertIn("jo***om", message)
        self.assertNotIn("john@example.com", message)

        # Verify context is included
        self.assertIn("Test context", message)

    @patch("verenigingen.e_boekhouden.utils.data_integrity.frappe")
    def test_logs_with_error(self, mock_frappe):
        """Test that exception is included in error log"""
        import json

        from verenigingen.e_boekhouden.utils.data_integrity import safe_log_mutation_error

        # Make as_json return actual JSON
        mock_frappe.as_json.side_effect = lambda x, **kwargs: json.dumps(x, **kwargs)

        mutation = {"id": 12345}
        error = ValueError("Test error message")

        safe_log_mutation_error(
            title="Test Error",
            mutation=mutation,
            error=error,
        )

        # Get the message argument
        call_args = mock_frappe.log_error.call_args
        message = call_args[1]["message"]

        # Verify error is included
        self.assertIn("ValueError", message)
        self.assertIn("Test error message", message)


if __name__ == "__main__":
    unittest.main()
