"""Public pages of the short membership application: landing, door form, confirm page, routes."""

import frappe
from frappe.website.serve import get_response
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

SUBMISSION = "Membership Application Submission"


class TestWordLidPage(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        self.template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        self.door_extra = {"annual_dues_template": self.template}
        self._previous_user = frappe.session.user
        self._previous_request = getattr(frappe.local, "request", None)
        frappe.form_dict.pop("door", None)
        # The route map is cached in Redis; a migrate or website-cache clear refreshes it in a deployment.
        frappe.cache.delete_value("website_route_rules")

    def tearDown(self):
        frappe.local.request = self._previous_request
        frappe.set_user(self._previous_user)
        frappe.form_dict.pop("door", None)
        super().tearDown()

    def _page_context(self, door=None):
        from verenigingen.www import word_lid

        frappe.form_dict.pop("door", None)
        if door:
            frappe.form_dict["door"] = door
        return word_lid.get_context(frappe._dict())

    def _page_get(self, path, **query):
        """GET a public page as Guest through the real router (route rules need a request)."""
        # Dynamic route rules are only evaluated when a request exists.
        frappe.local.request = Request(EnvironBuilder(path=f"/{path}", query_string=query).get_environ())
        frappe.set_user("Guest")  # resets form_dict, so fill it afterwards
        frappe.form_dict.update(query)
        try:
            return get_response(path)
        finally:
            frappe.set_user(self._previous_user)
            for key in query:
                frappe.form_dict.pop(key, None)

    def _render_page_html(self, slug):
        response = self._page_get(f"word-lid/{slug}")
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_landing_lists_enabled_doors_in_order(self):
        first = self._door(title="Eerste", sort_order=-20)
        second = self._door(title="Tweede", sort_order=-10)
        disabled = self._door(title="Uit", sort_order=-30, enabled=0)
        slugs = [d.slug for d in self._page_context().doors]
        self.assertLess(slugs.index(first.slug), slugs.index(second.slug))
        self.assertNotIn(disabled.slug, slugs)

    def test_unknown_or_disabled_door_is_404(self):
        disabled = self._door(enabled=0)
        for slug in (disabled.slug, "bestaat-niet"):
            with self.assertRaises(frappe.PageDoesNotExistError):
                self._page_context(slug)
        enabled = self._door()
        context = self._page_context(enabled.slug)
        self.assertEqual(context.door.name, enabled.name)
        self.assertEqual(context.hidden, set())

    def test_hidden_question_not_rendered(self):
        shown = self._door()
        hiding = self._door(hidden_questions=[{"question": "birth_year"}])
        self.assertIn('name="birth_year"', self._render_page_html(shown.slug))
        html = self._render_page_html(hiding.slug)
        self.assertNotIn('name="birth_year"', html)
        self.assertIn('name="first_name"', html)

    def test_route_rule_resolves_bevestig_before_door(self):
        rules = frappe.get_hooks("website_route_rules")
        routes = [r["from_route"] for r in rules]
        self.assertIn("/word-lid/bevestig", routes)
        self.assertIn("/word-lid/<door>", routes)
        self.assertLess(routes.index("/word-lid/bevestig"), routes.index("/word-lid/<door>"))

    def test_confirm_page_get_renders_button_and_writes_nothing(self):
        from verenigingen.api import short_application as sa
        from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token

        door = self._door()
        submission = frappe.get_doc(
            {
                "doctype": SUBMISSION,
                "door": door.name,
                "email": f"page.{frappe.generate_hash(length=8).lower()}@example.org",
                "payload": "{}",
                "status": "Unconfirmed",
            }
        ).insert()
        self.track_doc(SUBMISSION, submission.name)
        token = generate_guest_return_token(sa.CONFIRM_TOKEN_PURPOSE, submission.name)
        response = self._page_get("word-lid/bevestig", submission=submission.name, token=token)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="confirm-button"', html)
        self.assertIn(f'data-submission="{submission.name}"', html)
        self.assertEqual(frappe.db.get_value(SUBMISSION, submission.name, "status"), "Unconfirmed")
        self.assertFalse(frappe.db.get_value(SUBMISSION, submission.name, "member"))

    def test_housemate_form_asks_for_paying_member_not_payment_details(self):
        regular = self._render_page_html(self._door().slug)
        housemate = self._render_page_html(self._door(form_shape="Housemate").slug)
        self.assertIn('name="iban"', regular)
        self.assertNotIn('name="housemate_of_name"', regular)
        self.assertIn('name="housemate_of_name"', housemate)
        self.assertNotIn('name="iban"', housemate)

    def test_landing_page_renders_without_door(self):
        door = self._door(title="Landingdeur")
        response = self._page_get("word-lid")
        self.assertEqual(response.status_code, 200)
        self.assertIn(f'href="/word-lid/{door.slug}"', response.get_data(as_text=True))

    def test_door_title_is_rendered_escaped(self):
        door = self._door(title="Deur <b>x</b>")
        for html in (self._render_page_html(door.slug), self._page_get("word-lid").get_data(as_text=True)):
            self.assertNotIn("<b>x</b>", html)
            self.assertIn("&lt;b&gt;x&lt;/b&gt;", html)

    def test_editor_text_renders_as_sanitized_html(self):
        editor_value = (
            '<div class="ql-editor read-mode"><p>Hallo <b>daar</b></p><script>alert(1)</script></div>'
        )
        # Spec: both texts are Text Editor fields, so admins write HTML into them.
        meta = frappe.get_meta("Membership Application Door")
        self.assertEqual(
            [meta.get_field(f).fieldtype for f in ("card_text", "intro_text")], ["Text Editor", "Text Editor"]
        )
        door = self._door(title="Editordeur")
        # Straight to the column, as an import would: the page must not rely on save-time cleaning.
        frappe.db.set_value(
            "Membership Application Door", door.name, {"card_text": editor_value, "intro_text": editor_value}
        )
        for label, html in (
            ("landing", self._page_get("word-lid").get_data(as_text=True)),
            ("door", self._render_page_html(door.slug)),
        ):
            with self.subTest(label):
                # Booleans, not assertIn: a failure would otherwise print the whole page.
                self.assertTrue("<b>daar</b>" in html, "editor markup must render as HTML")
                self.assertFalse("&lt;div" in html, "editor markup must not be shown escaped")
                self.assertFalse("<script>alert(1)" in html, "script must be stripped")

    def test_confirm_page_sends_no_referrer(self):
        html = self._page_get("word-lid/bevestig", submission="x", token="y").get_data(as_text=True)
        self.assertIn('name="referrer" content="no-referrer"', html)

    def test_card_and_intro_text_cannot_carry_links_or_form_controls(self):
        """The card is rendered inside the door's own link, and the intro next to the application
        form: a nested link or a form posting elsewhere must not survive."""
        hostile = '<p>Tekst <a href="/elders">link</a></p><form action="//evil.example"><input name="iban"></form>'
        door = self._door(title="Vijandige deur")
        frappe.db.set_value(
            "Membership Application Door", door.name, {"card_text": hostile, "intro_text": hostile}
        )
        landing = self._page_get("word-lid").get_data(as_text=True)
        door_page = self._render_page_html(door.slug)
        self.assertTrue("Tekst" in landing and "Tekst" in door_page, "control: the texts are rendered")
        self.assertFalse('href="/elders"' in landing, "no link nested in the card's link")
        for label, html in (("landing", landing), ("door", door_page)):
            with self.subTest(label):
                self.assertFalse("evil.example" in html, "no form posting elsewhere")
