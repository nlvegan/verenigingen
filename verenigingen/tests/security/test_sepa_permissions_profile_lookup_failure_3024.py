"""#3024: a FAILED role-profile lookup must not make SEPA derive permissions from role names.

``SEPAAuthorizationManager.get_user_permissions`` falls back to ``frappe.get_roles`` when the
profile-derived set is empty. ``AuthorizationEngine.get_user_role_profiles`` returns ``[]`` on an
ordinary error, so a lookup that FAILED looked exactly like "user has no profile" and the fallback
granted by role name. A failed lookup now fails closed (no permissions, recorded in the Error Log)
and a lock error (1213/1205) propagates. A user who genuinely has no profile keeps the fallback.

The failure is a real driver fault on the ``tabUser Role Profile`` read (the helper from the #2409
tests), not a mocked business function.
"""

import frappe

from verenigingen.tests.security.test_authorization_coverage import AuthorizationTestBase
from verenigingen.tests.security.test_sepa_authorization_lock_errors_2409 import (
    LOCK_ERRNOS,
    ORDINARY_ERRNO,
    _sepa2409_driver_fault,
)
from verenigingen.utils.security.authorization import SEPAAuthorizationManager, SEPAPermissionLevel
from verenigingen.utils.security.authorization_engine import get_authorization_engine

PROFILE_TABLE = "tabUser Role Profile"
LOG_PREFIX = "verenigingen.utils.security.authorization: OperationalError"


class TestSepaPermissionsProfileLookupFailure3024(AuthorizationTestBase):
    def setUp(self):
        super().setUp()
        self.manager = SEPAAuthorizationManager()
        # Direct System Manager role, NO role profile: the fallback's intended beneficiary.
        self.role_only = self._make_user_with_roles(["System Manager"], prefix="rolonly3024")
        # Real profile whose permissions are a strict subset of what the role fallback would grant.
        self.treasurer = self._make_user_with_role_profile("Verenigingen Treasurer", prefix="tre3024")

    def _perms_under_fault(self, user, errno):
        get_authorization_engine().invalidate_user_cache(user.name)
        with self.as_user(user.name), _sepa2409_driver_fault(PROFILE_TABLE, errno):
            return self.manager.get_user_permissions()

    def _lookup_error_rows(self):
        return frappe.get_all("Error Log", filters={"method": ["like", f"{LOG_PREFIX}%"]}, pluck="name")

    # ---- the defect

    def test_failed_lookup_does_not_grant_through_role_names(self):
        self.expectErrorLog(LOG_PREFIX)
        self.assertEqual(self._perms_under_fault(self.role_only, ORDINARY_ERRNO), [])

    def test_failed_lookup_is_recorded_unlike_no_profile(self):
        self.expectErrorLog(LOG_PREFIX)
        before = set(self._lookup_error_rows())
        self._perms_under_fault(self.role_only, ORDINARY_ERRNO)
        self.assertTrue(set(self._lookup_error_rows()) - before, "failed lookup left no Error Log row")

    def test_failed_lookup_does_not_widen_a_profiled_user(self):
        """Treasurer holds a Treasurer profile; a failure must deny, not re-derive from roles."""
        self.expectErrorLog(LOG_PREFIX)
        self.assertEqual(self._perms_under_fault(self.treasurer, ORDINARY_ERRNO), [])

    def test_lock_error_in_lookup_propagates(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                with self.assertRaises(error):
                    self._perms_under_fault(self.role_only, errno)

    # ---- controls (healthy lookup)

    def test_control_no_profile_user_keeps_the_role_fallback(self):
        get_authorization_engine().invalidate_user_cache(self.role_only.name)
        self.assertEqual(get_authorization_engine().get_user_role_profiles(self.role_only.name), [])
        before = set(self._lookup_error_rows())
        with self.as_user(self.role_only.name):
            perms = set(self.manager.get_user_permissions())
        self.assertEqual(perms, set(SEPAPermissionLevel))
        self.assertEqual(set(self._lookup_error_rows()), before)

    def test_control_profiled_user_gets_profile_permissions(self):
        get_authorization_engine().invalidate_user_cache(self.treasurer.name)
        with self.as_user(self.treasurer.name):
            perms = set(self.manager.get_user_permissions())
        self.assertIn(SEPAPermissionLevel.PROCESS, perms)
        self.assertNotIn(SEPAPermissionLevel.ADMIN, perms)
