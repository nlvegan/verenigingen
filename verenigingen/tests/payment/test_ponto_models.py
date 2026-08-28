"""
Ponto Domain Model Tests

Pure parsing / dataclass logic for ``ponto_models.py``:
- PontoAccount.from_api_response / iban property / to_dict
- PontoTransaction.from_api_response / date parsing / credit-debit / to_dict / to_bank_transaction_dict
- PontoSynchronization.from_api_response / status properties

These models are pure (no DB, no HTTP), so the tests feed realistic Ponto
JSON:API dicts and assert the parsed fields. No stubbing required.
"""

from datetime import date, datetime
from decimal import Decimal

from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from verenigingen.verenigingen_payments.ponto.core.ponto_models import (
    PontoAccount,
    PontoSynchronization,
    PontoTransaction,
)


class TestPontoAccountModel(FrappeTestCase):
    """PontoAccount parsing from JSON:API resource objects."""

    def _account_payload(self, **attr_overrides):
        attrs = {
            "reference": "NL91ABNA0417164300",
            "referenceType": "IBAN",
            "currency": "EUR",
            "currentBalance": "1234.56",
            "availableBalance": "1000.00",
            "description": "Main account",
            "product": "Business Current Account",
            "holderName": "Test Org BV",
            "financialInstitutionId": "fin-001",
            "internalReference": "INT-123",
            "deprecated": False,
        }
        attrs.update(attr_overrides)
        return {"type": "account", "id": "acct-uuid-1", "attributes": attrs}

    def test_from_api_response_basic_fields(self):
        acct = PontoAccount.from_api_response(self._account_payload())
        self.assertEqual(acct.id, "acct-uuid-1")
        self.assertEqual(acct.reference, "NL91ABNA0417164300")
        self.assertEqual(acct.reference_type, "IBAN")
        self.assertEqual(acct.currency, "EUR")
        self.assertEqual(acct.current_balance, Decimal("1234.56"))
        self.assertEqual(acct.available_balance, Decimal("1000.00"))
        self.assertEqual(acct.holder_name, "Test Org BV")
        self.assertEqual(acct.financial_institution_id, "fin-001")
        self.assertFalse(acct.deprecated)

    def test_iban_property_when_reference_type_iban(self):
        acct = PontoAccount.from_api_response(self._account_payload())
        self.assertEqual(acct.iban, "NL91ABNA0417164300")

    def test_iban_property_empty_when_not_iban(self):
        acct = PontoAccount.from_api_response(
            self._account_payload(referenceType="BBAN")
        )
        self.assertEqual(acct.iban, "")

    def test_currency_defaults_to_eur(self):
        payload = self._account_payload()
        del payload["attributes"]["currency"]
        acct = PontoAccount.from_api_response(payload)
        self.assertEqual(acct.currency, "EUR")

    def test_authorization_expiration_parsed(self):
        acct = PontoAccount.from_api_response(
            self._account_payload(
                authorizationExpirationExpectedAt="2026-12-31T23:59:59Z"
            )
        )
        self.assertIsInstance(acct.authorization_expiration_expected_at, datetime)
        self.assertEqual(acct.authorization_expiration_expected_at.year, 2026)

    def test_authorization_expiration_invalid_ignored(self):
        acct = PontoAccount.from_api_response(
            self._account_payload(authorizationExpirationExpectedAt="not-a-date")
        )
        self.assertIsNone(acct.authorization_expiration_expected_at)

    def test_missing_attributes_use_defaults(self):
        acct = PontoAccount.from_api_response({"id": "x"})
        self.assertEqual(acct.id, "x")
        self.assertEqual(acct.reference, "")
        self.assertEqual(acct.current_balance, Decimal("0"))
        self.assertEqual(acct.iban, "")  # reference_type not IBAN

    def test_to_dict_roundtrip(self):
        acct = PontoAccount.from_api_response(
            self._account_payload(authorizationExpirationExpectedAt="2026-06-01T00:00:00Z")
        )
        d = acct.to_dict()
        self.assertEqual(d["id"], "acct-uuid-1")
        self.assertEqual(d["current_balance"], "1234.56")
        self.assertEqual(d["reference_type"], "IBAN")
        self.assertTrue(d["authorization_expiration_expected_at"].startswith("2026-06-01"))

    def test_to_dict_null_expiration(self):
        acct = PontoAccount.from_api_response(self._account_payload())
        self.assertIsNone(acct.to_dict()["authorization_expiration_expected_at"])


class TestPontoTransactionModel(FrappeTestCase):
    """PontoTransaction parsing and computed properties."""

    def _txn_payload(self, **attr_overrides):
        attrs = {
            "amount": "-25.00",
            "currency": "EUR",
            "valueDate": "2026-03-15",
            "executionDate": "2026-03-16",
            "description": "Invoice payment",
            "counterpartName": "Supplier BV",
            "counterpartReference": "NL53RABO0123456789",
            "bankTransactionCode": "PMNT-RCDT-ESCT",
            "endToEndId": "E2E-1",
            "mandateId": "MND-1",
            "creditorId": "CRED-1",
        }
        attrs.update(attr_overrides)
        return {"type": "transaction", "id": "txn-uuid-1", "attributes": attrs}

    def test_from_api_response_basic(self):
        txn = PontoTransaction.from_api_response(self._txn_payload(), account_id="acct-1")
        self.assertEqual(txn.id, "txn-uuid-1")
        self.assertEqual(txn.amount, Decimal("-25.00"))
        self.assertEqual(txn.currency, "EUR")
        self.assertEqual(txn.value_date, date(2026, 3, 15))
        self.assertEqual(txn.execution_date, date(2026, 3, 16))
        self.assertEqual(txn.counterpart_name, "Supplier BV")
        self.assertEqual(txn.account_id, "acct-1")
        self.assertEqual(txn.mandate_id, "MND-1")

    def test_description_falls_back_to_remittance(self):
        payload = self._txn_payload()
        del payload["attributes"]["description"]
        payload["attributes"]["remittanceInformation"] = "Remittance text"
        txn = PontoTransaction.from_api_response(payload)
        self.assertEqual(txn.description, "Remittance text")

    def test_reference_prefers_structured(self):
        txn = PontoTransaction.from_api_response(
            self._txn_payload(remittanceInformationStructured="STRUCT-REF")
        )
        self.assertEqual(txn.reference, "STRUCT-REF")

    def test_fee_parsed_when_present(self):
        txn = PontoTransaction.from_api_response(self._txn_payload(fee="1.50"))
        self.assertEqual(txn.fee, Decimal("1.50"))

    def test_fee_none_when_absent(self):
        txn = PontoTransaction.from_api_response(self._txn_payload())
        self.assertIsNone(txn.fee)

    def test_is_credit_and_is_debit(self):
        debit = PontoTransaction.from_api_response(self._txn_payload(amount="-10"))
        credit = PontoTransaction.from_api_response(self._txn_payload(amount="42.00"))
        self.assertTrue(debit.is_debit)
        self.assertFalse(debit.is_credit)
        self.assertTrue(credit.is_credit)
        self.assertFalse(credit.is_debit)

    def test_counterpart_iban_property(self):
        txn = PontoTransaction.from_api_response(self._txn_payload())
        self.assertEqual(txn.counterpart_iban, "NL53RABO0123456789")

    def test_datetime_value_date_parsed_to_date(self):
        txn = PontoTransaction.from_api_response(
            self._txn_payload(valueDate="2026-03-15T08:30:00Z")
        )
        self.assertEqual(txn.value_date, date(2026, 3, 15))

    def test_missing_dates_default_to_today(self):
        # "Today" here is the SITE's calendar day (getdate()), not the server/process
        # one: this fallback becomes the transaction's booking date, and in the
        # late-UTC window the two name different days (#628).
        payload = self._txn_payload()
        del payload["attributes"]["valueDate"]
        del payload["attributes"]["executionDate"]
        txn = PontoTransaction.from_api_response(payload)
        self.assertEqual(txn.value_date, getdate())
        self.assertEqual(txn.execution_date, getdate())

    def test_invalid_date_defaults_to_today(self):
        txn = PontoTransaction.from_api_response(self._txn_payload(valueDate="garbage"))
        self.assertEqual(txn.value_date, getdate())

    def test_to_dict(self):
        txn = PontoTransaction.from_api_response(self._txn_payload(), account_id="acct-1")
        d = txn.to_dict()
        self.assertEqual(d["id"], "txn-uuid-1")
        self.assertEqual(d["amount"], "-25.00")
        self.assertEqual(d["value_date"], "2026-03-15")
        self.assertEqual(d["account_id"], "acct-1")
        self.assertIsNone(d["fee"])

    def test_to_bank_transaction_dict(self):
        txn = PontoTransaction.from_api_response(self._txn_payload(), account_id="acct-1")
        d = txn.to_bank_transaction_dict()
        self.assertEqual(d["date"], date(2026, 3, 15))
        self.assertEqual(d["amount"], -25.0)
        self.assertIsInstance(d["amount"], float)
        self.assertEqual(d["reference_number"], "txn-uuid-1")
        self.assertEqual(d["bank_party_name"], "Supplier BV")
        self.assertEqual(d["bank_party_iban"], "NL53RABO0123456789")
        self.assertEqual(d["custom_ponto_transaction_id"], "txn-uuid-1")
        self.assertEqual(d["custom_ponto_account_id"], "acct-1")


class TestPontoSynchronizationModel(FrappeTestCase):
    """PontoSynchronization parsing and status helper properties."""

    def _sync_payload(self, status="pending", **attr_overrides):
        attrs = {
            "subtype": "accountTransactions",
            "status": status,
            "resourceType": "account",
            "resourceId": "acct-1",
        }
        attrs.update(attr_overrides)
        return {"type": "synchronization", "id": "sync-uuid-1", "attributes": attrs}

    def test_from_api_response_basic(self):
        sync = PontoSynchronization.from_api_response(self._sync_payload())
        self.assertEqual(sync.id, "sync-uuid-1")
        self.assertEqual(sync.subtype, "accountTransactions")
        self.assertEqual(sync.status, "pending")
        self.assertEqual(sync.resource_type, "account")
        self.assertEqual(sync.resource_id, "acct-1")

    def test_timestamps_parsed(self):
        sync = PontoSynchronization.from_api_response(
            self._sync_payload(
                createdAt="2026-03-16T10:00:00Z",
                updatedAt="2026-03-16T10:05:00Z",
            )
        )
        self.assertIsInstance(sync.created_at, datetime)
        self.assertIsInstance(sync.updated_at, datetime)

    def test_invalid_timestamps_ignored(self):
        sync = PontoSynchronization.from_api_response(
            self._sync_payload(createdAt="bad", updatedAt="bad")
        )
        self.assertIsNone(sync.created_at)
        self.assertIsNone(sync.updated_at)

    def test_errors_parsed_from_dicts(self):
        sync = PontoSynchronization.from_api_response(
            self._sync_payload(
                status="error",
                errors=[
                    {"detail": "Bank unavailable"},
                    {"code": "noDetail"},
                ],
            )
        )
        self.assertEqual(len(sync.errors), 2)
        self.assertEqual(sync.errors[0], "Bank unavailable")
        # Second error has no 'detail' -> str(dict)
        self.assertIn("noDetail", sync.errors[1])

    def test_errors_parsed_from_strings(self):
        sync = PontoSynchronization.from_api_response(
            self._sync_payload(status="error", errors=["plain error"])
        )
        self.assertEqual(sync.errors, ["plain error"])

    def test_status_properties_pending(self):
        sync = PontoSynchronization.from_api_response(self._sync_payload(status="pending"))
        self.assertTrue(sync.is_pending)
        self.assertFalse(sync.is_running)
        self.assertFalse(sync.is_complete)

    def test_status_properties_running(self):
        sync = PontoSynchronization.from_api_response(self._sync_payload(status="running"))
        self.assertTrue(sync.is_running)
        self.assertFalse(sync.is_complete)

    def test_status_properties_success(self):
        sync = PontoSynchronization.from_api_response(self._sync_payload(status="success"))
        self.assertTrue(sync.is_success)
        self.assertTrue(sync.is_complete)
        self.assertFalse(sync.is_error)

    def test_status_properties_error(self):
        sync = PontoSynchronization.from_api_response(self._sync_payload(status="error"))
        self.assertTrue(sync.is_error)
        self.assertTrue(sync.is_complete)
        self.assertFalse(sync.is_success)
