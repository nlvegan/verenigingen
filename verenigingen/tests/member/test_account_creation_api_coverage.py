"""
Additional branch-coverage tests for
``verenigingen/services/member/account/account_creation_api.py``.

These complement ``test_account_creation_api.py`` by reaching branches it left
uncovered: the bulk "linked existing users, no new requests" path; the
volunteer-upgrade module-access expansion path; and the
``retry_all_failed_requests`` rate-limit filter + max-retry-cap branches.

(The multi-batch split / chaining path and the parallel batch processor are
deliberately left to the base suite's single-member happy path -- driving them
from a test transaction deadlocks on the committing BulkOperationTracker insert;
see the NOTEs in the class body.)

All tests create real Member / Volunteer / User / Account Creation Request rows
via the factory / real ``frappe.get_doc`` and run as the default Administrator
(no business-logic mocking). The ``@critical_api`` / ``@high_security_api``
decorators serialise the returned ``OperationResult`` into a nested response
dict, so the helpers below read that shape.
"""

import frappe

from verenigingen.services.member.account import account_creation_api as api
from verenigingen.tests.utils.base import VereningingenTestCase


class TestAccountCreationApiCoverage(VereningingenTestCase):
    """Cover the bulk / batch / retry branches left untouched by the base suite."""

    def setUp(self):
        super().setUp()
        self.uid = frappe.generate_hash(length=6)

    # --- response-shape helpers (mirror the base suite) -----------------------

    def _ok(self, result):
        self.assertTrue(result["success"], msg=result.get("error") or result.get("meta"))
        return result["data"]

    def _fail_msg(self, result):
        self.assertFalse(result["success"])
        return (result.get("error", {}).get("message") or "").lower()

    def _track_user(self, email):
        if email and frappe.db.exists("User", email):
            self.track_doc("User", email)

    def _make_member(self, tag, status="Active"):
        h = frappe.generate_hash(length=6)
        return self.create_test_member(
            first_name="AcctCov",
            last_name=f"{tag}{h}",
            email=f"acctcov.{tag.lower()}.{h}@test.invalid",
            status=status,
        )

    def _insert_acr(self, member, **overrides):
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

    # ===================================================== bulk: linked existing users, no requests

    def test_bulk_queue_links_existing_user_no_new_requests(self):
        """When every member already has a matching, role-bearing User, the bulk
        service LINKS them instead of creating requests; the endpoint then returns
        ok with users_linked > 0 and requests_created == 0 (the
        'Linked N existing user accounts' branch)."""
        member = self._make_member("Linked")
        # Build (via the factory) a User already carrying the Member role so no
        # completion ACR is needed, then align its first/last name with the member
        # because link_existing_user enforces name equality as a security check.
        user = self.create_test_user(member.email, roles=["Verenigingen Member"])
        self.track_doc("User", user.name)
        frappe.db.set_value(
            "User",
            user.name,
            {
                "first_name": member.first_name,
                "last_name": member.last_name,
                "user_type": "Website User",
            },
        )
        # Member must not already point at the user (force the link path).
        self.assertFalse(frappe.db.get_value("Member", member.name, "user"))

        result = api.queue_bulk_account_creation_for_members([member.name])
        data = self._ok(result)
        self.assertEqual(data["requests_created"], 0)
        self.assertGreaterEqual(data["users_linked"], 1)
        # The member is now linked to the existing user.
        self.assertEqual(frappe.db.get_value("Member", member.name, "user"), user.name)

    # NOTE: the multi-batch split / chaining path is intentionally NOT driven
    # here. queue_bulk_account_creation_for_members enqueues its first batch, which
    # under frappe.flags.in_test runs process_bulk_account_creation_batch inline;
    # that path plus BulkOperationTracker.create_tracker (a committing
    # secure_document_operation) deadlocks against the open FrappeTestCase
    # transaction on a MySQL 1205 row-lock wait. The single-member bulk happy path
    # in the base suite is the safe entry point and already covers tracker setup.

    # NOTE: process_bulk_account_creation_batch() is intentionally NOT driven
    # directly here. Its worker threads call frappe.connect()/frappe.db.close()
    # and BulkOperationTracker.create_tracker() runs a committing
    # secure_document_operation; against an open FrappeTestCase transaction this
    # deadlocks on a row-lock wait (MySQL 1205). The base suite already exercises
    # the processor once inline via test_bulk_queue_single_member_happy_path,
    # which is the safe single-request entry path.

    # ===================================================== upgrade: module-access expansion

    def test_upgrade_website_user_expands_module_access(self):
        """Upgrading a Website User to System User clears block_modules and rebuilds
        it to allow the volunteer modules (HRMS/HR) while blocking the rest -- the
        module-access expansion branch. The user keeps a desk role so the upgrade
        sticks (User.validate derives user_type from roles)."""
        member = self._make_member("Upgrade")
        email = f"acctcov.upgrade.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(email, roles=["Verenigingen Volunteer"])
        self.track_doc("User", user.name)
        frappe.db.set_value("User", user.name, "user_type", "Website User")
        frappe.db.set_value("Member", member.name, "user", user.name)

        result = api.upgrade_member_to_volunteer_user(member.name)
        data = self._ok(result)
        self.assertEqual(data["user"], user.name)
        self.assertEqual(frappe.db.get_value("User", user.name, "user_type"), "System User")
        # The expansion rebuilt block_modules to EXCLUDE HRMS / HR (allowed) and
        # include other modules. Verify HRMS is not blocked.
        blocked = frappe.get_all("Block Module", filters={"parent": user.name}, pluck="module")
        self.assertNotIn("HRMS", blocked)
        # And at least one non-allowed module IS blocked (expansion ran).
        self.assertTrue(blocked)

    # ===================================================== retry_all: rate_limit filter

    def test_retry_all_filter_rate_limit_matches_throttled(self):
        """The 'rate_limit' filter retries only failures whose reason mentions
        'throttled' / 'rate limit'. A matching failure is retried (retried >= 1)."""
        member = self._make_member("RateLimit")
        request = self._insert_acr(member)
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "User creation throttled", "retry_count": 0},
        )
        result = api.retry_all_failed_requests(failure_type="rate_limit")
        self._track_user(member.email)
        data = self._ok(result)
        self.assertGreaterEqual(data["retried"], 1)

    def test_retry_all_filter_rate_limit_excludes_nonmatching(self):
        """A failure whose reason does NOT mention throttling is filtered out by the
        rate_limit filter (retried == 0)."""
        member = self._make_member("RateLimitNo")
        request = self._insert_acr(member)
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "some unrelated error", "retry_count": 0},
        )
        result = api.retry_all_failed_requests(failure_type="rate_limit")
        data = self._ok(result)
        self.assertEqual(data["retried"], 0)

    def test_retry_all_skips_requests_at_max_retry_count(self):
        """retry_all only considers failed requests with retry_count < 3; a request
        already at the cap is excluded from the candidate set."""
        member = self._make_member("MaxRetry")
        request = self._insert_acr(member)
        frappe.db.set_value(
            "Account Creation Request",
            request.name,
            {"status": "Failed", "failure_reason": "boom", "retry_count": 3},
        )
        result = api.retry_all_failed_requests()
        data = self._ok(result)
        # Our capped request must not appear in retried set.
        retried_names = [r["name"] for r in data.get("retried_requests", [])]
        self.assertNotIn(request.name, retried_names)
