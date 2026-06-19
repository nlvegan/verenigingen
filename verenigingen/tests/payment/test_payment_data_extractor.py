"""
Real-integration tests for PaymentDataExtractor.

The extractor is pure data-shaping logic over Mollie object/dict shapes. These
tests feed REAL plain-object / dict inputs (built with SimpleNamespace and
dicts, not Mock) and assert extracted values, validation errors, and fallbacks.

Complements `test_payment_data_extractor_examples.py` (which covers the
docstring happy-paths) by exercising the uncovered error branches, multi-type
extraction, currency validation against a real Company, and date parsing.
"""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen_payments.utils.payment_data_extractor import (
    MollieObjectType,
    PaymentDataExtractor,
    get_payment_data_extractor,
)


def _amount(value=None, currency=None, decimal_value=None):
    ns = SimpleNamespace()
    if value is not None:
        ns.value = value
    if currency is not None:
        ns.currency = currency
    if decimal_value is not None:
        ns.decimal_value = decimal_value
    return ns


class TestPaymentDataExtractor(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.extractor = PaymentDataExtractor()

    # ------------------------------------------------------------------
    # extract_amount: payment objects
    # ------------------------------------------------------------------
    def test_extract_amount_dict_payment(self):
        payment = SimpleNamespace(amount={"value": "25.50", "currency": "EUR"})
        self.assertEqual(self.extractor.extract_amount(payment), 25.50)

    def test_extract_amount_attr_payment(self):
        payment = SimpleNamespace(amount=_amount(value="10.00", currency="EUR"))
        self.assertEqual(self.extractor.extract_amount(payment), 10.0)

    def test_extract_amount_dict_like_payment(self):
        # dict-like object via .get()
        payment = {"amount": {"value": "7.25", "currency": "EUR"}}
        self.assertEqual(self.extractor.extract_amount(payment), 7.25)

    def test_extract_amount_missing_amount_raises(self):
        with self.assertRaises(ValueError):
            self.extractor.extract_amount(SimpleNamespace(amount=None))

    def test_extract_amount_negative_raises(self):
        payment = SimpleNamespace(amount={"value": "-5.00"})
        with self.assertRaises(ValueError):
            self.extractor.extract_amount(payment)

    def test_extract_amount_zero_disallowed_by_default(self):
        payment = SimpleNamespace(amount={"value": "0"})
        with self.assertRaises(ValueError):
            self.extractor.extract_amount(payment)

    def test_extract_amount_zero_allowed(self):
        payment = SimpleNamespace(amount={"value": "0"})
        self.assertEqual(self.extractor.extract_amount(payment, allow_zero=True), 0.0)

    def test_extract_amount_invalid_type_raises(self):
        payment = SimpleNamespace(amount={"value": ["not", "a", "number"]})
        with self.assertRaises(ValueError):
            self.extractor.extract_amount(payment)

    def test_extract_amount_large_warns_but_returns(self):
        payment = SimpleNamespace(amount={"value": "5000000"})
        # exceeds max_amount default (1_000_000) -> warns but returns the value
        self.assertEqual(self.extractor.extract_amount(payment), 5000000.0)

    # ------------------------------------------------------------------
    # extract_amount: balance transaction / settlement / subscription
    # ------------------------------------------------------------------
    def test_extract_amount_balance_transaction_result(self):
        txn = SimpleNamespace(result_amount=_amount(decimal_value="15.75", currency="EUR"))
        self.assertEqual(self.extractor.extract_amount(txn, source_type="balance_transaction"), 15.75)

    def test_extract_amount_balance_transaction_fallback_initial(self):
        txn = SimpleNamespace(
            result_amount=None,
            initial_amount=_amount(decimal_value="9.00", currency="EUR"),
        )
        self.assertEqual(self.extractor.extract_amount(txn, source_type="balance_transaction"), 9.0)

    def test_extract_amount_balance_transaction_missing_raises(self):
        txn = SimpleNamespace(result_amount=None, initial_amount=None)
        with self.assertRaises(ValueError):
            self.extractor.extract_amount(txn, source_type="balance_transaction")

    def test_extract_amount_settlement_decimal(self):
        settlement = SimpleNamespace(amount=_amount(decimal_value="123.45", currency="EUR"))
        self.assertEqual(self.extractor.extract_amount(settlement, source_type="settlement"), 123.45)

    def test_extract_amount_subscription_value_fallback(self):
        sub = SimpleNamespace(amount=_amount(value="12.00", currency="EUR"))
        self.assertEqual(
            self.extractor.extract_amount(sub, source_type="subscription", allow_zero=True), 12.0
        )

    def test_extract_amount_decimal_dict_access(self):
        obj = SimpleNamespace(amount={"decimal_value": "5.50", "currency": "EUR"})
        self.assertEqual(self.extractor.extract_amount(obj, source_type="settlement"), 5.5)

    def test_extract_amount_enum_source_type(self):
        settlement = SimpleNamespace(amount=_amount(decimal_value="50.00", currency="EUR"))
        self.assertEqual(
            self.extractor.extract_amount(settlement, source_type=MollieObjectType.SETTLEMENT), 50.0
        )

    def test_extract_amount_as_decimal(self):
        payment = SimpleNamespace(amount={"value": "25.50"})
        result = self.extractor.extract_amount_as_decimal(payment)
        self.assertIsInstance(result, Decimal)
        self.assertEqual(result, Decimal("25.5"))

    # ------------------------------------------------------------------
    # extract_currency (with company validation)
    # ------------------------------------------------------------------
    def _get_company(self):
        company = frappe.db.get_value("Company", {}, "name")
        self.assertTrue(company, "A Company must exist on the test site")
        return company

    def test_extract_currency_matches_company(self):
        company = self._get_company()
        company_currency = frappe.get_cached_value("Company", company, "default_currency")
        payment = SimpleNamespace(amount={"value": "1", "currency": company_currency})
        self.assertEqual(self.extractor.extract_currency(payment, company), company_currency)

    def test_extract_currency_invalid_format_raises(self):
        company = self._get_company()
        payment = SimpleNamespace(amount={"value": "1", "currency": "euro"})
        with self.assertRaises(ValueError):
            self.extractor.extract_currency(payment, company)

    def test_extract_currency_missing_strict_raises(self):
        company = self._get_company()
        payment = SimpleNamespace(amount={"value": "1"})  # no currency
        with self.assertRaises(ValueError):
            self.extractor.extract_currency(payment, company, strict_validation=True)

    def test_extract_currency_missing_lenient_defaults_eur(self):
        company = self._get_company()
        payment = SimpleNamespace(amount={"value": "1"})
        self.assertEqual(self.extractor.extract_currency(payment, company, strict_validation=False), "EUR")

    def test_extract_currency_balance_transaction(self):
        company = self._get_company()
        company_currency = frappe.get_cached_value("Company", company, "default_currency")
        txn = SimpleNamespace(result_amount=_amount(decimal_value="1", currency=company_currency))
        self.assertEqual(
            self.extractor.extract_currency(txn, company, source_type="balance_transaction"),
            company_currency,
        )

    # ------------------------------------------------------------------
    # extract_currency_simple (no company validation)
    # ------------------------------------------------------------------
    def test_currency_simple_payment(self):
        payment = SimpleNamespace(amount={"value": "1", "currency": "USD"})
        self.assertEqual(self.extractor.extract_currency_simple(payment), "USD")

    def test_currency_simple_settlement(self):
        settlement = SimpleNamespace(amount=_amount(decimal_value="1", currency="GBP"))
        self.assertEqual(self.extractor.extract_currency_simple(settlement, source_type="settlement"), "GBP")

    def test_currency_simple_balance_transaction_fallback_initial(self):
        txn = SimpleNamespace(result_amount=None, initial_amount=_amount(decimal_value="1", currency="EUR"))
        self.assertEqual(
            self.extractor.extract_currency_simple(txn, source_type="balance_transaction"), "EUR"
        )

    def test_currency_simple_missing_uses_fallback(self):
        payment = SimpleNamespace(amount={"value": "1"})  # no currency
        self.assertEqual(self.extractor.extract_currency_simple(payment, fallback="USD"), "USD")

    def test_currency_simple_missing_strict_raises(self):
        payment = SimpleNamespace(amount={"value": "1"})
        with self.assertRaises(ValueError):
            self.extractor.extract_currency_simple(payment, strict=True)

    def test_currency_simple_extraction_error_fallback(self):
        # amount present but not a dict and no .currency attr -> returns fallback
        payment = SimpleNamespace(amount=_amount(value="1"))
        self.assertEqual(self.extractor.extract_currency_simple(payment), "EUR")

    # ------------------------------------------------------------------
    # extract_payment_date / extract_date
    # ------------------------------------------------------------------
    def test_extract_payment_date_iso_string(self):
        data = {"paid_at": "2025-12-01T23:45:30+00:00"}
        self.assertEqual(self.extractor.extract_payment_date(data), date(2025, 12, 1))

    def test_extract_payment_date_fallback_field(self):
        data = {"created_at": "2025-11-15T10:00:00+00:00"}
        self.assertEqual(self.extractor.extract_payment_date(data), date(2025, 11, 15))

    def test_extract_payment_date_datetime_object(self):
        data = {"paid_at": datetime(2025, 10, 5, 8, 0, 0)}
        self.assertEqual(self.extractor.extract_payment_date(data), date(2025, 10, 5))

    def test_extract_payment_date_date_object(self):
        data = {"paid_at": date(2025, 9, 9)}
        self.assertEqual(self.extractor.extract_payment_date(data), date(2025, 9, 9))

    def test_extract_payment_date_missing_falls_back_to_today(self):
        result = self.extractor.extract_payment_date({})
        self.assertEqual(result, frappe.utils.getdate())

    def test_extract_payment_date_attr_object(self):
        obj = SimpleNamespace(paid_at="2025-08-08T00:00:00+00:00", created_at=None)
        self.assertEqual(self.extractor.extract_payment_date(obj), date(2025, 8, 8))

    def test_extract_date_present(self):
        obj = SimpleNamespace(paid_at="2025-07-07")
        self.assertEqual(self.extractor.extract_date(obj), date(2025, 7, 7))

    def test_extract_date_missing_fallback_today(self):
        obj = SimpleNamespace()
        self.assertEqual(self.extractor.extract_date(obj), frappe.utils.getdate())

    def test_extract_date_missing_strict_raises(self):
        obj = SimpleNamespace()
        with self.assertRaises(ValueError):
            self.extractor.extract_date(obj, fallback_to_today=False)

    # ------------------------------------------------------------------
    # extract_payment_id / extract_description
    # ------------------------------------------------------------------
    def test_extract_payment_id(self):
        self.assertEqual(self.extractor.extract_payment_id(SimpleNamespace(id="tr_abc")), "tr_abc")

    def test_extract_payment_id_missing_raises(self):
        with self.assertRaises(ValueError):
            self.extractor.extract_payment_id(SimpleNamespace(id=None))

    def test_extract_description_present(self):
        self.assertEqual(
            self.extractor.extract_description(SimpleNamespace(description="Donation")), "Donation"
        )

    def test_extract_description_fallback(self):
        obj = SimpleNamespace(description=None)
        self.assertEqual(self.extractor.extract_description(obj, fallback_description="Fallback"), "Fallback")

    def test_extract_description_uses_payment_id(self):
        obj = SimpleNamespace(description=None, id="tr_xyz")
        self.assertEqual(self.extractor.extract_description(obj), "Mollie payment tr_xyz")

    def test_extract_description_unknown_id(self):
        obj = SimpleNamespace(description=None)
        self.assertEqual(self.extractor.extract_description(obj), "Mollie payment UNKNOWN")

    # ------------------------------------------------------------------
    # extract_balance_amounts
    # ------------------------------------------------------------------
    def test_extract_balance_amounts_full(self):
        balance = SimpleNamespace(
            available_amount=_amount(decimal_value="1234.56", currency="EUR"),
            pending_amount=_amount(decimal_value="567.89", currency="EUR"),
        )
        result = self.extractor.extract_balance_amounts(balance)
        self.assertEqual(result["available"], 1234.56)
        self.assertEqual(result["pending"], 567.89)
        self.assertEqual(result["currency"], "EUR")

    def test_extract_balance_amounts_missing_returns_zeros(self):
        balance = SimpleNamespace(available_amount=None, pending_amount=None)
        result = self.extractor.extract_balance_amounts(balance)
        self.assertEqual(result, {"available": 0.0, "pending": 0.0, "currency": "EUR"})

    def test_extract_balance_amounts_currency_from_pending(self):
        # available has no currency -> currency taken from pending
        balance = SimpleNamespace(
            available_amount=_amount(decimal_value="10.00"),
            pending_amount=_amount(decimal_value="5.00", currency="USD"),
        )
        result = self.extractor.extract_balance_amounts(balance)
        self.assertEqual(result["available"], 10.0)
        self.assertEqual(result["currency"], "USD")

    def test_factory_returns_extractor(self):
        self.assertIsInstance(get_payment_data_extractor(), PaymentDataExtractor)
