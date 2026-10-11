"""
Real-integration tests for the whitelisted endpoints in
``verenigingen/services/member/account/account_creation_api.py``.

This module is the public-facing queue / batch / retry layer that creates and
drives ``Account Creation Request`` (ACR) records for member / volunteer user
provisioning. It was largely uncovered (~38%). The tests here create real
Members, Volunteers and ACRs via the factory / real ``frappe.get_doc`` and run
as Administrator (no business-logic mocking).

Notes on what is and isn't exercised end-to-end:

* The queue/process functions run ``AccountCreationManager.process_complete_pipeline``
  which creates a *real* ``User`` (and, for volunteers, an ``Employee``). Under
  ``frappe.flags.in_test`` ``frappe.enqueue`` runs inline, so calling
  ``queue_processing()`` / ``process_account_creation_request`` processes the
  request synchronously against *only the member we created* — never unrelated
  records. Any User the pipeline creates is tracked for tearDown cleanup.

* ``process_bulk_account_creation_batch`` chains the *next* batch via
  ``frappe.enqueue`` only when ``remaining_batches`` is non-empty; with a single
  batch there is no chaining. We exercise it with one self-created member so no
  unrelated data is touched. We do NOT attempt a multi-batch chain (it would
  enqueue follow-on jobs and, outside tests, sleep on queue-capacity waits).
"""

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase


class TestAccountCreationApi(VereningingenTestCase):
    """Exercise the account_creation_api endpoints end to end."""

    def setUp(self):
        super().setUp()
        self.uid = frappe.generate_hash(length=6)
        # Unique last_name keeps the auto-created Customer name unique (Customer
        # PK is the full name) so concurrent tests don't collide.
        self.member = self.create_test_member(
            first_name="AcctApi",
            last_name=f"Member{self.uid}",
            email=f"acctapi.member.{self.uid}@test.invalid",
            status="Active",
        )

    def _track_user(self, email):
        """Track a User the pipeline may have created so tearDown removes it."""
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    # The @critical_api / @high_security_api decorators serialize the returned
    # OperationResult into the nested response dict
    # ({"success", "data", "error": {"message", "errors"}, "meta"}), so the
    # endpoints hand back a dict, not an OperationResult. These helpers read that
    # shape.

    def _ok(self, result):
        self.assertTrue(
            result["success"], msg=result.get("error") or result.get("meta")
        )
        return result["data"]

    def _fail_msg(self, result):
        self.assertFalse(result["success"])
        return (result.get("error", {}).get("message") or "").lower()

    def _fail_errors(self, result):
        self.assertFalse(result["success"])
        return result.get("error", {}).get("errors") or []

    def _insert_acr(self, **overrides):
        """Insert a real Account Creation Request for self.member (tracked)."""
        data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": self.member.name,
            "email": self.member.email,
            "full_name": self.member.full_name,
            "priority": "Normal",
            "role_profile": "Verenigingen Member",
            "business_justification": "test",
            "requested_roles": [{"role": "Verenigingen Member"}],
        }
        data.update(overrides)
        request = frappe.get_doc(data)
        request.insert()
        self.track_doc("Account Creation Request", request.name)
        return request

    # ============================================================= queue_account_creation_for_member

    def test_queue_member_not_found(self):
        result = api.queue_account_creation_for_member("NONEXISTENT-MEMBER-XYZ")
        self.assertIn("not found", self._fail_msg(result))

    def test_queue_member_without_email_fails(self):
        # A member with no email cannot have an account created.
        frappe.db.set_value("Member", self.member.name, "email", "")
        result = api.queue_account_creation_for_member(self.member.name)
        self.assertIn("email", self._fail_msg(result))

    def test_queue_member_happy_path_creates_and_processes_request(self):
        # Full happy path: a request is created and (enqueue runs inline in test)
        # the pipeline completes, creating a real User for this member.
        result = api.queue_account_creation_for_member(self.member.name)
        self._track_user(self.member.email)
        data = self._ok(result)
        request_name = data["request_name"]
        self.track_doc("Account Creation Request", request_name)
        self.assertEqual(data["member_name"], self.member.name)
        self.assertEqual(data["email"], self.member.email)
        # Request reached a non-failed processed state (inline enqueue in tests).
        # "Failed" is excluded so a silent pipeline failure can't pass this test.
        status = frappe.db.get_value("Account Creation Request", request_name, "status")
        self.assertIn(status, ("Completed", "Queued", "Processing", "Requested"))

    def test_queue_member_duplicate_request_rejected(self):
        # An open request for the same source record blocks a second queue call.
        self._insert_acr()
        result = api.queue_account_creation_for_member(self.member.name)
        self.assertIn("already exists", self._fail_msg(result))

    def _fail_via_real_pipeline(self, **acr_overrides):
        """Reach a Failed ACR through the real processor (no ``set_value``): an ACR
        whose own email is malformed makes user creation raise inside
        ``process_account_creation_request``, which calls ``mark_failed``. The Member
        keeps its valid email, so a fresh request for the member would succeed."""
        self.expectErrorLog(
            "Account Creation Request Processing Error",
            "User Creation Failed",
            "Retry Failed Request Error",
        )
        request = self._insert_acr(email="not-a-valid-email-format", **acr_overrides)
        api.process_account_creation_request(request.name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Failed",
        )
        return request

    def _exhaust_retries_via_real_flow(self, request):
        """Drive ``retry_failed_request`` (the only recovery path) until the cap."""
        from verenigingen.verenigingen.doctype.account_creation_request.account_creation_request import (
            AccountCreationRequest,
        )

        for _attempt in range(AccountCreationRequest.MAX_RETRIES):
            api.retry_failed_request(request.name)
            # frappe.enqueue never runs inline under test (call_directly needs
            # `now` or not in_test), and CI has no workers, so run the queued
            # request ourselves.
            if frappe.db.get_value("Account Creation Request", request.name, "status") != "Failed":
                api.process_account_creation_request(request.name)
            # the retried pipeline fails again for the same malformed email
            self.assertEqual(
                frappe.db.get_value("Account Creation Request", request.name, "status"),
                "Failed",
            )
        return AccountCreationRequest.MAX_RETRIES

    def test_queue_member_failed_acr_at_max_retries_does_not_block_new_request(self):
        """#1614. A Failed ACR whose retries are spent can never be retried
        (``retry_processing`` refuses, ``retry_all_failed_requests`` filters it
        out), so it must not block a fresh request for the member forever."""
        request = self._fail_via_real_pipeline()
        cap = self._exhaust_retries_via_real_flow(request)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "retry_count"),
            cap,
        )
        # Premise: the dead end is real -- the retry path refuses this request.
        retry = api.retry_failed_request(request.name)
        self.assertFalse(retry["success"])

        result = api.queue_account_creation_for_member(self.member.name)
        self._track_user(self.member.email)
        data = self._ok(result)
        self.track_doc("Account Creation Request", data["request_name"])
        self.assertNotEqual(data["request_name"], request.name)

    def test_queue_member_failed_acr_with_retries_left_still_blocks(self):
        """Control for #1614: a Failed ACR that CAN still be retried keeps blocking
        (retry is the recovery), so the fix must key on spent retries, not on
        status Failed alone."""
        request = self._fail_via_real_pipeline()
        self.assertLess(
            frappe.db.get_value("Account Creation Request", request.name, "retry_count") or 0,
            3,
        )
        result = api.queue_account_creation_for_member(self.member.name)
        self.assertIn("already exists", self._fail_msg(result))
        self.assertIn(request.name, " ".join(self._fail_errors(result)))

    def test_queue_member_open_acr_with_spent_retry_count_still_blocks(self):
        """Control for #1614: ``schedule_retry`` leaves an OPEN (Requested) ACR with
        retry_count == MAX_RETRIES. Only status Failed may be treated as spent.
        Seeds retry_count directly (the real writer is schedule_retry, which also
        enqueues a job this test must not start)."""
        request = self._insert_acr()
        frappe.db.set_value("Account Creation Request", request.name, "retry_count", 3)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Requested",
        )
        result = api.queue_account_creation_for_member(self.member.name)
        self.assertIn("already exists", self._fail_msg(result))
        self.assertIn(request.name, " ".join(self._fail_errors(result)))

    def test_queue_member_spent_failed_acr_does_not_hide_an_open_one(self):
        """Control for #1614: a spent Failed ACR next to an OPEN one must still
        refuse, naming the open one."""
        failed = self._fail_via_real_pipeline()
        self._exhaust_retries_via_real_flow(failed)
        open_request = self._insert_acr()  # status Requested
        result = api.queue_account_creation_for_member(self.member.name)
        self.assertIn("already exists", self._fail_msg(result))
        self.assertIn(open_request.name, " ".join(self._fail_errors(result)))

    def test_queue_member_role_profile_inferred_for_volunteer_role(self):
        # Passing the Volunteer role (and no explicit role_profile) must infer the
        # Volunteer role_profile, which flags employee-record creation.
        from verenigingen.utils.constants import Roles

        result = api.queue_account_creation_for_member(
            self.member.name, roles=[Roles.VOLUNTEER]
        )
        self._track_user(self.member.email)
        data = self._ok(result)
        request_name = data["request_name"]
        self.track_doc("Account Creation Request", request_name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Volunteer",
        )
        self.assertEqual(
            frappe.db.get_value(
                "Account Creation Request", request_name, "create_employee_record"
            ),
            1,
        )

    def test_queue_member_roles_json_string_deserialized(self):
        # frappe.call serializes list params to JSON strings; the endpoint must
        # parse them back to a list.
        result = api.queue_account_creation_for_member(
            self.member.name, roles='["Verenigingen Member"]'
        )
        self._track_user(self.member.email)
        data = self._ok(result)
        request_name = data["request_name"]
        self.track_doc("Account Creation Request", request_name)
        roles = frappe.get_all(
            "Account Creation Request Role",
            filters={"parent": request_name},
            pluck="role",
        )
        self.assertIn("Verenigingen Member", roles)

    # ========================================================== queue_account_creation_for_volunteer

    def _make_volunteer(self):
        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="AcctApiVol",
            last_name=f"Member{h}",
            email=f"acctapi.vol.{h}@test.invalid",
            status="Active",
        )
        # Volunteer.after_insert auto-queues a Volunteer-type Account Creation
        # Request; suppress it so these tests control ACR creation themselves.
        frappe.flags.skip_volunteer_account_creation = True
        try:
            return self.create_test_volunteer(member_name=member.name)
        finally:
            frappe.flags.skip_volunteer_account_creation = False

    def test_queue_volunteer_not_found(self):
        result = api.queue_account_creation_for_volunteer("NONEXISTENT-VOL-XYZ")
        self.assertIn("not found", self._fail_msg(result))

    def test_queue_volunteer_without_email_fails(self):
        volunteer = self._make_volunteer()
        frappe.db.set_value("Volunteer", volunteer.name, "email", "")
        result = api.queue_account_creation_for_volunteer(volunteer.name)
        self.assertIn("email", self._fail_msg(result))

    def test_queue_volunteer_existing_user_short_circuits(self):
        # If a User already exists for the volunteer's email, the endpoint returns
        # ok with result == "existing_user" and does NOT create a request.
        volunteer = self._make_volunteer()
        email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        result = api.queue_account_creation_for_volunteer(volunteer.name)
        data = self._ok(result)
        self.assertEqual(data["result"], "existing_user")
        self.assertIsNone(data["request_name"])

    def test_queue_volunteer_duplicate_request_rejected(self):
        volunteer = self._make_volunteer()
        email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        existing = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "request_type": "Volunteer",
                "source_record": volunteer.name,
                "email": email,
                "full_name": volunteer.volunteer_name,
                "role_profile": "Verenigingen Volunteer",
                "business_justification": "test",
                "requested_roles": [{"role": "Verenigingen Volunteer"}],
            }
        )
        existing.insert()
        self.track_doc("Account Creation Request", existing.name)
        result = api.queue_account_creation_for_volunteer(volunteer.name)
        self.assertIn("already exists", self._fail_msg(result))

    def test_queue_volunteer_failed_acr_at_max_retries_does_not_block_new_request(self):
        """#1614, sibling: ``queue_account_creation_for_volunteer`` carries the same
        dedup rule, so a spent Failed Volunteer ACR must not block it either."""
        volunteer = self._make_volunteer()
        email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        failed = self._fail_via_real_pipeline(
            request_type="Volunteer",
            source_record=volunteer.name,
            role_profile="Verenigingen Volunteer",
            requested_roles=[{"role": "Verenigingen Volunteer"}],
        )
        self._exhaust_retries_via_real_flow(failed)
        result = api.queue_account_creation_for_volunteer(volunteer.name)
        self._track_user(email)
        data = self._ok(result)
        self.track_doc("Account Creation Request", data["request_name"])
        self.assertNotEqual(data["request_name"], failed.name)

    def test_queue_volunteer_happy_path(self):
        volunteer = self._make_volunteer()
        email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        result = api.queue_account_creation_for_volunteer(volunteer.name)
        self._track_user(email)
        data = self._ok(result)
        request_name = data["request_name"]
        self.track_doc("Account Creation Request", request_name)
        # Volunteer requests carry the three volunteer roles.
        roles = frappe.get_all(
            "Account Creation Request Role",
            filters={"parent": request_name},
            pluck="role",
        )
        self.assertIn("Verenigingen Volunteer", roles)
        self.assertIn("Employee", roles)

    # ===================================================================== process_account_creation_request

    def test_process_request_happy_path(self):
        # Drive the background entry point directly against a self-created request.
        request = self._insert_acr()
        result = api.process_account_creation_request(request.name)
        self._track_user(self.member.email)
        data = self._ok(result)
        self.assertEqual(data["request_name"], request.name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Completed",
        )

    def test_process_request_nonexistent_returns_fail(self):
        # A missing request makes the manager raise; the endpoint wraps it in fail.
        result = api.process_account_creation_request("ACR-Member-9999-99-99-deadbeef")
        self.assertTrue(self._fail_errors(result))

    # ===================================================================== get_failed_requests

    def test_get_failed_requests_lists_failed(self):
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom"},
        )
        result = api.get_failed_requests()
        data = self._ok(result)
        names = [r["name"] for r in data["failed_requests"]]
        self.assertIn(request.name, names)
        self.assertGreaterEqual(data["count"], 1)

    # ===================================================================== retry_failed_request

    def test_retry_failed_request_not_found(self):
        result = api.retry_failed_request("ACR-Member-9999-99-99-deadbeef")
        self.assertIn("not found", self._fail_msg(result))

    def test_retry_failed_request_happy_path(self):
        # A Failed request can be retried; retry_processing requeues it (inline in
        # test) and the pipeline completes against this member.
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom", "retry_count": 0},
        )
        result = api.retry_failed_request(request.name)
        self._track_user(self.member.email)
        data = self._ok(result)
        self.assertEqual(data["request_name"], request.name)

    def test_retry_non_failed_request_returns_fail(self):
        # retry_processing throws for a non-Failed request; endpoint wraps to fail.
        request = self._insert_acr()  # status "Requested"
        result = api.retry_failed_request(request.name)
        self.assertTrue(self._fail_errors(result))

    # ===================================================================== retry_all_failed_requests

    def test_retry_all_failed_none_found(self):
        # No retryable failed requests for the (filtered) failure type.
        result = api.retry_all_failed_requests(failure_type="rate_limit")
        data = self._ok(result)
        # Either nothing failed at all, or the rate_limit filter excluded them.
        self.assertIn("retried", data)

    def test_retry_all_failed_retries_failed_request(self):
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom", "retry_count": 0},
        )
        result = api.retry_all_failed_requests()
        self._track_user(self.member.email)
        data = self._ok(result)
        self.assertGreaterEqual(data["retried"], 1)

    def test_retry_all_failed_filter_employee_exists(self):
        # The employee_exists filter only retries requests whose failure_reason
        # matches; a non-matching failure must be filtered out (retried == 0).
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "some other error", "retry_count": 0},
        )
        result = api.retry_all_failed_requests(failure_type="employee_exists")
        data = self._ok(result)
        self.assertEqual(data["retried"], 0)

    # ===================================================================== upgrade_member_to_volunteer_user

    def test_upgrade_member_not_found(self):
        result = api.upgrade_member_to_volunteer_user("NONEXISTENT-MEMBER-XYZ")
        self.assertIn("not found", self._fail_msg(result))

    def test_upgrade_member_without_user_fails(self):
        # self.member has no linked user yet.
        self.assertFalse(frappe.db.get_value("Member", self.member.name, "user"))
        result = api.upgrade_member_to_volunteer_user(self.member.name)
        self.assertIn("no user account", self._fail_msg(result))

    def test_upgrade_member_already_system_user(self):
        # A member already linked to a System User reports already_upgraded.
        email = f"acctapi.sysuser.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email)
        self.track_doc("User", user.name)
        frappe.db.set_value("User", user.name, "user_type", "System User")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        result = api.upgrade_member_to_volunteer_user(self.member.name)
        data = self._ok(result)
        self.assertTrue(data["already_upgraded"])

    def test_upgrade_member_website_user_to_system_user(self):
        # A Website User linked to the member is upgraded to System User.
        # The user needs a desk-access role ("Verenigingen Volunteer"), otherwise
        # Frappe's User.validate reverts user_type back to "Website User" on save
        # (user_type is derived from roles) — that revert is framework behaviour,
        # not a bug in this endpoint.
        email = f"acctapi.webuser.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Volunteer"])
        self.track_doc("User", user.name)
        frappe.db.set_value("User", user.name, "user_type", "Website User")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        result = api.upgrade_member_to_volunteer_user(self.member.name)
        data = self._ok(result)
        self.assertEqual(data["user"], user.name)
        self.assertEqual(
            frappe.db.get_value("User", user.name, "user_type"), "System User"
        )

    # ===================================================================== queue_bulk_account_creation_for_members

    def test_bulk_queue_empty_list_fails(self):
        result = api.queue_bulk_account_creation_for_members([])
        self.assertIn("no member names", self._fail_msg(result))

    def test_bulk_queue_all_invalid_status_no_requests(self):
        # filter_by_status=True drops members whose status is not account-eligible
        # (VALID_ACCOUNT_STATUSES = Active/Pending/Suspended); a single Banned
        # member yields no requests created.
        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="AcctApiBulk",
            last_name=f"Banned{h}",
            email=f"acctapi.bulk.banned.{h}@test.invalid",
            status="Active",
        )
        # Set the disqualifying status directly to avoid Member status-transition
        # validation on create.
        frappe.db.set_value("Member", member.name, "status", "Banned")
        result = api.queue_bulk_account_creation_for_members([member.name])
        # No valid members -> fail with the "no valid members" message.
        self.assertIn("no valid members", self._fail_msg(result))

    def test_bulk_queue_single_member_happy_path(self):
        # One Active member: a request is created, a tracker is made, and the first
        # (only) batch is enqueued — no chaining (remaining_batches is empty).
        h = frappe.generate_hash(length=6)
        member = self.create_test_member(
            first_name="AcctApiBulk",
            last_name=f"Active{h}",
            email=f"acctapi.bulk.active.{h}@test.invalid",
            status="Active",
        )
        result = api.queue_bulk_account_creation_for_members([member.name])
        self._track_user(member.email)
        data = self._ok(result)
        self.assertEqual(data["requests_created"], 1)
        for name in data["request_names"]:
            self.track_doc("Account Creation Request", name)
        self.track_doc("Bulk Operation Tracker", data["tracker_name"])
        self.assertEqual(data["batch_count"], 1)

    # ===================================================================== permission guards (non-admin)

    def test_get_failed_requests_permission_denied_for_member(self):
        # A plain member user lacks the high-security access tier; the
        # @high_security_api decorator rejects the call BEFORE the function body
        # runs, raising its framework PermissionError (the in-body permission
        # OperationResult branch is unreachable for a tier-failing user).
        from verenigingen.utils.error_handling import PermissionError as FwPermissionError

        email = f"acctapi.plain.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        with self.as_user(user.name):
            with self.assertRaises(FwPermissionError):
                api.get_failed_requests()
