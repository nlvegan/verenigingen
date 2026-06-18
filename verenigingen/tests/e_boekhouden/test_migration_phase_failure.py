"""Unit tests for the migration phase-failure helpers (audit T2.2).

The e-Boekhouden migration phase methods catch their own exceptions and
return a structured ``{"success": bool, "message": str}`` result instead of
raising. start_migration must detect a failed phase from that result and
reflect it in migration_status, otherwise a failed phase is still recorded
as a "Completed" migration.

Run with:
    bench --site veg11.veganisme.org run-tests --app verenigingen \
        --module verenigingen.tests.e_boekhouden.test_migration_phase_failure
"""

import unittest

import frappe

from verenigingen.e_boekhouden.doctype.e_boekhouden_migration.e_boekhouden_migration import (
    _migration_phase_failed,
    _resolve_migration_status,
    check_rest_api_status,
    update_account_type_mapping,
)


class TestMigrationPhaseFailed(unittest.TestCase):
    """Detect a failed migration phase from its structured result."""

    def test_success_result_is_not_failure(self):
        """A phase result with success=True is not a failure."""
        self.assertFalse(_migration_phase_failed({"success": True, "message": "Imported 5"}))

    def test_failure_result_is_failure(self):
        """A phase result with success=False is a failure."""
        self.assertTrue(
            _migration_phase_failed({"success": False, "message": "Error migrating Transactions"})
        )

    def test_missing_success_key_is_failure(self):
        """A dict without an explicit success=True is treated as a failure."""
        self.assertTrue(_migration_phase_failed({"message": "something"}))
        self.assertTrue(_migration_phase_failed({}))

    def test_non_true_success_value_is_failure(self):
        """Only a literal True counts as success — a truthy string does not."""
        self.assertTrue(_migration_phase_failed({"success": "yes"}))
        self.assertTrue(_migration_phase_failed({"success": 1}))

    def test_non_dict_result_is_failure(self):
        """A malformed (non-dict) result is treated as a failure — fail loud,
        never silently record a broken phase as Completed."""
        self.assertTrue(_migration_phase_failed(None))
        self.assertTrue(_migration_phase_failed(""))
        self.assertTrue(_migration_phase_failed("Error migrating Transactions"))


class TestResolveMigrationStatus(unittest.TestCase):
    """start_migration's final status reflects whether any phase failed."""

    def test_no_failed_phases_is_completed(self):
        """An empty failed-phases list resolves to Completed."""
        status, operation = _resolve_migration_status([])
        self.assertEqual(status, "Completed")
        self.assertEqual(operation, "Migration completed successfully")

    def test_one_failed_phase_is_failed(self):
        """A single failed phase resolves to Failed and names the phase."""
        status, operation = _resolve_migration_status(["Transactions"])
        self.assertEqual(status, "Failed")
        self.assertIn("Transactions", operation)

    def test_multiple_failed_phases_named(self):
        """All failed phases are named in the operation message."""
        status, operation = _resolve_migration_status(["Transactions", "Cost Centers"])
        self.assertEqual(status, "Failed")
        self.assertIn("Transactions", operation)
        self.assertIn("Cost Centers", operation)


class TestUpdateAccountTypeMappingValidation(unittest.TestCase):
    """Input-validation branches of update_account_type_mapping.

    These branches return structured error dicts (no raise) before any account
    lookup, so they are deterministic and need no fixtures.
    """

    def test_missing_parameters(self):
        """Any missing required parameter returns MISSING_PARAMETERS."""
        for args in (("", "Bank", "Co"), ("Acc", "", "Co"), ("Acc", "Bank", "")):
            result = update_account_type_mapping(*args)
            self.assertFalse(result["success"])
            self.assertEqual(result["error_code"], "MISSING_PARAMETERS")

    def test_invalid_account_type(self):
        """An account type not in Account.account_type options is rejected.

        This branch runs before account lookup, so the company need not exist.
        """
        result = update_account_type_mapping("Some Account", "DefinitelyNotAType", "AnyCompany")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "INVALID_ACCOUNT_TYPE")
        self.assertIn("DefinitelyNotAType", result["error"])

    def test_valid_type_but_missing_account(self):
        """A valid account type but unknown account name -> ACCOUNT_NOT_FOUND.

        Uses a real Account.account_type option so validation passes and we
        reach the lookup, which fails because neither the name nor the
        display-name match for the (nonexistent) company.
        """
        options = frappe.get_meta("Account").get_field("account_type").options
        valid_type = next(t.strip() for t in options.split("\n") if t.strip())
        result = update_account_type_mapping("NO-SUCH-ACCOUNT-XYZ", valid_type, "NO-SUCH-COMPANY-XYZ")
        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "ACCOUNT_NOT_FOUND")


class TestCheckRestApiStatusNoToken(unittest.TestCase):
    """check_rest_api_status without configured credentials."""

    def test_no_token_reports_not_configured(self):
        """With no api_token/rest_api_token, returns configured=False.

        The veg11/test sites have no live eBoekhouden credentials, so this
        exercises the no-creds early return rather than a real API call.
        """
        settings = frappe.get_single("E-Boekhouden Settings")
        # raise_exception=False: a half-configured token (field set, stored
        # password missing) reads as None here, matching how the function under
        # test now treats it — i.e. as "not configured".
        has_token = settings.get_password("api_token", raise_exception=False) or settings.get_password(
            "rest_api_token", raise_exception=False
        )
        if has_token:
            self.skipTest("Site has eBoekhouden API token configured")
        result = check_rest_api_status()
        self.assertFalse(result["configured"])
        self.assertIn("not configured", result["message"].lower())


if __name__ == "__main__":
    unittest.main()
