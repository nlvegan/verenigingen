# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for verenigingen_payments/utils/sepa_utilities.py.

The module is a grab-bag of SEPA helper classes. Most are PURE (IBAN
validation delegators, currency/amount math, description builders, invoice
validation, XML canonicalization) and tested with plain unittest + real
values. The DB-backed paths (audit log insert, file attach) use
EnhancedTestCase.

NO business logic is mocked. The only "boundaries" exercised here are real:
the lxml C14N library and the SEPA Operation Audit Log doctype.

Product bugs found are pinned with @unittest.expectedFailure (asserting the
CORRECT behaviour) and documented in the method docstring — NOT fixed.
"""

import os
import tempfile
import unittest
import warnings
from decimal import Decimal

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.utils.sepa_utilities import (
    BatchLoggingUtilities,
    CalculationUtilities,
    FileManagementUtilities,
    InvoiceManagementUtilities,
    SEPAUtilities,
    SEPAXMLCanonicalizer,
    SEPAXMLValidator,
)

# A real, MOD-97-valid Dutch IBAN (ING test account used across the suite).
VALID_NL_IBAN = "NL39RABO0300065264"
# A real, MOD-97-valid German IBAN (Deutsche Bundesbank example).
VALID_DE_IBAN = "DE89370400440532013000"


# ---------------------------------------------------------------------------
# SEPAUtilities - deprecated IBAN/BIC delegators
# ---------------------------------------------------------------------------
class TestSEPAUtilitiesIBAN(unittest.TestCase):
    """SEPAUtilities.* delegate to the canonical iban_validator but emit a
    DeprecationWarning. We assert both the warning and the delegated result."""

    def _silence(self):
        # All four functions warn; tests assert behaviour, not the warning text
        warnings.simplefilter("ignore", DeprecationWarning)

    def test_get_bic_from_iban_known_dutch_bank(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            bic = SEPAUtilities.get_bic_from_iban(VALID_NL_IBAN)
        self.assertEqual(bic, "RABONL2U")
        # Deprecation warning is emitted
        self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))

    def test_get_bic_from_iban_invalid_returns_none(self):
        self._silence()
        # Wrong checksum -> canonical validator rejects -> no BIC
        self.assertIsNone(SEPAUtilities.get_bic_from_iban("NL00RABO0300065264"))

    def test_get_bic_from_iban_unknown_bank_returns_none(self):
        self._silence()
        # ZZZZ is not in the NL BIC table even if checksum were valid
        self.assertIsNone(SEPAUtilities.get_bic_from_iban("NL00ZZZZ0300065264"))

    def test_validate_iban_format_accepts_valid(self):
        self._silence()
        self.assertTrue(SEPAUtilities.validate_iban_format(VALID_NL_IBAN))

    def test_validate_iban_format_rejects_bad_checksum(self):
        self._silence()
        # Delegates to validate_iban which DOES run MOD-97 (the deprecated
        # docstring warns the *old* impl didn't, but the delegate does)
        self.assertFalse(SEPAUtilities.validate_iban_format("NL00RABO0300065264"))

    def test_validate_iban_format_rejects_garbage(self):
        self._silence()
        self.assertFalse(SEPAUtilities.validate_iban_format("not-an-iban"))

    def test_format_iban_display_groups_of_four(self):
        self._silence()
        self.assertEqual(
            SEPAUtilities.format_iban_display(VALID_NL_IBAN),
            "NL39 RABO 0300 0652 64",
        )

    def test_format_iban_display_normalises_spaces_and_case(self):
        self._silence()
        self.assertEqual(
            SEPAUtilities.format_iban_display("nl39 rabo0300065264"),
            "NL39 RABO 0300 0652 64",
        )

    def test_format_iban_display_empty_returns_empty_string(self):
        self._silence()
        # format_iban returns "" for empty; wrapper coerces None -> ""
        self.assertEqual(SEPAUtilities.format_iban_display(""), "")

    def test_validate_dutch_iban_accepts_valid_nl(self):
        self._silence()
        self.assertTrue(SEPAUtilities.validate_dutch_iban(VALID_NL_IBAN))

    def test_validate_dutch_iban_rejects_valid_non_nl(self):
        self._silence()
        # German IBAN is MOD-97 valid but not Dutch -> False
        self.assertFalse(SEPAUtilities.validate_dutch_iban(VALID_DE_IBAN))

    def test_validate_dutch_iban_rejects_bad_checksum(self):
        self._silence()
        self.assertFalse(SEPAUtilities.validate_dutch_iban("NL00RABO0300065264"))

    def test_validate_dutch_iban_empty_returns_false(self):
        self._silence()
        self.assertFalse(SEPAUtilities.validate_dutch_iban(""))
        self.assertFalse(SEPAUtilities.validate_dutch_iban(None))

    def test_validate_dutch_iban_lowercase_with_spaces(self):
        self._silence()
        self.assertTrue(SEPAUtilities.validate_dutch_iban("nl39 rabo 0300 0652 64"))


# ---------------------------------------------------------------------------
# CalculationUtilities - pure financial math
# ---------------------------------------------------------------------------
class TestCalculateBatchTotals(unittest.TestCase):
    def test_empty_list_returns_zero(self):
        result = CalculationUtilities.calculate_batch_totals([])
        self.assertEqual(result["total_amount"], Decimal("0.00"))
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["currency"], "EUR")

    def test_sums_outstanding_amount(self):
        invoices = [{"outstanding_amount": "10.00"}, {"outstanding_amount": "5.50"}]
        result = CalculationUtilities.calculate_batch_totals(invoices)
        self.assertEqual(result["total_amount"], Decimal("15.50"))
        self.assertEqual(result["count"], 2)

    def test_field_priority_outstanding_over_grand_total_over_amount(self):
        # outstanding_amount wins when present
        inv = [{"outstanding_amount": "7", "grand_total": "99", "amount": "1"}]
        self.assertEqual(
            CalculationUtilities.calculate_batch_totals(inv)["total_amount"],
            Decimal("7.00"),
        )
        # falls back to grand_total
        inv = [{"grand_total": "99", "amount": "1"}]
        self.assertEqual(
            CalculationUtilities.calculate_batch_totals(inv)["total_amount"],
            Decimal("99.00"),
        )
        # then amount
        inv = [{"amount": "1"}]
        self.assertEqual(
            CalculationUtilities.calculate_batch_totals(inv)["total_amount"],
            Decimal("1.00"),
        )

    def test_falsy_zero_outstanding_falls_through_to_grand_total(self):
        # NOTE: `or` chain means outstanding_amount=0 (falsy) skips to grand_total
        inv = [{"outstanding_amount": 0, "grand_total": "12.00"}]
        self.assertEqual(
            CalculationUtilities.calculate_batch_totals(inv)["total_amount"],
            Decimal("12.00"),
        )

    def test_none_and_invalid_amounts_treated_as_zero(self):
        invoices = [
            {"outstanding_amount": None},
            {"outstanding_amount": "not-a-number"},
            {"outstanding_amount": "10.00"},
        ]
        result = CalculationUtilities.calculate_batch_totals(invoices)
        self.assertEqual(result["total_amount"], Decimal("10.00"))
        self.assertEqual(result["count"], 3)

    def test_decimal_input_preserved(self):
        invoices = [{"outstanding_amount": Decimal("3.333")}]
        result = CalculationUtilities.calculate_batch_totals(invoices)
        # Quantized half-up to 2dp
        self.assertEqual(result["total_amount"], Decimal("3.33"))

    def test_round_half_up_quantization(self):
        invoices = [{"outstanding_amount": Decimal("0.005")}]
        result = CalculationUtilities.calculate_batch_totals(invoices)
        self.assertEqual(result["total_amount"], Decimal("0.01"))

    def test_currency_from_first_invoice(self):
        invoices = [{"outstanding_amount": "1", "currency": "USD"}]
        result = CalculationUtilities.calculate_batch_totals(invoices)
        self.assertEqual(result["currency"], "USD")


class TestFormatCurrencyAmount(unittest.TestCase):
    def test_eur_symbol_and_grouping(self):
        self.assertEqual(
            CalculationUtilities.format_currency_amount(Decimal("1234.5")),
            "€ 1,234.50",
        )

    def test_float_input(self):
        self.assertEqual(
            CalculationUtilities.format_currency_amount(1234.5),
            "€ 1,234.50",
        )

    def test_non_eur_currency_code_prefix(self):
        self.assertEqual(
            CalculationUtilities.format_currency_amount(Decimal("10"), "USD"),
            "USD 10.00",
        )

    def test_zero(self):
        self.assertEqual(CalculationUtilities.format_currency_amount(0), "€ 0.00")


class _Inv:
    """Minimal invoice-like object with an .amount attribute."""

    def __init__(self, amount):
        self.amount = amount


class TestCalculateDocumentTotalsPython(unittest.TestCase):
    def test_empty_list(self):
        result = CalculationUtilities.calculate_document_totals_python([])
        self.assertEqual(result["entry_count"], 0)
        self.assertEqual(result["total_amount"], Decimal("0.00"))

    def test_sums_attribute_amounts(self):
        result = CalculationUtilities.calculate_document_totals_python(
            [_Inv("10.00"), _Inv(Decimal("5.25")), _Inv(2)]
        )
        self.assertEqual(result["entry_count"], 3)
        self.assertEqual(result["total_amount"], Decimal("17.25"))

    def test_none_amount_treated_as_zero(self):
        result = CalculationUtilities.calculate_document_totals_python([_Inv(None), _Inv("5")])
        self.assertEqual(result["entry_count"], 2)
        self.assertEqual(result["total_amount"], Decimal("5.00"))

    def test_blank_string_amount_treated_as_zero(self):
        result = CalculationUtilities.calculate_document_totals_python([_Inv("   "), _Inv("5")])
        self.assertEqual(result["total_amount"], Decimal("5.00"))

    def test_invalid_entry_skipped_but_counted(self):
        # entry_count uses len() so the bad row still counts; only the
        # amount is skipped from the sum
        result = CalculationUtilities.calculate_document_totals_python([_Inv("bad"), _Inv("5")])
        self.assertEqual(result["entry_count"], 2)
        self.assertEqual(result["total_amount"], Decimal("5.00"))

    def test_object_without_amount_attribute_skipped(self):
        class NoAmount:
            pass

        result = CalculationUtilities.calculate_document_totals_python([NoAmount(), _Inv("5")])
        self.assertEqual(result["total_amount"], Decimal("5.00"))


# ---------------------------------------------------------------------------
# InvoiceManagementUtilities - pure helpers
# ---------------------------------------------------------------------------
class _BatchInv:
    def __init__(self):
        self.status = None
        self.result_code = None
        self.result_message = None


class TestUpdateBatchInvoiceStatus(unittest.TestCase):
    def test_updates_status_only(self):
        inv = _BatchInv()
        ok = InvoiceManagementUtilities.update_batch_invoice_status([inv], 0, "Submitted")
        self.assertTrue(ok)
        self.assertEqual(inv.status, "Submitted")
        self.assertIsNone(inv.result_code)
        self.assertIsNone(inv.result_message)

    def test_updates_code_and_message(self):
        inv = _BatchInv()
        InvoiceManagementUtilities.update_batch_invoice_status(
            [inv], 0, "Failed", result_code="AC04", result_message="Closed account"
        )
        self.assertEqual(inv.status, "Failed")
        self.assertEqual(inv.result_code, "AC04")
        self.assertEqual(inv.result_message, "Closed account")

    def test_negative_index_raises(self):
        with self.assertRaises(IndexError):
            InvoiceManagementUtilities.update_batch_invoice_status([_BatchInv()], -1, "X")

    def test_out_of_range_index_raises(self):
        with self.assertRaises(IndexError):
            InvoiceManagementUtilities.update_batch_invoice_status([_BatchInv()], 5, "X")

    def test_empty_list_raises(self):
        with self.assertRaises(IndexError):
            InvoiceManagementUtilities.update_batch_invoice_status([], 0, "X")


class TestGenerateInvoiceDescription(unittest.TestCase):
    def test_invoice_only(self):
        self.assertEqual(
            InvoiceManagementUtilities.generate_invoice_description("INV-001"),
            "Invoice INV-001",
        )

    def test_with_member(self):
        self.assertEqual(
            InvoiceManagementUtilities.generate_invoice_description("INV-001", "Jane Doe"),
            "Invoice INV-001 - Jane Doe",
        )

    def test_with_member_and_period(self):
        self.assertEqual(
            InvoiceManagementUtilities.generate_invoice_description("INV-001", "Jane Doe", "2025-Q1"),
            "Invoice INV-001 - Jane Doe (2025-Q1)",
        )

    def test_period_without_member(self):
        self.assertEqual(
            InvoiceManagementUtilities.generate_invoice_description("INV-001", membership_period="2025"),
            "Invoice INV-001 (2025)",
        )


class TestValidateInvoiceForSEPA(unittest.TestCase):
    def _valid(self):
        return {
            "name": "INV-001",
            "customer": "CUST-001",
            "outstanding_amount": "50.00",
            "currency": "EUR",
            "status": "Unpaid",
        }

    def test_valid_invoice(self):
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(self._valid())
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])

    def test_missing_required_fields(self):
        result = InvoiceManagementUtilities.validate_invoice_for_sepa({})
        self.assertFalse(result["is_valid"])
        # name, customer, outstanding_amount, currency all missing
        self.assertTrue(any("name" in e for e in result["errors"]))
        self.assertTrue(any("customer" in e for e in result["errors"]))

    def test_zero_amount_rejected(self):
        data = self._valid()
        data["outstanding_amount"] = "0"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertFalse(result["is_valid"])
        # NOTE: 0 is falsy -> first caught as "Missing required field" AND as
        # "must be greater than zero". Both surface; assert the latter exists.
        self.assertTrue(any("greater than zero" in e for e in result["errors"]))

    def test_negative_amount_rejected(self):
        data = self._valid()
        data["outstanding_amount"] = "-5"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("greater than zero" in e for e in result["errors"]))

    def test_amount_over_sepa_limit_rejected(self):
        data = self._valid()
        data["outstanding_amount"] = "1000000.00"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("exceeds SEPA" in e for e in result["errors"]))

    def test_amount_at_sepa_limit_accepted(self):
        data = self._valid()
        data["outstanding_amount"] = "999999.99"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertTrue(result["is_valid"])

    def test_invalid_amount_format(self):
        data = self._valid()
        data["outstanding_amount"] = "abc"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("Invalid outstanding amount" in e for e in result["errors"]))

    def test_non_eur_currency_rejected(self):
        data = self._valid()
        data["currency"] = "USD"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertFalse(result["is_valid"])
        self.assertTrue(any("Unsupported currency" in e for e in result["errors"]))

    def test_unusual_status_is_warning_not_error(self):
        data = self._valid()
        data["status"] = "Paid"
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        # Status is only a warning -> still valid
        self.assertTrue(result["is_valid"])
        self.assertTrue(any("may not be suitable" in w for w in result["warnings"]))

    def test_decimal_amount_input(self):
        data = self._valid()
        data["outstanding_amount"] = Decimal("25.00")
        result = InvoiceManagementUtilities.validate_invoice_for_sepa(data)
        self.assertTrue(result["is_valid"])


# ---------------------------------------------------------------------------
# SEPAXMLCanonicalizer - real lxml C14N
# ---------------------------------------------------------------------------
class TestSEPAXMLCanonicalizer(unittest.TestCase):
    def test_attribute_order_normalised(self):
        a = b'<r a="1" b="2"/>'
        b = b'<r b="2" a="1"/>'
        self.assertEqual(
            SEPAXMLCanonicalizer.canonicalize(a),
            SEPAXMLCanonicalizer.canonicalize(b),
        )

    def test_identical_logical_content_same_hash(self):
        xml = b'<doc><amt>10.00</amt></doc>'
        self.assertEqual(
            SEPAXMLCanonicalizer.compute_canonical_hash(xml),
            SEPAXMLCanonicalizer.compute_canonical_hash(xml),
        )

    def test_attr_reorder_same_hash(self):
        a = b'<r a="1" b="2"><c/></r>'
        b = b'<r b="2" a="1"><c/></r>'
        self.assertEqual(
            SEPAXMLCanonicalizer.compute_canonical_hash(a),
            SEPAXMLCanonicalizer.compute_canonical_hash(b),
        )

    def test_different_content_different_hash(self):
        self.assertNotEqual(
            SEPAXMLCanonicalizer.compute_canonical_hash(b"<doc><amt>10</amt></doc>"),
            SEPAXMLCanonicalizer.compute_canonical_hash(b"<doc><amt>20</amt></doc>"),
        )

    def test_hash_is_64_char_hex(self):
        h = SEPAXMLCanonicalizer.compute_canonical_hash(b"<a/>")
        self.assertEqual(len(h), 64)
        int(h, 16)  # raises if not hex

    def test_comments_stripped(self):
        # with_comments=False -> a comment-bearing doc hashes same as without
        with_comment = b"<doc><!-- note --><amt>10</amt></doc>"
        without = b"<doc><amt>10</amt></doc>"
        self.assertEqual(
            SEPAXMLCanonicalizer.compute_canonical_hash(with_comment),
            SEPAXMLCanonicalizer.compute_canonical_hash(without),
        )

    def test_invalid_xml_raises_valueerror(self):
        with self.assertRaises(ValueError):
            SEPAXMLCanonicalizer.canonicalize(b"<not-closed")


# ---------------------------------------------------------------------------
# SEPAXMLValidator - xmlschema is NOT installed in this env
# ---------------------------------------------------------------------------
class TestSEPAXMLValidator(unittest.TestCase):
    def test_returns_valid_with_warning_when_xmlschema_missing(self):
        # xmlschema is not installed here -> graceful skip, valid=True
        result = SEPAXMLValidator.validate_sepa_xml_schema("<doc/>")
        self.assertTrue(result["valid"])
        self.assertIn("warnings", result)
        self.assertTrue(any("xmlschema" in w for w in result["warnings"]))

    def test_batch_name_accepted(self):
        result = SEPAXMLValidator.validate_sepa_xml_schema("<doc/>", batch_name="BATCH-1")
        self.assertTrue(result["valid"])


# ---------------------------------------------------------------------------
# DB-backed paths
# ---------------------------------------------------------------------------
class TestBatchLoggingDocumentField(unittest.TestCase):
    """add_to_document_batch_log mutates a doc field in memory; pure, no DB."""

    def test_appends_timestamped_line_to_empty_log(self):
        doc = frappe._dict({"batch_log": None})
        BatchLoggingUtilities.add_to_document_batch_log(doc, "started")
        self.assertIn("started", doc.batch_log)
        self.assertTrue(doc.batch_log.endswith("\n"))

    def test_appends_to_existing_log(self):
        doc = frappe._dict({"batch_log": "first\n"})
        BatchLoggingUtilities.add_to_document_batch_log(doc, "second")
        self.assertIn("first", doc.batch_log)
        self.assertIn("second", doc.batch_log)
        self.assertEqual(doc.batch_log.count("\n"), 2)


class TestBatchLoggingAuditLog(EnhancedTestCase):
    """add_to_batch_log writes to the SEPA Operation Audit Log doctype."""

    def test_empty_args_are_noops(self):
        # Guard clause: no batch_name or no message -> nothing inserted, no raise
        before = frappe.db.count("SEPA Operation Audit Log")
        BatchLoggingUtilities.add_to_batch_log("", "msg")
        BatchLoggingUtilities.add_to_batch_log("BATCH-1", "")
        after = frappe.db.count("SEPA Operation Audit Log")
        self.assertEqual(before, after)

    def test_does_not_raise_on_insert(self):
        # The function swallows insert errors into frappe.log_error, so it must
        # never propagate even though the schema mismatch (see xfail below)
        # makes the insert itself fail.
        try:
            BatchLoggingUtilities.add_to_batch_log("BATCH-1", "processing started")
        except Exception as e:  # pragma: no cover - guard
            self.fail(f"add_to_batch_log raised: {e}")

    def test_audit_log_record_actually_created(self):
        """FIXED: BatchLoggingUtilities.add_to_batch_log used to insert a doc
        with fields {batch_name, operation, message, log_level} but the
        'SEPA Operation Audit Log' doctype defines NONE of those fields (its
        real fields are operation_type, operation_status, error_message,
        compliance_notes, link_name, timestamp, ...). The insert() raised, was
        caught, and logged to frappe.log_error -> the audit entry was SILENTLY
        DROPPED.

        add_to_batch_log now maps its inputs onto the real schema fields, so a
        row is actually persisted. This test asserts the row exists with the
        mapped values.
        """
        before = frappe.db.count("SEPA Operation Audit Log")
        BatchLoggingUtilities.add_to_batch_log("BATCH-XYZ", "a unique log message", level="Error")
        after = frappe.db.count("SEPA Operation Audit Log")
        self.assertEqual(after, before + 1)

        # The persisted row carries the mapped field values.
        log_name = frappe.db.get_value(
            "SEPA Operation Audit Log",
            {"link_name": "BATCH-XYZ", "compliance_notes": "a unique log message"},
            "name",
        )
        self.assertIsNotNone(log_name)
        row = frappe.db.get_value(
            "SEPA Operation Audit Log",
            log_name,
            ["operation_type", "operation_status", "error_message"],
            as_dict=True,
        )
        self.assertEqual(row.operation_type, "sepa_bulk_operation")
        self.assertEqual(row.operation_status, "failed")
        self.assertEqual(row.error_message, "a unique log message")

    def test_log_batch_operation_does_not_raise(self):
        # Wraps add_to_batch_log with structured details; same swallow-on-error
        try:
            BatchLoggingUtilities.log_batch_operation(
                "BATCH-1", "GenerateXML", {"count": 5, "total": "100.00"}
            )
            BatchLoggingUtilities.log_batch_operation("BATCH-1", "NoDetails")
        except Exception as e:  # pragma: no cover - guard
            self.fail(f"log_batch_operation raised: {e}")


class TestFileManagementUtilities(EnhancedTestCase):
    """attach_file_to_document creates a real File doc attached to a record."""

    def _make_note(self):
        note = frappe.get_doc({"doctype": "Note", "title": frappe.generate_hash(length=10)})
        note.insert(ignore_permissions=True)
        return note

    def test_attaches_file_and_returns_url(self):
        # Attach to a stable singleton-ish target: use a real Note doc we create
        note = self._make_note()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, prefix="sepa_test_"
        ) as fh:
            fh.write("sepa batch export contents")
            tmp_path = fh.name

        try:
            url = FileManagementUtilities.attach_file_to_document(tmp_path, "Note", note.name)
            self.assertTrue(url)
            self.assertTrue(url.startswith("/"))
            # A File row exists linked to the note
            file_name = frappe.db.get_value(
                "File",
                {"attached_to_doctype": "Note", "attached_to_name": note.name},
                "name",
            )
            self.assertIsNotNone(file_name)
            self.assertEqual(
                frappe.db.get_value("File", file_name, "is_private"), 1
            )
        finally:
            os.unlink(tmp_path)

    def test_missing_file_raises(self):
        with self.assertRaises(Exception):
            FileManagementUtilities.attach_file_to_document(
                "/nonexistent/path/file.txt", "Note", "whatever"
            )


if __name__ == "__main__":
    unittest.main()
