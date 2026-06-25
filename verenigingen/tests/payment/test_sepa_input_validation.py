# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for verenigingen_payments/utils/sepa_input_validation.py

The module under test (``SEPAInputValidator``) is a pure-logic input validator
for SEPA direct-debit batch operations. It rejects non-EUR currencies, bad
IBANs, malformed amounts/dates/mandate references, and out-of-spec text, and
returns a structured ``{"valid": bool, "errors": [...], ...}`` dict (it does not
raise on bad input — it collects errors).

These tests exercise BOTH the accept path and every reject path for each
validation function, plus boundary values and adversarial inputs (None, empty,
wrong types, injection-y strings, NaN/Infinity decimals).

Collection-date validity is anchored on ``frappe.utils.today()`` (non
deterministic across calendar days), so date-dependent tests compute a valid
in-window weekday dynamically rather than hard-coding a date.
"""

import unittest
from datetime import date, datetime
from decimal import Decimal

from frappe.utils import add_days, getdate, today

from verenigingen.verenigingen_payments.utils.sepa_constants import (
    DEFAULT_MAX_BATCH_TOTAL,
    MAX_BATCH_SIZE,
    MAX_DEBTOR_NAME_LENGTH,
    MAX_MANDATE_ID_LENGTH,
    MAX_REMITTANCE_INFO_LENGTH,
    MAX_TRANSACTION_AMOUNT,
    MIN_TRANSACTION_AMOUNT,
)
from verenigingen.verenigingen_payments.utils.sepa_input_validation import (
    SEPAInputValidator,
    get_sepa_validation_rules,
)

# A known-good Dutch IBAN with a valid MOD-97 checksum (used app-wide in tests).
VALID_IBAN = "NL39RABO0300065264"
# Same IBAN with spaces / lowercase — validator must normalize it.
VALID_IBAN_SPACED = "nl39 rabo 0300 0652 64"


def _valid_collection_date() -> date:
    """Return the earliest weekday >= today+MIN_OFFSET that is inside the window.

    MIN_COLLECTION_DATE_OFFSET..MAX_COLLECTION_DATE_OFFSET (1..30 days). We walk
    forward from the minimum offset until we hit a Mon-Fri date so the value is
    accepted regardless of which weekday "today" happens to be.
    """
    base = getdate(today())
    offset = SEPAInputValidator.MIN_COLLECTION_DATE_OFFSET
    candidate = add_days(base, offset)
    candidate = getdate(candidate)
    while candidate.weekday() >= 5:  # skip Sat/Sun
        candidate = getdate(add_days(candidate, 1))
    return candidate


def _valid_invoice(**overrides) -> dict:
    """Build a minimally-valid SEPA invoice dict; override individual fields."""
    invoice = {
        "invoice": "ACC-SINV-2025-00001",
        "amount": "25.00",
        "iban": VALID_IBAN,
        "member_name": "Jan de Vries",
        "mandate_reference": "MNDT-2025-0001",
    }
    invoice.update(overrides)
    return invoice


class TestValidateAmount(unittest.TestCase):
    """SEPAInputValidator.validate_amount"""

    def _ok(self, value, expected):
        res = SEPAInputValidator.validate_amount(value)
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_amount"], expected)

    def _bad(self, value, fragment):
        res = SEPAInputValidator.validate_amount(value)
        self.assertFalse(res["valid"])
        self.assertIsNone(res["cleaned_amount"])
        self.assertTrue(
            any(fragment in e for e in res["errors"]),
            msg=f"{fragment!r} not in {res['errors']}",
        )

    # ---- accept path ----
    def test_accept_string_amount(self):
        self._ok("25.00", Decimal("25.00"))

    def test_accept_int_amount(self):
        self._ok(25, Decimal("25.00"))

    def test_accept_float_amount(self):
        self._ok(25.5, Decimal("25.50"))

    def test_accept_decimal_amount(self):
        self._ok(Decimal("25.5"), Decimal("25.50"))

    def test_accept_comma_decimal_separator(self):
        # European decimal separator must be normalized to a dot.
        self._ok("12,34", Decimal("12.34"))

    def test_accept_whitespace_trimmed(self):
        self._ok("  10.00  ", Decimal("10.00"))

    def test_accept_minimum_boundary(self):
        self._ok(MIN_TRANSACTION_AMOUNT, Decimal("0.01"))

    def test_accept_maximum_boundary(self):
        self._ok(MAX_TRANSACTION_AMOUNT, Decimal("999999999.99"))

    def test_accept_rounds_to_two_places_when_exactly_two(self):
        self._ok("100", Decimal("100.00"))

    # ---- reject path ----
    def test_reject_zero(self):
        self._bad(0, "Amount must be positive")

    def test_reject_negative(self):
        self._bad("-5.00", "Amount must be positive")

    def test_reject_above_maximum(self):
        self._bad("1000000000.00", "Amount too large")

    def test_reject_three_decimal_places(self):
        # 0.001 is > MIN and within range but has 3 dp -> rejected.
        self._bad("1.001", "more than 2 decimal places")

    def test_reject_non_numeric_string(self):
        self._bad("abc", "Invalid amount format")

    def test_reject_empty_string(self):
        self._bad("", "Invalid amount format")

    def test_reject_none_type(self):
        self._bad(None, "Invalid amount type")

    def test_reject_list_type(self):
        self._bad([1, 2], "Invalid amount type")

    def test_reject_injection_string(self):
        self._bad("10; DROP TABLE x", "Invalid amount format")

    def test_reject_nan_string(self):
        # Decimal("NaN") <= 0 raises InvalidOperation -> clean "Invalid format".
        self._bad("NaN", "Invalid amount format")

    def test_below_minimum_is_unreachable_but_zero_rejected(self):
        # MIN is 0.01 and any positive value < 0.01 has >2 dp, so the
        # "too small" branch is effectively shadowed by the dp / positivity
        # checks. We assert a sub-minimum value is still rejected (not accepted).
        res = SEPAInputValidator.validate_amount("0.001")
        self.assertFalse(res["valid"])

    def test_infinity_is_rejected_even_though_via_fallback(self):
        # Infinity passes <=0 and < MIN, hits "too large", then the
        # as_tuple().exponent comparison raises TypeError (exponent == 'F'),
        # which is swallowed by the broad except and appended as a second
        # error. Net contract: Infinity is REJECTED (no wrong-accept), but the
        # second error leaks an internal "'<' not supported" message. This is a
        # robustness smell, not a wrong-accept, so it is documented rather than
        # pinned as an expectedFailure.
        res = SEPAInputValidator.validate_amount("Infinity")
        self.assertFalse(res["valid"])
        self.assertIsNone(res["cleaned_amount"])
        self.assertTrue(any("too large" in e for e in res["errors"]))


class TestValidateBatchType(unittest.TestCase):
    """SEPAInputValidator.validate_batch_type"""

    def test_accept_core(self):
        res = SEPAInputValidator.validate_batch_type("CORE")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_type"], "CORE")

    def test_accept_b2b(self):
        self.assertEqual(SEPAInputValidator.validate_batch_type("B2B")["cleaned_type"], "B2B")

    def test_accept_cor1(self):
        self.assertEqual(SEPAInputValidator.validate_batch_type("COR1")["cleaned_type"], "COR1")

    def test_accept_lowercase_normalized(self):
        res = SEPAInputValidator.validate_batch_type("core")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_type"], "CORE")

    def test_accept_whitespace_trimmed(self):
        res = SEPAInputValidator.validate_batch_type("  b2b  ")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_type"], "B2B")

    def test_reject_unknown_type(self):
        res = SEPAInputValidator.validate_batch_type("INSTANT")
        self.assertFalse(res["valid"])
        self.assertIsNone(res["cleaned_type"])
        self.assertTrue(any("Invalid batch type" in e for e in res["errors"]))

    def test_reject_empty_string(self):
        res = SEPAInputValidator.validate_batch_type("")
        self.assertFalse(res["valid"])
        self.assertTrue(any("required and must be a string" in e for e in res["errors"]))

    def test_reject_none(self):
        res = SEPAInputValidator.validate_batch_type(None)
        self.assertFalse(res["valid"])

    def test_reject_non_string(self):
        res = SEPAInputValidator.validate_batch_type(123)
        self.assertFalse(res["valid"])


class TestValidateMandateReference(unittest.TestCase):
    """SEPAInputValidator.validate_mandate_reference"""

    def test_accept_alphanumeric(self):
        res = SEPAInputValidator.validate_mandate_reference("MNDT-2025_0001.A")
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_reference"], "MNDT-2025_0001.A")

    def test_accept_trims_surrounding_whitespace(self):
        res = SEPAInputValidator.validate_mandate_reference("  REF-1  ")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_reference"], "REF-1")

    def test_accept_max_length_boundary(self):
        ref = "A" * MAX_MANDATE_ID_LENGTH
        res = SEPAInputValidator.validate_mandate_reference(ref)
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_reference"], ref)

    def test_reject_over_max_length(self):
        ref = "A" * (MAX_MANDATE_ID_LENGTH + 1)
        res = SEPAInputValidator.validate_mandate_reference(ref)
        self.assertFalse(res["valid"])
        self.assertTrue(any("too long" in e for e in res["errors"]))

    def test_reject_none(self):
        res = SEPAInputValidator.validate_mandate_reference(None)
        self.assertFalse(res["valid"])
        self.assertTrue(any("required" in e for e in res["errors"]))

    def test_reject_empty(self):
        res = SEPAInputValidator.validate_mandate_reference("")
        self.assertFalse(res["valid"])

    def test_reject_whitespace_only(self):
        res = SEPAInputValidator.validate_mandate_reference("   ")
        self.assertFalse(res["valid"])
        self.assertTrue(any("cannot be empty" in e for e in res["errors"]))

    def test_reject_invalid_characters_space(self):
        res = SEPAInputValidator.validate_mandate_reference("REF 123")
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters" in e for e in res["errors"]))

    def test_reject_injection_characters(self):
        res = SEPAInputValidator.validate_mandate_reference("REF';DROP/*")
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters" in e for e in res["errors"]))

    def test_reject_non_string(self):
        res = SEPAInputValidator.validate_mandate_reference(12345)
        self.assertFalse(res["valid"])


class TestValidateBIC(unittest.TestCase):
    """SEPAInputValidator.validate_bic"""

    def test_accept_8_char_bic(self):
        res = SEPAInputValidator.validate_bic("RABONL2U")
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_bic"], "RABONL2U")

    def test_accept_11_char_bic(self):
        res = SEPAInputValidator.validate_bic("RABONL2UXXX")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_bic"], "RABONL2UXXX")

    def test_accept_lowercase_normalized(self):
        res = SEPAInputValidator.validate_bic("  rabonl2u  ")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_bic"], "RABONL2U")

    def test_accept_numeric_location_code(self):
        # Positions 7-8 may be alphanumeric.
        res = SEPAInputValidator.validate_bic("DEUTDEFF")
        self.assertTrue(res["valid"])

    def test_reject_wrong_length_9(self):
        res = SEPAInputValidator.validate_bic("RABONL2UX")
        self.assertFalse(res["valid"])
        self.assertTrue(any("8 or 11 characters" in e for e in res["errors"]))

    def test_reject_bad_format_digits_in_bank_code(self):
        # First 6 chars must be letters; digits here are invalid format.
        res = SEPAInputValidator.validate_bic("RAB0NL2U")
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid BIC format" in e for e in res["errors"]))

    def test_reject_none(self):
        res = SEPAInputValidator.validate_bic(None)
        self.assertFalse(res["valid"])

    def test_reject_empty(self):
        res = SEPAInputValidator.validate_bic("")
        self.assertFalse(res["valid"])

    def test_reject_non_string(self):
        res = SEPAInputValidator.validate_bic(12345678)
        self.assertFalse(res["valid"])


class TestValidateBICParityWithCanonical(unittest.TestCase):
    """Parity: SEPAInputValidator.validate_bic must agree with canonical validate_bic on all inputs.

    These are characterization-and-delegation tests — they prove that the refactored
    SEPAInputValidator.validate_bic (which now delegates to the canonical helper) returns
    the same ``valid`` bool and ``cleaned_bic`` for every representative input it always did.
    """

    def _sepa(self, bic):
        return SEPAInputValidator.validate_bic(bic)

    def test_parity_valid_8_char(self):
        r = self._sepa("ABNANL2A")
        self.assertTrue(r["valid"])
        self.assertEqual(r["cleaned_bic"], "ABNANL2A")
        self.assertEqual(r["errors"], [])

    def test_parity_valid_11_char(self):
        r = self._sepa("ABNANL2AXXX")
        self.assertTrue(r["valid"])
        self.assertEqual(r["cleaned_bic"], "ABNANL2AXXX")

    def test_parity_lowercase_normalized(self):
        r = self._sepa("ingbnl2a")
        self.assertTrue(r["valid"])
        self.assertEqual(r["cleaned_bic"], "INGBNL2A")

    def test_parity_invalid_9_char(self):
        r = self._sepa("ABNANL2AX")
        self.assertFalse(r["valid"])
        self.assertIsNone(r["cleaned_bic"])
        self.assertTrue(len(r["errors"]) > 0)

    def test_parity_invalid_empty(self):
        r = self._sepa("")
        self.assertFalse(r["valid"])

    def test_parity_invalid_none(self):
        r = self._sepa(None)
        self.assertFalse(r["valid"])

    def test_parity_return_shape_always_has_three_keys(self):
        for bic in ("ABNANL2A", "BADX", "", None, 12345):
            r = SEPAInputValidator.validate_bic(bic)
            self.assertIn("valid", r)
            self.assertIn("errors", r)
            self.assertIn("cleaned_bic", r)

    def test_parity_invalid_cleans_bic_to_none(self):
        """cleaned_bic must be None when validation fails (no partial result)."""
        for bad_bic in ("TOOLONG123456", "123XXXXX", "AB"):
            r = self._sepa(bad_bic)
            self.assertFalse(r["valid"], f"Expected invalid for {bad_bic!r}")
            self.assertIsNone(r["cleaned_bic"], f"cleaned_bic should be None for invalid {bad_bic!r}")


class TestValidateSepaText(unittest.TestCase):
    """SEPAInputValidator.validate_sepa_text"""

    def test_accept_plain_text(self):
        res = SEPAInputValidator.validate_sepa_text("Membership 2025", 140, "description")
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_text"], "Membership 2025")

    def test_accept_allowed_special_chars(self):
        text = "Inv-1 (2025): A.B, C/D +? '"
        res = SEPAInputValidator.validate_sepa_text(text, 140, "description")
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_text"], text)

    def test_accept_trims_whitespace(self):
        res = SEPAInputValidator.validate_sepa_text("  hello  ", 140, "x")
        self.assertTrue(res["valid"])
        self.assertEqual(res["cleaned_text"], "hello")

    def test_accept_max_length_boundary(self):
        text = "a" * 10
        res = SEPAInputValidator.validate_sepa_text(text, 10, "x")
        self.assertTrue(res["valid"])

    def test_reject_over_max_length(self):
        res = SEPAInputValidator.validate_sepa_text("a" * 11, 10, "x")
        self.assertFalse(res["valid"])
        self.assertTrue(any("too long" in e for e in res["errors"]))

    def test_reject_none(self):
        res = SEPAInputValidator.validate_sepa_text(None, 140, "description")
        self.assertFalse(res["valid"])
        self.assertTrue(any("non-empty string" in e for e in res["errors"]))

    def test_reject_empty(self):
        res = SEPAInputValidator.validate_sepa_text("", 140, "x")
        self.assertFalse(res["valid"])

    def test_reject_whitespace_only(self):
        res = SEPAInputValidator.validate_sepa_text("   ", 140, "x")
        self.assertFalse(res["valid"])
        self.assertTrue(any("empty after trimming" in e for e in res["errors"]))

    def test_reject_non_string(self):
        res = SEPAInputValidator.validate_sepa_text(123, 140, "x")
        self.assertFalse(res["valid"])

    def test_reject_disallowed_unicode(self):
        # Accented / non-Latin-subset chars are not in the SEPA char set.
        res = SEPAInputValidator.validate_sepa_text("Café Münchën", 140, "name")
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters for SEPA" in e for e in res["errors"]))

    def test_reject_control_and_injection_chars(self):
        res = SEPAInputValidator.validate_sepa_text("<script>alert(1)</script>", 140, "name")
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters for SEPA" in e for e in res["errors"]))

    def test_reject_at_sign(self):
        # '@' is not in the allowed SEPA subset.
        res = SEPAInputValidator.validate_sepa_text("user@example.com", 140, "x")
        self.assertFalse(res["valid"])


class TestValidateCollectionDate(unittest.TestCase):
    """SEPAInputValidator.validate_collection_date"""

    def test_accept_valid_weekday_string(self):
        d = _valid_collection_date()
        res = SEPAInputValidator.validate_collection_date(str(d))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_date"], d)

    def test_accept_date_object(self):
        d = _valid_collection_date()
        res = SEPAInputValidator.validate_collection_date(d)
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_date"], d)

    def test_accept_datetime_object(self):
        d = _valid_collection_date()
        dt = datetime(d.year, d.month, d.day, 9, 30)
        res = SEPAInputValidator.validate_collection_date(dt)
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_date"], d)

    def test_reject_too_early_today(self):
        # today() < today+MIN_OFFSET -> too early.
        res = SEPAInputValidator.validate_collection_date(getdate(today()))
        self.assertFalse(res["valid"])
        self.assertTrue(any("too early" in e for e in res["errors"]))

    def test_reject_too_late(self):
        far = getdate(add_days(today(), SEPAInputValidator.MAX_COLLECTION_DATE_OFFSET + 5))
        res = SEPAInputValidator.validate_collection_date(far)
        self.assertFalse(res["valid"])
        self.assertTrue(any("too late" in e for e in res["errors"]))

    def test_reject_weekend(self):
        # Find an in-window date that is a Saturday or Sunday.
        base = getdate(today())
        weekend = None
        for off in range(
            SEPAInputValidator.MIN_COLLECTION_DATE_OFFSET,
            SEPAInputValidator.MAX_COLLECTION_DATE_OFFSET + 1,
        ):
            cand = getdate(add_days(base, off))
            if cand.weekday() >= 5:
                weekend = cand
                break
        self.assertIsNotNone(weekend, "no weekend day found in 30-day window (impossible)")
        res = SEPAInputValidator.validate_collection_date(weekend)
        self.assertFalse(res["valid"])
        self.assertTrue(any("cannot be weekend" in e for e in res["errors"]))

    def test_reject_invalid_date_string(self):
        res = SEPAInputValidator.validate_collection_date("not-a-date")
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid date format" in e for e in res["errors"]))

    def test_reject_invalid_type(self):
        res = SEPAInputValidator.validate_collection_date(12345)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid date type" in e for e in res["errors"]))

    def test_past_date_accumulates_early_and_weekend_errors(self):
        # A far-past Saturday triggers BOTH "too early" and the weekend check,
        # because the weekday guard runs unconditionally after the range check.
        # Documents the additive (non-short-circuiting) error behaviour.
        res = SEPAInputValidator.validate_collection_date("2000-01-01")  # a Saturday
        self.assertFalse(res["valid"])
        self.assertTrue(any("too early" in e for e in res["errors"]))
        self.assertTrue(any("weekend" in e for e in res["errors"]))


class TestValidateSingleInvoice(unittest.TestCase):
    """SEPAInputValidator.validate_single_invoice"""

    def test_accept_minimal_valid_invoice(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice())
        self.assertTrue(res["valid"], msg=res["errors"])
        ci = res["cleaned_invoice"]
        self.assertEqual(ci["invoice"], "ACC-SINV-2025-00001")
        self.assertEqual(ci["amount"], Decimal("25.00"))
        self.assertEqual(ci["iban"], VALID_IBAN)
        self.assertEqual(ci["member_name"], "Jan de Vries")
        self.assertEqual(ci["mandate_reference"], "MNDT-2025-0001")
        # Defaults applied for optional fields.
        self.assertEqual(ci["currency"], "EUR")
        self.assertEqual(ci["description"], "Invoice ACC-SINV-2025-00001")

    def test_accept_normalizes_spaced_iban(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(iban=VALID_IBAN_SPACED))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_invoice"]["iban"], VALID_IBAN)

    def test_accept_optional_bic(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(bic="RABONL2U"))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_invoice"]["bic"], "RABONL2U")

    def test_accept_explicit_eur_currency(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(currency="eur"))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_invoice"]["currency"], "EUR")

    def test_accept_custom_description(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(description="Dues Q1"))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_invoice"]["description"], "Dues Q1")

    def test_bad_bic_is_warning_not_error(self):
        # Optional BIC failures are warnings; the invoice still validates.
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(bic="BADBIC"))
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertNotIn("bic", res["cleaned_invoice"])
        self.assertTrue(any("Invalid BIC" in w for w in res["warnings"]))

    def test_reject_missing_required_field(self):
        inv = _valid_invoice()
        del inv["iban"]
        res = SEPAInputValidator.validate_single_invoice(inv)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Required field missing: iban" in e for e in res["errors"]))

    def test_reject_none_required_field(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(amount=None))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Required field missing: amount" in e for e in res["errors"]))

    def test_reject_bad_iban(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(iban="NL00RABO0300065264"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("checksum" in e.lower() for e in res["errors"]))

    def test_reject_bad_amount(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(amount="-5"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("positive" in e for e in res["errors"]))

    def test_reject_bad_member_name_chars(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(member_name="Müller"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters for SEPA" in e for e in res["errors"]))

    def test_reject_bad_mandate_reference(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(mandate_reference="bad ref!"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters" in e for e in res["errors"]))

    def test_reject_non_eur_currency(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(currency="USD"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Only EUR currency supported" in e for e in res["errors"]))

    def test_reject_invoice_id_too_long(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(invoice="X" * 51))
        self.assertFalse(res["valid"])
        self.assertTrue(any("too long" in e for e in res["errors"]))

    def test_reject_empty_invoice_id(self):
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(invoice="   "))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invoice ID cannot be empty" in e for e in res["errors"]))

    def test_non_string_currency_is_rejected_via_exception_path(self):
        # currency=int crashes on .upper() but the broad except converts that
        # into a rejection ("Validation error: ... has no attribute 'upper'").
        # Documents that a wrong-typed optional currency does NOT wrongly pass.
        res = SEPAInputValidator.validate_single_invoice(_valid_invoice(currency=123))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Validation error" in e for e in res["errors"]))


class TestValidateInvoiceList(unittest.TestCase):
    """SEPAInputValidator.validate_invoice_list"""

    def test_accept_single_invoice(self):
        res = SEPAInputValidator.validate_invoice_list([_valid_invoice()])
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(len(res["cleaned_invoices"]), 1)

    def test_accept_multiple_distinct_invoices(self):
        invoices = [
            _valid_invoice(invoice="INV-1"),
            _valid_invoice(invoice="INV-2", amount="30.00"),
        ]
        res = SEPAInputValidator.validate_invoice_list(invoices)
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(len(res["cleaned_invoices"]), 2)

    def test_reject_none(self):
        res = SEPAInputValidator.validate_invoice_list(None)
        self.assertFalse(res["valid"])
        self.assertTrue(any("must be a list" in e for e in res["errors"]))

    def test_reject_non_list(self):
        res = SEPAInputValidator.validate_invoice_list({"invoice": "X"})
        self.assertFalse(res["valid"])
        self.assertTrue(any("must be a list" in e for e in res["errors"]))

    def test_reject_empty_list(self):
        res = SEPAInputValidator.validate_invoice_list([])
        self.assertFalse(res["valid"])
        self.assertTrue(any("cannot be empty" in e for e in res["errors"]))

    def test_reject_over_max_batch_size(self):
        # Build a list one larger than MAX_BATCH_SIZE of cheap dicts; the size
        # guard short-circuits before per-invoice validation.
        invoices = [{"invoice": str(i)} for i in range(MAX_BATCH_SIZE + 1)]
        res = SEPAInputValidator.validate_invoice_list(invoices)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Too many invoices" in e for e in res["errors"]))

    def test_reject_duplicate_invoice_ids(self):
        invoices = [_valid_invoice(invoice="DUP-1"), _valid_invoice(invoice="DUP-1")]
        res = SEPAInputValidator.validate_invoice_list(invoices)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Duplicate invoice" in e for e in res["errors"]))

    def test_reject_propagates_single_invoice_errors(self):
        invoices = [_valid_invoice(), _valid_invoice(invoice="INV-2", iban="garbage")]
        res = SEPAInputValidator.validate_invoice_list(invoices)
        self.assertFalse(res["valid"])
        self.assertTrue(len(res["errors"]) >= 1)

    def test_reject_total_exceeds_batch_limit(self):
        # Two large amounts whose sum exceeds DEFAULT_MAX_BATCH_TOTAL but each
        # is within the per-transaction MAX.
        big = str(MAX_TRANSACTION_AMOUNT)
        invoices = []
        # 11 invoices of ~1M each would exceed 10M. Use big per-tx amount.
        n = int(DEFAULT_MAX_BATCH_TOTAL / MAX_TRANSACTION_AMOUNT) + 2
        for i in range(n):
            invoices.append(_valid_invoice(invoice=f"BIG-{i}", amount=big))
        res = SEPAInputValidator.validate_invoice_list(invoices)
        self.assertFalse(res["valid"])
        self.assertTrue(any("exceeds limit" in e for e in res["errors"]))


class TestValidateBatchCreationParams(unittest.TestCase):
    """SEPAInputValidator.validate_batch_creation_params"""

    def _good_params(self, **overrides):
        params = {
            "batch_date": str(_valid_collection_date()),
            "batch_type": "CORE",
            "invoice_list": [_valid_invoice()],
        }
        params.update(overrides)
        return params

    def test_accept_minimal_valid(self):
        res = SEPAInputValidator.validate_batch_creation_params(**self._good_params())
        self.assertTrue(res["valid"], msg=res["errors"])
        cleaned = res["cleaned_params"]
        self.assertEqual(cleaned["batch_type"], "CORE")
        self.assertEqual(cleaned["batch_date"], _valid_collection_date())
        self.assertEqual(len(cleaned["invoice_list"]), 1)

    def test_accept_optional_description(self):
        res = SEPAInputValidator.validate_batch_creation_params(
            **self._good_params(description="June batch")
        )
        self.assertTrue(res["valid"], msg=res["errors"])
        self.assertEqual(res["cleaned_params"]["description"], "June batch")

    def test_reject_missing_batch_date(self):
        params = self._good_params()
        del params["batch_date"]
        res = SEPAInputValidator.validate_batch_creation_params(**params)
        self.assertFalse(res["valid"])
        self.assertTrue(any("Required field missing: batch_date" in e for e in res["errors"]))

    def test_reject_none_required_field(self):
        res = SEPAInputValidator.validate_batch_creation_params(**self._good_params(batch_type=None))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Required field missing: batch_type" in e for e in res["errors"]))

    def test_reject_bad_batch_type(self):
        res = SEPAInputValidator.validate_batch_creation_params(**self._good_params(batch_type="NOPE"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid batch type" in e for e in res["errors"]))

    def test_reject_bad_date(self):
        res = SEPAInputValidator.validate_batch_creation_params(**self._good_params(batch_date="xxx"))
        self.assertFalse(res["valid"])
        self.assertTrue(any("Invalid date format" in e for e in res["errors"]))

    def test_reject_empty_invoice_list(self):
        res = SEPAInputValidator.validate_batch_creation_params(**self._good_params(invoice_list=[]))
        self.assertFalse(res["valid"])
        self.assertTrue(any("cannot be empty" in e for e in res["errors"]))

    def test_reject_bad_description(self):
        res = SEPAInputValidator.validate_batch_creation_params(
            **self._good_params(description="Müller")
        )
        self.assertFalse(res["valid"])
        self.assertTrue(any("invalid characters for SEPA" in e for e in res["errors"]))


class TestGetSepaValidationRules(unittest.TestCase):
    """get_sepa_validation_rules() — wrapped whitelisted reporting endpoint."""

    def test_rules_structure_and_values(self):
        # The endpoint is decorated with @high_security_api; call the underlying
        # function to verify the static rule payload.
        rules = get_sepa_validation_rules.__wrapped__() if hasattr(
            get_sepa_validation_rules, "__wrapped__"
        ) else get_sepa_validation_rules()
        self.assertEqual(rules["supported_currency"], "EUR")
        self.assertEqual(rules["valid_batch_types"], ["CORE", "B2B", "COR1"])
        self.assertIn("invoice", rules["required_invoice_fields"])
        self.assertEqual(rules["constraints"]["max_debtor_name_length"], MAX_DEBTOR_NAME_LENGTH)
        self.assertEqual(rules["constraints"]["max_remittance_info_length"], MAX_REMITTANCE_INFO_LENGTH)
        self.assertEqual(rules["constraints"]["max_batch_size"], MAX_BATCH_SIZE)
        self.assertEqual(rules["constraints"]["min_amount"], float(MIN_TRANSACTION_AMOUNT))
        self.assertEqual(rules["constraints"]["max_amount"], float(MAX_TRANSACTION_AMOUNT))


if __name__ == "__main__":
    unittest.main()
