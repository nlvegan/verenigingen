"""
Tests for the app-side replacement of two Frappe CORE RPCs that leak record
existence: frappe.client.has_permission and frappe.client.get_doc_permissions
(both bare @frappe.whitelist() in frappe/client.py, reachable by any
authenticated user for ANY doctype/docname pair).

#1411 found both reachable app-wide via a real HTTP probe (test_site_11,
Frappe v16.30.0): they load the caller-supplied docname (frappe.get_lazy_doc)
before deciding permission, raising frappe.DoesNotExistError for an unknown
name while returning a value (not an exception) for a real-but-forbidden one.

The fix (verenigingen/utils/security/core_client_permission_oracle.py) is
registered via override_whitelisted_methods
(verenigingen/hooks/whitelisted_methods.py) so frappe.
override_whitelisted_method() -- consulted by frappe/handler.py,
frappe/api/v2.py, frappe/model/mapper.py and frappe/desk/treeview.py at
dispatch -- resolves the ORIGINAL frappe.client dotted paths to these
functions instead. This module tests both the dispatch wiring itself and the
functions' behaviour.

Every case here is checked for TWO non-Administrator callers: a "bare" user
with no meaningful role beyond the automatic "All", and a real
"Verenigingen Member" role-profile user -- #1411 measured both as reachable
this way.

**Third review round changed get_doc_permissions' contract**: it no longer
returns a permissions dict for a forbidden/unknown docname at all -- it
raises frappe.PermissionError identically for both, and only returns the
real dict for a document the caller can actually read (see the module
docstring's "Third review round" section for why). has_permission is
unchanged: it still returns {"has_permission": False} for both.
"""

import os
from unittest import mock

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.security.core_client_permission_oracle import (
    get_doc_permissions as safe_get_doc_permissions,
    has_permission as safe_has_permission,
)


def _make_bare_user(email):
    """A logged-in user with no meaningful role beyond the automatic "All" --
    create_test_user() can't produce this: it defaults an empty/falsy `roles`
    list to ["System Manager"], the opposite of what "bare" needs here."""
    if not frappe.db.exists("User", email):
        frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Probe",
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
    return email


class TestCoreClientPermissionOracleOverride(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.bare_user = _make_bare_user(f"core-oracle-bare-{frappe.generate_hash()[:8]}@test.invalid")
        self.track_doc("User", self.bare_user)

        self.role_user = self.create_test_user(
            f"core-oracle-role-{frappe.generate_hash()[:8]}@test.invalid",
            roles=["Verenigingen Member"],
        ).name

        # A real ToDo the outsiders above have no relationship to (owned/
        # allocated to Administrator).
        self.foreign_todo = self._create_todo(allocated_to="Administrator")

        # A real Member neither outsider owns or is linked to.
        self.foreign_member = self.create_test_member()

        # A real, ORDINARY existing User -- deliberately NOT Administrator/
        # Guest (frappe.STANDARD_USERS). User's own has_permission hook
        # (frappe/core/doctype/user/user.py:1281) denies unconditionally for
        # STANDARD_USERS only; for everyone else it permits, and the REAL
        # decision falls to the role-permission dict.
        self.foreign_other_user = _make_bare_user(
            f"core-oracle-other-{frappe.generate_hash()[:8]}@test.invalid"
        )
        self.track_doc("User", self.foreign_other_user)

        self.unknown_user_name = f"totally-fake-user-{frappe.generate_hash()[:10]}@test.invalid"
        self.unknown_todo_name = f"totally-fake-todo-{frappe.generate_hash()[:10]}"
        self.unknown_member_name = f"Totally-Fake-Member-{frappe.generate_hash()[:10]}"

    def _create_todo(self, allocated_to):
        """Fixture helper: a real ToDo allocated to `allocated_to`, tracked for cleanup."""
        todo = frappe.get_doc(
            {
                "doctype": "ToDo",
                "description": f"core-oracle-probe-todo-{frappe.generate_hash()[:8]}",
                "allocated_to": allocated_to,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("ToDo", todo.name)
        return todo

    def _create_test_login_password(self, email):
        """Set a real password for `email` and commit it.

        The commit is load-bearing, not decoration: the caller spawns a
        SEPARATE process (a fresh DB connection) that logs in as this user
        over a real WSGI request. It carries across TWO things this test's
        own transaction would otherwise keep invisible to that process: the
        password set here, and the `email` User row itself -- setUp's
        _make_bare_user() inserts it in the same (still-open) transaction, so
        without this commit the subprocess's login fails with
        AuthenticationError (no such user), not merely a stale password."""
        from frappe.utils.password import update_password

        password = f"Probe-{frappe.generate_hash()[:12]}!"
        update_password(email, password)
        frappe.db.commit()
        return password

    def _create_user_permission_scoped_user(self, role, allow, for_value):
        """Fixture helper: a user with `role` (a real DocPerm on the scoped
        doctype) plus an is_default=1 User Permission restricting `allow` to
        `for_value`. This is the FINDING A (3rd review round) shape: any
        caller scoped this way must not be able to tell an unknown docname
        of the scoped doctype apart from an OUT-of-scope existing one."""
        email = f"core-oracle-scoped-{frappe.generate_hash()[:8]}@test.invalid"
        user = self.create_test_user(email, roles=[role]).name
        permission = frappe.get_doc(
            {
                "doctype": "User Permission",
                "user": user,
                "allow": allow,
                "for_value": for_value,
                "is_default": 1,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("User Permission", permission.name)
        return user

    # ---- dispatch wiring -----------------------------------------------

    def test_override_is_registered_and_dispatch_reachable(self):
        """frappe.override_whitelisted_method (what handler.py/api/v2.py/
        mapper.py/treeview.py all call at dispatch) must resolve the two core
        RPC names to this app's replacements, and those replacements must
        themselves be whitelisted (checked the same way frappe.handler.
        execute_cmd checks it: frappe.is_whitelisted, which raises rather
        than returning False on failure)."""
        resolved_has_permission = frappe.override_whitelisted_method("frappe.client.has_permission")
        resolved_get_doc_permissions = frappe.override_whitelisted_method(
            "frappe.client.get_doc_permissions"
        )
        self.assertEqual(
            resolved_has_permission,
            "verenigingen.utils.security.core_client_permission_oracle.has_permission",
        )
        self.assertEqual(
            resolved_get_doc_permissions,
            "verenigingen.utils.security.core_client_permission_oracle.get_doc_permissions",
        )

        has_permission_fn = frappe.get_attr(resolved_has_permission)
        get_doc_permissions_fn = frappe.get_attr(resolved_get_doc_permissions)
        self.assertIs(has_permission_fn, safe_has_permission)
        self.assertIs(get_doc_permissions_fn, safe_get_doc_permissions)

        # Does not raise => dispatch-whitelisted, exactly what execute_cmd/
        # handle_rpc_call check before calling frappe.call(method, **kwargs).
        frappe.is_whitelisted(has_permission_fn)
        frappe.is_whitelisted(get_doc_permissions_fn)

        # The exact final step of frappe.handler.execute_cmd /
        # frappe.api.v2.handle_rpc_call after method resolution and the
        # is_whitelisted check above.
        with self.as_user(self.bare_user):
            result = frappe.call(
                has_permission_fn, doctype="ToDo", docname=self.unknown_todo_name, perm_type="read"
            )
        self.assertEqual(result, {"has_permission": False})

    # ---- has_permission: unknown vs existing-forbidden, per doctype ----

    def _assert_has_permission_unknown_matches_forbidden(self, user, doctype, unknown_name, forbidden_name):
        with self.as_user(user):
            unknown = safe_has_permission(doctype=doctype, docname=unknown_name, perm_type="read")
            forbidden = safe_has_permission(doctype=doctype, docname=forbidden_name, perm_type="read")
        self.assertEqual(unknown, forbidden)
        self.assertEqual(forbidden, {"has_permission": False})

    def test_has_permission_user_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_has_permission_unknown_matches_forbidden(
                    user, "User", self.unknown_user_name, "Administrator"
                )

    def test_has_permission_todo_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_has_permission_unknown_matches_forbidden(
                    user, "ToDo", self.unknown_todo_name, self.foreign_todo.name
                )

    def test_has_permission_member_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_has_permission_unknown_matches_forbidden(
                    user, "Member", self.unknown_member_name, self.foreign_member.name
                )

    # ---- get_doc_permissions: unknown vs existing-forbidden ------------
    #
    # Third review round: get_doc_permissions no longer returns a shape for a
    # forbidden/unknown docname -- it raises frappe.PermissionError
    # identically for both (and only for both: a readable/own document still
    # returns the real dict, see the "permitted caller" tests below).

    def _assert_get_doc_permissions_refuses_identically(self, user, doctype, unknown_name, forbidden_name):
        """Both names must raise the exact same frappe.PermissionError (type,
        message, and message_log state) -- not merely "both raise something".
        """
        with self.as_user(user):
            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as unknown_ctx:
                safe_get_doc_permissions(doctype=doctype, docname=unknown_name)
            unknown_log = frappe.get_message_log()

            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError) as forbidden_ctx:
                safe_get_doc_permissions(doctype=doctype, docname=forbidden_name)
            forbidden_log = frappe.get_message_log()

        self.assertEqual(str(unknown_ctx.exception), str(forbidden_ctx.exception))
        self.assertEqual(unknown_log, forbidden_log)
        self.assertEqual(unknown_log, [])

    def test_get_doc_permissions_user_doctype(self):
        """Compared against a typical (non-standard) foreign user, not
        Administrator -- see the setUp comment on self.foreign_other_user."""
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_get_doc_permissions_refuses_identically(
                    user, "User", self.unknown_user_name, self.foreign_other_user
                )

    def test_get_doc_permissions_todo_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_get_doc_permissions_refuses_identically(
                    user, "ToDo", self.unknown_todo_name, self.foreign_todo.name
                )

    def test_get_doc_permissions_member_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_get_doc_permissions_refuses_identically(
                    user, "Member", self.unknown_member_name, self.foreign_member.name
                )

    def test_get_doc_permissions_role_doctype_hookless(self):
        """"Role" (System Manager only) carries no has_permission controller
        hook at all -- unlike User/ToDo/Member, its "forbidden" comes purely
        from lacking doctype-level role permission. Required by the 3rd
        review round explicitly, to prove the refusal is uniform regardless
        of whether a hook is involved."""
        unknown_role = f"No Such Role {frappe.generate_hash()[:8]}"
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                self._assert_get_doc_permissions_refuses_identically(
                    user, "Role", unknown_role, "System Manager"
                )

    def test_get_doc_permissions_user_permission_scoped_doctype(self):
        """FINDING A (3rd review round, CRITICAL): a caller scoped by an
        is_default=1 User Permission -- Company -> Cost Center is the
        reviewer's own example and extremely common in ERPNext -- must see
        an unknown docname as indistinguishable from an OUT-of-scope
        EXISTING record, never from an IN-scope one.

        The prior (84fffff15) synthetic frappe.new_doc() approach failed
        this exact case: new_doc() -> make_new_doc ->
        set_user_and_static_default_values (frappe/model/create_new.py)
        autofills Link field defaults from the CALLER's own is_default User
        Permissions, so the fabricated "unknown" document's Company field
        silently took the caller's OWN default company -- making an unknown
        Cost Center indistinguishable from one the caller CAN read, and
        clearly different from one it cannot. This fix has no synthetic
        document at all any more, so there is nothing left to autofill.

        "_Test Company" / "_Test Company 1" are standing ERPNext fixture
        companies (shipped with every site, not created by this test), used
        here exactly as the reviewer's own probe did.
        """
        scoped_user = self._create_user_permission_scoped_user(
            role="Accounts User", allow="Company", for_value="_Test Company"
        )
        in_scope_cost_center = "_Test Company - _TC"
        out_of_scope_cost_center = "_Test Company 1 - _TC1"
        unknown_cost_center = f"Totally-Fake-Cost-Center-{frappe.generate_hash()[:8]}"

        self._assert_get_doc_permissions_refuses_identically(
            scoped_user, "Cost Center", unknown_cost_center, out_of_scope_cost_center
        )

        # No over-refusal: the in-scope record must still work.
        with self.as_user(scoped_user):
            result = safe_get_doc_permissions(doctype="Cost Center", docname=in_scope_cost_center)
        self.assertTrue(result["permissions"].get("read"))

    # ---- controls: Administrator and permitted callers are unaffected --

    def test_administrator_unknown_docname_still_raises_not_found(self):
        """Administrator keeps get_doc_permissions' existing "not found"
        experience -- there is no forbidden state to hide it behind, and
        frappe.get_lazy_doc has no Administrator short-circuit the way
        frappe.permissions.has_permission does. has_permission is different:
        core's frappe.permissions.has_permission returns True for the literal
        "Administrator" user BEFORE ever loading the document (frappe/
        permissions.py), for ANY docname including an unknown one -- a
        pre-existing core quirk, unrelated to this fix, that the wrapper must
        not touch."""
        self.assertEqual(
            safe_has_permission(doctype="User", docname=self.unknown_user_name, perm_type="read"),
            {"has_permission": True},
        )
        with self.assertRaises(frappe.DoesNotExistError):
            safe_get_doc_permissions(doctype="User", docname=self.unknown_user_name)

    def test_administrator_unknown_docname_message_preserved_not_trimmed(self):
        """get_doc_permissions' message-log trim is deliberately NOT a
        blanket `finally`: a `finally` runs even while the `except` block's
        own `raise` is propagating, which would delete the "not found"
        message frappe.get_lazy_doc queued for exactly the two callers who
        are SUPPOSED to still see it (Administrator, and an unknown
        doctype). This asserts the message survives for Administrator --
        the ordering the coordinator asked to be tested explicitly, not just
        the exception type."""
        frappe.clear_messages()
        with self.assertRaises(frappe.DoesNotExistError):
            safe_get_doc_permissions(doctype="User", docname=self.unknown_user_name)
        log = frappe.get_message_log()
        self.assertEqual(len(log), 1, log)
        self.assertIn(self.unknown_user_name, log[0]["message"])
        self.assertIn("not found", log[0]["message"])

    def test_administrator_has_permission_true_for_existing_docs(self):
        self.assertEqual(
            safe_has_permission(doctype="ToDo", docname=self.foreign_todo.name, perm_type="read"),
            {"has_permission": True},
        )

    def test_administrator_get_doc_permissions_reads_any_existing_doc(self):
        """Administrator's frappe.has_permission(doctype, "read", doc) call
        inside get_doc_permissions short-circuits to True before ever
        touching the document (frappe/permissions.py), so `readable` is
        always True for Administrator on an EXISTING doc regardless of who
        owns it -- the real permission dict, never a refusal."""
        result = safe_get_doc_permissions(doctype="ToDo", docname=self.foreign_todo.name)
        self.assertIn("permissions", result)

    def test_unknown_doctype_itself_is_not_swallowed(self):
        """This fix targets a record-existence oracle, not a DocType-existence
        one -- an invalid `doctype` must keep raising exactly as core does,
        for a non-Admin caller. (Administrator's has_permission never reaches
        DocType resolution at all -- see the quirk documented on
        test_administrator_unknown_docname_still_raises_not_found above -- so
        it is not a useful control for THIS assertion; get_doc_permissions
        still raises for Administrator too, covered by that same test.)"""
        fake_doctype = f"Not A Real Doctype {frappe.generate_hash()[:8]}"
        with self.as_user(self.bare_user):
            with self.assertRaises(frappe.DoesNotExistError):
                safe_has_permission(doctype=fake_doctype, docname="whatever", perm_type="read")

            frappe.clear_messages()
            with self.assertRaises(frappe.DoesNotExistError):
                safe_get_doc_permissions(doctype=fake_doctype, docname="whatever")
            # Same ordering guarantee as test_administrator_unknown_docname_
            # message_preserved_not_trimmed, for the OTHER re-raise branch
            # (unknown doctype rather than Administrator): the message must
            # survive, not be trimmed by the length-diff cleanup.
            log = frappe.get_message_log()
            self.assertEqual(len(log), 1, log)
            self.assertIn(fake_doctype, log[0]["message"])

    def test_permitted_caller_keeps_real_answer_for_todo(self):
        """The fix must not overcorrect: a user who genuinely owns/is
        assigned the record still gets the real (permitted) answer, not a
        forced refusal."""
        owned_todo = self._create_todo(allocated_to=self.bare_user)

        with self.as_user(self.bare_user):
            result = safe_has_permission(doctype="ToDo", docname=owned_todo.name, perm_type="read")
            perms = safe_get_doc_permissions(doctype="ToDo", docname=owned_todo.name)

        self.assertEqual(result, {"has_permission": True})
        self.assertTrue(perms["permissions"].get("read"))

    def test_permitted_caller_keeps_real_answer_for_own_member(self):
        """A Verenigingen Member reading their OWN member record must still
        see it, unaffected by the fix's unknown-docname substitution.

        "Verenigingen Member"'s Member DocPerm is if_owner-gated (measured:
        has_if_owner_enabled=True, plain read/write zeroed once if_owner
        applies), and if_owner keys off Frappe's own `owner` field, not
        Member.user -- so `db_set("owner", ...)` is required here for the
        permission system's role-permission half to grant access at all,
        on top of has_member_permission's OWN "own record" check (which does
        key off Member.user) passing at the controller-hook layer.
        """
        own_member = self.create_test_member()
        own_member.db_set("user", self.role_user)
        own_member.db_set("owner", self.role_user)

        with self.as_user(self.role_user):
            result = safe_has_permission(doctype="Member", docname=own_member.name, perm_type="read")
            perms = safe_get_doc_permissions(doctype="Member", docname=own_member.name)

        self.assertEqual(result, {"has_permission": True})
        self.assertTrue(perms["permissions"].get("read"))

    def test_permitted_caller_keeps_real_answer_for_own_user_record(self):
        """Every ordinary user can read their OWN User doctype record --
        NOT via role permissions or if_owner (measured: both are 0/disabled
        for a plain "All"-only user on this doctype), but via a DocShare
        Frappe creates automatically for a user's own record, which
        frappe.has_permission's share-fallback (`false_if_not_shared`) picks
        up and `readable` therefore reflects. Confirms get_doc_permissions'
        new read-gated design does not over-refuse this extremely common
        case: the call must return normally (no PermissionError), not raise.

        Note what this does NOT assert: that the returned dict itself shows
        read=1. frappe.permissions.get_doc_permissions (core, unmodified,
        called here exactly as core's own client.get_doc_permissions always
        has) does not consider sharing at all -- only controller hooks, role
        permissions, and User Permissions -- so it can legitimately show 0
        even for a document `readable` (and frappe.has_permission) correctly
        says the caller can see. That asymmetry is a pre-existing Frappe
        core quirk, not something this fix introduces or is responsible for
        reconciling -- this test instead checks equality with calling core's
        function directly, to confirm the fix doesn't distort the value it
        passes through.
        """
        with self.as_user(self.bare_user):
            doc = frappe.get_lazy_doc("User", self.bare_user)
            expected = frappe.permissions.get_doc_permissions(doc)
            result = safe_get_doc_permissions(doctype="User", docname=self.bare_user)
        self.assertEqual(result, {"permissions": expected})

    # ---- message-log hygiene --------------------------------------------

    def test_unknown_docname_leaves_no_message_log_entry(self):
        """frappe.get_lazy_doc's load_from_db appends "<doctype> <docname> not
        found" to frappe.local.message_log via frappe.throw BEFORE it raises
        (frappe/model/document.py) -- catching the exception does not undo
        that append. The fix captures len(frappe.message_log) before the call
        and deletes everything past that point on the substituted-unknown
        exit; this test asserts the log is empty afterwards, directly, for
        both endpoints."""
        with self.as_user(self.bare_user):
            frappe.clear_messages()
            safe_has_permission(doctype="User", docname=self.unknown_user_name, perm_type="read")
            self.assertEqual(frappe.get_message_log(), [])

            frappe.clear_messages()
            with self.assertRaises(frappe.PermissionError):
                safe_get_doc_permissions(doctype="User", docname=self.unknown_user_name)
            self.assertEqual(frappe.get_message_log(), [])

    def test_message_log_symmetric_between_existing_forbidden_and_unknown(self):
        """DEFECT 2 (2nd review round): has_permission's message-log leak was
        not fully closed by clearing only the unknown/except branch --
        residue could survive on the EXISTS path too, via a nested
        has_permission(doc.doctype) nested call whose OWN
        print_has_permission_check_logs decorator (frappe/permissions.py:43)
        used to default print_logs to True regardless of the outer call's
        intent.

        On Frappe 16.35 (this bench, verified by reading frappe/permissions.py):
        that nested call now passes print_logs=False explicitly
        (`elif has_permission(doc.doctype, print_logs=False):`), and the
        outer frappe.__init__.has_permission passes print_logs=throw down to
        it -- so THIS SPECIFIC leak no longer reproduces on stock 16.35.

        **This test's has_permission assertions (existing_log/unknown_log
        above) are therefore a REGRESSION GUARD on 16.35, NOT a red/green
        discriminator for this round.** Measured directly, both against the
        FULL 2nd-review-round implementation (parent commit 2f2bd3d09,
        clear_last_message()-only, no length-trim on the success path at
        all) and against a surgical mutation of THIS round's own
        has_permission that removes only its success-path
        `del frappe.message_log[log_len:]` (the trim added specifically
        because of this defect): existing_log and unknown_log are BOTH `[]`
        either way on this bench -- the assertions pass whether or not the
        fix is present, because the underlying core mechanism the fix
        targeted is gone on 16.35 regardless. The get_doc_permissions
        assertions below it DO still discriminate (they depend on the 3rd
        review round's raise-based contract, which neither older
        implementation has), which is why running this whole test method
        against 2f2bd3d09 or 84fffff15 still fails overall -- but not for
        the message-log reason its own name and docstring describe.

        Kept anyway: the trim is cheap and harmless, and protects against
        this class of leak if a future Frappe version (or a hook this app
        adds) ever queues a message on the success path again -- exactly
        the situation Frappe 16.30 was already in before 16.35's fix.

        "Role" (no controller hook) isolates the has_permission side of this
        from any get_doc_permissions shape/refusal question.
        """
        existing_role = "System Manager"
        unknown_role = f"No Such Role {frappe.generate_hash()[:8]}"

        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user), self.as_user(user):
                frappe.clear_messages()
                safe_has_permission(doctype="Role", docname=existing_role, perm_type="read")
                existing_log = frappe.get_message_log()

                frappe.clear_messages()
                safe_has_permission(doctype="Role", docname=unknown_role, perm_type="read")
                unknown_log = frappe.get_message_log()

                self.assertEqual(existing_log, [], "existing-forbidden has_permission leaked a message")
                self.assertEqual(unknown_log, [])

                frappe.clear_messages()
                with self.assertRaises(frappe.PermissionError):
                    safe_get_doc_permissions(doctype="Role", docname=existing_role)
                self.assertEqual(frappe.get_message_log(), [])

                frappe.clear_messages()
                with self.assertRaises(frappe.PermissionError):
                    safe_get_doc_permissions(doctype="Role", docname=unknown_role)
                self.assertEqual(frappe.get_message_log(), [])

    # ---- error propagation ------------------------------------------------

    def test_non_resumable_db_error_propagates_uncaught(self):
        """FINDING B (3rd review round): the prior (84fffff15)
        `_forbidden_doc_permissions`'s bare `except Exception: return {}`
        silently swallowed verenigingen.utils.transaction_errors.
        NON_RESUMABLE_DB_ERRORS (QueryDeadlockError, QueryTimeoutError) --
        exactly the "silent swallow, worse than log-and-return" class that
        module warns against, since a 1213/1205 rolls back the WHOLE
        transaction and the caller would continue believing it got an
        ordinary "forbidden" answer.

        This round's get_doc_permissions has no bare `except Exception`
        anywhere -- only `except frappe.DoesNotExistError` -- so there is
        nothing left that COULD catch a deadlock. Simulated by patching
        frappe.get_lazy_doc (framework infrastructure, not this app's
        business logic -- there is none left in this function to mock
        around) to raise frappe.QueryDeadlockError directly.
        """
        # Mock justified: infrastructure -- simulates a DB-level deadlock
        # raised by the framework's document loader; this fix's own logic
        # under test has no business-logic call left to substitute for.
        with mock.patch("frappe.get_lazy_doc", side_effect=frappe.QueryDeadlockError("deadlock")):
            with self.as_user(self.bare_user):
                with self.assertRaises(frappe.QueryDeadlockError):
                    safe_get_doc_permissions(doctype="User", docname=self.unknown_user_name)

    # ---- real request round trip ------------------------------------------

    def test_session_login_roleless_user_unknown_matches_forbidden_over_real_request(self):
        """A caller authenticated by SESSION COOKIE (not a direct Python call,
        and not token auth) reaches a mechanism none of the tests above do:
        frappe/app.py's outer WSGI exception handler is decorated with
        frappe.permissions.handle_does_not_exist_error, which intercepts an
        ESCAPING frappe.DoesNotExistError and calls
        frappe.permissions.check_doctype_permission(doctype) -- a DOCTYPE-level
        (no-document) permission check that IGNORES sharing. When the caller
        has no role-based permission on the doctype AT ALL (this test's
        roleless user has none on "User"), that check raises
        frappe.PermissionError, and handle_does_not_exist_error substitutes
        THAT for the original DoesNotExistError -- masking "not found" behind
        "no permission for the doctype" for whoever could never have read any
        record of it anyway.

        This fix's wrapper closes it as a side effect, not a separate branch:
        it catches the DoesNotExistError INSIDE has_permission()/
        get_doc_permissions() before it can ever escape to app.py's outer
        exception handler, so handle_does_not_exist_error's masking logic
        never runs at all for a caller who reaches this fix.

        has_permission still returns HTTP 200 for both unknown and forbidden
        (unchanged contract). get_doc_permissions is DIFFERENT as of the 3rd
        review round: both unknown and forbidden now return HTTP 403
        (frappe.PermissionError), not 200 -- the deliberate behaviour change
        documented in the module docstring.

        Run as a SUBPROCESS rather than in-process: frappe.app.application
        calls frappe.destroy()/frappe.init() per request, which would tear
        down and reinitialise frappe.local out from under this already-running
        EnhancedTestCase (its DB transaction and fixtures included). A
        subprocess keeps that entirely outside this test's own frappe.local.
        It inherits this process's PYTHONPATH, so it exercises whichever
        verenigingen is actually importable -- the worktree when run with
        PYTHONPATH set, the installed app otherwise -- exactly like every
        other test in this file.
        """
        import json
        import subprocess
        import sys
        import textwrap

        from frappe.utils import get_bench_path

        password = self._create_test_login_password(self.bare_user)

        site = frappe.local.site
        sites_dir = os.path.join(get_bench_path(), "sites")

        script = textwrap.dedent(
            f"""
            import json, uuid
            import frappe

            frappe.init(site={site!r})
            frappe.connect()
            frappe.clear_cache()
            frappe.destroy()

            import frappe.app
            from werkzeug.test import Client

            client = Client(frappe.app.application)
            headers = {{"X-Frappe-Site-Name": {site!r}}}
            login = client.post(
                "/api/method/login",
                data={{"usr": {self.bare_user!r}, "pwd": {password!r}}},
                headers=headers,
            )
            assert login.status_code == 200, login.get_data(as_text=True)
            cookie_header = "; ".join(
                c.split(";")[0] for c in login.headers.get_all("Set-Cookie")
            )

            def call(method, docname):
                url = f"/api/method/{{method}}?doctype=User&docname={{docname}}&perm_type=read"
                r = client.get(url, headers={{**headers, "Cookie": cookie_header}})
                return {{"status": r.status_code, "body": r.get_data(as_text=True)}}

            fake_1 = "totally-fake-user-" + uuid.uuid4().hex[:12]
            fake_2 = "totally-fake-user-" + uuid.uuid4().hex[:12]
            print(json.dumps({{
                "has_permission_unknown": call("frappe.client.has_permission", fake_1),
                "has_permission_forbidden": call("frappe.client.has_permission", "Administrator"),
                "get_doc_permissions_unknown": call("frappe.client.get_doc_permissions", fake_2),
                "get_doc_permissions_forbidden": call(
                    "frappe.client.get_doc_permissions", {self.foreign_other_user!r}
                ),
            }}))
            """
        )

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=sites_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])

        # has_permission: unchanged contract -- 200 both sides, identical body.
        hp_unknown = out["has_permission_unknown"]
        hp_forbidden = out["has_permission_forbidden"]
        self.assertEqual(hp_unknown["status"], 200, hp_unknown)
        self.assertEqual(hp_unknown["status"], hp_forbidden["status"])
        self.assertEqual(json.loads(hp_unknown["body"]), json.loads(hp_forbidden["body"]))
        self.assertNotIn("_server_messages", hp_unknown["body"])
        self.assertNotIn("messages", hp_unknown["body"])

        # get_doc_permissions: 3rd review round -- both now refuse with 403.
        gdp_unknown = out["get_doc_permissions_unknown"]
        gdp_forbidden = out["get_doc_permissions_forbidden"]
        self.assertEqual(gdp_unknown["status"], 403, gdp_unknown)
        self.assertEqual(gdp_unknown["status"], gdp_forbidden["status"])
        self.assertEqual(
            json.loads(gdp_unknown["body"])["exc_type"],
            json.loads(gdp_forbidden["body"])["exc_type"],
        )
        self.assertEqual(json.loads(gdp_unknown["body"])["exc_type"], "PermissionError")
