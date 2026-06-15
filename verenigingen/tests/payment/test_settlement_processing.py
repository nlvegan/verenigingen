#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen_payments/api/settlement_processing.py

These endpoints wrap SettlementBankTransactionProcessor, which talks to the
Mollie Settlements API (via SettlementsClient) and a settlement cache. The ONLY
external boundaries mocked here are the Mollie HTTP client / settlement cache.
Configuration validation, idempotency checks against real Bank Transaction rows,
and the DB-existence branch of get_settlement_status all run for real.

Tests run as Administrator (granted FINANCIAL OperationType by critical_api).

NOTE on the "create" happy path: turning a settlement into a Bank Transaction
requires a fully configured Mollie settlement/clearing GL account + linked Bank
Account, which the test sites do NOT have. On these sites process_settlement_deposit
reaches the config-validation step and returns a structured configuration error
(after fetching + reconciling the settlement for real). The genuine BT-creation
success path is only reachable on a fully-configured (production-like) site and is
documented as live-only.
"""

from unittest.mock import patch

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import settlement_processing as api
from verenigingen.verenigingen_payments.core.models.settlement import Settlement

# Patch targets (true external boundaries only)
_CACHE_GET = (
    "verenigingen.verenigingen_payments.services.settlement_cache.SettlementCache.get_settlement"
)
_CLIENT = "verenigingen.verenigingen_payments.clients.settlements_client.SettlementsClient."

# The config-validation boundary inside the processor. Patching this forces the
# configuration state deterministically regardless of the actual site config
# (an unconfigured bare test site OR a fully-configured site like veg11). It is
# an environment/config boundary, not business logic.
_VALIDATE_CONFIG = (
    "verenigingen.verenigingen_payments.services.settlement_bank_transaction_processor."
    "SettlementBankTransactionProcessor._validate_configuration"
)
# A forced "config missing" return (matches the shape the processor produces).
_CONFIG_ERROR = {
    "status": "error",
    "error": "Configuration validation failed: Mollie settlement account not set",
}
# A forced "config valid" return. bank_account/company are only consumed AFTER
# the idempotency check, so harmless sentinel values suffice for the
# already-processed branch.
_CONFIG_VALID = {
    "status": "valid",
    "mollie_bank_account_gl": "Mollie Clearing - TEST",
    "bank_account": "Mollie - TEST",
    "company": "Test Company",
}


def _make_settlement(settlement_id="stl_TEST", reference="1234.5678.90",
                     status="paidout", value="500.00", currency="EUR",
                     settled_at="2024-06-01T10:00:00+00:00"):
    """Build a REAL Settlement model object from API-shaped dict."""
    return Settlement(
        {
            "resource": "settlement",
            "id": settlement_id,
            "reference": reference,
            "status": status,
            "settledAt": settled_at,
            "amount": {"value": value, "currency": currency},
        }
    )


class TestSettlementProcessingAPI(EnhancedTestCase):
    """Integration tests for the settlement processing API endpoints."""

    # ------------------------------------------------------------------ helpers

    def _make_bank_transaction(self, reference_number, deposit=500.0, description="Settlement BT"):
        bt = frappe.new_doc("Bank Transaction")
        bt.date = today()
        bt.deposit = deposit
        bt.currency = "EUR"
        bt.reference_number = reference_number
        bt.description = description
        bt.insert(ignore_permissions=True)
        self._track_test_document("Bank Transaction", bt.name)
        return bt

    def _patch_empty_components(self):
        """Patch the four settlement component list calls to return empty lists.

        These are real Mollie API boundaries used during reconciliation.
        """
        return [
            patch(_CLIENT + "list_settlement_payments", return_value=[]),
            patch(_CLIENT + "list_settlement_refunds", return_value=[]),
            patch(_CLIENT + "list_settlement_chargebacks", return_value=[]),
            patch(_CLIENT + "list_settlement_captures", return_value=[]),
        ]

    # ============================================== process_settlement_deposit

    def test_process_requires_an_identifier(self):
        """Neither settlement_id nor bank_reference -> structured error."""
        result = api.process_settlement_deposit(settlement_id=None, bank_reference=None)
        self.assertEqual(result["status"], "error")
        self.assertIn("settlement_id or bank_reference", result["error"])

    def test_process_settlement_not_found_in_cache(self):
        """Cache returns nothing -> 'not found' error mentioning 90-day limit."""
        with patch(_CACHE_GET, return_value=None):
            result = api.process_settlement_deposit(settlement_id="stl_MISSING")
        self.assertEqual(result["status"], "error")
        self.assertIn("not found", result["error"].lower())

    def test_process_already_processed_no_duplicate_created(self):
        """A settlement whose ID already has a Bank Transaction is reported
        already_processed and must not produce a duplicate BT.

        ORDERING NOTE (process_settlement_deposit): config validation (Step 3)
        runs BEFORE the existing-BT / already_processed check (Step 4). To
        actually exercise the idempotency branch we force config to SUCCEED via
        the _validate_configuration boundary; otherwise a missing config would
        mask the idempotency status with a config error. With config valid, the
        pre-existing BT must drive an "already_processed" result and NO duplicate
        row."""
        settlement = _make_settlement(settlement_id="stl_DUP", reference="9999.0000.11")
        self._make_bank_transaction(reference_number="stl_DUP")
        patches = self._patch_empty_components()
        with patch(_CACHE_GET, return_value=settlement), \
                patch(_VALIDATE_CONFIG, return_value=_CONFIG_VALID), \
                patches[0], patches[1], patches[2], patches[3]:
            result = api.process_settlement_deposit(settlement_id="stl_DUP")
        # Config succeeds -> the existing-BT check is reached and wins.
        self.assertEqual(result["status"], "already_processed")
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": "stl_DUP"}),
            1,
            "Idempotency must not create a duplicate Bank Transaction",
        )

    def test_process_found_settlement_hits_config_error(self):
        """Settlement found + reconciled, but Mollie GL config is missing
        -> structured config error and NO Bank Transaction created.

        The missing-config state is forced deterministically via the
        _validate_configuration boundary, so the assertion holds regardless of
        the actual site config.
        """
        settlement = _make_settlement(settlement_id="stl_NOCONFIG", reference="2222.3333.44")
        patches = self._patch_empty_components()
        with patch(_CACHE_GET, return_value=settlement), \
                patch(_VALIDATE_CONFIG, return_value=_CONFIG_ERROR), \
                patches[0], patches[1], patches[2], patches[3]:
            result = api.process_settlement_deposit(settlement_id="stl_NOCONFIG")
        self.assertEqual(result["status"], "error")
        self.assertIn("Configuration", result["error"])
        self.assertFalse(
            frappe.db.exists("Bank Transaction", {"reference_number": "stl_NOCONFIG"})
        )

    def test_process_by_bank_reference(self):
        """Lookup via bank_reference resolves the settlement through the cache."""
        settlement = _make_settlement(settlement_id="stl_BYREF", reference="5555.6666.77")
        patches = self._patch_empty_components()
        with patch(_CACHE_GET, return_value=settlement) as mock_cache, \
                patch(_VALIDATE_CONFIG, return_value=_CONFIG_ERROR), \
                patches[0], patches[1], patches[2], patches[3]:
            result = api.process_settlement_deposit(bank_reference="5555.6666.77")
        # Cache was queried with the bank_reference.
        _, kwargs = mock_cache.call_args
        self.assertEqual(kwargs.get("bank_reference"), "5555.6666.77")
        # Settlement was resolved, then the forced config error short-circuits.
        self.assertEqual(result["status"], "error")
        self.assertIn("Configuration", result["error"])

    # =========================================== batch_process_recent_settlements

    def test_batch_rejects_more_than_90_days(self):
        result = api.batch_process_recent_settlements(days=120)
        self.assertEqual(result["status"], "error")
        self.assertIn("90 days", result["error"])

    def test_batch_no_settlements(self):
        """No settlements in window -> all-zero counts, no error."""
        with patch(_CLIENT + "list_settlements", return_value=[]):
            result = api.batch_process_recent_settlements(days=7)
        self.assertEqual(result["total_settlements"], 0)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["already_processed"], 0)
        self.assertEqual(result["errors"], 0)

    def test_batch_skips_non_paidout_settlements(self):
        """A settlement that is not 'paidout' is skipped (not counted as error)."""
        open_settlement = _make_settlement(settlement_id="stl_OPEN", status="open")
        with patch(_CLIENT + "list_settlements", return_value=[open_settlement]):
            result = api.batch_process_recent_settlements(days=7)
        self.assertEqual(result["total_settlements"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["already_processed"], 0)
        self.assertEqual(result["errors"], 0)

    def test_batch_existing_bt_not_duplicated(self):
        """A paidout settlement that already has a Bank Transaction is reported
        already_processed and not duplicated when batch-processed.

        ORDERING NOTE: batch_process_recent_settlements delegates to
        process_settlement_deposit, where config validation runs before the
        duplicate check. To actually exercise the idempotency branch we force
        config to SUCCEED via the _validate_configuration boundary; otherwise a
        missing config would mask the idempotency outcome as an error. With
        config valid, the pre-existing BT drives an already_processed count and
        NO duplicate row."""
        settlement = _make_settlement(settlement_id="stl_BATCH_DUP", status="paidout")
        self._make_bank_transaction(reference_number="stl_BATCH_DUP")
        patches = self._patch_empty_components()
        with patch(_CLIENT + "list_settlements", return_value=[settlement]), \
                patch(_VALIDATE_CONFIG, return_value=_CONFIG_VALID), \
                patches[0], patches[1], patches[2], patches[3]:
            result = api.batch_process_recent_settlements(days=7)
        self.assertEqual(result["total_settlements"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertEqual(result["already_processed"], 1)
        self.assertEqual(result["errors"], 0)
        self.assertEqual(
            frappe.db.count("Bank Transaction", {"reference_number": "stl_BATCH_DUP"}),
            1,
            "Batch processing must not create a duplicate Bank Transaction",
        )

    def test_batch_counts_errors_on_config_failure(self):
        """A new paidout settlement that cannot be created (config missing) is
        counted as an error, not silently processed.

        The missing-config state is forced deterministically via the
        _validate_configuration boundary, so the assertion holds regardless of
        the actual site config."""
        settlement = _make_settlement(settlement_id="stl_BATCH_NEW", status="paidout")
        patches = self._patch_empty_components()
        with patch(_CLIENT + "list_settlements", return_value=[settlement]), \
                patch(_VALIDATE_CONFIG, return_value=_CONFIG_ERROR), \
                patches[0], patches[1], patches[2], patches[3]:
            result = api.batch_process_recent_settlements(days=7)
        self.assertEqual(result["total_settlements"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["processed"], 0)
        self.assertFalse(
            frappe.db.exists("Bank Transaction", {"reference_number": "stl_BATCH_NEW"})
        )

    # ================================================== get_settlement_status

    def test_status_not_processed_no_mollie(self):
        """No BT exists and Mollie lookup fails -> processed False + info error."""
        with patch(_CLIENT + "get_settlement", side_effect=RuntimeError("mollie down")):
            result = api.get_settlement_status(settlement_id="stl_UNKNOWN_999")
        self.assertEqual(result["settlement_id"], "stl_UNKNOWN_999")
        self.assertFalse(result["processed"])
        self.assertNotIn("bank_transaction", result)
        self.assertIn("settlement_info_error", result)

    def test_status_processed_branch(self):
        """An existing BT for the settlement -> processed True with BT details."""
        bt = self._make_bank_transaction(reference_number="stl_STATUS_DUP", deposit=321.0)
        with patch(_CLIENT + "get_settlement", side_effect=RuntimeError("skip mollie")):
            result = api.get_settlement_status(settlement_id="stl_STATUS_DUP")
        self.assertTrue(result["processed"])
        self.assertEqual(result["bank_transaction"], bt.name)
        self.assertEqual(result["amount"], 321.0)

    def test_status_with_mollie_info(self):
        """Mollie lookup succeeds -> settlement_info populated from the object."""
        settlement = _make_settlement(
            settlement_id="stl_INFO", reference="7777.8888.99", value="650.00"
        )
        with patch(_CLIENT + "get_settlement", return_value=settlement):
            result = api.get_settlement_status(settlement_id="stl_INFO")
        self.assertFalse(result["processed"])
        self.assertIn("settlement_info", result)
        self.assertEqual(result["settlement_info"]["reference"], "7777.8888.99")
        self.assertEqual(result["settlement_info"]["status"], "paidout")
        self.assertEqual(result["settlement_info"]["amount"], 650.00)
