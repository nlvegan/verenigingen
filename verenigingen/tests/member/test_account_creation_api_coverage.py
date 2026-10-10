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

from contextlib import contextmanager
from unittest.mock import patch

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


class TestRequestableVolunteerRoles(VereningingenTestCase):
    """The Activate Volunteer dialog's "Additional Roles" options.

    It used to offer two hardcoded names ("Volunteer Team Member" / "Volunteer
    Team Leader") that are not Roles at all, so picking one failed the request.
    Board and team roles are granted only through the chapter or team itself,
    so they are never offered here either.
    """

    # Never offered: automatic or system-level roles, and the base role the
    # dialog always adds.
    NEVER_OFFERED = {"Administrator", "Guest", "All", "Desk User", "System Manager", "Verenigingen Volunteer"}

    def _profile_roles(self, *profiles):
        return set(
            frappe.get_all(
                "Has Role", filters={"parenttype": "Role Profile", "parent": ["in", profiles]}, pluck="role"
            )
        )

    def _position_and_volunteer_roles(self):
        """Roles the board / team leader / national board profiles grant, plus the
        base volunteer profile's (activation grants those already)."""
        return self._profile_roles(
            "Verenigingen Chapter Board Member",
            "Verenigingen Team Leader",
            "Verenigingen National Board Member",
            "Verenigingen Treasurer",
            "Verenigingen Volunteer",
        )

    def _deskless_roles(self):
        return set(frappe.get_all("Role", filters={"desk_access": 0}, pluck="name"))

    def _user_with_profile(self, role_profile):
        """A user whose roles come from a real Role Profile, as an activator's do."""
        email = f"req-roles-{frappe.generate_hash(length=8)}@example.com"
        user = self.create_test_user(email)
        user.append("role_profiles", {"role_profile": role_profile})
        user.save(ignore_permissions=True)
        return user.name

    def test_administrator_is_offered_real_roles_only(self):
        roles = api.get_requestable_volunteer_roles()

        self.assertIn("Verenigingen Auditor", roles)
        self.assertNotIn("Volunteer Team Member", roles)
        self.assertNotIn("Volunteer Team Leader", roles)
        self.assertFalse(self.NEVER_OFFERED & set(roles), roles)
        for role in roles:
            self.assertFalse(frappe.db.get_value("Role", role, "disabled"), role)

    def test_board_team_and_base_volunteer_roles_are_never_offered(self):
        excluded = self._position_and_volunteer_roles()
        # Control: the fixture really carries the roles this test is about.
        self.assertTrue(
            {"Verenigingen Chapter Board Member", "Expense Approver", "Employee"} <= excluded, excluded
        )

        roles = api.get_requestable_volunteer_roles()

        self.assertTrue(roles)
        self.assertFalse(excluded & set(roles), excluded & set(roles))

    def test_national_board_and_treasurer_roles_are_never_offered(self):
        """Granted only by a seat on the national chapter's board, never from here."""
        national = self._profile_roles("Verenigingen National Board Member", "Verenigingen Treasurer")
        self.assertTrue(
            {"Verenigingen National Board Member", "Verenigingen Treasurer"} <= national, national
        )

        roles = api.get_requestable_volunteer_roles()

        self.assertTrue(roles)
        self.assertFalse(national & set(roles), national & set(roles))

    def test_roles_without_desk_access_are_never_offered(self):
        deskless = self._deskless_roles()
        # Control: a service role really sits in a Verenigingen profile.
        self.assertIn("Verenigingen Webhook User", deskless)
        self.assertIn("Verenigingen Webhook User", self._profile_roles("Verenigingen Webhook User"))

        roles = api.get_requestable_volunteer_roles()

        self.assertTrue(roles)
        self.assertFalse(deskless & set(roles), deskless & set(roles))

    def test_a_profile_mapped_onto_a_chapter_stops_being_offered(self):
        self.assertIn("Verenigingen Auditor", api.get_requestable_volunteer_roles())
        chapter = self.create_test_chapter()
        # Board configuration, not a flow state: this is how an admin maps it.
        frappe.db.set_value(
            "Chapter", chapter.name, "default_board_role_profile", "Verenigingen Auditor", update_modified=False
        )

        roles = api.get_requestable_volunteer_roles()

        self.assertNotIn("Verenigingen Auditor", roles)
        self.assertTrue(roles)

    def test_offer_does_not_exceed_the_activating_users_own_roles(self):
        user = self._user_with_profile("Verenigingen Administrator")
        # What the user actually holds, which is not the whole profile: ERPNext
        # drops "Employee" from a user with no Employee record.
        held = self._profile_roles("Verenigingen Administrator") & set(frappe.get_roles(user))

        with self.as_user(user):
            roles = api.get_requestable_volunteer_roles()

        self.assertTrue(roles)
        self.assertEqual(
            set(roles),
            held - self.NEVER_OFFERED - self._position_and_volunteer_roles() - self._deskless_roles(),
        )
        # Offered to Administrator, but not part of this user's profile.
        self.assertNotIn("Verenigingen Auditor", roles)

    def test_user_who_cannot_create_users_is_offered_nothing(self):
        user = self._user_with_profile("Verenigingen Staff")

        with self.as_user(user):
            self.assertFalse(frappe.has_permission("User", "create"))
            roles = api.get_requestable_volunteer_roles()

        self.assertEqual(roles, [])

    def test_non_system_manager_with_user_create_is_offered_only_what_the_acr_accepts(self):
        """Only System Manager creates Users on a stock site, so the ACR's own role
        gates are otherwise unreachable here. Grant User create to Staff to reach them.
        Of the Staff profile's roles only "Support Team" survives the position-profile
        exclusion ("Verenigingen Staff" sits in the national board profiles), so this
        exercises the gates through "Support Team", which the ACR does not let a
        non-System Manager request."""
        user = self._user_with_profile("Verenigingen Staff")
        self.assertTrue({"Support Team", "Verenigingen Staff"} <= set(frappe.get_roles(user)))

        with self._user_create_granted("Verenigingen Staff"), self.as_user(user):
            self.assertTrue(frappe.has_permission("User", "create"))
            roles = api.get_requestable_volunteer_roles()

        self.assertEqual(roles, [])

    @contextmanager
    def _user_create_granted(self, role):
        """Grant User read+create to ``role`` via a transaction-scoped Custom DocPerm,
        and pin ``frappe.get_meta("User")`` to a Meta built here. Same reasoning as
        test_payment_entry_creation_service._payment_entry_create_granted: the shared
        meta cache can be rebuilt without an uncommitted grant."""
        from frappe.model.meta import load_meta
        from frappe.permissions import add_permission, update_permission_property

        add_permission("User", role, 0)
        update_permission_property("User", role, 0, "create", 1)
        meta = load_meta("User")
        self.assertTrue([p for p in meta.permissions if p.role == role and p.get("create")])

        real_get_meta = frappe.get_meta

        def pinned_get_meta(doctype, *args, **kwargs):
            if doctype == "User":
                return meta
            return real_get_meta(doctype, *args, **kwargs)

        with patch("frappe.get_meta", pinned_get_meta):
            yield
