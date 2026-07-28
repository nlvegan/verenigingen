#!/usr/bin/env python3
"""
Tests for verenigingen.email.email_group_sync.

This module keeps Frappe Email Groups (the newsletter distribution lists) in step
with Member status and consent. Two entrypoints matter:

  * `scheduled_email_group_sync` - daily scheduler job
    (verenigingen/hooks/scheduler.py:26), gated behind the
    `enable_email_group_sync` flag on Verenigingen Settings.
  * `sync_member_on_change` - Member document hook
    (verenigingen/hooks/doc_events.py:66).

The privacy-relevant property is symmetric: a member who is Active AND accepts
optional communications must be IN the list, and a member who is not must be OUT
of it - and an explicit newsletter unsubscribe must survive both directions.

`sync_email_groups_manually()` calls frappe.db.commit(), so the tests that go
through it rely on EnhancedTestCase's insert-capture teardown to drain the
committed rows rather than on transaction rollback.
"""

import unittest

import frappe

from verenigingen.email.email_group_sync import (
    add_to_email_group,
    get_email_group_stats,
    remove_from_email_group,
    scheduled_email_group_sync,
    sync_member_on_change,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

ACTIVE_MEMBERS_GROUP_TITLE = "Active Members"


class EmailGroupMixin:
    def _setup_groups(self):
        self.marker = f"egs{self.uid}"
        self.group = self._ensure_group(f"EGS Test Group {self.uid}", track=True)

    def _ensure_group(self, title, track=False):
        existing = frappe.db.get_value("Email Group", {"title": title}, "name")
        if existing:
            return existing
        doc = frappe.get_doc({"doctype": "Email Group", "title": title})
        doc.insert()
        if track:
            self.track_doc("Email Group", doc.name)
        return doc.name

    def _member(self, tag, **kwargs):
        kwargs.setdefault("accepts_optional_communications", 1)
        email = f"{tag}.{self.marker}@example.com"
        member = self.create_test_member(
            first_name=tag.replace(".", "").title(), last_name=f"Egs{self.uid}", email=email, **kwargs
        )
        self.assertEqual(member.email, email, "factory mangled the test email")
        return member

    def _rows(self, group=None):
        return frappe.get_all(
            "Email Group Member",
            filters={"email_group": group or self.group},
            fields=["name", "email", "unsubscribed"],
        )

    def _emails_in_group(self, group=None):
        return {r.email for r in self._rows(group)}


class TestEmailGroupMembershipPrimitives(EmailGroupMixin, EnhancedTestCase):
    """add_to_email_group / remove_from_email_group - the two write primitives."""

    def setUp(self):
        super().setUp()
        self._setup_groups()

    def test_adding_creates_a_subscribed_row(self):
        add_to_email_group(f"new.{self.marker}@example.com", self.group)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].email, f"new.{self.marker}@example.com")
        self.assertEqual(rows[0].unsubscribed, 0)

    def test_adding_twice_does_not_duplicate_the_recipient(self):
        """A repeated sync must not make the member receive two copies."""
        email = f"dup.{self.marker}@example.com"

        add_to_email_group(email, self.group)
        add_to_email_group(email, self.group)

        self.assertEqual(len(self._rows()), 1)

    def test_re_adding_does_not_resurrect_an_explicit_unsubscribe(self):
        """Someone who hit 'unsubscribe' must stay unsubscribed across syncs."""
        email = f"unsub.{self.marker}@example.com"
        add_to_email_group(email, self.group)
        row = self._rows()[0]
        frappe.db.set_value("Email Group Member", row.name, "unsubscribed", 1)

        add_to_email_group(email, self.group)

        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].unsubscribed, 1, "a sync re-subscribed someone who had unsubscribed")

    def test_removing_deletes_the_membership(self):
        email = f"rm.{self.marker}@example.com"
        add_to_email_group(email, self.group)

        remove_from_email_group(email, self.group)

        self.assertEqual(self._rows(), [])

    def test_removing_a_non_member_is_a_silent_no_op(self):
        """Sync loops call remove blindly; it must not raise or log."""
        with self.assertNoErrorLog():
            remove_from_email_group(f"ghost.{self.marker}@example.com", self.group)

        self.assertEqual(self._rows(), [])

    def test_membership_is_scoped_to_one_group(self):
        other_group = self._ensure_group(f"EGS Other Group {self.uid}", track=True)
        email = f"scoped.{self.marker}@example.com"
        add_to_email_group(email, self.group)

        self.assertEqual(self._emails_in_group(self.group), {email})
        self.assertNotIn(email, self._emails_in_group(other_group))


class TestSyncMemberOnChange(EmailGroupMixin, EnhancedTestCase):
    """The per-member reconciliation called from the Member hook."""

    def setUp(self):
        super().setUp()
        self._setup_groups()
        self.active_group = self._ensure_group(ACTIVE_MEMBERS_GROUP_TITLE)

    def test_active_consenting_member_is_added(self):
        member = self._member("syncin")

        result = sync_member_on_change(member)

        self.assertTrue(result["success"])
        self.assertIn(member.email, self._emails_in_group(self.active_group))

    def test_opting_out_removes_the_member_from_the_list(self):
        """The core privacy path: withdrawing consent must take effect."""
        member = self._member("syncout")
        sync_member_on_change(member)
        self.assertIn(member.email, self._emails_in_group(self.active_group))

        member.accepts_optional_communications = 0
        sync_member_on_change(member)

        self.assertNotIn(member.email, self._emails_in_group(self.active_group))

    def test_non_active_member_is_removed_from_the_list(self):
        member = self._member("syncquit")
        sync_member_on_change(member)

        member.status = "Quit"
        sync_member_on_change(member)

        self.assertNotIn(member.email, self._emails_in_group(self.active_group))

    def test_member_without_an_email_is_skipped_without_error(self):
        member = self._member("syncnomail")
        member.email = None

        with self.assertNoErrorLog():
            result = sync_member_on_change(member)

        self.assertTrue(result["success"])
        self.assertEqual(result["message"], "No email address")

    def test_chapter_group_membership_follows_the_members_chapters(self):
        """A member of a chapter that has a group is added to that group too."""
        chapter = self.create_test_chapter(chapter_name=f"EGS Chapter {self.uid}")
        chapter_group = self._ensure_group(f"{chapter.name} - All Members", track=True)
        member = self._member("syncchapter")
        chapter.append("members", {"member": member.name, "enabled": 1})
        chapter.save()
        member.reload()

        sync_member_on_change(member)

        self.assertIn(member.email, self._emails_in_group(chapter_group))

        member.accepts_optional_communications = 0
        sync_member_on_change(member)

        self.assertNotIn(
            member.email,
            self._emails_in_group(chapter_group),
            "opting out did not remove the member from their chapter list",
        )


class TestOptOutDestroysTheUnsubscribeRecord(EmailGroupMixin, EnhancedTestCase):
    """PRODUCT BUG: an opt-out/opt-in round trip silently re-subscribes someone.

    `sync_member_on_change` reconciles by DELETING the Email Group Member row
    (email_group_sync.py:284-300) when a member is not Active-and-consenting,
    and re-INSERTING it with `unsubscribed: 0` (line 265-278) when they are.

    The Email Group Member row is also where Frappe records an explicit
    newsletter unsubscribe. So this sequence loses it:

        1. member is Active + accepts optional communications  -> row, unsub=0
        2. member clicks "unsubscribe" in a newsletter          -> row, unsub=1
        3. member (or staff) clears accepts_optional_communications
                                                                -> row DELETED
        4. accepts_optional_communications set back to 1        -> row, unsub=0

    The explicit unsubscribe from step 2 is gone and the member is mailed again.
    A correct implementation would toggle `unsubscribed` instead of deleting, or
    at minimum remember prior unsubscribes.
    """

    def setUp(self):
        super().setUp()
        self._setup_groups()
        self.active_group = self._ensure_group(ACTIVE_MEMBERS_GROUP_TITLE)

    @unittest.expectedFailure
    def test_explicit_unsubscribe_survives_an_opt_out_opt_in_round_trip(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        member = self._member("roundtrip")
        sync_member_on_change(member)
        row = frappe.db.get_value(
            "Email Group Member", {"email": member.email, "email_group": self.active_group}, "name"
        )
        frappe.db.set_value("Email Group Member", row, "unsubscribed", 1)

        member.accepts_optional_communications = 0
        sync_member_on_change(member)
        member.accepts_optional_communications = 1
        sync_member_on_change(member)

        unsubscribed = frappe.db.get_value(
            "Email Group Member",
            {"email": member.email, "email_group": self.active_group},
            "unsubscribed",
        )
        self.assertEqual(unsubscribed, 1, "an explicit newsletter unsubscribe was silently reversed")


class TestMemberHookNeverFires(EmailGroupMixin, EnhancedTestCase):
    """Member email-group sync does not run on save — now by explicit decision.

    Originally this handler was registered under a Member `after_save` event that
    Frappe never dispatches (Document.run_post_save_methods() runs `on_update` and
    `on_change` only), so it silently never ran. That dead event key has since been
    removed from hooks/doc_events.py and is blocked by
    tests/test_hooks_modules.py::TestDocEventNamesAreDispatched.

    `sync_member_on_change` was deliberately NOT re-registered under the working
    events, because activating it would activate two open defects with it:
      1. remove_from_email_group() DELETES the Email Group Member row, which is
         where Frappe records an explicit newsletter unsubscribe — so an
         opt-out -> opt-in toggle silently clears that unsubscribe
         (see TestConsentRoundTripReversesUnsubscribe above).
      2. Unlike its scheduled twin, it is not behind `enable_email_group_sync`,
         so it would add unconditional DB writes to every Member save.

    Consequence is unchanged for now: email-group membership is not maintained on
    member status/consent change, and the daily `scheduled_email_group_sync` is
    itself gated behind `enable_email_group_sync` (default 0).
    """

    def setUp(self):
        super().setUp()
        self._setup_groups()
        self.active_group = self._ensure_group(ACTIVE_MEMBERS_GROUP_TITLE)

    def test_handler_is_not_wired_to_any_member_event(self):
        """Guard: pins the deliberate non-registration, so the bug test stays accurate.

        This fails the moment someone wires the handler up — which is the point:
        the consent defect above must be fixed in the same change.
        """
        from verenigingen.hooks.doc_events import doc_events

        wired = [
            event
            for event, handlers in doc_events["Member"].items()
            if "verenigingen.email.email_group_sync.sync_member_on_change"
            in ([handlers] if isinstance(handlers, str) else handlers)
        ]
        self.assertEqual(
            [],
            wired,
            f"sync_member_on_change is now wired to Member {wired} — fix the "
            "unsubscribe-reversal defect before enabling it, then update this test.",
        )

    # NOTE: an @unittest.expectedFailure test asserting that saving a Member syncs
    # their email group used to live here. It has been removed: the non-registration
    # is a deliberate decision (see class docstring), not a defect, so an xfail
    # asserting the opposite is misleading — the moment someone "fixed" it, the xfail
    # would report an unexpected success that reads as a regression.
    # test_handler_is_not_wired_to_any_member_event above is the correct pin.


class TestScheduledEmailGroupSync(EmailGroupMixin, EnhancedTestCase):
    """The daily scheduler job and its feature flag."""

    def setUp(self):
        super().setUp()
        self._setup_groups()
        self.active_group = self._ensure_group(ACTIVE_MEMBERS_GROUP_TITLE)

        # sync_email_groups_manually() calls frappe.db.commit(), which persists this
        # Singles write past the test transaction — and the EnhancedTestCase insert
        # capture does not cover Singles. Left on, the flag makes every later test and
        # every scheduler tick on this database rebuild the whole membership's email
        # groups. Restore whatever the site had.
        original_flag = frappe.db.get_single_value("Verenigingen Settings", "enable_email_group_sync")
        self.addCleanup(
            frappe.db.set_single_value,
            "Verenigingen Settings",
            "enable_email_group_sync",
            original_flag or 0,
        )

    def test_entrypoint_is_registered_as_a_daily_scheduler_job(self):
        from verenigingen.hooks.scheduler import scheduler_events

        self.assertIn(
            "verenigingen.email.email_group_sync.scheduled_email_group_sync", scheduler_events["daily"]
        )

    def test_job_does_nothing_while_the_feature_flag_is_off(self):
        """The flag is the only guard against a full-membership list rebuild."""
        frappe.db.set_single_value("Verenigingen Settings", "enable_email_group_sync", 0)
        member = self._member("flagoff")
        before = self._emails_in_group(self.active_group)

        scheduled_email_group_sync()

        self.assertEqual(self._emails_in_group(self.active_group), before)
        self.assertNotIn(member.email, self._emails_in_group(self.active_group))

    def test_job_adds_opted_in_members_and_leaves_opted_out_ones_out(self):
        """With the flag on, the list must reflect status + consent exactly."""
        frappe.db.set_single_value("Verenigingen Settings", "enable_email_group_sync", 1)
        opted_in = self._member("flagin")
        opted_out = self._member("flagout", accepts_optional_communications=0)
        quit_member = self._member("flagquit")
        frappe.db.set_value("Member", quit_member.name, "status", "Quit", update_modified=False)

        scheduled_email_group_sync()

        emails = self._emails_in_group(self.active_group)
        self.assertIn(opted_in.email, emails)
        self.assertNotIn(opted_out.email, emails, "an opted-out member was added to the mailing list")
        self.assertNotIn(quit_member.email, emails, "a member who quit was added to the mailing list")

    def test_job_removes_a_member_who_opts_out_after_being_added(self):
        frappe.db.set_single_value("Verenigingen Settings", "enable_email_group_sync", 1)
        member = self._member("flagremove")
        scheduled_email_group_sync()
        self.assertIn(member.email, self._emails_in_group(self.active_group))

        frappe.db.set_value(
            "Member", member.name, "accepts_optional_communications", 0, update_modified=False
        )
        scheduled_email_group_sync()

        self.assertNotIn(member.email, self._emails_in_group(self.active_group))


class TestEmailGroupStats(EmailGroupMixin, EnhancedTestCase):
    """get_email_group_stats() - the admin-facing summary."""

    def setUp(self):
        super().setUp()
        self._setup_groups()

    def _my_stats(self):
        groups = get_email_group_stats()["groups"]
        return next(g for g in groups if g["name"] == self.group)

    def test_subscribed_and_unsubscribed_are_counted_separately(self):
        add_to_email_group(f"a.{self.marker}@example.com", self.group)
        add_to_email_group(f"b.{self.marker}@example.com", self.group)
        row = frappe.db.get_value(
            "Email Group Member", {"email": f"b.{self.marker}@example.com", "email_group": self.group}, "name"
        )
        frappe.db.set_value("Email Group Member", row, "unsubscribed", 1)

        stats = self._my_stats()

        self.assertEqual(stats["member_count"], 1, "unsubscribed members must not count as recipients")
        self.assertEqual(stats["unsubscribed_count"], 1)
        self.assertEqual(stats["total_count"], 2)

    def test_an_empty_group_reports_zeroes(self):
        stats = self._my_stats()

        self.assertEqual(
            (stats["member_count"], stats["unsubscribed_count"], stats["total_count"]), (0, 0, 0)
        )

    @unittest.expectedFailure
    def test_group_description_is_reported(self):
        """EXPECTED FAILURE - PRODUCT BUG: description is always None.

        email_group_sync.py:319 selects only ["name", "title"] from Email Group
        but line 334 reads `group.description`. frappe._dict returns None for a
        missing key instead of raising, so the admin summary silently shows no
        descriptions at all.
        """
        frappe.db.set_value("Email Group", self.group, "description", "Coverage probe description")

        self.assertEqual(self._my_stats()["description"], "Coverage probe description")
