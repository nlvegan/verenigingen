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
"""

import os

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

    def _assert_get_doc_permissions_unknown_matches_forbidden(
        self, user, doctype, unknown_name, forbidden_name
    ):
        with self.as_user(user):
            unknown = safe_get_doc_permissions(doctype=doctype, docname=unknown_name)
            forbidden = safe_get_doc_permissions(doctype=doctype, docname=forbidden_name)
        self.assertEqual(unknown, forbidden)
        return forbidden

    def test_get_doc_permissions_user_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                forbidden = self._assert_get_doc_permissions_unknown_matches_forbidden(
                    user, "User", self.unknown_user_name, "Administrator"
                )
                # User and ToDo both ship a core has_permission hook, so a
                # denial always takes the controller-hook shape.
                self.assertEqual(forbidden, {"permissions": {None: 0}})

    def test_get_doc_permissions_todo_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                forbidden = self._assert_get_doc_permissions_unknown_matches_forbidden(
                    user, "ToDo", self.unknown_todo_name, self.foreign_todo.name
                )
                self.assertEqual(forbidden, {"permissions": {None: 0}})

    def test_get_doc_permissions_member_doctype(self):
        for user in (self.bare_user, self.role_user):
            with self.subTest(user=user):
                forbidden = self._assert_get_doc_permissions_unknown_matches_forbidden(
                    user, "Member", self.unknown_member_name, self.foreign_member.name
                )
                self.assertEqual(forbidden, {"permissions": {None: 0}})

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

    def test_administrator_has_permission_true_for_existing_docs(self):
        self.assertEqual(
            safe_has_permission(doctype="ToDo", docname=self.foreign_todo.name, perm_type="read"),
            {"has_permission": True},
        )

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
            with self.assertRaises(frappe.DoesNotExistError):
                safe_get_doc_permissions(doctype=fake_doctype, docname="whatever")

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

        self.assertEqual(result, {"has_permission": True})

    # ---- CHANGES-REQUIRED review round: message_log survives the catch ---

    def test_unknown_docname_leaves_no_message_log_entry(self):
        """frappe.get_lazy_doc's load_from_db appends "<doctype> <docname> not
        found" to frappe.local.message_log via frappe.throw BEFORE it raises
        (frappe/model/document.py) -- catching the exception does not undo
        that append. Confirmed over a real WSGI round trip (see
        test_session_login_roleless_user_unknown_matches_forbidden_over_real_request
        below) that an uncleared entry here reaches the HTTP response as
        _server_messages/messages, alongside the substituted (and otherwise
        correct) has_permission/permissions value -- the oracle survived one
        layer up even though the return value and status code were already
        fixed. The fix calls frappe.clear_last_message() in both except
        branches; this test asserts the log is empty afterwards, directly."""
        with self.as_user(self.bare_user):
            frappe.clear_messages()
            safe_has_permission(doctype="User", docname=self.unknown_user_name, perm_type="read")
            self.assertEqual(frappe.get_message_log(), [])

            frappe.clear_messages()
            safe_get_doc_permissions(doctype="User", docname=self.unknown_user_name)
            self.assertEqual(frappe.get_message_log(), [])

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

        Measured over a real WSGI round trip (frappe.app.application via a
        werkzeug test client, session-cookie login through POST /api/method/
        login) against UNFIXED core code (no override registered): unknown
        docname -> HTTP 403 PermissionError "User <x> does not have doctype
        access via role permission for document User"; existing-but-forbidden
        (Administrator) -> HTTP 200 {"has_permission": false}. Two different
        outcomes for the identical question, via a THIRD mechanism (neither
        DoesNotExistError-vs-value at the direct-call layer this file's other
        tests exercise, nor the message_log leak the test above covers).

        This fix's wrapper closes it as a side effect, not a separate branch:
        it catches the DoesNotExistError INSIDE has_permission()/
        get_doc_permissions() before it can ever escape to app.py's outer
        exception handler, so handle_does_not_exist_error's masking logic
        never runs at all for a caller who reaches this fix. Verified over the
        same real WSGI round trip, on this branch: unknown and
        existing-but-forbidden both return HTTP 200 with an identical body,
        for both endpoints, with no _server_messages/messages leak.

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
                "get_doc_permissions_forbidden": call("frappe.client.get_doc_permissions", "Administrator"),
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

        for endpoint in ("has_permission", "get_doc_permissions"):
            unknown = out[f"{endpoint}_unknown"]
            forbidden = out[f"{endpoint}_forbidden"]
            with self.subTest(endpoint=endpoint):
                self.assertEqual(unknown["status"], 200, unknown)
                self.assertEqual(unknown["status"], forbidden["status"])
                self.assertEqual(json.loads(unknown["body"]), json.loads(forbidden["body"]))
                self.assertNotIn("_server_messages", unknown["body"])
                self.assertNotIn("messages", unknown["body"])
