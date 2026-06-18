# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Unit tests for ING Checkout (Pay.nl) data models.

These exercise the dataclasses in ``models.py`` end-to-end: enum status
mapping, ``from_api_response`` parsing (amount-in-cents, date parsing, debtor/
customer fallbacks), the ``is_*`` predicate properties, and the ``to_dict`` /
``to_doctype_dict`` serialization. The models have no Frappe dependencies so the
tests run as plain assertions on real objects (no mocking).
"""

from datetime import date
from decimal import Decimal

from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.models import (
    DirectDebitStatus,
    INGDirectDebit,
    INGMandate,
    INGTransaction,
    MandateStatus,
    MandateType,
    TransactionStatus,
)


class TestTransactionStatusEnum(FrappeTestCase):
    def test_known_upper_and_lower_map(self):
        self.assertEqual(TransactionStatus.from_api_status("PAID"), TransactionStatus.PAID)
        self.assertEqual(TransactionStatus.from_api_status("paid"), TransactionStatus.PAID)
        self.assertEqual(TransactionStatus.from_api_status("CANCEL"), TransactionStatus.CANCELLED)
        self.assertEqual(TransactionStatus.from_api_status("refund"), TransactionStatus.REFUNDED)

    def test_unknown_status_defaults_to_pending(self):
        self.assertEqual(TransactionStatus.from_api_status("something_weird"), TransactionStatus.PENDING)

    def test_enum_is_str_valued(self):
        # str-Enum: the .value is the human label used in DocType fields.
        self.assertEqual(TransactionStatus.PAID.value, "Paid")


class TestMandateStatusEnum(FrappeTestCase):
    def test_active_mapping(self):
        self.assertEqual(MandateStatus.from_api_status("ACTIVE"), MandateStatus.ACTIVE)
        self.assertEqual(MandateStatus.from_api_status("failed"), MandateStatus.FAILED)

    def test_unknown_defaults_to_pending(self):
        self.assertEqual(MandateStatus.from_api_status("zzz"), MandateStatus.PENDING)


class TestDirectDebitStatusEnum(FrappeTestCase):
    def test_paid_aliases_to_completed(self):
        # Pay.nl reports "paid" for a settled debit; we model it as COMPLETED.
        self.assertEqual(DirectDebitStatus.from_api_status("PAID"), DirectDebitStatus.COMPLETED)
        self.assertEqual(DirectDebitStatus.from_api_status("reversed"), DirectDebitStatus.REVERSED)

    def test_unknown_defaults_to_pending(self):
        self.assertEqual(DirectDebitStatus.from_api_status("nope"), DirectDebitStatus.PENDING)


class TestINGTransactionFromAPI(FrappeTestCase):
    def test_amount_converted_from_cents(self):
        txn = INGTransaction.from_api_response(
            {"id": "EX-1", "status": "PAID", "amount": {"value": 12345, "currency": "EUR"}}
        )
        self.assertEqual(txn.amount, Decimal("123.45"))
        self.assertEqual(txn.currency, "EUR")
        self.assertEqual(txn.status, TransactionStatus.PAID)
        self.assertEqual(txn.transaction_id, "EX-1")

    def test_amount_as_scalar_not_dict(self):
        txn = INGTransaction.from_api_response({"id": "EX-2", "amount": "50.00"})
        self.assertEqual(txn.amount, Decimal("50.00"))
        # No currency in scalar form -> defaults to EUR.
        self.assertEqual(txn.currency, "EUR")

    def test_payment_method_from_dict_name(self):
        txn = INGTransaction.from_api_response(
            {"id": "EX-3", "amount": {}, "paymentMethod": {"name": "iDEAL", "id": 10}}
        )
        self.assertEqual(txn.payment_method, "iDEAL")

    def test_payment_method_falls_back_to_id(self):
        txn = INGTransaction.from_api_response({"id": "EX-4", "amount": {}, "paymentMethod": {"id": 10}})
        self.assertEqual(txn.payment_method, "10")

    def test_payment_method_scalar(self):
        txn = INGTransaction.from_api_response({"id": "EX-5", "amount": {}, "paymentMethod": "ideal"})
        self.assertEqual(txn.payment_method, "ideal")

    def test_customer_falls_back_to_debtor(self):
        txn = INGTransaction.from_api_response(
            {"id": "EX-6", "amount": {}, "debtor": {"name": "Jan", "iban": "NL00", "bic": "INGBNL2A"}}
        )
        self.assertEqual(txn.customer_name, "Jan")
        self.assertEqual(txn.customer_iban, "NL00")
        self.assertEqual(txn.customer_bic, "INGBNL2A")

    def test_redirect_url_from_links_then_fallback(self):
        with_links = INGTransaction.from_api_response(
            {"id": "EX-7", "amount": {}, "links": {"redirect": "https://pay/abc"}}
        )
        self.assertEqual(with_links.redirect_url, "https://pay/abc")
        fallback = INGTransaction.from_api_response(
            {"id": "EX-8", "amount": {}, "redirectUrl": "https://pay/xyz"}
        )
        self.assertEqual(fallback.redirect_url, "https://pay/xyz")

    def test_transaction_id_falls_back_to_orderId(self):
        txn = INGTransaction.from_api_response({"orderId": "EX-9", "amount": {}})
        self.assertEqual(txn.transaction_id, "EX-9")

    def test_raw_response_preserved(self):
        data = {"id": "EX-10", "amount": {"value": 100}}
        txn = INGTransaction.from_api_response(data)
        self.assertEqual(txn.raw_response, data)


class TestINGTransactionPredicates(FrappeTestCase):
    def _txn(self, status):
        return INGTransaction(transaction_id="t", status=status, amount=Decimal("1"))

    def test_is_paid(self):
        self.assertTrue(self._txn(TransactionStatus.PAID).is_paid)
        self.assertTrue(self._txn(TransactionStatus.PAID_PE_FAILED).is_paid)
        self.assertFalse(self._txn(TransactionStatus.PENDING).is_paid)

    def test_is_pending(self):
        self.assertTrue(self._txn(TransactionStatus.PENDING).is_pending)
        self.assertTrue(self._txn(TransactionStatus.PROCESSING).is_pending)
        self.assertFalse(self._txn(TransactionStatus.PAID).is_pending)

    def test_is_failed(self):
        self.assertTrue(self._txn(TransactionStatus.CANCELLED).is_failed)
        self.assertTrue(self._txn(TransactionStatus.EXPIRED).is_failed)
        self.assertTrue(self._txn(TransactionStatus.DENIED).is_failed)
        self.assertFalse(self._txn(TransactionStatus.PAID).is_failed)


class TestINGTransactionSerialization(FrappeTestCase):
    def test_to_dict_uses_string_amount_and_status_value(self):
        txn = INGTransaction(
            transaction_id="EX-1",
            status=TransactionStatus.PAID,
            amount=Decimal("12.50"),
            payment_method="iDEAL",
        )
        d = txn.to_dict()
        self.assertEqual(d["status"], "Paid")
        self.assertEqual(d["amount"], "12.50")
        self.assertEqual(d["transaction_id"], "EX-1")
        self.assertNotIn("doctype", d)

    def test_to_doctype_dict_uses_float_amount_and_doctype_key(self):
        txn = INGTransaction(transaction_id="EX-1", status=TransactionStatus.PAID, amount=Decimal("12.50"))
        d = txn.to_doctype_dict()
        self.assertEqual(d["doctype"], "ING Checkout Transaction")
        self.assertEqual(d["amount"], 12.50)
        self.assertIsInstance(d["amount"], float)
        self.assertEqual(d["status"], "Paid")


class TestINGMandateFromAPI(FrappeTestCase):
    def test_type_parsed_and_lowercased(self):
        m = INGMandate.from_api_response({"id": "IO-1", "type": "RECURRING", "status": "active"})
        self.assertEqual(m.mandate_type, MandateType.RECURRING)

    def test_invalid_type_defaults_to_single(self):
        m = INGMandate.from_api_response({"id": "IO-2", "type": "bogus"})
        self.assertEqual(m.mandate_type, MandateType.SINGLE)

    def test_mandate_id_falls_back_to_id(self):
        m = INGMandate.from_api_response({"id": "IO-3"})
        self.assertEqual(m.mandate_id, "IO-3")
        m2 = INGMandate.from_api_response({"mandateId": "IO-4"})
        self.assertEqual(m2.mandate_id, "IO-4")

    def test_amount_dict_converted_from_cents(self):
        m = INGMandate.from_api_response({"id": "IO-5", "amount": {"value": 2500}})
        self.assertEqual(m.amount, Decimal("25"))

    def test_amount_scalar(self):
        m = INGMandate.from_api_response({"id": "IO-6", "amount": "30.00"})
        self.assertEqual(m.amount, Decimal("30.00"))

    def test_amount_absent_is_none(self):
        m = INGMandate.from_api_response({"id": "IO-7"})
        self.assertIsNone(m.amount)

    def test_debtor_fields(self):
        m = INGMandate.from_api_response(
            {
                "id": "IO-8",
                "debtor": {
                    "name": "Jan",
                    "iban": "NL00",
                    "email": "j@x.nl",
                    "bic": "INGBNL2A",
                },
            }
        )
        self.assertEqual(m.debtor_name, "Jan")
        self.assertEqual(m.debtor_email, "j@x.nl")
        self.assertEqual(m.debtor_bic, "INGBNL2A")

    def test_dates_parsed_from_iso_and_datetime(self):
        m = INGMandate.from_api_response(
            {
                "id": "IO-9",
                "createdAt": "2025-01-15T10:30:00Z",
                "firstCollectionDate": "2025-02-01",
                "validUntil": "2026-01-01",
            }
        )
        self.assertEqual(m.created_date, date(2025, 1, 15))
        self.assertEqual(m.first_collection_date, date(2025, 2, 1))
        self.assertEqual(m.expiry_date, date(2026, 1, 1))

    def test_bad_date_is_none(self):
        self.assertIsNone(INGMandate._parse_date("not-a-date"))
        self.assertIsNone(INGMandate._parse_date(None))
        self.assertIsNone(INGMandate._parse_date(""))


class TestINGMandatePredicates(FrappeTestCase):
    def _m(self, status=MandateStatus.ACTIVE, mtype=MandateType.SINGLE):
        return INGMandate(mandate_id="m", mandate_type=mtype, status=status)

    def test_is_active(self):
        self.assertTrue(self._m(status=MandateStatus.ACTIVE).is_active)
        self.assertFalse(self._m(status=MandateStatus.PENDING).is_active)

    def test_is_usable(self):
        self.assertTrue(self._m(status=MandateStatus.ACTIVE).is_usable)
        self.assertTrue(self._m(status=MandateStatus.PENDING).is_usable)
        self.assertFalse(self._m(status=MandateStatus.CANCELLED).is_usable)

    def test_is_recurring(self):
        self.assertTrue(self._m(mtype=MandateType.RECURRING).is_recurring)
        self.assertTrue(self._m(mtype=MandateType.FLEXIBLE).is_recurring)
        self.assertFalse(self._m(mtype=MandateType.SINGLE).is_recurring)


class TestINGMandateSerialization(FrappeTestCase):
    def test_to_dict_none_amount_and_dates(self):
        m = INGMandate(mandate_id="IO-1", mandate_type=MandateType.SINGLE, status=MandateStatus.PENDING)
        d = m.to_dict()
        self.assertIsNone(d["amount"])
        self.assertIsNone(d["created_date"])
        self.assertEqual(d["mandate_type"], "single")
        self.assertEqual(d["status"], "Pending")

    def test_to_dict_with_amount_and_dates(self):
        m = INGMandate(
            mandate_id="IO-1",
            mandate_type=MandateType.FLEXIBLE,
            status=MandateStatus.ACTIVE,
            amount=Decimal("25.00"),
            created_date=date(2025, 1, 1),
            expiry_date=date(2026, 1, 1),
        )
        d = m.to_dict()
        self.assertEqual(d["amount"], "25.00")
        self.assertEqual(d["created_date"], "2025-01-01")
        self.assertEqual(d["expiry_date"], "2026-01-01")

    def test_to_doctype_dict_float_amount(self):
        m = INGMandate(
            mandate_id="IO-1",
            mandate_type=MandateType.SINGLE,
            status=MandateStatus.ACTIVE,
            amount=Decimal("25.00"),
        )
        d = m.to_doctype_dict()
        self.assertEqual(d["doctype"], "ING Checkout Mandate")
        self.assertEqual(d["amount"], 25.0)
        self.assertIsInstance(d["amount"], float)

    def test_to_doctype_dict_none_amount(self):
        m = INGMandate(mandate_id="IO-1", mandate_type=MandateType.SINGLE, status=MandateStatus.ACTIVE)
        self.assertIsNone(m.to_doctype_dict()["amount"])


class TestINGDirectDebitFromAPI(FrappeTestCase):
    def test_amount_from_cents_and_dates(self):
        dd = INGDirectDebit.from_api_response(
            {
                "referenceId": "IL-1",
                "mandateId": "IO-1",
                "status": "PAID",
                "amount": {"value": 5000, "currency": "EUR"},
                "processDate": "2025-03-01",
                "executionDate": "2025-03-02T08:00:00Z",
            }
        )
        self.assertEqual(dd.amount, Decimal("50"))
        self.assertEqual(dd.status, DirectDebitStatus.COMPLETED)
        self.assertEqual(dd.process_date, date(2025, 3, 1))
        self.assertEqual(dd.execution_date, date(2025, 3, 2))

    def test_reference_id_falls_back_to_id(self):
        dd = INGDirectDebit.from_api_response({"id": "IL-9", "amount": 0})
        self.assertEqual(dd.reference_id, "IL-9")

    def test_amount_scalar(self):
        dd = INGDirectDebit.from_api_response({"referenceId": "IL-2", "amount": "10.00"})
        self.assertEqual(dd.amount, Decimal("10.00"))


class TestINGDirectDebitPredicates(FrappeTestCase):
    def _dd(self, status):
        return INGDirectDebit(reference_id="r", mandate_id="m", status=status, amount=Decimal("1"))

    def test_is_completed(self):
        self.assertTrue(self._dd(DirectDebitStatus.COMPLETED).is_completed)
        self.assertFalse(self._dd(DirectDebitStatus.PENDING).is_completed)

    def test_is_pending(self):
        self.assertTrue(self._dd(DirectDebitStatus.PENDING).is_pending)
        self.assertTrue(self._dd(DirectDebitStatus.PROCESSING).is_pending)
        self.assertFalse(self._dd(DirectDebitStatus.COMPLETED).is_pending)

    def test_is_failed(self):
        self.assertTrue(self._dd(DirectDebitStatus.FAILED).is_failed)
        self.assertTrue(self._dd(DirectDebitStatus.REVERSED).is_failed)
        self.assertFalse(self._dd(DirectDebitStatus.COMPLETED).is_failed)

    def test_to_dict(self):
        dd = INGDirectDebit(
            reference_id="IL-1",
            mandate_id="IO-1",
            status=DirectDebitStatus.COMPLETED,
            amount=Decimal("50.00"),
            process_date=date(2025, 3, 1),
        )
        d = dd.to_dict()
        self.assertEqual(d["status"], "Completed")
        self.assertEqual(d["amount"], "50.00")
        self.assertEqual(d["process_date"], "2025-03-01")
        self.assertIsNone(d["execution_date"])
