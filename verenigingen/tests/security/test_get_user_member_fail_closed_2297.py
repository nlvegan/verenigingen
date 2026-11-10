"""#2297: a failed caller->Member lookup must refuse, not skip the deep TOCTOU content check.

The self-service decorator resolves the caller's Member twice: once inside the ownership gate
(`validate_access`) and again to run the deep request-content inspection, which only runs
`if user_member:`. `SelfServiceAccessController.get_user_member` used to turn ANY exception into
None, so a lookup error on the second resolution silently dropped the inspection.

The failure is injected at `frappe.db.get_value` (below get_member_name_for_board_access and the
controller's own except) and only on the SECOND Member.user lookup, so the ownership gate has
already passed -- the exact state the issue describes. The request smuggles a foreign member
inside a nested payload: the shallow gate cannot see it, only the deep check can. The caller is a
plain "Verenigingen Member" user, not Administrator. The side effect is a list append in the body.

Fixture note: Member.user is linked with db_set (the state under test, not a flow stand-in).
"""

import frappe
from frappe.exceptions import QueryDeadlockError

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.error_handling import PermissionError as VPermissionError
from verenigingen.utils.security.api_security_framework import self_service_api
from verenigingen.utils.security.types import OperationType

SIDE_EFFECTS = []


@self_service_api(operation_type=OperationType.MEMBER_DATA)
def probe_2297_update_own(member=None, data=None):
    SIDE_EFFECTS.append((member, data))
    return {"ok": True}


class TestGetUserMemberFailClosed2297(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        SIDE_EFFECTS.clear()
        email = f"ss2297-{frappe.generate_hash(length=8)}0@example.com"
        self.member = self.create_test_member(
            first_name="Ss", last_name="Toctou", email=email, birth_date="1990-01-01"
        )
        self.member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        self.member.db_set("user", email)
        self.user = email
        self.victim = self.create_test_member(
            first_name="Vic", last_name="Tim", email=f"vic2297-{frappe.generate_hash(length=8)}0@example.com",
            birth_date="1991-01-01",
        )

    def _call(self, data):
        with self.as_user(self.user):
            return probe_2297_update_own(member=self.member.name, data=data)

    def _fail_on_nth_member_lookup(self, nth, exc):
        """Patch frappe.db.get_value: raise `exc` on the `nth` Member.user lookup for the caller."""
        real = frappe.db.get_value
        calls = {"n": 0}

        def flaky(doctype, filters=None, *args, **kwargs):
            if doctype == "Member" and isinstance(filters, dict) and filters.get("user") == self.user:
                calls["n"] += 1
                if calls["n"] == nth:
                    raise exc
            return real(doctype, filters, *args, **kwargs)

        frappe.db.get_value = flaky  # Mock justified: a real transient DB error needs a second session
        self.addCleanup(setattr, frappe.db, "get_value", real)
        return calls

    def test_control_clean_own_request_passes(self):
        self.assertEqual(self._call({"note": "x"}), {"ok": True})
        self.assertEqual(len(SIDE_EFFECTS), 1)

    def test_control_the_deep_check_really_catches_a_nested_foreign_member(self):
        with self.assertRaises(VPermissionError) as ctx:
            self._call({"member": self.victim.name})
        self.assertIn("only be performed on your own data", str(ctx.exception))
        self.assertEqual(SIDE_EFFECTS, [])

    def test_a_failed_second_lookup_refuses_instead_of_skipping_the_deep_check(self):
        self.expectErrorLog("Self-service member lookup failed")
        calls = self._fail_on_nth_member_lookup(2, frappe.ValidationError("boom-secret"))
        with self.assertRaises(VPermissionError) as ctx:
            self._call({"member": self.victim.name})
        self.assertGreaterEqual(calls["n"], 2, "the injected failure never fired on the 2nd lookup")
        self.assertEqual(SIDE_EFFECTS, [], "the endpoint ran although the TOCTOU check was skipped")
        self.assertNotIn("boom-secret", str(ctx.exception))
        self.assertNotIn(self.victim.name, str(ctx.exception))

    def test_a_failed_second_lookup_refuses_even_a_clean_request(self):
        """Refusal, not 'skip only when suspicious': the check cannot be known to pass."""
        self.expectErrorLog("Self-service member lookup failed")
        self._fail_on_nth_member_lookup(2, frappe.ValidationError("boom"))
        with self.assertRaises(VPermissionError):
            self._call({"note": "x"})
        self.assertEqual(SIDE_EFFECTS, [])

    def test_the_failure_is_recorded_in_the_error_log(self):
        self.expectErrorLog("Self-service member lookup failed")
        self._fail_on_nth_member_lookup(2, frappe.ValidationError("boom"))
        before = frappe.db.count("Error Log", {"method": ["like", "%Self-service member lookup failed%"]})
        with self.assertRaises(VPermissionError):
            self._call({"note": "x"})
        after = frappe.db.count("Error Log", {"method": ["like", "%Self-service member lookup failed%"]})
        self.assertEqual(after, before + 1)

    def test_a_deadlock_propagates_unflattened(self):
        self._fail_on_nth_member_lookup(2, QueryDeadlockError("1213"))
        with self.assertRaises(QueryDeadlockError):
            self._call({"note": "x"})
        self.assertEqual(SIDE_EFFECTS, [])

    def test_a_failed_first_lookup_still_refuses(self):
        """The ownership gate's own lookup erroring was already closed; keep it closed."""
        self.expectErrorLog("Self-service member lookup failed")
        self._fail_on_nth_member_lookup(1, frappe.ValidationError("boom"))
        with self.assertRaises(VPermissionError):
            self._call({"note": "x"})
        self.assertEqual(SIDE_EFFECTS, [])

    def test_a_user_with_no_member_keeps_the_existing_refusal(self):
        """Control for the opposite harm: no-Member is NOT an error and keeps its own message."""
        email = f"nomember2297-{frappe.generate_hash(length=8)}0@example.com"
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        with self.as_user(email):
            with self.assertRaises(VPermissionError) as ctx:
                probe_2297_update_own(member=self.member.name, data=None)
        self.assertIn("Unable to verify member access for this user", str(ctx.exception))
        self.assertNotIn("right now", str(ctx.exception), "no-Member must not read as a lookup failure")
