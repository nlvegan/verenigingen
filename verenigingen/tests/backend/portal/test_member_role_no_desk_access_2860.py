"""
#2860: a member-only account must be a Website User with NO desk access.

`Verenigingen Member` shipped with desk_access=1, so Frappe's `User.set_system_user` made every
member-only account a System User. The maintainer ruling (option b): drop the member-facing
/app links, set desk_access=0 on the role fixture, and add a patch that recomputes user_type for
existing member-only users.

Probe shortcuts (declared):
* `test_site_role_row_matches_the_fixture` / the WSGI class assume the site's Role row equals the
  fixture (CI installs fixtures; a long-lived site gets it from `bench migrate`).
* The patch tests put the Role row back to the OLD value (desk_access=1) inside the test
  transaction to reproduce the pre-fix site; the users are then created through the real
  User insert, so their user_type is what Frappe really derived.
* The two page renders create the Sales Invoice / Payment Entry / Contribution Amendment Request
  rows through the real factories and render the page through `get_response_content` as the
  member.
"""

import json
import os
import re
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.backend.portal.test_page_portal_cluster import PortalPageTestBase
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ROLE = "Verenigingen Member"
APP_ROOT = frappe.get_app_path("verenigingen")


def _fixture_roles_2860():
    with open(os.path.join(APP_ROOT, "fixtures", "role.json")) as fixture:
        return {row["name"]: row for row in json.load(fixture)}


class TestMemberRoleFixture2860(EnhancedTestCase):
    def test_the_member_role_ships_without_desk_access(self):
        self.assertEqual(_fixture_roles_2860()[ROLE]["desk_access"], 0)

    def test_the_roles_that_need_the_desk_still_ship_with_it(self):
        """Control: only the member role changed. A blanket 0 would lock staff out of /app."""
        roles = _fixture_roles_2860()
        desk_roles = [name for name in roles if name not in (ROLE, "Verenigingen Webhook User")]
        self.assertGreaterEqual(len(desk_roles), 5)
        for name in desk_roles:
            with self.subTest(role=name):
                self.assertEqual(roles[name]["desk_access"], 1)

    def test_the_member_role_profile_does_not_carry_the_automatic_all_role(self):
        """The profile listed "All"; a stored Has Role "All" row has desk_access=1 on its own, so a
        profile-created member stayed a System User whatever the member role said."""
        with open(os.path.join(APP_ROOT, "fixtures", "role_profile.json")) as fixture:
            profiles = {row["name"]: [r["role"] for r in row["roles"]] for row in json.load(fixture)}
        self.assertEqual(profiles[ROLE], [ROLE])
        # Control: the profile that really is a desk profile still ships what it did.
        self.assertIn("All", profiles["Verenigingen System Administrator"])

    def test_site_member_role_profile_matches_the_fixture(self):
        self.assertEqual(
            frappe.get_all("Has Role", filters={"parent": ROLE, "parenttype": "Role Profile"}, pluck="role"),
            [ROLE],
        )

    def test_the_member_role_service_fallback_does_not_add_all(self):
        from verenigingen.services.member.account.member_role_service import get_member_role_service

        name = self._user_with_roles_2860("fallback", ["Verenigingen Staff"])
        get_member_role_service()._assign_individual_member_roles(name)
        self.assertEqual(frappe.get_all("Has Role", filters={"parent": name}, pluck="role"), [ROLE])
        self.assertEqual(frappe.db.get_value("User", name, "user_type"), "Website User")

    def test_site_role_row_matches_the_fixture(self):
        self.assertEqual(
            frappe.db.get_value("Role", ROLE, "desk_access"), _fixture_roles_2860()[ROLE]["desk_access"]
        )

    def test_a_user_made_by_the_real_member_account_flow_is_a_website_user(self):
        from verenigingen.services.member.account.member_user_account_service import (
            get_member_user_account_service,
        )

        member = self.create_test_member(
            first_name="Nodesk", last_name="Member", birth_date="1990-01-01", user=None
        )
        member.reload()
        member.db_set("user", None)
        username, action = get_member_user_account_service().create_user_for_member(
            member, send_welcome_email=False, silent=True
        )
        self.track_doc("User", username)
        self.assertEqual(action, "created_new")
        self.assertIn(ROLE, frappe.get_roles(username))
        self.assertEqual(frappe.db.get_value("User", username, "user_type"), "Website User")
        self.assertFalse(frappe.get_doc("User", username).has_desk_access())

    def test_the_next_save_does_not_flip_a_member_back_to_system_user(self):
        """Frappe recomputes a standard user_type from the roles on every save; the explicit
        user_type = "System User" in the account services is therefore overwritten. A member
        who also holds a desk role is the control: the same save keeps them System User."""
        member_only = self._user_with_roles_2860("member-only", [ROLE])
        member_staff = self._user_with_roles_2860("member-staff", [ROLE, "Verenigingen Staff"])
        for name in (member_only, member_staff):
            user = frappe.get_doc("User", name)
            user.user_type = "System User"
            user.save()
        self.assertEqual(frappe.db.get_value("User", member_only, "user_type"), "Website User")
        self.assertEqual(frappe.db.get_value("User", member_staff, "user_type"), "System User")

    def _user_with_roles_2860(self, label, roles):
        email = f"nodesk2860-{label}-{frappe.generate_hash(length=6)}@test.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Nodesk",
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        return user.name


class TestPatchRecomputesMemberUserType2860(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._old_desk_access = frappe.db.get_value("Role", ROLE, "desk_access")
        # reproduce the pre-fix site: the member role grants the desk
        frappe.db.set_value("Role", ROLE, "desk_access", 1)
        self.addCleanup(frappe.db.set_value, "Role", ROLE, "desk_access", self._old_desk_access)

    def _make(self, label, roles):
        email = f"patch2860-{label}-{frappe.generate_hash(length=6)}@test.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "Patch",
                "send_welcome_email": 0,
                "roles": [{"role": role} for role in roles],
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        return user.name

    def _user_type(self, name):
        return frappe.db.get_value("User", name, "user_type")

    def _patch(self):
        from verenigingen.patches.v2_2 import member_role_without_desk_access_2860

        return member_role_without_desk_access_2860

    def test_patch_converts_only_users_whose_desk_access_came_from_the_member_role(self):
        member_only = self._make("member-only", [ROLE])
        member_staff = self._make("member-staff", [ROLE, "Verenigingen Staff"])
        member_sysmgr = self._make("member-sysmgr", [ROLE, "System Manager"])
        staff_only = self._make("staff-only", ["Verenigingen Staff"])
        for name in (member_only, member_staff, member_sysmgr, staff_only):
            self.assertEqual(self._user_type(name), "System User", f"fixture: {name} is a desk user")

        changed = self._patch().convert_member_only_users()

        self.assertIn(member_only, changed)
        self.assertEqual(self._user_type(member_only), "Website User")
        for name in (member_staff, member_sysmgr, staff_only):
            with self.subTest(control=name):
                self.assertNotIn(name, changed)
                self.assertEqual(self._user_type(name), "System User")
        self.assertNotIn("Administrator", changed)
        self.assertEqual(self._user_type("Administrator"), "System User")

    def test_patch_sets_the_role_row_itself_because_it_runs_before_the_fixture_sync(self):
        self.assertEqual(frappe.db.get_value("Role", ROLE, "desk_access"), 1)
        self._patch().execute()
        self.assertEqual(frappe.db.get_value("Role", ROLE, "desk_access"), 0)

    def test_patch_is_idempotent(self):
        member_only = self._make("idem", [ROLE])
        self._patch().execute()
        self.assertEqual(self._user_type(member_only), "Website User")
        modified = frappe.db.get_value("User", member_only, "modified")
        self.assertEqual(self._patch().convert_member_only_users(), [])
        self._patch().execute()
        self.assertEqual(frappe.db.get_value("User", member_only, "modified"), modified)

    def test_patch_converts_a_member_whose_only_other_role_is_all_and_the_next_save_keeps_it(self):
        """The profile-created shape: [Verenigingen Member, All]. The All row is dropped, otherwise
        the next save of the account would make it a System User again (All carries desk_access)."""
        member_all = self._make("member-all", [ROLE, "All"])
        staff_all = self._make("staff-all", ["Verenigingen Staff", "All"])
        self.assertEqual(self._user_type(member_all), "System User")
        self._patch().execute()  # execute(), not the helper: it also sets the Role row the save reads
        self.assertEqual(self._user_type(member_all), "Website User")
        self.assertEqual(frappe.get_all("Has Role", filters={"parent": member_all}, pluck="role"), [ROLE])
        user = frappe.get_doc("User", member_all)
        user.save()
        self.assertEqual(self._user_type(member_all), "Website User")
        self.assertEqual(self._user_type(staff_all), "System User")
        self.assertIn("All", frappe.get_all("Has Role", filters={"parent": staff_all}, pluck="role"))

    def test_patch_removes_all_from_the_member_role_profile_row(self):
        frappe.get_doc(
            {
                "doctype": "Has Role",
                "parent": ROLE,
                "parenttype": "Role Profile",
                "parentfield": "roles",
                "role": "All",
            }
        ).db_insert()
        self.assertIn("All", frappe.get_all("Has Role", filters={"parent": ROLE, "parenttype": "Role Profile"}, pluck="role"))
        self._patch().execute()
        self.assertEqual(
            frappe.get_all("Has Role", filters={"parent": ROLE, "parenttype": "Role Profile"}, pluck="role"),
            [ROLE],
        )

    def test_patch_leaves_a_member_with_a_desk_role_granted_by_a_role_profile_alone(self):
        """The profile materialises its roles as Has Role rows; Staff via a profile is still staff."""
        email = self._make("profile-staff", [ROLE])
        user = frappe.get_doc("User", email)
        user.role_profile_name = "Verenigingen Staff"
        user.save()
        self.assertEqual(self._user_type(email), "System User")
        self.assertNotIn(email, self._patch().convert_member_only_users())
        self.assertEqual(self._user_type(email), "System User")


WSGI_SCRIPT = textwrap.dedent(
    """
    import json
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")

    from frappe.utils.password import update_password
    from verenigingen.services.member.account.member_role_service import get_member_role_service

    PW = "Pw-2860-" + frappe.generate_hash(length=8) + "!aA1"
    emails = {{}}
    out = {{}}
    try:
        def make(label, roles):
            email = f"wsgi2860-{{label}}-{{frappe.generate_hash(length=5)}}@test.invalid"
            user = frappe.get_doc({{"doctype": "User", "email": email, "first_name": "Wsgi",
                                    "send_welcome_email": 0,
                                    "roles": [{{"role": r}} for r in roles]}})
            user.insert(ignore_permissions=True)
            emails[label] = email
            return email

        member = make("member", ["Verenigingen Member"])
        # the real member role flow (role profile REPLACE), as the account services run it
        get_member_role_service().add_member_roles_to_user(member)
        make("member_staff", ["Verenigingen Member", "Verenigingen Staff"])
        make("staff", ["Verenigingen Staff"])
        for email in emails.values():
            update_password(email, PW)
        frappe.db.commit()
        out["user_types"] = {{k: frappe.db.get_value("User", v, "user_type") for k, v in emails.items()}}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client

        def get_app(label):
            client = Client(frappe.app.application)
            headers = {{"X-Frappe-Site-Name": SITE}}
            login = client.post("/api/method/login", data={{"usr": emails[label], "pwd": PW}},
                                headers=headers)
            assert login.status_code == 200, (label, login.status_code, login.get_data(as_text=True)[:300])
            resp = client.get("/desk", headers=headers, follow_redirects=True)
            body = resp.get_data(as_text=True)
            return {{"status": resp.status_code, "location": resp.headers.get("Location"),
                     "refused": "not permitted" in body.lower(), "boot": "frappe.boot" in body}}

        for label in emails:
            out["app_" + label] = get_app(label)
    finally:
        try:
            frappe.destroy()
        except Exception:
            pass
        frappe.init(site=SITE)
        frappe.connect()
        frappe.set_user("Administrator")
        for email in emails.values():
            if frappe.db.exists("User", email):
                frappe.delete_doc("User", email, force=True, ignore_permissions=True)
        frappe.db.commit()
        out["cleaned"] = not any(frappe.db.exists("User", e) for e in emails.values())
        frappe.destroy()
    print("RESULT" + json.dumps(out))
    """
)


class TestMemberHittingDeskOverRealWsgi2860(EnhancedTestCase):
    """A member logs in and requests the desk (/app, which Frappe redirects to /desk) through frappe.app.application (real dispatch).

    Run as a SUBPROCESS (frappe.app.application destroys/re-inits frappe.local per request, as in
    test_ponto_callback_wsgi). The subprocess commits its three users and deletes them in a
    `finally`; the test process commits nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        result = subprocess.run(
            [sys.executable, "-c", WSGI_SCRIPT.format(site=frappe.local.site)],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=240,
        )
        lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT")]
        assert lines, result.stdout[-3000:] + "\n" + result.stderr[-3000:]
        cls.out = json.loads(lines[-1][len("RESULT") :])

    def test_subprocess_cleaned_up(self):
        self.assertTrue(self.out["cleaned"])

    def test_the_member_is_refused_the_desk(self):
        resp = self.out["app_member"]
        self.assertEqual(self.out["user_types"]["member"], "Website User")
        self.assertEqual(resp["status"], 403, resp)
        self.assertTrue(resp["refused"], resp)

    def test_staff_still_get_the_desk(self):
        """Controls with real rows: a desk-only staff user and a member who also holds a staff role."""
        for label in ("staff", "member_staff"):
            with self.subTest(user=label):
                self.assertEqual(self.out["user_types"][label], "System User")
                self.assertEqual(self.out["app_" + label]["status"], 200, self.out["app_" + label])
                self.assertFalse(self.out["app_" + label]["refused"])


APP_HREF = re.compile(r"""(?:href|src|action)\s*=\s*["']\s*(/app(?:[/?#"'][^"']*)?)["']""", re.I)


def _app_hrefs_2860(html):
    return [m.group(1) for m in APP_HREF.finditer(html)]


class TestMemberPagesRenderNoDeskLinks2860(PortalPageTestBase):
    def _render(self, user, route):
        from frappe.website.serve import get_response_content

        with self.as_user(user):
            return get_response_content(route)

    def test_my_dues_schedule_shows_invoices_and_payments_without_desk_links(self):
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        member, user = self._make_member_with_user()
        self.create_test_membership(member_name=member.name)
        paid = self.create_test_sales_invoice(member.name)
        if paid.docstatus == 0:
            paid.submit()
        entry = get_payment_entry(paid.doctype, paid.name)
        entry.reference_no = f"TEST-{paid.name}"
        entry.reference_date = frappe.utils.today()
        entry.insert()
        entry.submit()
        self.factory.track_document("Payment Entry", entry.name, priority=6)
        due = self.create_test_sales_invoice(member.name)
        if due.docstatus == 0:
            due.submit()
        frappe.db.set_value("Sales Invoice", due.name, "due_date", frappe.utils.add_days(frappe.utils.today(), 20))

        html = self._render(user, "my_dues_schedule")

        # the rows are really on the page (the control: with the old links they carried /app hrefs)
        self.assertIn(paid.name, html)
        self.assertIn(entry.name, html)
        self.assertIn(due.name, html)
        self.assertEqual(_app_hrefs_2860(html), [])
        for desk_doctype in ("sales-invoice", "payment-entry"):
            self.assertNotIn(f"/app/{desk_doctype}/", html)

    def test_membership_adjustment_shows_a_pending_request_inline_without_a_desk_link(self):
        member, user, _mt, membership = self._member_with_active_membership_2860()
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 987.65,
                "reason": "test amendment 2860",
                "effective_date": frappe.utils.today(),
                "requested_by_member": 1,
            }
        )
        amendment.insert()
        self.track_doc("Contribution Amendment Request", amendment.name)
        # probe shortcut (declared): auto-approval may settle the request on insert; the page lists
        # only Draft / Pending Approval ones, so put this one in the state the page shows.
        frappe.db.set_value("Contribution Amendment Request", amendment.name, "status", "Pending Approval")

        html = self._render(user, "membership_adjustment")

        # the request is on the page, inline (requested amount + status), not behind a link
        self.assertIn("987.65", html)
        self.assertIn("Pending Approval", html)
        self.assertEqual(_app_hrefs_2860(html), [])
        self.assertNotIn(f"/app/contribution-amendment-request/{amendment.name}", html)

    def _member_with_active_membership_2860(self):
        member, user = self._make_member_with_user()
        mt = self.create_test_membership_type(membership_type_name="Adj2860", minimum_amount=10.0)
        membership = self.create_test_membership(member_name=member.name, membership_type_name=mt.name)
        membership.reload()
        if membership.docstatus == 0:
            membership.submit()
        if membership.status != "Active":
            membership.db_set("status", "Active")
        return member, user, mt, membership

    def test_no_member_facing_portal_source_links_into_the_desk(self):
        """Sweep ratchet over the pages a member can open. Staff-only pages (chapter_dashboard,
        mollie_*, mt940_import, e-boekhouden_*, ...) legitimately link into /app and are not listed."""
        member_pages = [
            "address_change", "application_status", "application_success", "apply_for_membership",
            "chapter_join", "contact_request", "donate", "me", "member_portal", "membership_adjustment",
            "my_addresses", "my_dues_schedule", "my_teams", "payment_plan_pay", "payment_plans",
            "payment_retry", "payment_success", "personal_details", "team_members",
        ]
        pages = os.path.join(APP_ROOT, "templates", "pages")
        scanned = 0
        offenders = []
        for page in member_pages:
            for ext in (".html", ".py"):
                path = os.path.join(pages, page + ext)
                if not os.path.exists(path):
                    continue
                scanned += 1
                with open(path) as source:
                    for number, line in enumerate(source, 1):
                        if re.search(r"""["'`(]/app(["'`/?#)]|$)""", line):
                            offenders.append(f"{page}{ext}:{number}")
        self.assertGreater(scanned, 20)
        self.assertEqual(offenders, [])

    def test_the_sweep_pattern_does_find_a_staff_page_link(self):
        """Control: the pattern the ratchet uses does match the known staff-only /app links."""
        with open(os.path.join(APP_ROOT, "templates", "pages", "chapter_dashboard.html")) as source:
            hits = [line for line in source if re.search(r"""["'`(]/app(["'`/?#)]|$)""", line)]
        self.assertTrue(hits)
