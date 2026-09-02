#!/usr/bin/env python3
"""
Tests for verenigingen.email.automated_campaigns, with emphasis on the DAILY
SCHEDULED ENTRYPOINT.

`verenigingen.email.automated_campaigns.process_scheduled_campaigns` is wired
into the scheduler at verenigingen/hooks/scheduler.py:27. A scheduled job has no
user watching it: if it raises, the failure lands in a log nobody reads; if it
sends, it sends to real members. So the entrypoint is exercised the way the
scheduler exercises it - resolved from its dotted path, against real Email
Campaign rows in the database - and the tests assert BOTH halves of the
contract:

  1. it completes without raising and without writing an Error Log, and
  2. it sends nothing (no Email Queue row, no Newsletter, no Communication).

Per the module docstring, automated campaigns are a deliberate no-op today: the
custom fields the feature needs (`campaign_type` / `template_id` /
`content_config` / `chapter` / `segment`) were never added to the standard
ERPNext Email Campaign DocType. "Safe no-op" is a real, load-bearing property -
the previous behaviour was a KeyError plus an Error Log for every due campaign -
so these tests pin exactly that, and would fail if the job started blasting mail
or started erroring again.
"""

import json
import unittest
from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, now_datetime, today

from verenigingen.email.automated_campaigns import (
    AutomatedCampaignManager,
    get_campaign_types,
    process_scheduled_campaigns,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

SCHEDULER_PATH = "verenigingen.email.automated_campaigns.process_scheduled_campaigns"


class EmailCampaignFixtureMixin:
    """Builds real ERPNext Email Campaign rows (Campaign + schedule + recipient)."""

    def _make_campaign_definition(self, tag):
        template = self.create_test_email_template(
            name=f"campaign_{tag}_{self.uid}",
            subject="Campaign fixture subject",
            response_html="<p>fixture</p>",
        )
        campaign = frappe.get_doc(
            {
                "doctype": "Campaign",
                "campaign_name": f"Camp {tag} {self.uid}",
                "campaign_schedules": [{"send_after_days": 1, "email_template": template.name}],
            }
        )
        campaign.insert()
        self.track_doc("Campaign", campaign.name)
        return campaign

    def _make_email_group(self, tag):
        group = frappe.get_doc({"doctype": "Email Group", "title": f"Camp Group {tag} {self.uid}"})
        group.insert()
        self.track_doc("Email Group", group.name)
        return group

    def _make_email_campaign(self, tag, start_date=None):
        """An Email Campaign the scheduler's query can actually pick up."""
        campaign = self._make_campaign_definition(tag)
        group = self._make_email_group(tag)
        email_campaign = frappe.get_doc(
            {
                "doctype": "Email Campaign",
                "campaign_name": campaign.name,
                "email_campaign_for": "Email Group",
                "recipient": group.name,
                "start_date": start_date or today(),
                "sender": "Administrator",
            }
        )
        email_campaign.insert()
        self.track_doc("Email Campaign", email_campaign.name)
        # `campaign_name` is the Campaign LINK, and that is what the scheduler
        # reports in processed/skipped/errors - keep it for the assertions.
        email_campaign.reload()
        return email_campaign

    # NOTE: "Newsletter" is deliberately absent - that DocType does not exist on
    # Frappe v16 (it was extracted into a separate `newsletter` app that is not
    # installed on this bench), which is itself a live defect in the email module;
    # see test_simplified_email_manager.TestNewsletterDoctypeIsMissing.
    OUTBOUND_DOCTYPES = ("Email Queue", "Communication")

    def _outbound_counts(self):
        return {doctype: frappe.db.count(doctype) for doctype in self.OUTBOUND_DOCTYPES}

    def assertNothingWasSent(self, before, after):
        for doctype, count in before.items():
            self.assertEqual(
                after[doctype],
                count,
                f"the scheduled campaign job created {after[doctype] - count} new {doctype} row(s); "
                "it must not send mail while the feature is an unbuilt no-op",
            )


class TestScheduledCampaignEntrypoint(EmailCampaignFixtureMixin, EnhancedTestCase):
    """The daily scheduler entrypoint, end to end."""

    def test_entrypoint_is_registered_as_a_daily_scheduler_job(self):
        """If this path is renamed/moved, the job silently stops running."""
        from verenigingen.hooks.scheduler import scheduler_events

        self.assertIn(SCHEDULER_PATH, scheduler_events["daily"])

    def test_scheduler_can_resolve_the_dotted_path_it_is_configured_with(self):
        """frappe resolves scheduler jobs by string; a bad string fails at runtime only."""
        resolved = frappe.get_attr(SCHEDULER_PATH)

        self.assertIs(resolved, process_scheduled_campaigns)

    def test_due_campaign_is_skipped_cleanly_and_nothing_is_sent(self):
        """A due (In Progress) campaign must be skipped, not errored, and not mailed.

        This is the regression the module docstring describes: the job used to
        KeyError on the missing `campaign_type` custom field and log an Error for
        every due campaign, every day.
        """
        email_campaign = self._make_email_campaign("due")
        self.assertEqual(email_campaign.status, "In Progress", "fixture is not actually due")

        before = self._outbound_counts()
        with self.assertNoErrorLog():
            result = frappe.get_attr(SCHEDULER_PATH)()
        after = self._outbound_counts()

        self.assertEqual(result["errors"], [], "the daily job reported campaign failures")
        self.assertTrue(result["success"])
        self.assertIn(email_campaign.campaign_name, result["skipped"])
        self.assertNotIn(email_campaign.campaign_name, result["processed"])
        self.assertEqual(result["total_processed"], len(result["processed"]))
        self.assertNothingWasSent(before, after)

    def test_job_is_idempotent(self):
        """The daily job must be safe to re-run (retries, catch-up runs)."""
        email_campaign = self._make_email_campaign("idem")

        before = self._outbound_counts()
        first = frappe.get_attr(SCHEDULER_PATH)()
        second = frappe.get_attr(SCHEDULER_PATH)()
        after = self._outbound_counts()

        self.assertEqual(first["skipped"], second["skipped"])
        self.assertEqual(first["processed"], second["processed"])
        self.assertNothingWasSent(before, after)
        self.assertEqual(
            frappe.db.get_value("Email Campaign", email_campaign.name, "status"),
            "In Progress",
            "the job mutated campaign state despite processing nothing",
        )

    def test_future_dated_campaign_is_not_picked_up(self):
        """A campaign that has not started yet must stay untouched."""
        future = self._make_email_campaign("future", start_date=add_days(today(), 5))
        self.assertEqual(future.status, "Scheduled", "fixture should not be due yet")

        result = frappe.get_attr(SCHEDULER_PATH)()

        self.assertNotIn(future.campaign_name, result["skipped"])
        self.assertNotIn(future.campaign_name, result["processed"])

    def test_completed_campaign_is_not_reprocessed(self):
        """A finished campaign must not be resurrected by the daily sweep."""
        finished = self._make_email_campaign("done")
        frappe.db.set_value("Email Campaign", finished.name, "status", "Completed", update_modified=False)

        result = frappe.get_attr(SCHEDULER_PATH)()

        self.assertNotIn(finished.campaign_name, result["skipped"])
        self.assertNotIn(finished.campaign_name, result["processed"])

    def test_result_shape_is_stable_for_the_scheduler_log(self):
        """The job's return value is what ends up in the Scheduled Job Log."""
        self._make_email_campaign("shape")

        result = frappe.get_attr(SCHEDULER_PATH)()

        for key in ("success", "processed", "skipped", "errors", "total_processed"):
            self.assertIn(key, result)
        self.assertIsInstance(result["processed"], list)
        self.assertIsInstance(result["skipped"], list)
        self.assertIsInstance(result["errors"], list)


class TestTriggerCampaignTest(EmailCampaignFixtureMixin, EnhancedTestCase):
    """The admin-facing 'test this campaign' button must never blast the membership."""

    def test_manual_test_run_of_an_unconfigured_campaign_sends_nothing(self):
        email_campaign = self._make_email_campaign("manual")

        from verenigingen.email.automated_campaigns import trigger_campaign_test

        before = self._outbound_counts()
        result = trigger_campaign_test(email_campaign.name)
        after = self._outbound_counts()

        self.assertFalse(result["success"])
        self.assertTrue(result.get("skipped"), f"unexpected non-skip result: {result}")
        self.assertNothingWasSent(before, after)


class TestCampaignCreationIsASafeNoOp(EnhancedTestCase):
    """create_campaign() must fail closed - never leave a half-built campaign behind."""

    def setUp(self):
        super().setUp()
        self.manager = AutomatedCampaignManager()

    def test_invalid_campaign_type_is_rejected_without_touching_the_database(self):
        before = frappe.db.count("Email Campaign")

        result = self.manager.create_campaign("not_a_real_campaign_type")

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Invalid campaign type")
        self.assertEqual(frappe.db.count("Email Campaign"), before)

    def test_valid_campaign_type_fails_closed_rather_than_creating_a_broken_row(self):
        """The feature is unbuilt: creation must not persist a partial campaign.

        `create_campaign` writes `campaign_name` = the human label ("Monthly
        Newsletter"), but on the standard Email Campaign DocType that field is a
        Link to Campaign, so insert() fails validation. What matters for safety
        is that the failure is caught and NOTHING is persisted - a half-built
        campaign row would later be picked up by the daily job.
        """
        self.expectErrorLog("Automated Campaigns")
        before = frappe.db.count("Email Campaign")

        result = self.manager.create_campaign("monthly_newsletter", title="Coverage probe")

        self.assertFalse(result["success"], "campaign creation unexpectedly succeeded - re-review this test")
        self.assertEqual(
            frappe.db.count("Email Campaign"), before, "a failed campaign creation left a row behind"
        )


class TestNextRunCalculation(EnhancedTestCase):
    """_calculate_next_run drives when a campaign would fire."""

    def setUp(self):
        super().setUp()
        self.manager = AutomatedCampaignManager()

    def test_monthly_runs_on_the_first_of_next_month_at_0900(self):
        next_run = self.manager._calculate_next_run({"frequency": "monthly"})

        expected = add_months(now_datetime().replace(day=1, hour=9, minute=0, second=0, microsecond=0), 1)
        self.assertEqual(next_run, expected)
        self.assertEqual(next_run.day, 1)
        self.assertEqual(next_run.hour, 9)
        self.assertGreater(next_run, now_datetime())

    def test_quarterly_runs_on_the_first_day_of_the_next_quarter(self):
        next_run = self.manager._calculate_next_run({"frequency": "quarterly"})

        self.assertEqual(next_run.day, 1)
        self.assertIn(next_run.month, (1, 4, 7, 10))
        self.assertEqual(next_run.hour, 9)
        self.assertGreater(next_run, now_datetime(), "next quarterly run is in the past")

    def test_annual_runs_one_year_out(self):
        now = now_datetime()

        next_run = self.manager._calculate_next_run({"frequency": "annual"})

        self.assertEqual(next_run.year, now.year + 1)
        self.assertEqual((next_run.month, next_run.day), (now.month, now.day))

    def test_event_driven_campaigns_have_no_scheduled_run(self):
        """An event-driven campaign must never be picked up by a date sweep."""
        self.assertIsNone(self.manager._calculate_next_run({"frequency": "event_driven"}))

    def test_annual_clamps_to_feb_28_on_a_leap_day_anchor(self):
        """29 Feb has no 'same date next year' - #696.

        `datetime.replace(year=...)` does not clamp, so an annual campaign
        anchored on 29 Feb (next real occurrence: 2028-02-29) raised ValueError
        computing its next run instead of scheduling one. The anchor is pinned
        directly rather than waited for, since the next occurrence is two years
        out - see test_site_timezone_today.py for the same manufactured-clock
        rationale.
        """
        leap_day = datetime(2028, 2, 29, 14, 30, 0)
        with patch("verenigingen.email.automated_campaigns.now_datetime", return_value=leap_day):
            next_run = self.manager._calculate_next_run({"frequency": "annual"})

        self.assertEqual((next_run.year, next_run.month, next_run.day), (2029, 2, 28))
        self.assertEqual(
            (next_run.hour, next_run.minute, next_run.second, next_run.microsecond), (9, 0, 0, 0)
        )


class TestCampaignContentGeneration(EnhancedTestCase):
    """Content generation must never invent member-facing facts."""

    def setUp(self):
        super().setUp()
        self.manager = AutomatedCampaignManager()

    def test_monthly_newsletter_content_defaults_to_empty_not_fabricated(self):
        """Regression guard: this once shipped a fake volunteer spotlight and invented figures.

        With no content configured, every editorial slot must come back EMPTY so
        the newsletter shows nothing rather than something untrue.
        """
        content = self.manager._generate_monthly_newsletter_content({"chapter": "Some Chapter"}, {})

        self.assertEqual(content["highlights"], "")
        self.assertEqual(content["upcoming_events"], "")
        self.assertEqual(content["volunteer_spotlight"], "")
        self.assertEqual(content["chapter_name"], "Some Chapter")
        self.assertEqual(content["month_year"], now_datetime().strftime("%B %Y"))

    def test_monthly_newsletter_content_passes_configured_values_through(self):
        config = {
            "highlights": "We planted 40 trees",
            "upcoming_events": "AGM on the 3rd",
            "volunteer_spotlight": "Thanks to the kitchen crew",
        }

        content = self.manager._generate_monthly_newsletter_content({"chapter": "Utrecht"}, config)

        self.assertEqual(content["highlights"], config["highlights"])
        self.assertEqual(content["upcoming_events"], config["upcoming_events"])
        self.assertEqual(content["volunteer_spotlight"], config["volunteer_spotlight"])

    def test_volunteer_recruitment_content_defaults_to_empty_contact_details(self):
        """Never invent a contact address - mail would point members at nobody."""
        content = self.manager._generate_volunteer_content({}, {})

        self.assertEqual(content["contact_info"], "")
        self.assertEqual(content["contact_email"], "")
        self.assertEqual(content["opportunity_title"], "")

    def test_campaign_types_without_a_generator_produce_no_content(self):
        """An unhandled content-requiring type must yield None, not a stub payload."""
        self.assertIsNone(self.manager._generate_campaign_content({"campaign_type": "event_reminders"}, {}))

    def test_execute_campaign_aborts_when_content_cannot_be_generated(self):
        """No content => no send. The manager must stop before touching the mailer."""
        result = self.manager._execute_campaign(
            {
                "name": "fake",
                "campaign_name": "fake",
                "campaign_type": "monthly_newsletter",
                "template_id": "monthly_update",
                "content_config": json.dumps({}),
            }
        )
        # NOTE: an `assertIsInstance(result, dict)` used to sit here. It could never
        # fail, so it has been dropped — the complementary case below (a
        # requires_content type with no generator) is what this test actually pins.
        no_generator = self.manager._execute_campaign(
            {
                "name": "fake2",
                "campaign_name": "fake2",
                "campaign_type": "volunteer_recruitment",
                "template_id": "volunteer_recruitment",
                "content_config": "not-valid-json",
            }
        )
        self.assertFalse(no_generator["success"], "malformed content_config must not proceed to a send")

    def test_execute_campaign_skips_campaigns_with_no_campaign_type(self):
        """The real-world case: the custom field does not exist, so it is absent."""
        result = self.manager._execute_campaign({"name": "x", "campaign_name": "x"})

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])

    def test_execute_campaign_skips_unknown_campaign_types(self):
        """A stale/renamed campaign_type must skip, not fall through to a send."""
        result = self.manager._execute_campaign(
            {"name": "x", "campaign_name": "x", "campaign_type": "retired_type"}
        )

        self.assertFalse(result["success"])
        self.assertTrue(result["skipped"])


class TestCampaignTypeCatalogue(EnhancedTestCase):
    """The catalogue is what the admin UI offers; its shape is a contract."""

    def test_every_advertised_campaign_type_is_fully_specified(self):
        result = get_campaign_types()

        self.assertTrue(result["success"])
        types = result["campaign_types"]
        self.assertEqual(
            set(types),
            {
                "monthly_newsletter",
                "welcome_series",
                "event_reminders",
                "membership_renewal",
                "volunteer_recruitment",
            },
        )
        for campaign_type, definition in types.items():
            with self.subTest(campaign_type=campaign_type):
                for key in ("name", "description", "frequency", "template_id", "requires_content"):
                    self.assertIn(key, definition, f"{campaign_type} is missing '{key}'")

    # membership_renewal is excluded here and pinned separately below - it points
    # at a template that does not exist (product bug).
    RESOLVABLE_CAMPAIGN_TYPES = (
        "monthly_newsletter",
        "welcome_series",
        "event_reminders",
        "volunteer_recruitment",
    )

    def _template_ids(self):
        from verenigingen.email.newsletter_templates import NewsletterTemplateManager

        return set(NewsletterTemplateManager().templates)

    def test_campaign_template_ids_resolve_to_a_real_template(self):
        """A campaign pointing at a non-existent template renders nothing and sends nothing."""
        template_ids = self._template_ids()
        campaign_types = get_campaign_types()["campaign_types"]

        for campaign_type in self.RESOLVABLE_CAMPAIGN_TYPES:
            with self.subTest(campaign_type=campaign_type):
                template_id = campaign_types[campaign_type]["template_id"]
                self.assertIn(
                    template_id,
                    template_ids,
                    f"campaign type '{campaign_type}' references unknown template '{template_id}'",
                )

    @unittest.expectedFailure
    def test_membership_renewal_campaign_has_a_template(self):
        """EXPECTED FAILURE - PRODUCT BUG: dangling template reference.

        automated_campaigns.py:74-81 declares the `membership_renewal` campaign
        type with template_id "membership_renewal", but
        NewsletterTemplateManager._load_templates() (newsletter_templates.py:28-89)
        defines no such template. A renewal campaign therefore renders nothing:
        send_templated_email() returns {"success": False, "error": "Template not
        found"} and no renewal reminder is ever sent.
        """
        template_id = get_campaign_types()["campaign_types"]["membership_renewal"]["template_id"]

        self.assertIn(template_id, self._template_ids(), f"missing template '{template_id}'")

    def test_frequencies_are_ones_calculate_next_run_understands(self):
        """A frequency the scheduler cannot compute silently never runs."""
        manager = AutomatedCampaignManager()
        for campaign_type, definition in manager.campaign_types.items():
            with self.subTest(campaign_type=campaign_type):
                next_run = manager._calculate_next_run(definition)
                if definition["frequency"] == "event_driven":
                    self.assertIsNone(next_run)
                else:
                    self.assertIsInstance(
                        next_run,
                        datetime,
                        f"frequency '{definition['frequency']}' has no next-run rule",
                    )


class TestKnownCampaignApiBugs(EmailCampaignFixtureMixin, EnhancedTestCase):
    """Whitelisted endpoints that raise instead of returning a result.

    Both are pinned with @unittest.expectedFailure (house pattern): the test
    states the correct behaviour and flips to an unexpected success once fixed.
    """

    @unittest.expectedFailure
    def test_get_active_campaigns_accepts_a_chapter_filter(self):
        """EXPECTED FAILURE - PRODUCT BUG.

        automated_campaigns.py:508-530 filters Email Campaign on a `chapter`
        field. That custom field was never created (module docstring), so
        frappe.get_all raises and the whitelisted endpoint 500s for every
        chapter-scoped call. It should return an empty/OK result instead.
        """
        from verenigingen.email.automated_campaigns import get_active_campaigns

        chapter = self.create_test_chapter(chapter_name=f"Campaign Chapter {self.uid}")

        result = get_active_campaigns(chapter_name=chapter.name)

        self.assertTrue(result["success"])

    @unittest.expectedFailure
    def test_trigger_event_campaigns_skips_unconfigured_campaigns(self):
        """EXPECTED FAILURE - PRODUCT BUG.

        automated_campaigns.py:386-418 selects only
        [name, campaign_name, email_campaign_for, recipient, sender] but then
        reads `campaign["template_id"]` (line 405), a key that is never present.
        Every in-progress campaign therefore raises KeyError, is swallowed into
        `errors`, and the call reports success=False.

        This is exactly the defect the module docstring says was fixed in
        `_execute_campaign` - the fix was never applied to this second call site.
        Correct behaviour: skip campaigns that are not configured for the event,
        as `_execute_campaign` does.
        """
        self._make_email_campaign("evt")
        manager = AutomatedCampaignManager()

        result = manager.trigger_event_campaigns("member_activation", {"member_names": "Someone"})

        self.assertEqual(result["errors"], [])
        self.assertTrue(result["success"])
