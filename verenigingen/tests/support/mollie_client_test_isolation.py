"""Shared test helper: isolate MollieClient construction from ambient Mollie
Settings, so a MolliePaymentOrchestrator can be built in tests without live
credentials.

Extracted here because three test files
(test_mollie_orchestrator_coverage_b2.py, test_payment_processing_recovery.py,
test_mollie_payment_orchestrator_cache_invalidation.py) had each independently
defined an identical ``_isolate_mollie_client`` body -- exactly the class of
copy-paste `scripts/validation/duplicate_helper_validator.py`'s ratchet exists
to catch ("a copy-pasted helper is where a fix goes to die"). New tests
needing this isolation should import ``isolate_mollie_client`` from here
instead of re-defining it.
"""

from verenigingen.verenigingen_payments.mollie.core import client as client_mod
from verenigingen.verenigingen_payments.services import mollie_payment_orchestrator as orch_mod


def isolate_mollie_client(test_case) -> None:
    """Patch MollieClient._get_api_key and reset the orchestrator singleton.

    Makes MolliePaymentOrchestrator() (and the DuesPaymentProcessor it builds
    internally) constructible without live Mollie credentials, and ensures a
    stale singleton built under polluted settings isn't reused across
    tests/shards.

    Registers cleanups on ``test_case`` (anything with ``addCleanup``, i.e. a
    unittest.TestCase) so both are restored after the test.
    """
    real_get_key = client_mod.MollieClient._get_api_key
    client_mod.MollieClient._get_api_key = lambda self: "test_dummy_key_for_tests"
    test_case.addCleanup(setattr, client_mod.MollieClient, "_get_api_key", real_get_key)

    prev = orch_mod._orchestrator_instance
    orch_mod._orchestrator_instance = None
    test_case.addCleanup(setattr, orch_mod, "_orchestrator_instance", prev)
