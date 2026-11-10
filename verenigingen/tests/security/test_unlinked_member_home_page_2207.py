"""#2207: the home-page routing resolves the Member STRICTLY (Member.user only) and an unlinked
logged-in user gets a readable "not linked, contact the office" outcome, never a 403.

Maintainer ruling 2026-11-08: keep #1936's strict identity; `get_member_home_page` only picks a route
(no member data), so it sits outside the strict self-service gate; `auth_hooks` resolves strictly.

Fixtures: the unlinked cases are built by clearing Member.user with db_set (the state of a legacy
record whose email matches a User) -- that IS the state under test, not a stand-in for a flow. Callers
are plain "Verenigingen Member" users (no blanket doctype access), not Administrator.
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path
from frappe.utils.password import update_password

from verenigingen import auth_hooks
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.member_utils import get_not_linked_message


class TestUnlinkedMemberHomePage2207(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.linked = self._user_and_member(linked=True)
        self.email_only = self._user_and_member(linked=False)
        self.no_member = self._user_without_member()

    def _user_and_member(self, linked):
        email = f"hp2207-{frappe.generate_hash()[:8]}@example.com"
        member = self.create_test_member(
            first_name="Hp", last_name="Link" if linked else "Email", email=email, birth_date="1990-01-01"
        )
        member.db_set("status", "Active")
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        member.db_set("user", email if linked else None)
        return email

    def _user_without_member(self):
        email = f"hp2207-none-{frappe.generate_hash()[:8]}@example.com"
        self.create_test_user_with_roles(email=email, roles=["Verenigingen Member"])
        self.assertFalse(frappe.db.exists("Member", {"email": email}))
        return email

    def _create_login_password(self, *emails):
        """Set a real password and COMMIT: the WSGI probe is a separate process with its own DB
        connection and cannot see this transaction's users otherwise (same as #core_client oracle)."""
        password = f"Probe-{frappe.generate_hash()[:12]}!"
        for email in emails:
            update_password(email, password)
        frappe.db.commit()
        return password

    # ---- routing, driven as the real users ----

    def test_linked_member_still_routes_to_member_portal(self):
        with self.as_user(self.linked):
            self.assertEqual(auth_hooks.get_member_home_page(), "/member_portal")
            self.assertEqual(auth_hooks.get_default_home_page(self.linked), "/member_portal")

    def test_email_only_user_without_member_role_is_not_routed_as_a_member(self):
        """Strict resolution: a bare email match is not a membership. The user holds NO member role,
        so only the (lenient on develop) Member lookup could send them to the portal."""
        email = self.email_only
        frappe.get_doc("User", email).remove_roles("Verenigingen Member")
        self.assertNotEqual(auth_hooks.get_default_home_page(email), "/member_portal")

    def test_member_role_user_with_no_member_is_not_refused(self):
        with self.as_user(self.no_member):
            route = auth_hooks.get_member_home_page()  # develop: PermissionError from the gate
        self.assertEqual(route, "/member_portal")  # the portal renders the not-linked banner

    def test_guest_is_still_refused(self):
        with self.as_user("Guest"):
            with self.assertRaises(frappe.PermissionError):
                auth_hooks.get_member_home_page()

    def test_guest_default_home_page_is_unchanged(self):
        self.assertEqual(auth_hooks.get_default_home_page("Guest"), "/web")

    def test_portal_no_member_banners_say_not_linked_never_member_record_not_found(self):
        """The pages an unlinked user can still reach (bookmark, direct URL) use the same sentence."""
        from verenigingen.templates.pages import contact_request, member_portal
        from verenigingen.utils.member_portal_utils import setup_portal_context

        with self.as_user(self.no_member):
            for label, ctx in (
                ("setup_portal_context", self._ctx(lambda c: setup_portal_context(c, "My Addresses"))),
                ("member_portal", self._ctx(member_portal.get_context)),
                ("contact_request", self._ctx(contact_request.get_context)),
            ):
                self.assertTrue(ctx.get("no_member_record"), label)
                self.assertEqual(ctx.error_message, get_not_linked_message(), label)
                self.assertNotIn("Member Record Not Found", ctx.error_title, label)

    def _ctx(self, fn):
        context = frappe._dict()
        fn(context)
        return context

    # ---- real WSGI requests ----

    PAGES = (
        "/member_portal",
        "/address_change",
        "/payment_dashboard",
        "/my_teams",
        "/team_members",
        "/manage_donations",
        "/membership_adjustment",
    )

    def _wsgi(self, users, paths):
        """Log in as each user over a real WSGI request (separate process, own connection) and GET
        each path. Returns {user: {"login": {...}, "endpoint": {...}, path: {status, body}}}."""
        password = self._create_login_password(*[u for u in users if u])
        site = frappe.local.site
        script = textwrap.dedent(
            f"""
            import json
            import frappe

            frappe.init(site={site!r})
            frappe.connect()
            frappe.clear_cache()
            frappe.destroy()

            import frappe.app
            from werkzeug.test import Client

            headers = {{"X-Frappe-Site-Name": {site!r}}}
            endpoint = "/api/method/verenigingen.auth_hooks.get_member_home_page"

            def run(user):
                client = Client(frappe.app.application)
                out = {{}}
                h = dict(headers)
                if user:
                    login = client.post("/api/method/login", data={{"usr": user, "pwd": {password!r}}},
                                        headers=headers)
                    assert login.status_code == 200, login.get_data(as_text=True)
                    out["login"] = json.loads(login.get_data(as_text=True))
                    h["Cookie"] = "; ".join(c.split(";")[0] for c in login.headers.get_all("Set-Cookie"))
                for key, path in [("endpoint", endpoint)] + [(p, p) for p in {list(paths)!r}]:
                    r = client.get(path, headers=h)
                    out[key] = {{"status": r.status_code, "body": r.get_data(as_text=True)}}
                return out

            print(json.dumps({{(u or "Guest"): run(u) for u in {list(users)!r}}}))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def _assert_readable_not_linked_pages(self, out):
        for path in self.PAGES:
            with self.subTest(page=path):
                page = out[path]
                self.assertEqual(page["status"], 200, f"{path}: {page['body'][:300]}")
                self.assertIn(get_not_linked_message(), page["body"])
                for bad in ("Traceback", "UndefinedError", "Member Record Not Found"):
                    self.assertNotIn(bad, page["body"])

    def test_wsgi_home_page_endpoint_is_200_for_unlinked_users_and_refuses_guest(self):
        out = self._wsgi([self.linked, self.email_only, self.no_member, None], ())
        for user in (self.linked, self.email_only, self.no_member):
            self.assertEqual(out[user]["endpoint"]["status"], 200, out[user]["endpoint"])
            self.assertEqual(json.loads(out[user]["endpoint"]["body"])["message"], "/member_portal", user)
            self.assertNotIn("exc", json.loads(out[user]["endpoint"]["body"]), user)
        self.assertEqual(out["Guest"]["endpoint"]["status"], 403, out["Guest"]["endpoint"])

    def test_wsgi_login_lands_a_user_with_no_member_on_a_readable_portal(self):
        """The REAL login outcome (the on_session_creation hook is not registered): Frappe returns
        home_page member_portal, and that page and its portal siblings say 'not linked'."""
        out = self._wsgi([self.no_member], self.PAGES)[self.no_member]
        self.assertEqual(out["login"]["home_page"], "member_portal")
        self._assert_readable_not_linked_pages(out)

    def test_wsgi_pages_for_an_email_only_user_are_readable(self):
        """Needs #1936's strict Member lookup (PR #2216): on develop without it the email match still
        finds the Member, so the real pages render."""
        out = self._wsgi([self.email_only], self.PAGES)[self.email_only]
        self._assert_readable_not_linked_pages(out)

    # A marker that appears ONLY inside each template's `{% if not no_member_record %}` block (the
    # <title>/head blocks carry shorter strings), so an always-false guard hides it.
    CONTENT_MARKERS = {
        "/address_change": "Update Your Address",
        "/payment_dashboard": "min-h-screen bg-gradient-to-br from-gray-50",
        "/my_teams": "View and manage your team memberships",
        "/team_members": "Choose a team to view its members",
        "/manage_donations": "Manage Your Donations",
        "/membership_adjustment": "Adjust Your Membership",
    }

    def test_wsgi_linked_member_still_sees_the_page_content(self):
        """Control: the guards must hide the page only from an unlinked account. A linked, Active
        member with an active membership (membership_adjustment needs one, else it 404s) gets the
        real content and no banner."""
        member_name = frappe.db.get_value("Member", {"user": self.linked}, "name")
        self.create_test_membership(member_name=member_name)
        out = self._wsgi([self.linked], tuple(self.CONTENT_MARKERS))[self.linked]
        for path, marker in self.CONTENT_MARKERS.items():
            with self.subTest(page=path):
                page = out[path]
                self.assertEqual(page["status"], 200, f"{path}: {page['body'][:300]}")
                self.assertNotIn(get_not_linked_message(), page["body"])
                self.assertIn(marker, page["body"])
