"""#2445: a bad role-profile security mapping, or a failing validation, must be RECORDED.

`APISecurityFramework._validate_role_profile_configuration` reported both only through
`frappe.logger()`, whose output is not captured anywhere readable. Initialisation keeps its
"never fail" contract and now writes an Error Log row.

Mock justified: ROLE_PROFILE_SECURITY_MAPPING is configuration, so the invalid entry is injected
into that dict (the validation itself is real). A database failure cannot be produced for real
from one session, so `frappe.db.exists` is made to fail only for the Role Profile lookup the
validation performs; every other lookup (including Error Log's own insert) passes through.
"""

from unittest import mock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.api_security_framework import APISecurityFramework
from verenigingen.utils.security.authorization_policy import AuthorizationPolicy

MAPPING_T = "Security framework: invalid security level mappings"
FAILED_T = "Security framework: role profile configuration validation failed"
BAD_PROFILE = "Role Profile 2445 Bad Mapping"
BOOM = "db-down-2445"


class TestRoleProfileConfigErrorLogging2445(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.framework = APISecurityFramework()

    def _rows(self, title):
        return frappe.get_all("Error Log", filters={"method": title}, fields=["name", "error"], order_by="creation asc")

    def _bad_mapping(self, level="not-a-SecurityLevel"):
        # Mock justified: configuration dict, restored on exit.
        return mock.patch.dict(AuthorizationPolicy.ROLE_PROFILE_SECURITY_MAPPING, {BAD_PROFILE: [level]})

    def _db_exists_fails(self):
        real = frappe.db.exists

        def flaky(doctype, *args, **kwargs):
            if doctype == "Role Profile":
                raise RuntimeError(BOOM)
            return real(doctype, *args, **kwargs)

        # Mock justified: a DB failure cannot be produced for real from one session.
        return mock.patch.object(frappe.db, "exists", flaky)

    def test_invalid_mapping_entry_is_recorded(self):
        self.expectErrorLog(MAPPING_T)
        before = len(self._rows(MAPPING_T))
        with self._bad_mapping("not-a-SecurityLevel"):
            self.framework._validate_role_profile_configuration()  # must not raise
        rows = self._rows(MAPPING_T)
        self.assertEqual(len(rows), before + 1)
        self.assertIn(BAD_PROFILE, rows[-1].error)
        self.assertIn("not-a-SecurityLevel", rows[-1].error)

    def test_validation_failure_is_recorded(self):
        self.expectErrorLog(FAILED_T)
        before = len(self._rows(FAILED_T))
        with self._db_exists_fails():
            self.framework._validate_role_profile_configuration()  # must not raise
        rows = self._rows(FAILED_T)
        self.assertEqual(len(rows), before + 1)
        self.assertIn(BOOM, rows[-1].error)
        self.assertIn("Traceback", rows[-1].error)

    def test_control_valid_configuration_records_nothing(self):
        before = (len(self._rows(MAPPING_T)), len(self._rows(FAILED_T)))
        self.framework._validate_role_profile_configuration()
        self.assertEqual((len(self._rows(MAPPING_T)), len(self._rows(FAILED_T))), before)

    def test_init_survives_log_error_itself_raising(self):
        """Recording is best-effort on both paths."""
        # Mock justified: a failure inside frappe.log_error cannot be produced for real.
        with mock.patch.object(frappe, "log_error", side_effect=OSError("log-2445")):
            with self._bad_mapping():
                self.framework._validate_role_profile_configuration()
            with self._db_exists_fails():
                self.framework._validate_role_profile_configuration()
