"""#2445: a bad role-profile security mapping, or a failing validation, must be RECORDED.

`APISecurityFramework._validate_role_profile_configuration` reported both only through
`frappe.logger()`, whose output is not captured anywhere readable. Initialisation keeps its
"never fail" contract and now writes an Error Log row.

Mock justified: ROLE_PROFILE_SECURITY_MAPPING is configuration, so the invalid entry is injected
into that dict (the validation itself is real). The validation failure is real: a None mapping value raises a TypeError inside the loop.
"""

from unittest import mock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.error_log_assertions import error_log_rows
from verenigingen.utils.security.api_security_framework import APISecurityFramework
from verenigingen.utils.security.authorization_policy import AuthorizationPolicy

MAPPING_T = "Security framework: invalid security level mappings"
FAILED_T = "Security framework: role profile configuration validation failed"
BAD_PROFILE = "Role Profile 2445 Bad Mapping"


class TestRoleProfileConfigErrorLogging2445(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.framework = APISecurityFramework()

    def _bad_mapping(self, level="not-a-SecurityLevel"):
        # Mock justified: configuration dict, restored on exit.
        return mock.patch.dict(AuthorizationPolicy.ROLE_PROFILE_SECURITY_MAPPING, {BAD_PROFILE: [level]})

    def test_invalid_mapping_entry_is_recorded(self):
        self.expectErrorLog(MAPPING_T)
        before = len(error_log_rows(MAPPING_T))
        with self._bad_mapping("not-a-SecurityLevel"):
            self.framework._validate_role_profile_configuration()  # must not raise
        rows = error_log_rows(MAPPING_T)
        self.assertEqual(len(rows), before + 1)
        self.assertIn(BAD_PROFILE, rows[-1].error)
        self.assertIn("not-a-SecurityLevel", rows[-1].error)

    def test_validation_failure_is_recorded(self):
        self.expectErrorLog(FAILED_T)
        before = len(error_log_rows(FAILED_T))
        # A non-iterable mapping value makes the validation raise a real TypeError.
        with mock.patch.dict(AuthorizationPolicy.ROLE_PROFILE_SECURITY_MAPPING, {BAD_PROFILE: None}):
            self.framework._validate_role_profile_configuration()  # must not raise
        rows = error_log_rows(FAILED_T)
        self.assertEqual(len(rows), before + 1)
        self.assertIn("TypeError", rows[-1].error)
        self.assertIn("Traceback", rows[-1].error)

    def test_control_valid_configuration_records_nothing(self):
        before = (len(error_log_rows(MAPPING_T)), len(error_log_rows(FAILED_T)))
        self.framework._validate_role_profile_configuration()
        self.assertEqual((len(error_log_rows(MAPPING_T)), len(error_log_rows(FAILED_T))), before)

    def test_init_survives_log_error_itself_raising(self):
        """Recording is best-effort on both paths, and falls back to the file logger."""
        # Mock justified: a failure inside frappe.log_error cannot be produced for real; the
        # logger is patched only to observe the fallback.
        with mock.patch.object(frappe, "log_error", side_effect=OSError("log-2445")), mock.patch.object(
            frappe, "logger"
        ) as logger:
            with self._bad_mapping():
                self.framework._validate_role_profile_configuration()
            self.assertEqual(logger.return_value.error.call_count, 1)
            self.assertIn(BAD_PROFILE, logger.return_value.error.call_args[0][0])
            with mock.patch.dict(AuthorizationPolicy.ROLE_PROFILE_SECURITY_MAPPING, {BAD_PROFILE: None}):
                self.framework._validate_role_profile_configuration()
            self.assertEqual(logger.return_value.error.call_count, 2)
