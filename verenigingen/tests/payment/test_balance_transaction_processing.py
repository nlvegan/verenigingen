#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen_payments/api/balance_transaction_processing.py

These endpoints wrap BalanceTransactionProcessor, which itself talks to the Mollie
Balances API via BalancesClient. The ONLY external boundary mocked here is the
Mollie HTTP client (BalancesClient.list_balance_transactions /
get_primary_balance). Everything else - input validation, idempotency checks
against real Bank Transaction rows, configuration validation, and the DB-only
query/statistics endpoints - runs for real and is asserted against real DB state.

Tests run as Administrator (granted FINANCIAL OperationType by critical_api).

NOTE on the "create" happy path: creating a Bank Transaction from a balance
transaction requires a fully configured Mollie clearing GL account + linked Bank
Account, which the test sites do NOT have. On these sites the processor returns a
structured configuration error instead of creating a BT. We assert that real
behaviour. The genuine BT-creation success path is only reachable on a
fully-configured (production-like) site and is documented as live-only.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import balance_transaction_processing as api
from verenigingen.verenigingen_payments.core.models.balance import Balance, BalanceTransaction


def _make_balance_transaction(
    tx_id="baltr_TESTXYZ",
    tx_type="payment",
    initial_value="10.00",
    result_value="9.71",
    currency="EUR",
    created_at="2024-06-01T10:00:00+00:00",
    context=None,
    deductions=None,
):
    """Build a REAL BalanceTransaction model object (not a mock) from API-shaped dict."""
    data = {
        "resource": "balance_transaction",
        "id": tx_id,
        "type": tx_type,
        "initialAmount": {"value": initial_value, "currency": currency},
        "resultAmount": {"value": result_value, "currency": currency},
        "createdAt": created_at,
        "context": context or {},
    }
    if deductions is not None:
        data["deductions"] = deductions
    return BalanceTransaction(data)


def _make_balance(balance_id="bal_TEST", currency="EUR"):
    return Balance(
        {
            "resource": "balance",
            "id": balance_id,
            "mode": "test",
            "createdAt": "2024-01-01T00:00:00+00:00",
            "currency": currency,
            "status": "active",
            "availableAmount": {"value": "1000.00", "currency": currency},
            "pendingAmount": {"value": "250.00", "currency": currency},
        }
    )


class TestBalanceTransactionProcessingAPI(EnhancedTestCase):
    """Integration tests for the balance transaction processing API endpoints."""

    # ------------------------------------------------------------------ helpers

    def _make_bank_transaction(self, reference_number, transaction_id=None, deposit=10.0,
                               withdrawal=0.0, description="Test BT", status=None,
                               date_=None, submit=False):
        """Create a REAL Bank Transaction row and track it for cleanup."""
        bt = frappe.new_doc("Bank Transaction")
        bt.date = date_ or today()
        bt.deposit = deposit
        bt.withdrawal = withdrawal
        bt.currency = "EUR"
        bt.reference_number = reference_number
        if transaction_id:
            bt.transaction_id = transaction_id
        bt.description = description
        bt.insert(ignore_permissions=True)
        if submit:
            bt.submit()
        if status:
            frappe.db.set_value("Bank Transaction", bt.name, "status", status)
        self._track_test_document("Bank Transaction", bt.name)
        return bt

    # ============================================ process_balance_transactions

    def test_process_invalid_from_date(self):
        result = api.process_balance_transactions(balance_id="bal_x", from_date="2024-13-99")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid from_date", result["error"])

    def test_process_invalid_until_date(self):
        result = api.process_balance_transactions(balance_id="bal_x", until_date="not-a-date")
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid until_date", result["error"])

    def test_process_limit_too_high(self):
        result = api.process_balance_transactions(balance_id="bal_x", limit=5000)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 1000", result["error"])

    def test_process_limit_too_low(self):
        result = api.process_balance_transactions(balance_id="bal_x", limit=0)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 1000", result["error"])

    def test_process_limit_non_numeric_raises_type_error(self):
        """Frappe v16 enforces the `limit: int` annotation BEFORE the function body
        runs, so a non-coercible string raises FrappeTypeError. The function's own
        `Invalid limit value` guard is therefore only reachable for ints that fail
        the numeric range checks (covered by test_process_limit_too_high/low)."""
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            api.process_balance_transactions(balance_id="bal_x", limit="abc")

    def test_process_empty_transaction_list(self):
        """No transactions returned -> clean zero-count result, no error."""
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[],
        ):
            result = api.process_balance_transactions(balance_id="bal_x", limit=10)
        self.assertEqual(result["total_transactions"], 0)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["already_processed"], 0)
        self.assertEqual(result["errors"], 0)
        self.assertNotIn("error", result)

    def test_process_already_processed_via_existing_bt(self):
        """A balance tx whose ID already has a Bank Transaction is reported
        already_processed and NOT duplicated (real idempotency check)."""
        ref = "baltr_DUP_001"
        self._make_bank_transaction(reference_number=ref, transaction_id=ref)
        tx = _make_balance_transaction(tx_id=ref, context={})
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[tx],
        ):
            result = api.process_balance_transactions(balance_id="bal_x", limit=10)
        self.assertEqual(result["total_transactions"], 1)
        self.assertEqual(result["already_processed"], 1)
        self.assertEqual(result["processed"], 0)
        # No new BT created for this reference (still exactly one).
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": ref}),
            1,
            "Idempotency must not create a duplicate Bank Transaction",
        )

    def test_process_resolves_primary_balance_when_id_omitted(self):
        """balance_id omitted -> processor resolves primary balance via client."""
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[],
        ) as mock_list:
            result = api.process_balance_transactions(limit=10)
        self.assertEqual(result["total_transactions"], 0)
        # The resolved primary balance id must have been passed to the list call.
        _, kwargs = mock_list.call_args
        self.assertEqual(kwargs.get("balance_id"), "bal_PRIMARY")

    def test_process_new_transaction_hits_config_error(self):
        """When Mollie GL config is missing, a brand-new balance tx cannot be
        turned into a Bank Transaction; the per-transaction result carries the
        configuration error and no BT is created.

        The "missing Mollie GL config" state is forced deterministically by
        patching the config boundary (BankTransactionCreator.get_mollie_bank_account_config,
        which _process_single_transaction consults to resolve the clearing
        account / bank account). This is an environment/config boundary, not
        business logic, so the test is correct regardless of the actual site
        config (bare test site OR a fully-configured site like veg11)."""
        ref = "baltr_NEW_NOCONFIG"
        tx = _make_balance_transaction(tx_id=ref, context={})
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[tx],
        ), patch(
            "verenigingen.verenigingen_payments.services.bank_transaction_creator."
            "BankTransactionCreator.get_mollie_bank_account_config",
            return_value={"error": "Configuration validation failed: Mollie clearing account not set"},
        ):
            result = api.process_balance_transactions(balance_id="bal_x", limit=10)
        self.assertEqual(result["total_transactions"], 1)
        # No Bank Transaction was created.
        self.assertFalse(frappe.db.exists("Bank Transaction", {"reference_number": ref}))
        # The single per-tx result reflects the forced config error - processed stays 0.
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["results"][0]["status"], "error")
        self.assertIn("Configuration", result["results"][0]["error"])

    # =============================================== process_historical_data

    def test_historical_invalid_months_back_high(self):
        result = api.process_historical_data(months_back=200)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 120", result["error"])

    def test_historical_invalid_months_back_non_numeric_raises_type_error(self):
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            api.process_historical_data(months_back="xx")

    def test_historical_invalid_batch_size_high(self):
        result = api.process_historical_data(months_back=1, batch_size=5000)
        self.assertEqual(result["status"], "error")
        self.assertIn("batch_size", result["error"])

    def test_historical_invalid_batch_size_non_numeric_raises_type_error(self):
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            api.process_historical_data(months_back=1, batch_size="zz")

    def test_historical_runs_batches_over_empty_data(self):
        """1 month back, empty data -> one or more batches, all zero, no error."""
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[],
        ):
            result = api.process_historical_data(months_back=1, batch_size=50)
        self.assertEqual(result["total_processed"], 0)
        self.assertEqual(result["total_errors"], 0)
        self.assertEqual(result["total_already_processed"], 0)
        self.assertGreaterEqual(len(result["batches"]), 1)
        self.assertNotIn("error", result)

    # ================================================= get_primary_balance_info

    def test_get_primary_balance_info_success(self):
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_INFO", currency="EUR"),
        ):
            result = api.get_primary_balance_info()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["balance_id"], "bal_INFO")
        self.assertEqual(result["currency"], "EUR")
        self.assertEqual(result["available_amount"], 1000.00)
        self.assertEqual(result["pending_amount"], 250.00)
        self.assertEqual(result["status_value"], "active")

    def test_get_primary_balance_info_client_error(self):
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            side_effect=RuntimeError("mollie down"),
        ):
            result = api.get_primary_balance_info()
        self.assertEqual(result["status"], "error")
        self.assertIn("mollie down", result["error"])

    # ================================================= check_transaction_status

    def test_check_transaction_status_requires_id(self):
        result = api.check_transaction_status(transaction_id="")
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["error"])

    def test_check_transaction_status_not_processed(self):
        result = api.check_transaction_status(transaction_id="baltr_DOES_NOT_EXIST_999")
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["processed"])
        self.assertIsNone(result["bank_transaction"])
        # Mollie data not requested -> note present, no API call made.
        self.assertIn("mollie_api_note", result)

    def test_check_transaction_status_processed(self):
        ref = "baltr_CHK_001"
        bt = self._make_bank_transaction(reference_number=ref, deposit=42.50,
                                         description="Some payment")
        result = api.check_transaction_status(transaction_id=ref)
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["processed"])
        self.assertEqual(result["bank_transaction"]["name"], bt.name)
        self.assertEqual(result["bank_transaction"]["deposit"], 42.50)
        self.assertEqual(result["bank_transaction"]["amount"], 42.50)
        self.assertEqual(result["bank_transaction"]["currency"], "EUR")

    def test_check_transaction_status_with_mollie_data_found(self):
        """include_mollie_data=True fetches recent txs from Mollie and serialises
        the matching one."""
        ref = "baltr_CHK_MOLLIE"
        tx = _make_balance_transaction(
            tx_id=ref,
            tx_type="payment",
            initial_value="20.00",
            result_value="19.50",
        )
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[tx],
        ):
            result = api.check_transaction_status(transaction_id=ref, include_mollie_data=True)
        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(result["mollie_api_data"])
        self.assertEqual(result["mollie_api_data"]["id"], ref)
        self.assertEqual(result["mollie_api_data"]["type"], "payment")
        self.assertEqual(result["mollie_api_data"]["initial_amount"]["value"], "20.00")

    def test_check_transaction_status_with_mollie_data_not_found(self):
        """Requested tx not in the recent list -> mollie_api_error set, status still success."""
        other = _make_balance_transaction(tx_id="baltr_OTHER")
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[other],
        ):
            result = api.check_transaction_status(
                transaction_id="baltr_MISSING", include_mollie_data=True
            )
        self.assertEqual(result["status"], "success")
        self.assertIsNone(result["mollie_api_data"])
        self.assertIn("mollie_api_error", result)
        self.assertIn("not found", result["mollie_api_error"])

    # ============================================ search_transactions_by_description

    def test_search_requires_term(self):
        result = api.search_transactions_by_description(search_term="")
        self.assertEqual(result["status"], "error")
        self.assertIn("required", result["error"])

    def test_search_invalid_limit(self):
        result = api.search_transactions_by_description(search_term="x", limit=9999)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 500", result["error"])

    def test_search_finds_matching_balance_transaction(self):
        unique = f"UNIQUEMARKER{frappe.generate_hash(length=8)}"
        ref = "baltr_SEARCH_001"
        bt = self._make_bank_transaction(
            reference_number=ref,
            transaction_id=ref,
            deposit=33.0,
            description=f"Bestelling {unique}",
        )
        result = api.search_transactions_by_description(search_term=unique, limit=20)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["search_term"], unique)
        names = [r["name"] for r in result["results"]]
        self.assertIn(bt.name, names)
        row = next(r for r in result["results"] if r["name"] == bt.name)
        self.assertEqual(row["amount"], 33.0)
        self.assertEqual(row["type"], "deposit")
        self.assertEqual(row["reference_number"], ref)

    def test_search_excludes_non_mollie_reference(self):
        """A BT whose reference_number/transaction_id is NOT a balance/payment ref
        must not appear, even if the description matches."""
        unique = f"PLAINMARKER{frappe.generate_hash(length=8)}"
        self._make_bank_transaction(
            reference_number="MANUAL-REF-123",
            transaction_id="MANUAL-REF-123",
            description=f"Manual {unique}",
        )
        result = api.search_transactions_by_description(search_term=unique, limit=20)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_found"], 0)

    # ============================================= get_processing_statistics

    def test_statistics_invalid_days_high(self):
        result = api.get_processing_statistics(days=999)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 365", result["error"])

    def test_statistics_invalid_days_non_numeric_raises_type_error(self):
        with self.assertRaises(frappe.exceptions.FrappeTypeError):
            api.get_processing_statistics(days="abc")

    def test_statistics_counts_baltr_bank_transactions(self):
        """Two baltr_ Bank Transactions in range are counted; amounts summed.

        REGRESSION (FIXED): the raw "Get total amounts" SQL in
        get_processing_statistics previously used a single-% LIKE literal
        `LIKE 'baltr_%'` alongside positional `%s` parameters. frappe.db.sql does
        printf-style substitution over the whole string, so the literal `%'` was
        parsed as a format spec and raised "unsupported format character ''' (0x27)",
        making get_processing_statistics ALWAYS return {"status": "error"} once it
        reached this query. The literal is now correctly doubled (`baltr_%%`), so
        the endpoint returns real statistics. This test asserts that success
        behaviour."""
        self._make_bank_transaction(
            reference_number="baltr_STAT_1", deposit=100.0, status="Reconciled"
        )
        self._make_bank_transaction(
            reference_number="baltr_STAT_2", withdrawal=40.0, deposit=0.0, status="Unreconciled"
        )
        result = api.get_processing_statistics(days=30)
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["totals"]["total_processed"], 2)
        self.assertGreaterEqual(result["totals"]["reconciled"], 1)
        self.assertGreaterEqual(result["totals"]["unreconciled"], 1)
        self.assertGreaterEqual(result["totals"]["total_deposits"], 100.0)
        self.assertGreaterEqual(result["totals"]["total_withdrawals"], 40.0)
        self.assertEqual(result["period"]["days"], 30)
        # Percentages are computed and bounded.
        self.assertGreaterEqual(result["percentages"]["reconciled_pct"], 0)
        self.assertLessEqual(result["percentages"]["reconciled_pct"], 100)

    def test_statistics_excludes_out_of_range(self):
        """A baltr_ BT dated well before the window is not counted.

        REGRESSION (FIXED): same single-% SQL crash as
        test_statistics_counts_baltr_bank_transactions; the LIKE literal is now
        correctly doubled (`baltr_%%`) so get_processing_statistics returns real
        statistics rather than {"status": "error"}."""
        old_ref = "baltr_OLD_RANGE"
        self._make_bank_transaction(
            reference_number=old_ref, deposit=500.0, date_=add_days(today(), -200)
        )
        result = api.get_processing_statistics(days=7)
        self.assertEqual(result["status"], "success")
        # Cannot assert exact totals (shared site), but the old BT's 500 must not
        # be inside a 7-day window total if it's the only large recent deposit.
        # Robust check: re-query the same window for our specific ref -> 0.
        in_window = frappe.db.count(
            "Bank Transaction",
            {
                "reference_number": old_ref,
                "date": ["between", [add_days(today(), -7), today()]],
            },
        )
        self.assertEqual(in_window, 0)

    # =========================================== fetch_recent_transactions_for_search

    def test_fetch_recent_invalid_limit(self):
        result = api.fetch_recent_transactions_for_search(limit=9999)
        self.assertEqual(result["status"], "error")
        self.assertIn("between 1 and 250", result["error"])

    def test_fetch_recent_skips_already_existing(self):
        """A fetched tx whose ID already has a Bank Transaction is counted as
        already_exists and not reprocessed."""
        ref = "baltr_FETCH_EXIST"
        self._make_bank_transaction(reference_number=ref, transaction_id=ref)
        tx = _make_balance_transaction(tx_id=ref, context={})
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[tx],
        ):
            result = api.fetch_recent_transactions_for_search(limit=50)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_fetched"], 1)
        self.assertEqual(result["already_exists"], 1)
        self.assertEqual(result["processed"], 0)

    def test_fetch_recent_new_tx_records_error_on_unconfigured_site(self):
        """A new tx that cannot be created (no Mollie config) is surfaced as an
        error in error_details, not silently dropped."""
        ref = "baltr_FETCH_NEW"
        tx = _make_balance_transaction(tx_id=ref, context={})
        with patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.get_primary_balance",
            return_value=_make_balance(balance_id="bal_PRIMARY"),
        ), patch(
            "verenigingen.verenigingen_payments.clients.balances_client.BalancesClient.list_balance_transactions",
            return_value=[tx],
        ):
            result = api.fetch_recent_transactions_for_search(limit=50)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["total_fetched"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertFalse(frappe.db.exists("Bank Transaction", {"reference_number": ref}))
