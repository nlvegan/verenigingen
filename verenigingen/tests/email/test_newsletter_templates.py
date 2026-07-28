#!/usr/bin/env python3
"""
Tests for verenigingen.email.newsletter_templates.

NewsletterTemplateManager turns admin-supplied variables into the HTML that goes
out to members, so the two things that matter are:

  * what reaches the recipient (no leftover placeholders, no fabricated text), and
  * what an admin can smuggle into it (the sanitiser).

The existing tests/email/test_email_template_xss_protection.py covers the Jinja
`Email Template` DocType records; this file covers the separate, hard-coded
Python template catalogue in newsletter_templates.py, which that file never
touches.

Nothing here sends: the send path is exercised only through the guards that must
reject before reaching the mailer.
"""

import json
import re
import unittest

from verenigingen.email.newsletter_templates import (
    NewsletterTemplateManager,
    get_newsletter_templates,
    get_template_details,
    preview_template,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ALL_TEMPLATE_IDS = {
    "monthly_update",
    "event_announcement",
    "welcome_new_members",
    "volunteer_recruitment",
    "agm_invitation",
    "fundraising_campaign",
}


class TestTemplateCatalogue(EnhancedTestCase):
    """The catalogue an admin picks from."""

    def setUp(self):
        super().setUp()
        self.manager = NewsletterTemplateManager()

    def test_all_templates_are_listed_with_id_name_and_category(self):
        listed = self.manager.list_templates()

        self.assertEqual({t["id"] for t in listed}, ALL_TEMPLATE_IDS)
        for entry in listed:
            with self.subTest(template=entry["id"]):
                self.assertTrue(entry["name"])
                self.assertTrue(entry["category"])

    def test_category_filter_returns_only_that_category(self):
        events = self.manager.list_templates("Events")

        self.assertEqual({t["id"] for t in events}, {"event_announcement"})

    def test_unknown_category_returns_an_empty_list_not_everything(self):
        self.assertEqual(self.manager.list_templates("Nonexistent Category"), [])

    def test_advertised_categories_match_the_templates_that_exist(self):
        """The endpoint hardcodes a category list; a drift leaves an empty tab."""
        advertised = set(get_newsletter_templates()["categories"])
        actual = {t["category"] for t in self.manager.list_templates()}

        self.assertEqual(advertised, actual)

    def test_unknown_template_id_is_reported_rather_than_defaulting(self):
        self.assertIsNone(self.manager.get_template("no_such_template"))

        result = get_template_details("no_such_template")
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Template not found")


class TestTemplateRendering(EnhancedTestCase):
    """render_template() - what the member actually receives."""

    def setUp(self):
        super().setUp()
        self.manager = NewsletterTemplateManager()

    def _full_event_variables(self):
        return {
            "event_title": "Spring Potluck",
            "event_date": "12 April",
            "event_location": "Utrecht",
            "event_description": "Bring a dish",
            "registration_link": "https://example.org/register",
        }

    def test_unknown_template_renders_nothing(self):
        self.assertIsNone(self.manager.render_template("no_such_template", {}))

    def test_subject_and_content_are_both_substituted(self):
        rendered = self.manager.render_template("event_announcement", self._full_event_variables())

        self.assertEqual(rendered["subject"], "Join us: Spring Potluck - 12 April")
        self.assertIn("Spring Potluck", rendered["content"])
        self.assertIn("Utrecht", rendered["content"])
        self.assertIn("https://example.org/register", rendered["content"])
        self.assertEqual(rendered["template_name"], "Event Announcement")

    def test_no_declared_placeholder_survives_a_fully_populated_render(self):
        """A leftover '{event_date}' in a sent email is a visible defect."""
        rendered = self.manager.render_template("event_announcement", self._full_event_variables())

        for variable in self._full_event_variables():
            with self.subTest(variable=variable):
                self.assertNotIn(f"{{{variable}}}", rendered["content"])
                self.assertNotIn(f"{{{variable}}}", rendered["subject"])

    def test_missing_variables_do_not_raise_and_are_stripped_from_the_subject(self):
        """Partial input must degrade gracefully, not explode mid-campaign."""
        rendered = self.manager.render_template("event_announcement", {"event_title": "Potluck"})

        self.assertIn("Potluck", rendered["subject"])
        self.assertNotIn("{event_date}", rendered["subject"])

    def test_numeric_and_none_values_are_accepted(self):
        rendered = self.manager.render_template(
            "fundraising_campaign",
            {"campaign_title": "Winter drive", "current_amount": 1500, "campaign_goal": None},
        )

        self.assertIn("1500", rendered["content"])
        self.assertIn("Winter drive", rendered["subject"])


class TestTemplateSanitisation(EnhancedTestCase):
    """_sanitize_template_value() is the only barrier between admin input and the recipient."""

    def setUp(self):
        super().setUp()
        self.manager = NewsletterTemplateManager()

    def test_html_tags_in_a_value_are_escaped_not_rendered(self):
        rendered = self.manager.render_template(
            "welcome_new_members",
            {"chapter_name": "Utrecht", "new_member_names": "<script>alert(1)</script>"},
        )

        self.assertNotIn("<script>", rendered["content"])
        self.assertIn("&lt;script&gt;", rendered["content"])

    def test_quotes_are_escaped_so_a_value_cannot_break_out_of_an_attribute(self):
        rendered = self.manager.render_template(
            "event_announcement", {"registration_link": '" onmouseover="alert(1)'}
        )

        self.assertNotIn('" onmouseover="', rendered["content"])
        self.assertIn("&quot;", rendered["content"])

    def test_lowercase_javascript_url_is_neutralised(self):
        rendered = self.manager.render_template(
            "event_announcement", {"registration_link": "javascript:alert(1)"}
        )

        self.assertNotIn("javascript:alert", rendered["content"])
        self.assertIn("javascript-blocked:", rendered["content"])

    @unittest.expectedFailure
    def test_mixed_case_javascript_url_is_neutralised(self):
        """EXPECTED FAILURE - PRODUCT BUG: the sanitiser is case-blind by two cases only.

        newsletter_templates.py:447-450 neutralises each dangerous pattern by
        doing `sanitized.replace(pattern.lower(), ...)` and
        `sanitized.replace(pattern.upper(), ...)`. Only all-lower and all-UPPER
        spellings are matched, so `JaVaScRiPt:` passes straight through into
        `<a href="{registration_link}">` (line 160). html.escape() does not help:
        the payload contains no characters it escapes.

        A case-insensitive scheme check (re.sub with re.IGNORECASE, or better a
        scheme allow-list of http/https/mailto) is the fix.
        """
        rendered = self.manager.render_template(
            "event_announcement", {"registration_link": "JaVaScRiPt:alert(1)"}
        )

        self.assertNotIn("JaVaScRiPt:alert", rendered["content"])

    @unittest.expectedFailure
    def test_data_url_is_neutralised(self):
        """EXPECTED FAILURE - PRODUCT BUG: `data:` is missing from the block list.

        The dangerous_patterns list (newsletter_templates.py:437-445) covers
        javascript:/vbscript: but not data:, so a data: URL reaches the href of
        the "Register Now" / "Donate Now" call-to-action untouched.
        """
        rendered = self.manager.render_template(
            "event_announcement", {"registration_link": "data:text/html;base64,PHNjcmlwdD4="}
        )

        self.assertNotIn("data:text/html", rendered["content"])


class TestUnsubstitutedPlaceholdersReachTheRecipient(EnhancedTestCase):
    """PRODUCT BUGS: raw '{placeholder}' text can be mailed to members.

    render_template() (newsletter_templates.py:412-417) substitutes the CONTENT
    by plain string replacement, one supplied variable at a time. Unlike the
    subject path - which strips leftovers with `re.sub(r"\\{[^}]+\\}", "", ...)`
    at line 410 - nothing removes placeholders the caller did not supply. Two
    ways that reaches a member:

      1. a caller supplies only some variables (the automated-campaign content
         generators deliberately default to EMPTY STRING, but a hand-built call
         via preview_template/send_templated_email need not), and

      2. two templates contain placeholders that are NOT in their declared
         `variables` list at all, so an admin UI driven by that list can never
         supply them:
           - volunteer_recruitment declares 4 variables but its content also uses
             `{contact_email}` (line 253, inside `mailto:`)
           - fundraising_campaign never declares `{progress_percentage}`
             (line 330, inside a CSS width)
    """

    def setUp(self):
        super().setUp()
        self.manager = NewsletterTemplateManager()

    @unittest.expectedFailure
    def test_unsupplied_placeholders_are_stripped_from_the_content(self):
        """EXPECTED FAILURE - product bug 1, see class docstring."""
        rendered = self.manager.render_template("event_announcement", {"event_title": "Potluck"})

        self.assertNotIn("{event_date}", rendered["content"])

    @unittest.expectedFailure
    def test_every_placeholder_in_a_template_is_a_declared_variable(self):
        """EXPECTED FAILURE - product bug 2, see class docstring."""
        undeclared = {}
        for template_id, template in self.manager.templates.items():
            declared = set(template["variables"])
            used = set(
                re.findall(
                    r"\{([a-z_][a-z0-9_]*)\}", template["content_template"] + template["subject_template"]
                )
            )
            missing = used - declared
            if missing:
                undeclared[template_id] = sorted(missing)

        self.assertEqual(undeclared, {}, f"placeholders with no declared variable: {undeclared}")


class TestPreviewAndSendGuards(EnhancedTestCase):
    """The whitelisted entrypoints must fail closed before touching the mailer."""

    def test_preview_rejects_malformed_variables_json(self):
        result = preview_template("event_announcement", "{not valid json")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid variables JSON")

    def test_preview_rejects_an_unknown_template(self):
        result = preview_template("no_such_template", json.dumps({}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Template not found")

    def test_preview_returns_the_rendered_subject_and_content(self):
        result = preview_template(
            "welcome_new_members", json.dumps({"chapter_name": "Utrecht", "new_member_names": "Ada"})
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["preview"]["subject"], "Welcome to Utrecht!")
        self.assertIn("Ada", result["preview"]["content"])

    def test_send_stops_at_an_unknown_template_before_selecting_recipients(self):
        """An unknown template must not fall through to a full-membership send."""
        from verenigingen.email.newsletter_templates import send_templated_email

        result = send_templated_email("no_such_template", json.dumps({}))

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Template not found")

    def test_send_rejects_malformed_variables_json(self):
        from verenigingen.email.newsletter_templates import send_templated_email

        result = send_templated_email("event_announcement", "{not valid json")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid variables JSON")
