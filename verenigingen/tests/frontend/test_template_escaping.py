"""#1890: portal page and email templates must HTML-escape user-typed values.

Frappe renders page and email templates through ``frappe.get_jenv()``, whose autoescape is
OFF, so a bare ``{{ member.full_name }}`` prints an applicant's typed name as markup.

PROBE SHORTCUT, stated per the dispatch rules: the context is built by hand (a
``frappe._dict`` standing in for what each page controller returns) and the real
``page_content`` block of the real template file is rendered; the page controllers and the
``templates/web.html`` parent are not run. The claim is therefore "this template escapes
the value it is given", not "the live page is unreachable by this payload".
"""

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
            name="T-1", team_name=PAYLOAD, team_type="Project", status="Active", description=PAYLOAD
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

    def test_email_template_escapes_user_text(self):
        """Emails share the autoescape-off jenv; member_name and failure_reason are user/gateway text."""
        template = frappe.get_jenv().get_template("verenigingen/templates/emails/payment_retry_failed.html")
        html = template.render(frappe._dict(member_name=PAYLOAD, failure_reason=PAYLOAD))
        self.assert_escaped(html)
        self.assertGreaterEqual(html.count(ESCAPED_MARKER), 2)
