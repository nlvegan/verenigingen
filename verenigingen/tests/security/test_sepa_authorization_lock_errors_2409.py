"""#2409 point 2: the SEPA authorization manager must not turn 1213/1205 into a deny.

``SEPAAuthorizationManager._check_contextual_permissions`` (and every handler above and
beside it in authorization.py) ended in ``except Exception: log_error; return False``. A
deadlock / lock-wait timeout raised by a callee therefore read as an ordinary deny, and an
inner ``NON_RESUMABLE_DB_ERRORS`` re-raise (the engine's role-profile lookup, ``_load_allowed_ips``)
was defeated by the outer handler. Ordinary errors must KEEP their fail-closed deny.

The lock error is injected at the DRIVER, below every swallow layer: ``frappe.db.execute_query``
(the cursor call) raises a real ``OperationalError`` 1213/1205 and frappe's own dispatch converts it
into ``QueryDeadlockError`` / ``QueryTimeoutError``, exactly as production does. There is no way to
make a healthy test DB deadlock on demand. Each tested path is hit with the lock error AND with an
ordinary error (2013 "lost connection") at the same statement.
"""

import json
import traceback
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from verenigingen.tests.security.test_authorization_coverage import AuthorizationTestBase
from verenigingen.utils.error_handling import PermissionError as VerenigingenPermissionError
from verenigingen.utils.security import authorization as auth_module
from verenigingen.utils.security.authorization import (
    SEPAAuthorizationManager,
    SEPAOperation,
    SEPAPermissionLevel,
    check_sepa_operation_permission,
    get_user_sepa_permissions,
    require_sepa_permission,
)

SETTINGS = "Verenigingen Payments Settings"
LOCK_ERRNOS = {frappe.QueryDeadlockError: 1213, frappe.QueryTimeoutError: 1205}
ORDINARY_ERRNO = 2013


def _sepa2409_driver_fault(needle, errno):
    """Make the cursor fail with a real driver OperationalError for statements naming ``needle``."""
    real = frappe.db.execute_query
    # get_single_value serves a cached value without touching the cursor; drop it so the read is real.
    frappe.db.value_cache.pop(SETTINGS, None)

    def execute_query(query, values=None):
        # Recording a failure (log_error / log_security_event) reads and writes the same tables and must
        # not itself be failed, or a lock error would escape from INSIDE the swallow handler's logging
        # and the test would pass without the handler ever re-raising (seen: decorator + endpoint tests).
        recording = any(f.name in ("log_error", "log_security_event") for f in traceback.extract_stack())
        if not recording and (needle in query or needle in repr(values)):
            raise frappe.db.OperationalError(errno, f"injected {errno} for #2409")
        return real(query, values)

    return patch.object(frappe.db, "execute_query", execute_query)


class TestSepaAuthorizationLockErrors2409(AuthorizationTestBase):
    def setUp(self):
        super().setUp()
        self._request = getattr(frappe.local, "request", None)
        self._conf_had = "sepa_allowed_ips" in frappe.conf
        self._conf_value = frappe.conf.get("sepa_allowed_ips")
        frappe.conf.pop("sepa_allowed_ips", None)
        self.staff = self._make_user_with_role_profile("Verenigingen Staff", prefix="s2409")
        self.sysadmin = self._make_user_with_role_profile(
            "Verenigingen System Administrator", prefix="a2409"
        )
        self.member = self._make_user_with_role_profile("Verenigingen Member", prefix="m2409")

    def tearDown(self):
        frappe.local.request = self._request  # Mock justified: Infrastructure - restore
        if self._conf_had:
            frappe.conf["sepa_allowed_ips"] = self._conf_value
        else:
            frappe.conf.pop("sepa_allowed_ips", None)
        super().tearDown()

    def _http(self):
        frappe.local.request = SimpleNamespace(method="POST", environ={"REMOTE_ADDR": "203.0.113.5"})  # Mock justified: Infrastructure - simulated HTTP request

    def _manager_with_unreadable_ip_allowlist(self):
        """A manager built while the Settings read failed ordinarily: allowed_ips is None, so the
        next restricted check RETRIES the read (the callee that can raise inside the try)."""
        self.expectErrorLog("SEPA allowed IPs could not be read")
        with _sepa2409_driver_fault(SETTINGS, ORDINARY_ERRNO):
            manager = SEPAAuthorizationManager()
        self.assertIsNone(manager.allowed_ips)
        self._http()
        return manager

    def _escaped_from(self, call, error, frame_name):
        """Run ``call`` and return after asserting ``error`` escaped and its traceback passed
        through ``frame_name`` (assertRaises strips ``__traceback__``, hence the manual catch)."""
        try:
            call()
        except error as exc:
            frames = [f.name for f in traceback.extract_tb(exc.__traceback__)]
            self.assertIn(frame_name, frames, frames)
            return
        self.fail(f"{error.__name__} did not escape {frame_name}")

    # ------------------------------------------------ _check_contextual_permissions, IP retry

    def test_contextual_check_propagates_lock_error_from_ip_allowlist_retry(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                manager = self._manager_with_unreadable_ip_allowlist()
                with _sepa2409_driver_fault(SETTINGS, errno):
                    self._escaped_from(
                        lambda: manager._check_contextual_permissions(
                            SEPAOperation.SETTINGS_MODIFY, "Administrator"
                        ),
                        error,
                        "_check_ip_restrictions",
                    )

    def test_has_permission_propagates_lock_error_from_ip_allowlist_retry(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                manager = self._manager_with_unreadable_ip_allowlist()
                with self.as_user(self.sysadmin.name), _sepa2409_driver_fault(SETTINGS, errno):
                    with self.assertRaises(error):
                        manager.has_permission(SEPAOperation.SETTINGS_MODIFY)

    def test_control_ordinary_error_in_ip_allowlist_retry_still_denies_and_logs(self):
        manager = self._manager_with_unreadable_ip_allowlist()
        with self.as_user(self.sysadmin.name), _sepa2409_driver_fault(SETTINGS, ORDINARY_ERRNO):
            self.assertFalse(
                manager._check_contextual_permissions(SEPAOperation.SETTINGS_MODIFY, self.sysadmin.name)
            )
            self.assertFalse(manager.has_permission(SEPAOperation.SETTINGS_MODIFY))

    # ------------------------------------------------ _check_batch_permissions

    def _batch_context(self):
        return {"batch_name": f"NO-SUCH-BATCH-{frappe.generate_hash(length=6)}"}

    def test_batch_check_propagates_lock_error(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                with self.as_user(self.staff.name), _sepa2409_driver_fault("tabDirect Debit Batch", errno):
                    context = self._batch_context()
                    self._escaped_from(
                        lambda: self.manager._check_batch_permissions(context, self.staff.name),
                        error,
                        "_check_batch_permissions",
                    )
                    self._escaped_from(
                        lambda: self.manager._check_contextual_permissions(
                            SEPAOperation.BATCH_PROCESS, self.staff.name, context
                        ),
                        error,
                        "_check_batch_permissions",
                    )
                    with self.assertRaises(error):
                        self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context=context)

    def test_control_ordinary_error_in_batch_check_still_denies_and_logs(self):
        with self.as_user(self.staff.name), _sepa2409_driver_fault("tabDirect Debit Batch", ORDINARY_ERRNO):
            context = self._batch_context()
            with patch.object(auth_module, "log_error", wraps=auth_module.log_error) as logged:
                self.assertFalse(self.manager._check_batch_permissions(context, self.staff.name))
                self.assertFalse(self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context=context))
            self.assertTrue(logged.called)

    def test_control_missing_batch_still_denies(self):
        """A batch that does not exist is an ordinary DoesNotExistError: deny, as before."""
        with self.as_user(self.staff.name):
            self.assertFalse(
                self.manager.has_permission(SEPAOperation.BATCH_PROCESS, context=self._batch_context())
            )

    # ------------------------------------------------ get_user_permissions (engine re-raise)

    def test_get_user_permissions_propagates_lock_error_from_the_role_profile_lookup(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                user = self._make_user_with_role_profile("Verenigingen Staff", prefix="l2409")
                with _sepa2409_driver_fault("tabUser Role Profile", errno):
                    self._escaped_from(
                        lambda: self.manager.get_user_permissions(user.name),
                        error,
                        "get_user_role_profiles",
                    )
                    with self.assertRaises(error):
                        self.manager.has_permission(SEPAOperation.BATCH_CREATE, user.name)

    def test_control_ordinary_error_in_role_profile_lookup_denies(self):
        """An ordinary error in the lookup degrades (engine logs, returns no profiles) and a user
        with no SEPA role still gets nothing: never an allow, never an exception.

        A Member-profile user is used on purpose: for a Staff user the documented role-name
        fallback in get_user_permissions would re-derive the same levels from the user's roles."""
        self.expectErrorLog("role profile lookup failed")
        with _sepa2409_driver_fault("tabUser Role Profile", ORDINARY_ERRNO):
            auth_module.get_authorization_engine().invalidate_user_cache(self.member.name)
            self.assertFalse(self.manager.has_permission(SEPAOperation.BATCH_CREATE, self.member.name))
            self.assertEqual(self.manager.get_user_permissions(self.member.name), [])

    # ------------------------------------------------ callers above has_permission

    def test_validate_operation_propagates_lock_error_not_a_permission_error(self):
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                user = self._make_user_with_role_profile("Verenigingen Staff", prefix="v2409")
                with _sepa2409_driver_fault("tabUser Role Profile", errno):
                    with self.assertRaises(error):
                        self.manager.validate_operation(SEPAOperation.BATCH_CREATE, user.name)
                    with self.assertRaises(error):
                        self.manager.validate_operation(
                            SEPAOperation.BATCH_CREATE, user.name, raise_exception=False
                        )

    def test_require_sepa_permission_decorator_propagates_lock_error(self):
        @require_sepa_permission(SEPAPermissionLevel.CREATE, SEPAOperation.BATCH_CREATE)
        def endpoint_2409():
            return "ran"

        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                user = self._make_user_with_role_profile("Verenigingen Staff", prefix="d2409")
                auth_module._auth_manager = None  # Mock justified: Infrastructure - fresh singleton
                with self.as_user(user.name), _sepa2409_driver_fault("tabUser Role Profile", errno):
                    with self.assertRaises(error):
                        endpoint_2409()

    def test_check_sepa_operation_permission_endpoint_propagates_lock_error(self):
        """The public endpoint, decorators and all: the lock error comes from the batch read in the
        body (the role profile is already cached by the decorator's own authorization)."""
        context = json.dumps(self._batch_context())
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                auth_module._auth_manager = None  # Mock justified: Infrastructure - fresh singleton
                with self.as_user(self.staff.name), _sepa2409_driver_fault("tabDirect Debit Batch", errno):
                    with self.assertRaises(error):
                        check_sepa_operation_permission("batch_process", context)

    def test_get_user_sepa_permissions_body_propagates_lock_error(self):
        """Probe shortcut: the security decorator stack is bypassed (``__wrapped__``). With it on, the
        decorator's own authorization hits the same lookup first and raises before the body runs, so
        the body's handler is only reachable on a cache miss between the two reads."""
        body = get_user_sepa_permissions
        while hasattr(body, "__wrapped__"):
            body = body.__wrapped__
        self.assertEqual(body.__name__, "get_user_sepa_permissions")
        for error, errno in LOCK_ERRNOS.items():
            with self.subTest(error=error.__name__):
                user = self._make_user_with_role_profile("Verenigingen Staff", prefix="g2409")
                with self.as_user(user.name), _sepa2409_driver_fault("tabUser Role Profile", errno):
                    with self.assertRaises(error):
                        body()

    # ------------------------------------------------ controls: real rules still decide

    def test_control_staff_allowed_member_denied_by_the_real_rule(self):
        self.assertTrue(self.manager.has_permission(SEPAOperation.BATCH_CREATE, self.staff.name))
        self.assertFalse(self.manager.has_permission(SEPAOperation.BATCH_CREATE, self.member.name))
        self.assertFalse(self.manager.has_permission(SEPAOperation.SETTINGS_MODIFY, self.staff.name))

    def test_control_ordinary_failure_in_contextual_check_still_denies_and_logs(self):
        """A non-DB error raised by a callee under the contextual try: deny + log, never allow."""
        with patch.object(self.manager, "_check_batch_permissions", side_effect=ValueError("boom")):
            with patch.object(auth_module, "log_error", wraps=auth_module.log_error) as logged:
                self.assertFalse(
                    self.manager._check_contextual_permissions(
                        SEPAOperation.BATCH_PROCESS, self.staff.name, {"batch_name": "X"}
                    )
                )
        self.assertTrue(logged.called)

    def test_control_business_hours_rule_decides_real_allow_and_deny(self):
        manager = SEPAAuthorizationManager()
        manager.business_hours = {"enabled": True, "start_hour": 0, "end_hour": 24, "weekdays_only": False}
        self.assertTrue(manager._check_contextual_permissions(SEPAOperation.XML_GENERATE, self.staff.name))
        manager.business_hours = {"enabled": True, "start_hour": 3, "end_hour": 3, "weekdays_only": False}
        self.expectErrorLog("outside_business_hours")
        self.assertFalse(manager._check_contextual_permissions(SEPAOperation.XML_GENERATE, self.staff.name))

    def test_control_permission_error_type_is_unchanged_for_a_plain_deny(self):
        with self.assertRaises(VerenigingenPermissionError):
            self.manager.validate_operation(SEPAOperation.BATCH_CREATE, self.member.name)
