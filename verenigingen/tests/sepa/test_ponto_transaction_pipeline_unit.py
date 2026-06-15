"""
Unit tests for the Ponto transaction-import pipeline.

These are Tier-1 unit tests: they stub ONLY the HTTP boundary -- the inner
``PontoClient`` (its ``get`` / ``get_paginated`` wrappers around
``requests.Session``) -- and feed realistic JSON:API response dicts built by
``PontoTestDataFactory``. They assert request construction, response parsing
into dataclasses, the Ponto -> BankTransactionCreator transform, and the
import-service orchestration wiring. No live Ponto credentials are required.

Covers:
  - PontoTransactionsClient (transactions_client.py)
  - PontoAccountsClient (accounts_client.py)
  - PontoTransactionImporter transform/description logic (transaction_importer.py)
  - import_new_transactions orchestration (transaction_import_service.py)

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.sepa.test_ponto_transaction_pipeline_unit
"""

import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.ponto_test_data_factory import (
    PontoTestDataFactory,
    TestIBAN,
)
from verenigingen.verenigingen_payments.ponto.clients.accounts_client import PontoAccountsClient
from verenigingen.verenigingen_payments.ponto.clients.transaction_importer import (
    PontoTransactionImporter,
)
from verenigingen.verenigingen_payments.ponto.clients.transactions_client import (
    PontoTransactionsClient,
)
from verenigingen.verenigingen_payments.ponto.core.ponto_models import PontoTransaction


def _make_transaction(**kwargs) -> PontoTransaction:
    """Build a PontoTransaction with sane defaults (no API round-trip needed)."""
    defaults = dict(
        id="tx-0001",
        amount=Decimal("-25.00"),
        currency="EUR",
        value_date=date(2025, 1, 15),
        execution_date=date(2025, 1, 15),
        description="",
        counterpart_name="",
        counterpart_reference="",
        reference="",
        account_id="acc-0001",
    )
    defaults.update(kwargs)
    return PontoTransaction(**defaults)


class TestPontoTransactionsClientUnit(FrappeTestCase):
    """transactions_client.py -- HTTP boundary (inner PontoClient) stubbed."""

    ACCOUNT_ID = "acc-uuid-0001"

    def _client_with_stub(self):
        core = MagicMock()
        return PontoTransactionsClient(client=core), core

    def test_list_transactions_parses_into_dataclasses(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_transaction(
                transaction_id="t1", amount=-25.0, counterpart_name="Supplier BV"
            ),
            PontoTestDataFactory.create_transaction(
                transaction_id="t2", amount=100.0, counterpart_name="Donor Jan"
            ),
        ]

        txs = client.list_transactions(self.ACCOUNT_ID)

        self.assertEqual(len(txs), 2)
        self.assertIsInstance(txs[0], PontoTransaction)
        self.assertEqual(txs[0].id, "t1")
        self.assertEqual(txs[0].account_id, self.ACCOUNT_ID)  # injected from request context
        self.assertEqual(txs[0].counterpart_name, "Supplier BV")
        self.assertTrue(txs[1].is_credit)

    def test_list_transactions_hits_correct_endpoint(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = []

        client.list_transactions(self.ACCOUNT_ID, limit=50, max_pages=3)

        endpoint = core.get_paginated.call_args.args[0]
        self.assertEqual(endpoint, f"/accounts/{self.ACCOUNT_ID}/transactions")
        kwargs = core.get_paginated.call_args.kwargs
        self.assertEqual(kwargs["limit"], 50)
        self.assertEqual(kwargs["max_pages"], 3)

    def test_list_transactions_requires_account_id(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, _core = self._client_with_stub()
        with self.assertRaises(PontoAPIError):
            client.list_transactions("")

    def test_list_transactions_filters_by_date_client_side(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_transaction(transaction_id="old", execution_date="2024-12-01"),
            PontoTestDataFactory.create_transaction(transaction_id="mid", execution_date="2025-01-15"),
            PontoTestDataFactory.create_transaction(transaction_id="new", execution_date="2025-02-20"),
        ]

        txs = client.list_transactions(
            self.ACCOUNT_ID, from_date=date(2025, 1, 1), to_date=date(2025, 1, 31)
        )

        self.assertEqual([t.id for t in txs], ["mid"])

    def test_get_transaction_parses_single_resource(self):
        client, core = self._client_with_stub()
        core.get.return_value = {
            "data": PontoTestDataFactory.create_transaction(transaction_id="single", amount=-9.99)
        }

        tx = client.get_transaction(self.ACCOUNT_ID, "single")

        core.get.assert_called_once_with(f"/accounts/{self.ACCOUNT_ID}/transactions/single")
        self.assertEqual(tx.id, "single")
        self.assertEqual(tx.amount, Decimal("-9.99"))

    def test_get_transaction_requires_both_ids(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, _core = self._client_with_stub()
        with self.assertRaises(PontoAPIError):
            client.get_transaction(self.ACCOUNT_ID, "")

    def test_get_latest_transaction_returns_first(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_transaction(transaction_id="latest")
        ]
        self.assertEqual(client.get_latest_transaction(self.ACCOUNT_ID).id, "latest")

    def test_get_latest_transaction_none_when_empty(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = []
        self.assertIsNone(client.get_latest_transaction(self.ACCOUNT_ID))


class TestPontoAccountsClientUnit(FrappeTestCase):
    """accounts_client.py -- HTTP boundary (inner PontoClient) stubbed."""

    def _client_with_stub(self):
        core = MagicMock()
        return PontoAccountsClient(client=core), core

    def test_list_accounts_parses_into_dataclasses(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1, balance=5000.0),
            PontoTestDataFactory.create_account(iban=TestIBAN.ING_1, balance=250.0),
        ]

        accounts = client.list_accounts()

        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0].reference, TestIBAN.ABN_AMRO_1)
        self.assertEqual(accounts[0].iban, TestIBAN.ABN_AMRO_1)  # referenceType == IBAN
        self.assertEqual(accounts[0].current_balance, Decimal("5000.0"))
        core.get_paginated.assert_called_once_with("/accounts")

    def test_get_account_parses_single_resource(self):
        client, core = self._client_with_stub()
        core.get.return_value = {
            "data": PontoTestDataFactory.create_account(
                iban=TestIBAN.RABO_1, account_id="acc-77", balance=42.0
            )
        }

        account = client.get_account("acc-77")

        core.get.assert_called_once_with("/accounts/acc-77")
        self.assertEqual(account.id, "acc-77")
        self.assertEqual(account.reference, TestIBAN.RABO_1)

    def test_get_account_requires_account_id(self):
        from verenigingen.verenigingen_payments.ponto.exceptions import PontoAPIError

        client, _core = self._client_with_stub()
        with self.assertRaises(PontoAPIError):
            client.get_account("")

    def test_get_account_balance_returns_string_fields(self):
        client, core = self._client_with_stub()
        core.get.return_value = {
            "data": PontoTestDataFactory.create_account(account_id="acc-9", balance=1234.56)
        }

        balance = client.get_account_balance("acc-9")

        self.assertEqual(balance["current_balance"], "1234.56")
        self.assertEqual(balance["available_balance"], "1234.56")
        self.assertEqual(balance["currency"], "EUR")

    def test_find_account_by_iban_normalizes_spaces(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1),
            PontoTestDataFactory.create_account(iban=TestIBAN.ING_1),
        ]

        # Spaced + lowercase input must still match the stored IBAN.
        spaced = "nl20 ingb 0001 234567"
        found = client.find_account_by_iban(spaced)

        self.assertIsNotNone(found)
        self.assertEqual(found.reference, TestIBAN.ING_1)

    def test_find_account_by_iban_returns_none_when_absent(self):
        client, core = self._client_with_stub()
        core.get_paginated.return_value = [
            PontoTestDataFactory.create_account(iban=TestIBAN.ABN_AMRO_1)
        ]
        self.assertIsNone(client.find_account_by_iban(TestIBAN.SNS_1))


class TestPontoTransactionImporterTransformUnit(FrappeTestCase):
    """transaction_importer.py transform/description logic (no DB writes).

    These tests construct an importer with a stubbed transactions client and a
    stubbed bank-transaction creator so no Bank Transaction docs are written;
    they exercise the pure transform + description-building logic.
    """

    def _importer(self):
        imp = PontoTransactionImporter(transactions_client=MagicMock())
        # Replace collaborators that would touch the DB with stubs.
        imp._bank_tx_creator = MagicMock()
        imp._party_parser = MagicMock()
        return imp

    def test_transform_maps_core_fields(self):
        imp = self._importer()
        tx = _make_transaction(
            id="tx-abc",
            amount=Decimal("-25.00"),
            currency="EUR",
            value_date=date(2025, 1, 15),
            counterpart_name="Supplier BV",
            counterpart_reference=TestIBAN.RABO_1,
            description="Invoice INV-1",
        )
        imp._party_parser.find_or_create_party.return_value = ("Supplier BV", False)

        data = imp._transform_transaction(tx)

        self.assertEqual(data["date"], date(2025, 1, 15))
        self.assertEqual(data["amount"], -25.0)
        self.assertIsInstance(data["amount"], float)
        self.assertEqual(data["reference_number"], "tx-abc")
        self.assertEqual(data["custom_ponto_transaction_id"], "tx-abc")
        self.assertEqual(data["custom_ponto_account_id"], "acc-0001")
        self.assertEqual(data["bank_party_name"], "Supplier BV")
        self.assertEqual(data["bank_party_iban"], TestIBAN.RABO_1)

    def test_transform_negative_amount_matches_supplier(self):
        imp = self._importer()
        imp._party_parser.find_or_create_party.return_value = ("Supplier BV", False)
        tx = _make_transaction(amount=Decimal("-50.00"), counterpart_name="Supplier BV")

        data = imp._transform_transaction(tx)

        self.assertEqual(data["party_type"], "Supplier")
        # party_type passed to the parser must be Supplier for outgoing money
        _args, kwargs = imp._party_parser.find_or_create_party.call_args
        self.assertEqual(kwargs["party_type"], "Supplier")

    def test_transform_positive_amount_matches_customer(self):
        imp = self._importer()
        imp._party_parser.find_or_create_party.return_value = ("Donor Jan", True)
        tx = _make_transaction(amount=Decimal("100.00"), counterpart_name="Donor Jan")

        data = imp._transform_transaction(tx)

        self.assertEqual(data["party_type"], "Customer")
        self.assertEqual(data["party"], "Donor Jan")

    def test_transform_swallows_party_matching_errors(self):
        imp = self._importer()
        imp._party_parser.find_or_create_party.side_effect = RuntimeError("matcher down")
        tx = _make_transaction(amount=Decimal("100.00"), counterpart_name="Donor Jan")

        # Must not raise; party fields simply omitted.
        data = imp._transform_transaction(tx)

        self.assertNotIn("party", data)
        self.assertNotIn("party_type", data)

    def test_build_description_combines_parts(self):
        imp = self._importer()
        tx = _make_transaction(
            description="Invoice INV-1",
            reference="REF-99",
            counterpart_name="Supplier BV",
        )
        desc = imp._build_description(tx)
        self.assertEqual(desc, "Invoice INV-1 | Ref: REF-99 | From/To: Supplier BV")

    def test_build_description_skips_counterpart_already_in_description(self):
        imp = self._importer()
        tx = _make_transaction(description="Paid Supplier BV monthly", counterpart_name="Supplier BV")
        self.assertEqual(imp._build_description(tx), "Paid Supplier BV monthly")

    def test_build_description_empty_transaction_falls_back(self):
        """Regression: a transaction with no description/reference/counterpart
        must produce the 'Ponto Import' fallback, NOT 'From/To: ' with an
        empty name (broken operator precedence bug)."""
        imp = self._importer()
        tx = _make_transaction(description="", reference="", counterpart_name="")
        self.assertEqual(imp._build_description(tx), "Ponto Import")

    def test_build_description_counterpart_only(self):
        imp = self._importer()
        tx = _make_transaction(description="", reference="", counterpart_name="Acme BV")
        self.assertEqual(imp._build_description(tx), "From/To: Acme BV")


class TestPontoImportServiceOrchestrationUnit(FrappeTestCase):
    """transaction_import_service.py orchestration -- collaborators stubbed."""

    SERVICE = "verenigingen.verenigingen_payments.ponto.services.transaction_import_service"
    CONFIG = "verenigingen.verenigingen_payments.ponto.services.configuration_service.get_ponto_config"
    IMPORTER = (
        "verenigingen.verenigingen_payments.ponto.clients.transaction_importer."
        "PontoTransactionImporter"
    )

    def _result(self, imported=0, skipped=0, errors=None):
        res = MagicMock()
        res.imported = imported
        res.skipped = skipped
        res.errors = errors or []
        res.success = not res.errors
        return res

    def test_returns_error_when_account_not_mapped(self):
        from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
            import_new_transactions,
        )

        config = MagicMock()
        config.get_mapping_for_ponto_account.return_value = None
        with patch(self.CONFIG, return_value=config):
            out = import_new_transactions("acc-unmapped")

        self.assertFalse(out["success"])
        self.assertIn("not found", out["errors"][0])

    def test_skips_disabled_account(self):
        from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
            import_new_transactions,
        )

        config = MagicMock()
        config.get_mapping_for_ponto_account.return_value = {"enabled": 0}
        with patch(self.CONFIG, return_value=config):
            out = import_new_transactions("acc-disabled")

        self.assertTrue(out["success"])
        self.assertEqual(out["reason"], "account_disabled")
        self.assertEqual(out["imported"], 0)

    def test_errors_when_no_bank_account_linked(self):
        from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
            import_new_transactions,
        )

        config = MagicMock()
        config.get_mapping_for_ponto_account.return_value = {"enabled": 1, "bank_account": None}
        with patch(self.CONFIG, return_value=config):
            out = import_new_transactions("acc-nobank")

        self.assertFalse(out["success"])
        self.assertIn("No Bank Account", out["errors"][0])

    def test_happy_path_wires_importer_and_updates_counters(self):
        config = MagicMock()
        config.get_mapping_for_ponto_account.return_value = {
            "enabled": 1,
            "bank_account": "Main Bank Account",
        }

        importer = MagicMock()
        importer.import_transactions.return_value = self._result(imported=3, skipped=1)

        with patch(self.CONFIG, return_value=config), patch(
            self.IMPORTER, return_value=importer
        ):
            from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                import_new_transactions,
            )

            out = import_new_transactions("acc-ok", limit=50)

        # Importer called with the mapped bank account + account id.
        _args, kwargs = importer.import_transactions.call_args
        self.assertEqual(kwargs["account_id"], "acc-ok")
        self.assertEqual(kwargs["bank_account"], "Main Bank Account")
        self.assertEqual(kwargs["limit"], 50)

        # Counters / sync time updated only as appropriate.
        config.update_last_sync_time.assert_called_once_with(ponto_account_id="acc-ok")
        config.increment_transactions_imported.assert_called_once_with(
            ponto_account_id="acc-ok", count=3
        )

        self.assertTrue(out["success"])
        self.assertEqual(out["imported"], 3)
        self.assertEqual(out["skipped"], 1)

    def test_no_counter_increment_when_nothing_imported(self):
        config = MagicMock()
        config.get_mapping_for_ponto_account.return_value = {
            "enabled": 1,
            "bank_account": "Main Bank Account",
        }
        importer = MagicMock()
        importer.import_transactions.return_value = self._result(imported=0, skipped=5)

        with patch(self.CONFIG, return_value=config), patch(
            self.IMPORTER, return_value=importer
        ):
            from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                import_new_transactions,
            )

            import_new_transactions("acc-none")

        config.increment_transactions_imported.assert_not_called()

    def test_import_all_accounts_iterates_enabled_mappings(self):
        config = MagicMock()
        config.get_enabled_account_mappings.return_value = [
            {"ponto_account_id": "acc-a"},
            {"ponto_account_id": "acc-b"},
            {"ponto_account_id": None},  # skipped
        ]

        called = []

        def fake_import(account_id):
            called.append(account_id)
            return {"success": True, "imported": 0, "skipped": 0, "errors": []}

        with patch(self.CONFIG, return_value=config), patch(
            f"{self.SERVICE}.import_new_transactions", side_effect=fake_import
        ):
            from verenigingen.verenigingen_payments.ponto.services.transaction_import_service import (
                import_all_accounts,
            )

            results = import_all_accounts()

        self.assertEqual(set(called), {"acc-a", "acc-b"})
        self.assertEqual(set(results.keys()), {"acc-a", "acc-b"})


if __name__ == "__main__":
    unittest.main()
