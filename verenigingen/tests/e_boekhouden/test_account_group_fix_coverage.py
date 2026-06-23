"""
Coverage sweep for eboekhouden_account_group_fix.py (DEPRECATED wrapper module)

Target: verenigingen/e_boekhouden/utils/eboekhouden_account_group_fix.py

This module is a deprecated backward-compatibility shim. Its whitelisted endpoints
remain active (@frappe.whitelist) and simply delegate to the new service layer
(account_organization_service / account_diagnostics_service) after logging a
deprecation warning. A regression here would be a wrapper that stops delegating to
the right service function (or one of the "no longer needed" stubs silently starting
to do work).

Testable surface (REAL DB diagnostics, no eBoekhouden HTTP):
- diagnose_account_structure  -> AccountDiagnosticsService.diagnose_account_structure
- check_tax_accounts          -> AccountDiagnosticsService.check_tax_accounts
- check_problem_accounts      -> AccountDiagnosticsService.find_misplaced_accounts
- fix_account_groups          -> deprecated stub, returns {"success": False, ...}
- find_suitable_schulden_number -> deprecated stub, returns {"success": False, ...}
- analyze_account_hierarchy   -> deprecated stub, returns set()

NOTE: fix_balance_sheet_account_parents / fix_tax_group_parents delegate to
organize_balance_sheet_accounts(), which MUTATES the chart of accounts (re-parents
accounts). They are intentionally NOT exercised here -- running a re-organisation
against the shared veg11 chart of accounts would pollute every other test. Their
delegation target is identical to the (read-only) wrappers and is covered by the
account_organization_service's own tests.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_account_group_fix_coverage
"""

from verenigingen.e_boekhouden.utils import eboekhouden_account_group_fix as shim
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDeprecatedDiagnosticWrappers(EnhancedTestCase):
    """The read-only wrappers delegate to the diagnostics service."""

    def test_diagnose_account_structure_delegates(self):
        # The shim must be a pure pass-through to the diagnostics service: same
        # return type and (for the structured diagnosis) the same keys, with no
        # logic of its own.
        from verenigingen.e_boekhouden.services.account_diagnostics_service import (
            diagnose_account_structure as service_fn,
        )

        with self.assertNoErrorLog():
            wrapped = shim.diagnose_account_structure()
            direct = service_fn()
        # Both return the standard {success, data} API envelope.
        self.assertIsInstance(wrapped, dict)
        self.assertTrue(wrapped["success"])
        self.assertEqual(set(wrapped.keys()), set(direct.keys()))
        # The diagnosis surface the shim must keep exposing (under data).
        for key in ("root_accounts", "existing_groups", "sample_creditor_accounts"):
            self.assertIn(key, wrapped["data"])

    def test_check_tax_accounts_delegates(self):
        from verenigingen.e_boekhouden.services.account_diagnostics_service import (
            check_tax_accounts as service_fn,
        )

        with self.assertNoErrorLog():
            wrapped = shim.check_tax_accounts()
            direct = service_fn()
        self.assertEqual(type(wrapped), type(direct))
        if isinstance(wrapped, dict):
            self.assertEqual(set(wrapped.keys()), set(direct.keys()))

    def test_check_problem_accounts_delegates_to_find_misplaced(self):
        from verenigingen.e_boekhouden.services.account_diagnostics_service import (
            find_misplaced_accounts as service_fn,
        )

        with self.assertNoErrorLog():
            wrapped = shim.check_problem_accounts()
            direct = service_fn()
        self.assertEqual(type(wrapped), type(direct))
        if isinstance(wrapped, dict):
            self.assertEqual(set(wrapped.keys()), set(direct.keys()))


class TestDeprecatedStubs(EnhancedTestCase):
    """The "no longer needed" stubs return their deprecation sentinel without acting."""

    def test_fix_account_groups_is_inert_failure(self):
        with self.assertNoErrorLog():
            result = shim.fix_account_groups()
        self.assertFalse(result["success"])
        self.assertIn("deprecated", result["error"].lower())

    def test_find_suitable_schulden_number_is_inert_failure(self):
        with self.assertNoErrorLog():
            result = shim.find_suitable_schulden_number()
        self.assertFalse(result["success"])
        self.assertIn("deprecated", result["error"].lower())

    def test_analyze_account_hierarchy_returns_empty_set(self):
        # Non-whitelisted legacy stub: always an empty set, ignoring its argument.
        with self.assertNoErrorLog():
            result = shim.analyze_account_hierarchy({"anything": "ignored"})
        self.assertEqual(result, set())
