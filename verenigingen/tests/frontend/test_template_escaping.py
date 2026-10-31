"""#1890: portal page and email templates must HTML-escape user-typed values.

Frappe renders page and email templates through ``frappe.get_jenv()``, whose autoescape is
OFF, so a bare ``{{ member.full_name }}`` prints an applicant's typed name as markup.

PROBE SHORTCUT, stated per the dispatch rules: the context is built by hand (a
``frappe._dict`` standing in for what each page controller returns) and the real
``page_content`` block of the real template file is rendered; the page controllers and the
``templates/web.html`` parent are not run. The claim is therefore "this template escapes
the value it is given", not "the live page is unreachable by this payload".
"""

import json
import re

import frappe
from frappe.utils import now_datetime

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

PAYLOAD = '<img src=x onerror=alert(1)>"\''
ESCAPED_MARKER = "&lt;img src=x onerror=alert(1)&gt;"


def render_block(template_path, block, context):
    template = frappe.get_jenv().get_template(template_path)
    ctx = template.new_context(frappe._dict(context))
    return "".join(template.blocks[block](ctx))


class TestTemplateEscaping(EnhancedTestCase):
    def assert_escaped(self, html):
        self.assertNotIn("<img src=x", html, "payload printed as live markup")
        self.assertIn(ESCAPED_MARKER, html, "payload not rendered (control): the value never reached the page")

    def test_application_status_escapes_applicant_typed_name(self):
        """An applicant types full_name as a Guest; a reviewer later reads this page."""
        member = frappe._dict(
            name="M-1",
            application_id="APP-1",
            full_name=PAYLOAD,
            email=PAYLOAD,
            application_date=now_datetime(),
            application_status="Pending",
            payment_status="Unpaid",
        )
        html = render_block(
            "verenigingen/templates/pages/application_status.html", "page_content", {"member": member}
        )
        self.assert_escaped(html)
        self.assertEqual(html.count(ESCAPED_MARKER), 2, "both name and email should render escaped")

    def test_team_members_escapes_member_and_team_text(self):
        team = frappe._dict(
            name="T-1",
            team_name=PAYLOAD,
            team_type="Project",
            status="Active",
            description="<p>We write the <strong>newsletter</strong></p>",
        )
        member = frappe._dict(
            display_name=PAYLOAD,
            member_id=PAYLOAD,
            role_type="Team Member",
            role=PAYLOAD,
            status="Active",
            volunteer_name=PAYLOAD,
        )
        html = render_block(
            "verenigingen/templates/pages/team_members.html",
            "page_content",
            {"team": team, "team_members": [member], "teams": [team], "is_leader": False},
        )
        self.assert_escaped(html)
        # Team.description is a Text Editor field (sanitised on save): its markup must survive.
        self.assertIn("<strong>newsletter</strong>", html)

    def test_email_template_escapes_user_text(self):
        """Emails share the autoescape-off jenv; member_name and failure_reason are user/gateway text."""
        template = frappe.get_jenv().get_template("verenigingen/templates/emails/payment_retry_failed.html")
        html = template.render(frappe._dict(member_name=PAYLOAD, failure_reason=PAYLOAD))
        self.assert_escaped(html)
        self.assertGreaterEqual(html.count(ESCAPED_MARKER), 2)


class TestTemplateEscapingThroughRealControllers(EnhancedTestCase):
    """Render real pages end to end (get_context + web.html), as a real member user.

    The hand-built contexts above cannot see a template that is correct for a bare value
    but wrong for the value the controller really passes (a JSON string inside a
    <script>, #1890 review C1), nor a Text Editor field that must NOT be escaped.
    """

    def _member_with_user(self, label, *extra_roles):
        member = self.create_test_member(
            first_name=label,
            last_name="Escaping",
            email=f"esc-{label.lower()}-{frappe.generate_hash()[:8]}@example.com",
            birth_date="1985-06-15",
        )
        email = member.email
        if not frappe.db.exists("User", email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": label,
                    "send_welcome_email": 0,
                    "roles": [{"role": r} for r in ("Verenigingen Member", *extra_roles)],
                }
            ).insert(ignore_permissions=True)
        member.db_set("user", email)
        member.reload()
        return member, email

    def _render(self, path, user, **form):
        """Render `path` through the real website renderer as `user`.

        frappe.set_user() resets form_dict, so the query parameters are set INSIDE the
        user switch; set before it they silently vanish and the page takes its
        no-parameter branch.
        """
        from frappe.website.serve import get_response_without_exception_handling

        with self.as_user(user):
            frappe.form_dict.update(form)
            return str(get_response_without_exception_handling(path).data, "utf-8")

    def test_personal_details_inline_address_json_parses(self):
        """address_data_json inside <script> must be JSON: |e made it {&#34;city&#34;: ...}.

        Setup shortcut: the address fields are written with db.set_value on a real Address
        linked the way update_member_address links it, not through the portal endpoint.
        """
        from verenigingen.templates.pages.address_change import update_member_address

        member, user = self._member_with_user("Json")
        with self.as_user(user):
            result = update_member_address(
                {"country": "Netherlands", "address_line1": "Straat 1", "city": "'s-Hertogenbosch & Co"}
            )
        self.assertTrue(result["success"])
        self.track_doc("Address", result["address_name"])
        member.reload()

        html = self._render("personal_details", user)

        literal = re.search(r"var currentAddr = (\{.*?\});", html, re.S)
        self.assertIsNotNone(literal, "currentAddr literal not found in the rendered page")
        parsed = json.loads(literal.group(1))  # raises on the &#34; form
        self.assertEqual(parsed["city"], "'s-Hertogenbosch & Co")

    def test_team_members_keeps_description_markup_and_escapes_team_name(self):
        """Team.description (Text Editor) is rich text; team_name (Data) is escaped."""
        _member, user = self._member_with_user("Team", "Verenigingen Administrator")
        team = self.create_test_team(
            team_name="Crew & Co", description="<p>We write the <strong>newsletter</strong></p>"
        )

        html = self._render("team_members", user, team=team.name)

        self.assertIn("<strong>newsletter</strong>", html)
        self.assertIn("Crew &amp; Co", html, "Data field not escaped")
