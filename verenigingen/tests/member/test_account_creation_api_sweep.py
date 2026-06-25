"""
Augmenting branch-coverage tests for
``verenigingen/services/member/account/account_creation_api.py``.

This file complements (does NOT duplicate) ``test_account_creation_api.py`` and
``test_account_creation_api_coverage.py``. It reaches branches those suites left
uncovered, in particular:

* ``process_account_creation_request`` — the benign DoesNotExistError race branch
  (request name that does not exist anywhere -> clean fail, no Error Log) vs the
  generic-Exception branch (a present request whose pipeline genuinely fails).
* ``process_bulk_account_creation_batch`` — driven DIRECTLY (the existing suites
  deliberately skip it). Under ``frappe.flags.in_test`` the per-request worker
  threads run inline and the commit is skipped, so we can exercise: the
  not-found skip, the already-Completed skip, the Requested->Queued promotion +
  full pipeline success, and the "no remaining batches" terminal branch. We
  pass a real tracker so the tracker-update branch runs.
* ``queue_account_creation_for_member`` — explicit ``role_profile`` passed
  (bypasses the role-profile inference block).
* ``queue_account_creation_for_volunteer`` / ``get_failed_requests`` — the
  ``skip_user_permission_check`` flag short-circuit.
* ``upgrade_member_to_volunteer_user`` — already-System-User no-op via a member
  whose user already has user_type "System User".
* ``queue_bulk_account_creation_for_members`` — default roles/role_profile
  injection when both are omitted (multi-member, single batch).

All rows (Member / Volunteer / User / Account Creation Request / Bulk Operation
Tracker) are created via the factory or real ``frappe.get_doc`` and the suite
runs as the default Administrator -- no business-logic mocking. The
``@critical_api`` / ``@high_security_api`` decorators serialise the returned
``OperationResult`` into the nested response dict, so the helpers below read
that shape (mirroring the sibling suites).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase


class TestAccountCreationApiSweep(VereningingenTestCase):
    """Reach the queue/bulk/process/upgrade branches the sibling suites skip."""

    def setUp(self):
        super().setUp()
        self.uid = frappe.generate_hash(length=6)
        self.member = self.create_test_member(
            first_name="AcctSweep",
            last_name=f"Member{self.uid}",
            email=f"acctsweep.member.{self.uid}@test.invalid",
            status="Active",
        )

    # --- response-shape helpers (mirror the sibling suites) -------------------

    def _ok(self, result):
        self.assertTrue(result["success"], msg=result.get("error") or result.get("meta"))
        return result["data"]

    def _fail_msg(self, result):
        self.assertFalse(result["success"])
        return (result.get("error", {}).get("message") or "").lower()

    def _fail_errors(self, result):
        self.assertFalse(result["success"])
        return result.get("error", {}).get("errors") or []

    def _track_user(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    def _make_member(self, tag, status="Active"):
        h = frappe.generate_hash(length=6)
        return self.create_test_member(
            first_name="AcctSweep",
            last_name=f"{tag}{h}",
            email=f"acctsweep.{tag.lower()}.{h}@test.invalid",
            status=status,
        )

    def _insert_acr(self, member=None, **overrides):
        """Insert a real Account Creation Request (tracked)."""
        member = member or self.member
        data = {
            "doctype": "Account Creation Request",
            "request_type": "Member",
            "source_record": member.name,
            "email": member.email,
            "full_name": member.full_name,
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

    def _make_tracker(self, total_records=1):
        from verenigingen.verenigingen.doctype.bulk_operation_tracker.bulk_operation_tracker import (
            BulkOperationTracker,
        )

        tracker = BulkOperationTracker.create_tracker(
            operation_type="Account Creation",
            total_records=total_records,
            batch_size=50,
            priority="Normal",
        )
        self.track_doc("Bulk Operation Tracker", tracker.name)
        return tracker

    def _commit_setup(self):
        """Commit the current test transaction so a separate-connection worker
        thread can SEE the setup rows.

        process_bulk_account_creation_batch runs each request in a worker thread
        that opens its OWN database connection (frappe.connect) and does its own
        begin/commit. Rows inserted in the (uncommitted) test transaction are
        therefore INVISIBLE to that worker — it sees them as "not found" and
        skips them. To genuinely exercise the promote-and-process / failure
        branches the worker must see the ACR + source Member, which requires a
        commit here. Anything created/committed this way is cleaned up by
        _purge_email_artifacts + tracked-doc teardown (which both retry on the
        lock-wait that the async Contact-creation job can briefly hold)."""
        frappe.db.commit()

    def _purge_email_artifacts(self, email, wait_for_user=0.0):
        """Delete (with lock-wait retry) the User / Contact / Employee / User
        Permission rows the committed pipeline may have created for ``email``,
        and unlink them from the source Member, so tracked-doc teardown is not
        left fighting a linked, still-locked Contact.

        Frappe's User.after_insert creates a Contact named ``<full>-<full>``
        (duplicated first-last) and links it to the Member; a live background
        worker can hold a brief lock on that Contact, so each delete retries.

        ``wait_for_user``: when > 0, poll up to that many seconds for the User
        to appear before purging. Used by the bulk-queue test, where the first
        batch is dispatched as a REAL background job: on a bench with a live
        worker the User/Contact are created asynchronously AFTER the call
        returns, so we wait for them to materialise and then clean them up
        (preventing the async Contact from racing tracked-doc teardown). On a
        runner with no worker (CI) nothing materialises and the wait simply
        elapses with no artifacts to purge."""
        import time

        if not email:
            return

        if wait_for_user > 0:
            deadline = time.time() + wait_for_user
            while time.time() < deadline and not frappe.db.exists("User", email):
                time.sleep(0.25)
                frappe.db.commit()  # refresh snapshot so a worker-committed User becomes visible

        def _retry_delete(doctype, name):
            for attempt in range(5):
                try:
                    if frappe.db.exists(doctype, name):
                        frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                        frappe.db.commit()
                    return
                except Exception:
                    frappe.db.rollback()
                    time.sleep(0.5)
            # Last-ditch: leave it for tracked-doc teardown's own retry.

        user = frappe.db.exists("User", email)
        if not user:
            return

        # Unlink from any Member/Volunteer first so the Contact/User can be deleted.
        for member_name in frappe.get_all("Member", filters={"user": email}, pluck="name"):
            frappe.db.set_value("Member", member_name, "user", None, update_modified=False)
        for vol_name in frappe.get_all("Volunteer", filters={"user": email}, pluck="name"):
            frappe.db.set_value("Volunteer", vol_name, "user", None, update_modified=False)
        frappe.db.commit()

        for emp in frappe.get_all("Employee", filters={"user_id": email}, pluck="name"):
            _retry_delete("Employee", emp)
        for contact in frappe.get_all("Contact", filters={"user": email}, pluck="name"):
            _retry_delete("Contact", contact)
        for up in frappe.get_all("User Permission", filters={"user": email}, pluck="name"):
            _retry_delete("User Permission", up)
        _retry_delete("User", email)

    # ============================================== process_account_creation_request: race vs hard fail

    def test_process_request_truly_missing_is_benign_race_no_error_log(self):
        """A request name that does not exist anywhere makes the manager raise
        DoesNotExistError. That is the benign async-after-rollback race branch:
        the endpoint returns a clean fail AND must NOT write an Error Log
        (logged at debug instead). assertNoErrorLog catches a regression that
        re-routes this through the generic Exception (Error-Log-writing) path."""
        with self.assertNoErrorLog():
            result = api.process_account_creation_request(
                "ACR-Member-9999-99-99-deadbeefdead"
            )
        # The DoesNotExist branch returns the dedicated "no longer exists" message.
        self.assertIn("no longer exists", self._fail_msg(result))
        self.assertTrue(self._fail_errors(result))

    def test_process_request_pipeline_failure_writes_error_log(self):
        """A request that DOES exist but whose pipeline raises a non-DoesNotExist
        error must travel the generic Exception branch: return a fail AND write an
        Error Log titled 'Account Creation Request Processing Error'. We force the
        failure with an invalid email so user creation raises ValidationError
        (not DoesNotExistError)."""
        request = self._insert_acr(email="not-a-valid-email-format")
        # The manager logs "User Creation Failed: <email>" when user creation
        # raises; the endpoint then logs "Account Creation Request Processing
        # Error". Both are expected here.
        self.expectErrorLog(
            "Account Creation Request Processing Error", "User Creation Failed"
        )
        result = api.process_account_creation_request(request.name)
        self.assertTrue(self._fail_errors(result))
        # Generic message, not the benign "no longer exists" one.
        self.assertNotIn("no longer exists", self._fail_msg(result))
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Failed",
        )

    # ============================================== queue_account_creation_for_member: explicit role_profile

    def test_queue_member_explicit_role_profile_skips_inference(self):
        """Passing an explicit role_profile must bypass the inference block and be
        honoured verbatim, with create_employee_record driven off it."""
        result = api.queue_account_creation_for_member(
            self.member.name,
            roles=["Verenigingen Member"],
            role_profile="Verenigingen Volunteer",
        )
        self._track_user(self.member.email)
        data = self._ok(result)
        request_name = data["request_name"]
        self.track_doc("Account Creation Request", request_name)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request_name, "role_profile"),
            "Verenigingen Volunteer",
        )
        # role_profile == "Verenigingen Volunteer" => create_employee_record True.
        self.assertEqual(
            frappe.db.get_value(
                "Account Creation Request", request_name, "create_employee_record"
            ),
            1,
        )

    def test_queue_member_empty_roles_list_defaults_to_member(self):
        """An explicitly-empty roles list (len == 0) takes the default-roles branch
        and assigns the base member role."""
        result = api.queue_account_creation_for_member(self.member.name, roles=[])
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

    # ============================================== queue_account_creation_for_volunteer: skip-perm flag

    def test_queue_volunteer_skip_permission_flag_bypasses_check(self):
        """With frappe.flags.skip_user_permission_check set, the volunteer queue
        endpoint must skip the has_permission('User', 'create') guard entirely and
        proceed to the not-found check (here: a missing volunteer -> 'not found')."""
        frappe.flags.skip_user_permission_check = True
        try:
            result = api.queue_account_creation_for_volunteer("NONEXISTENT-VOL-SWEEP")
        finally:
            frappe.flags.skip_user_permission_check = False
        # Skipped the perm guard, fell through to the existence check.
        self.assertIn("not found", self._fail_msg(result))

    # ============================================== get_failed_requests: skip-perm flag

    def test_get_failed_requests_skip_permission_flag_bypasses_check(self):
        """With the skip flag set, get_failed_requests skips the
        has_permission('Account Creation Request', 'read') guard and returns the
        list directly."""
        request = self._insert_acr()
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom"},
        )
        frappe.flags.skip_user_permission_check = True
        try:
            result = api.get_failed_requests()
        finally:
            frappe.flags.skip_user_permission_check = False
        data = self._ok(result)
        self.assertIn(request.name, [r["name"] for r in data["failed_requests"]])

    # ============================================== upgrade_member_to_volunteer_user: already System User

    def test_upgrade_member_already_system_user_is_noop(self):
        """A member whose linked user is already a System User reports
        already_upgraded without re-running the module-access expansion."""
        email = f"acctsweep.sys.{frappe.generate_hash(length=6)}@test.invalid"
        # Give the user a desk role so user_type stays System User after save.
        user = self.create_test_user(email, roles=["Verenigingen Volunteer"])
        self.track_doc("User", user.name)
        frappe.db.set_value("User", user.name, "user_type", "System User")
        frappe.db.set_value("Member", self.member.name, "user", user.name)
        result = api.upgrade_member_to_volunteer_user(self.member.name)
        data = self._ok(result)
        self.assertTrue(data["already_upgraded"])
        self.assertEqual(data["user"], user.name)

    # ============================================== queue_bulk: default roles/role_profile injection

    def test_bulk_queue_omitted_roles_uses_defaults(self):
        """Omitting both roles and role_profile drives the default-setting branch
        (roles -> ['Verenigingen Member'], role_profile -> 'Verenigingen Member')
        and still creates a request + tracker for a single Active member.

        The real first batch is dispatched via ``frappe.enqueue(queue='long')``;
        we stub that infrastructure boundary (the same pattern as
        ``test_account_creation_pipeline``) so no live background job is spawned.
        The default-role injection and the ACR/tracker creation all happen
        synchronously *before* the enqueue, which is exactly what this test
        asserts. Driving the real worker would leak an async job that keeps
        retrying its Bulk Operation Tracker save minutes later and pollutes
        whichever sibling test happens to be running then."""
        member = self._make_member("BulkDefault")
        with patch("frappe.enqueue") as enqueued:
            result = api.queue_bulk_account_creation_for_members([member.name])
        data = self._ok(result)
        self.assertEqual(data["requests_created"], 1)
        for name in data["request_names"]:
            self.track_doc("Account Creation Request", name)
        self.track_doc("Bulk Operation Tracker", data["tracker_name"])
        # The single created request carries the default member role_profile.
        self.assertEqual(
            frappe.db.get_value(
                "Account Creation Request", data["request_names"][0], "role_profile"
            ),
            "Verenigingen Member",
        )
        # The first batch was handed to the background queue (chain-of-
        # responsibility entry point) carrying exactly the created request.
        enqueued.assert_called_once()
        self.assertEqual(enqueued.call_args.kwargs["request_names"], data["request_names"])

    # ============================================== process_bulk_account_creation_batch: driven directly

    def test_process_batch_request_not_found_is_skipped(self):
        """A request name that no longer exists is counted as a successful skip
        (reason 'not_found') -- completed++, no failure, no Error Log."""
        tracker = self._make_tracker(total_records=1)
        with self.assertNoErrorLog():
            result = api.process_bulk_account_creation_batch(
                request_names=["ACR-Member-9999-99-99-cafebabe0000"],
                batch_id="sweep_notfound",
                batch_number=1,
                tracker_name=tracker.name,
            )
        data = self._ok(result)
        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["failed"], 0)

    def test_process_batch_already_completed_is_skipped(self):
        """A request already in status Completed is skipped (reason
        'already_completed') -- counted as completed, pipeline NOT re-run."""
        request = self._insert_acr()
        # Force Completed directly (status is read-only post-validate).
        frappe.db.set_value(
            "Account Creation Request", request.name, "status", "Completed"
        )
        tracker = self._make_tracker(total_records=1)
        with self.assertNoErrorLog():
            result = api.process_bulk_account_creation_batch(
                request_names=[request.name],
                batch_id="sweep_completed",
                batch_number=1,
                tracker_name=tracker.name,
            )
        data = self._ok(result)
        self.assertEqual(data["completed"], 1)
        self.assertEqual(data["failed"], 0)
        # Status untouched (pipeline skipped).
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Completed",
        )

    def test_process_batch_requested_request_promotes_and_processes(self):
        """A Requested request is promoted to Queued and run through the full
        pipeline -> Completed, with the batch reporting one completion.

        The batch worker runs the request on its OWN database connection, so the
        ACR + source Member must be committed first (see _commit_setup) for the
        worker to see them and actually run the pipeline; otherwise the worker
        skips them as not_found. After the (synchronous) batch returns we commit
        the main connection to drop its stale snapshot before re-reading the
        worker-committed status, then purge the User/Contact/Employee the
        successful pipeline created."""
        member = self._make_member("BatchProc")
        request = self._insert_acr(member=member)
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Requested",
        )
        tracker = self._make_tracker(total_records=1)
        self._commit_setup()
        try:
            result = api.process_bulk_account_creation_batch(
                request_names=[request.name],
                batch_id="sweep_proc",
                batch_number=1,
                tracker_name=tracker.name,
            )
            # Drop the main connection's pre-batch snapshot so DB reads below see
            # what the worker committed on its own connection.
            frappe.db.commit()
            data = self._ok(result)
            self.assertEqual(data["total_requests"], 1)
            self.assertEqual(data["completed"], 1)
            self.assertEqual(data["failed"], 0)
            self.assertIn(request.name, data["completed_requests"])
            # Pipeline ran to completion (worker promoted Requested -> Queued ->
            # ran AccountCreationManager -> Completed).
            self.assertEqual(
                frappe.db.get_value("Account Creation Request", request.name, "status"),
                "Completed",
            )
            self.assertTrue(frappe.db.exists("User", member.email))
            # Tracker recorded the batch progress.
            tracker.reload()
            self.assertGreaterEqual(tracker.successful_records, 1)
        finally:
            self._purge_email_artifacts(member.email)

    def test_process_batch_pipeline_failure_is_isolated_and_logged(self):
        """A request whose pipeline raises is rolled back and counted as a failure
        (not a completion); the batch summary records the error and the batch
        writes the 'Bulk Account Creation Batch Errors' Error Log.

        The ACR must be committed (see _commit_setup) so the worker thread's own
        connection can see it and actually run the pipeline -- otherwise it is
        skipped as not_found and miscounted as a success. The invalid email makes
        User creation raise InvalidEmailAddressError inside the worker, so this
        path creates NO User/Contact (fully deterministic, no async-Contact
        cleanup race)."""
        request = self._insert_acr(email="batch-bad-email-format")
        tracker = self._make_tracker(total_records=1)
        self._commit_setup()
        # The manager logs "User Creation Failed: <email>" inside the worker;
        # the batch then logs "Bulk Account Creation Batch Errors". Both expected.
        self.expectErrorLog(
            "Bulk Account Creation Batch Errors", "User Creation Failed"
        )
        result = api.process_bulk_account_creation_batch(
            request_names=[request.name],
            batch_id="sweep_fail",
            batch_number=1,
            tracker_name=tracker.name,
        )
        frappe.db.commit()
        data = self._ok(result)
        self.assertEqual(data["completed"], 0)
        self.assertEqual(data["failed"], 1)
        self.assertIn(request.name, data["failed_requests"])
        self.assertTrue(data["errors"])
        # Worker rolled the request back and marked it Failed (isolation).
        self.assertEqual(
            frappe.db.get_value("Account Creation Request", request.name, "status"),
            "Failed",
        )
