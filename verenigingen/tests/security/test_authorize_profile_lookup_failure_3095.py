"""#3095: a FAILED role-profile lookup must not let ``AuthorizationEngine.authorize`` grant by role name.

``authorize`` read profiles with ``get_user_role_profiles(user)``, which returns ``[]`` on an ordinary
error, so a lookup that FAILED looked exactly like "user has no profile" and ``AuthorizationPolicy``
fell through to Rule 5 (individual role in the mapping) / Rule 6 (System Manager), both MEDIUM. A
failed lookup now denies with the same ``rule_7_deny`` result as an ordinary refusal and is recorded
in the Error Log; a lock error (1213/1205) propagates. A user who genuinely has NO profile keeps
Rules 5/6, and Rules 1-3 (PUBLIC / Guest / LOW) never depended on profiles so they still decide.

The failure is a real driver fault on the ``tabUser Role Profile`` read (helper from the #2409
tests), injected below every swallowing layer; no business function is mocked. Test users are made
through the real User doctype. The end-to-end refusal comparison pins ``developer_mode`` off
(it is on for sites 6-13) because dev mode appends profiles and roles to the message.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.security.test_authorization_coverage import AuthorizationTestBase
from verenigingen.tests.security.test_sepa_authorization_lock_errors_2409 import (
    LOCK_ERRNOS,
    ORDINARY_ERRNO,
    _sepa2409_driver_fault,
)
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.api_security_framework import SecurityProfile, get_security_framework
from verenigingen.utils.security.authorization_engine import (
    AuthorizationEngine,
    get_authorization_engine,
)
from verenigingen.utils.security.types import SecurityLevel

PROFILE_TABLE = "tabUser Role Profile"
LOG_TITLE = "Authorization engine: role profile lookup failed"


class TestAuthorizeProfileLookupFailure3095(AuthorizationTestBase):
    def setUp(self):
        super().setUp()
        self.engine = AuthorizationEngine()
        # Rule 6 beneficiary: direct System Manager role, NO role profile.
        self.sysmgr = self._make_user_with_roles(["System Manager"], prefix="sm3095")
        # Rule 5 beneficiary: direct role whose name is a mapping key (MEDIUM), NO role profile.
        self.auditor_role = self._make_user_with_roles(["Verenigingen Auditor"], prefix="aud3095")
        # Real profile that grants MEDIUM through Rule 4.
        self.auditor_profile = self._make_user_with_role_profile("Verenigingen Auditor", prefix="audp3095")

    def _authorize_under_fault(self, user, level, errno):
        get_authorization_engine().invalidate_user_cache(user.name)
        with self.as_user(user.name), _sepa2409_driver_fault(PROFILE_TABLE, errno):
            return self.engine.authorize(user.name, level)

    def _authorize_healthy(self, user, level):
        get_authorization_engine().invalidate_user_cache(user.name)
        with self.as_user(user.name):
            return self.engine.authorize(user.name, level)

    def _profile_lookup_error_rows_3095(self):
        return set(frappe.get_all("Error Log", filters={"method": ["like", f"{LOG_TITLE}%"]}, pluck="name"))

    # ---- the defect

    def test_failed_lookup_does_not_grant_rule_6_system_manager(self):
        self.expectErrorLog(LOG_TITLE)
        result = self._authorize_under_fault(self.sysmgr, SecurityLevel.MEDIUM, ORDINARY_ERRNO)
        self.assertFalse(result.granted, result)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_failed_lookup_does_not_grant_rule_5_individual_role(self):
        self.expectErrorLog(LOG_TITLE)
        result = self._authorize_under_fault(self.auditor_role, SecurityLevel.MEDIUM, ORDINARY_ERRNO)
        self.assertFalse(result.granted, result)
        self.assertEqual(result.rule_matched, "rule_7_deny")

    def test_failed_lookup_does_not_grant_a_user_whose_profile_would_have_granted(self):
        self.expectErrorLog(LOG_TITLE)
        result = self._authorize_under_fault(self.auditor_profile, SecurityLevel.MEDIUM, ORDINARY_ERRNO)
        self.assertFalse(result.granted, result)

    def test_failed_lookup_is_recorded_in_the_error_log(self):
        with self.assertErrorLog(LOG_TITLE):
            self._authorize_under_fault(self.sysmgr, SecurityLevel.MEDIUM, ORDINARY_ERRNO)

    def test_lock_error_in_lookup_propagates(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                with self.assertRaises(error):
                    self._authorize_under_fault(self.sysmgr, SecurityLevel.MEDIUM, errno)

    def test_failed_lookup_still_lets_levels_that_ignore_profiles_decide(self):
        """Rules 1-3 never read profiles: a broken profile table must not deny PUBLIC, LOW or Guest."""
        self.expectErrorLog(LOG_TITLE)
        public = self._authorize_under_fault(self.auditor_role, SecurityLevel.PUBLIC, ORDINARY_ERRNO)
        self.assertEqual((public.granted, public.rule_matched), (True, "rule_1_public"))
        low = self._authorize_under_fault(self.auditor_role, SecurityLevel.LOW, ORDINARY_ERRNO)
        self.assertEqual((low.granted, low.rule_matched), (True, "rule_3_any_authenticated"))
        with self.as_user("Guest"), _sepa2409_driver_fault(PROFILE_TABLE, ORDINARY_ERRNO):
            guest = self.engine.authorize("Guest", SecurityLevel.LOW)
        self.assertEqual((guest.granted, guest.rule_matched), (False, "rule_2_guest_denied"))

    def test_administrator_is_unaffected_by_a_failed_lookup(self):
        with _sepa2409_driver_fault(PROFILE_TABLE, ORDINARY_ERRNO):
            result = self.engine.authorize("Administrator", SecurityLevel.CRITICAL)
        self.assertEqual(result.rule_matched, "rule_0_administrator_break_glass")

    # ---- controls (healthy lookup)

    def test_control_healthy_lookup_still_grants_by_profile(self):
        result = self._authorize_healthy(self.auditor_profile, SecurityLevel.MEDIUM)
        self.assertEqual((result.granted, result.rule_matched), (True, "rule_4_role_profile"))

    def test_control_no_profile_user_keeps_rules_5_and_6(self):
        """'No profile' is not an error: the role-name grants stay, and no Error Log row is written."""
        before = self._profile_lookup_error_rows_3095()
        for user, rule in ((self.auditor_role, "rule_5_individual_role"), (self.sysmgr, "rule_6_system_manager")):
            self.assertEqual(get_authorization_engine().get_user_role_profiles(user.name), [], "fixture")
            result = self._authorize_healthy(user, SecurityLevel.MEDIUM)
            self.assertEqual((result.granted, result.rule_matched), (True, rule))
        self.assertEqual(self._profile_lookup_error_rows_3095(), before)

    # ---- end to end: the decorator's refusal channels

    def _validate_auth_refusal_3095(self, user, errno=None):
        """(exception type, message, new message_log entries, new Error Log titles) or the result."""
        get_authorization_engine().invalidate_user_cache(user.name)
        profile = SecurityProfile(level=SecurityLevel.MEDIUM)
        log_len = len(frappe.local.message_log)
        try:
            with patch.dict(frappe.conf, {"developer_mode": 0}), self.as_user(user.name):
                if errno is None:
                    return get_security_framework().validate_authentication(profile, user.name)
                with _sepa2409_driver_fault(PROFILE_TABLE, errno):
                    return get_security_framework().validate_authentication(profile, user.name)
        except VPermissionError as exc:
            entries = [
                {k: v for k, v in e.items() if k != "__frappe_exc_id"}
                for e in frappe.local.message_log[log_len:]
            ]
            return type(exc), str(exc), entries

    def test_endpoint_refuses_failed_lookup_identically_to_no_permission(self):
        self.expectErrorLog(LOG_TITLE)
        member = self._make_user_with_role_profile("Verenigingen Member", prefix="mem3095")
        no_permission = self._validate_auth_refusal_3095(member)
        self.assertIsInstance(no_permission, tuple, "control: a plain Member must be refused")
        failed = self._validate_auth_refusal_3095(self.sysmgr, ORDINARY_ERRNO)
        self.assertEqual(failed, no_permission)

    def test_control_endpoint_admits_a_healthy_no_profile_system_manager(self):
        self.assertIs(self._validate_auth_refusal_3095(self.sysmgr), True)
