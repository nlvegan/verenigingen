# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for cache invalidation on MolliePaymentOrchestrator's singleton
bank-config cache (#867).

MolliePaymentOrchestrator._get_bank_account_config() populates
self._bank_config_cache from BankTransactionCreator.get_mollie_bank_account_config()
exactly once and reuses it forever after, because get_payment_orchestrator()
returns a module-level singleton that survives for the life of a worker
process. Before this fix there was no reset/clear method at all -- unlike the
sibling caches in this app (sepa_config_manager, sepa_xml_adapter).

These tests exercise only the cache lifecycle (construction, per-instance
caching, clear_bank_config_cache, reset_payment_orchestrator, and the
hooks/doc_events.py wiring) -- not the Mollie HTTP-calling payment-processing
flow. That flow is covered by verenigingen_payments/mollie/tests/, which is
explicitly out of scope for this change (#874/#876 territory).
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.doc_events_test_helpers import get_doc_event_handlers
from verenigingen.tests.support.mollie_client_test_isolation import isolate_mollie_client
from verenigingen.verenigingen_payments.services import mollie_payment_orchestrator as orch_mod
from verenigingen.verenigingen_payments.services.mollie_payment_orchestrator import (
    MolliePaymentOrchestrator,
    get_payment_orchestrator,
    reset_payment_orchestrator,
)


class _OrchestratorTestBase(EnhancedTestCase):
    """Constructs a real MolliePaymentOrchestrator without live Mollie creds."""

    def setUp(self):
        super().setUp()
        isolate_mollie_client(self)


class TestBankConfigCacheClearing(_OrchestratorTestBase):
    def test_get_bank_account_config_caches_after_first_call(self):
        """A cached (non-None) value short-circuits the real lookup."""
        orchestrator = MolliePaymentOrchestrator()
        orchestrator._bank_config_cache = {"bank_account": "SENTINEL", "company": "SENTINEL Co"}
        self.assertEqual(orchestrator._get_bank_account_config()["bank_account"], "SENTINEL")

    def test_clear_bank_config_cache_resets_to_none(self):
        orchestrator = MolliePaymentOrchestrator()
        orchestrator._bank_config_cache = {"bank_account": "STALE"}

        orchestrator.clear_bank_config_cache()

        self.assertIsNone(orchestrator._bank_config_cache)

    def test_reset_payment_orchestrator_clears_singleton_cache(self):
        orchestrator = get_payment_orchestrator()
        orchestrator._bank_config_cache = {"bank_account": "STALE"}

        reset_payment_orchestrator()

        self.assertIsNone(get_payment_orchestrator()._bank_config_cache)
        # Same singleton instance -- reset must not replace it wholesale (that
        # would re-run the expensive __init__, including a fresh MollieClient
        # and DuesPaymentProcessor, for every subsequent caller).
        self.assertIs(get_payment_orchestrator(), orchestrator)

    def test_reset_payment_orchestrator_is_a_noop_before_first_use(self):
        """No orchestrator built yet -> nothing to clear, must not construct one."""
        orch_mod._orchestrator_instance = None

        reset_payment_orchestrator()  # must not raise

        self.assertIsNone(orch_mod._orchestrator_instance)

    def test_reset_payment_orchestrator_accepts_doc_events_signature(self):
        """doc_events calls handlers as fn(doc, method=None)."""
        orchestrator = get_payment_orchestrator()
        orchestrator._bank_config_cache = {"bank_account": "STALE"}

        fake_doc = frappe._dict({"doctype": "Mollie Settings"})
        reset_payment_orchestrator(fake_doc, method="on_update")

        self.assertIsNone(orchestrator._bank_config_cache)


class TestBankConfigCacheHookWiring(EnhancedTestCase):
    """#867: verify the doc_events wiring exists for the doctypes
    get_mollie_bank_account_config() reads (Bank Account, Verenigingen
    Settings) -- Mollie Settings itself is wired via its own controller
    on_update()/clear_configuration_cache(), not via doc_events.py.
    """

    TARGET = (
        "verenigingen.verenigingen_payments.services.mollie_payment_orchestrator."
        "reset_payment_orchestrator"
    )

    def test_bank_account_on_update_resets_orchestrator(self):
        self.assertIn(self.TARGET, get_doc_event_handlers("Bank Account", "on_update"))

    def test_verenigingen_settings_on_update_resets_orchestrator(self):
        self.assertIn(self.TARGET, get_doc_event_handlers("Verenigingen Settings", "on_update"))


if __name__ == "__main__":
    import unittest

    unittest.main()
