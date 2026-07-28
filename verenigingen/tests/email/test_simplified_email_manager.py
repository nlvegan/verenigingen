#!/usr/bin/env python3
"""
Recipient-set correctness tests for verenigingen.email.simplified_email_manager.

SimplifiedEmailManager is the module that actually *builds the mailing list* for
chapter and organisation-wide email. Every test here creates its own chapter, so
the assertions are on the EXACT audience, not on "at least N".

Nothing here sends. The send path is exercised only through `test_mode=True` /
`get_segment_preview()`, plus one explicitly-pinned test asserting that a real
send is currently impossible (see TestNewsletterDoctypeIsMissing).
"""

import unittest

import frappe

from verenigingen.email.simplified_email_manager import SimplifiedEmailManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class ChapterAudienceMixin:
    """One private chapter per test, so recipient counts are exact."""

    def _setup_audience(self):
        self.marker = f"sem{self.uid}"
        self.chapter = self.create_test_chapter(chapter_name=f"SEM Chapter {self.uid}")
        self.other_chapter = self.create_test_chapter(chapter_name=f"SEM Other {self.uid}")
        self.manager = SimplifiedEmailManager(self.chapter)

    def _member(self, tag, **kwargs):
        kwargs.setdefault("accepts_optional_communications", 1)
        email = f"{tag}.{self.marker}@example.com"
        member = self.create_test_member(
            first_name=tag.replace(".", "").title(), last_name=f"Sem{self.uid}", email=email, **kwargs
        )
        self.assertEqual(member.email, email, "factory mangled the audience email")
        return member

    def _join(self, member, chapter=None, enabled=1):
        chapter = chapter or self.chapter
        chapter.append("members", {"member": member.name, "enabled": enabled})
        chapter.save()

    def _volunteer(self, member, status="Active"):
        return self.create_test_volunteer(member_name=member.name, status=status)

    def _chapter_role(self, role_name="SEM Test Board Role"):
        if not frappe.db.exists("Chapter Role", role_name):
            role = frappe.get_doc(
                {
                    "doctype": "Chapter Role",
                    "role_name": role_name,
                    "permissions_level": "Basic",
                    "is_active": 1,
                }
            )
            role.insert()
            self.track_doc("Chapter Role", role.name)
        return role_name

    def _seat(self, volunteer, chapter=None, is_active=1, to_date=None):
        chapter = chapter or self.chapter
        row = {
            "volunteer": volunteer.name,
            "chapter_role": self._chapter_role(),
            "from_date": frappe.utils.today(),
            "is_active": is_active,
        }
        if to_date:
            row["to_date"] = to_date
        chapter.append("board_members", row)
        chapter.save()

    def _count(self, segment):
        result = self.manager.send_to_chapter_segment(
            chapter_name=self.chapter.name, segment=segment, test_mode=True
        )
        if not result.get("success"):
            return 0
        self.assertTrue(result["test_mode"], "test_mode must never fall through to a real send")
        return result["recipients_count"]

    def _preview_emails(self, segment):
        result = self.manager.get_segment_preview(self.chapter.name, segment)
        return {r["email"] for r in result.get("sample_recipients", [])}


class TestChapterAllSegment(ChapterAudienceMixin, EnhancedTestCase):
    """segment='all' - the ordinary chapter newsletter audience."""

    def setUp(self):
        super().setUp()
        self._setup_audience()

    def test_only_enabled_active_opted_in_chapter_members_are_counted(self):
        included = self._member("allin")
        self._join(included)

        opted_out = self._member("allout", accepts_optional_communications=0)
        self._join(opted_out)

        left = self._member("allleft")
        self._join(left, enabled=0)

        quit_member = self._member("allquit")
        self._join(quit_member)
        frappe.db.set_value("Member", quit_member.name, "status", "Quit", update_modified=False)

        elsewhere = self._member("allelsewhere")
        self._join(elsewhere, chapter=self.other_chapter)

        self.assertEqual(self._count("all"), 1)
        self.assertEqual(self._preview_emails("all"), {included.email})

    def test_opted_out_member_is_never_in_the_chapter_newsletter(self):
        """The single most important exclusion in this module."""
        kept = self._member("optkeep")
        self._join(kept)
        opted_out = self._member("optdrop", accepts_optional_communications=0)
        self._join(opted_out)

        self.assertEqual(self._count("all"), 1)
        self.assertNotIn(opted_out.email, self._preview_emails("all"))

    def test_empty_audience_is_reported_rather_than_sent_to_nobody(self):
        result = self.manager.send_to_chapter_segment(
            chapter_name=self.chapter.name, segment="all", test_mode=True
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No eligible recipients found")

    def test_unknown_segment_is_rejected_and_never_falls_back_to_all(self):
        member = self._member("unknownseg")
        self._join(member)

        result = self.manager.send_to_chapter_segment(
            chapter_name=self.chapter.name, segment="everyone", test_mode=True
        )

        self.assertFalse(result["success"])
        self.assertIn("Unknown segment", result["error"])
        self.assertNotIn("recipients_count", result)

    def test_a_member_in_two_chapters_is_counted_once_per_chapter(self):
        """DISTINCT must collapse the duplicate Chapter Member rows, not double-mail."""
        member = self._member("twochapters")
        self._join(member)
        self._join(member, chapter=self.other_chapter)

        self.assertEqual(self._count("all"), 1)


class TestChapterRoleSegments(ChapterAudienceMixin, EnhancedTestCase):
    """segment='board' / 'volunteers' - the operational audiences."""

    def setUp(self):
        super().setUp()
        self._setup_audience()

    def test_board_segment_contains_only_active_seats_of_this_chapter(self):
        seated = self._member("boardin")
        self._join(seated)
        self._seat(self._volunteer(seated))

        deactivated = self._member("boardoff")
        self._join(deactivated)
        self._seat(self._volunteer(deactivated), is_active=0)

        elsewhere = self._member("boardelsewhere")
        self._join(elsewhere)
        self._seat(self._volunteer(elsewhere), chapter=self.other_chapter)

        plain = self._member("boardplain")
        self._join(plain)

        self.assertEqual(self._count("board"), 1)

    def test_volunteers_segment_requires_an_active_volunteer_record(self):
        active = self._member("volin")
        self._join(active)
        self._volunteer(active, status="Active")

        inactive = self._member("volout")
        self._join(inactive)
        self._volunteer(inactive, status="Inactive")

        plain = self._member("volplain")
        self._join(plain)

        self.assertEqual(self._count("volunteers"), 1)

    def test_volunteer_in_another_chapter_is_not_in_this_chapters_audience(self):
        outsider = self._member("voloutside")
        self._join(outsider, chapter=self.other_chapter)
        self._volunteer(outsider, status="Active")

        self.assertEqual(self._count("volunteers"), 0)


class TestRoleSegmentsIgnoreConsentAndMembershipState(ChapterAudienceMixin, EnhancedTestCase):
    """PRODUCT BUGS in the 'board' and 'volunteers' recipient queries.

    simplified_email_manager.py:76-112 builds those two audiences with only:
        board       -> ChapterBoardMember.parent + is_active + Member.email NOT NULL
        volunteers  -> ChapterMember.parent + Volunteer.status + Member.email NOT NULL

    Three filters present on the 'all' audience are missing from both:

    1. `accepts_optional_communications` - documented as deliberate ("no opt-out
       filtering ... they need to receive organizational communications"). The
       problem is that these segments are NOT restricted to organisational
       notices: newsletter_templates.send_templated_email() forwards ANY template
       (including `fundraising_campaign` and `volunteer_recruitment`) with
       segment='board'/'volunteers'. So a marketing blast reaches people who
       switched optional communications off.

       This is also SELF-INCONSISTENT: get_segment_preview()'s sample SQL for the
       same two segments (lines 260-291) DOES filter
       `accepts_optional_communications = 1`. The admin previews an opted-in
       audience and then sends to a strictly larger one.

    2. `Member.status = 'Active'` - a member who Quit / was Banned still receives
       chapter mail as long as a Volunteer row survives.

    3. `ChapterMember.enabled = 1` (volunteers segment) - someone who LEFT the
       chapter keeps receiving that chapter's mail.

    Each is pinned below asserting the corrected behaviour.
    """

    def setUp(self):
        super().setUp()
        self._setup_audience()

    @unittest.expectedFailure
    def test_preview_sample_shows_a_different_audience_than_the_volunteers_send(self):
        """EXPECTED FAILURE - the admin previews an audience that is not the one mailed.

        The COUNT is not the problem: get_segment_preview() delegates straight to
        send_to_chapter_segment(test_mode=True) (simplified_email_manager.py:240) and
        returns its count, so comparing the two counts is tautological. Two earlier
        versions of this test were unsound for that family of reasons — one compared
        the count to len(sample_recipients) (the sample is LIMIT 5, so it broke on any
        audience above five), the other compared the count to its own source.

        The real discrepancy is in WHO is shown. The volunteers send query
        (:96-111) has no consent filter, but the preview's sample SQL (:275-289)
        adds `AND m.accepts_optional_communications = 1`. So an opted-out volunteer
        is mailed but never appears in the sample the admin approves.
        """
        opted_out = self._member("vololdoptout", accepts_optional_communications=0)
        self._join(opted_out)
        self._volunteer(opted_out)

        preview = self.manager.get_segment_preview(self.chapter.name, "volunteers")
        send = self.manager.send_to_chapter_segment(self.chapter.name, "volunteers", test_mode=True)

        # Sanity: the opted-out volunteer really is inside the audience that gets
        # mailed — the send query counts them even though the sample will not show
        # them. (Counts match by construction; asserted only to document that.)
        self.assertEqual(preview["recipients_count"], send["recipients_count"])
        self.assertGreaterEqual(
            send["recipients_count"], 2, "fixture did not put both volunteers in the send audience"
        )

        self.assertIn(
            opted_out.email,
            {r["email"] for r in preview["sample_recipients"]},
            "an opted-out volunteer is mailed but is hidden from the preview sample, "
            "so the admin approves a different audience than the one that receives it",
        )

    @unittest.expectedFailure
    def test_opted_out_volunteer_is_not_mailed_by_the_volunteers_segment(self):
        """EXPECTED FAILURE - product bug 1, see class docstring."""
        opted_out = self._member("volooptout", accepts_optional_communications=0)
        self._join(opted_out)
        self._volunteer(opted_out, status="Active")

        self.assertEqual(self._count("volunteers"), 0)

    @unittest.expectedFailure
    def test_member_who_quit_is_not_mailed_by_the_volunteers_segment(self):
        """EXPECTED FAILURE - product bug 2, see class docstring."""
        gone = self._member("volquit")
        self._join(gone)
        self._volunteer(gone, status="Active")
        frappe.db.set_value("Member", gone.name, "status", "Quit", update_modified=False)

        self.assertEqual(self._count("volunteers"), 0)

    @unittest.expectedFailure
    def test_member_who_left_the_chapter_is_not_mailed_by_the_volunteers_segment(self):
        """EXPECTED FAILURE - product bug 3, see class docstring."""
        departed = self._member("volleft")
        self._join(departed, enabled=0)
        self._volunteer(departed, status="Active")

        self.assertEqual(self._count("volunteers"), 0)

    @unittest.expectedFailure
    def test_banned_member_is_not_mailed_by_the_board_segment(self):
        """EXPECTED FAILURE - product bug 2, see class docstring."""
        banned = self._member("bdbanned")
        self._join(banned)
        self._seat(self._volunteer(banned))
        frappe.db.set_value("Member", banned.name, "status", "Banned", update_modified=False)

        self.assertEqual(self._count("board"), 0)


class TestBlankEmailIsNotAValidRecipient(ChapterAudienceMixin, EnhancedTestCase):
    """PRODUCT BUG: '' passes the NULL check and becomes a Newsletter recipient.

    simplified_email_manager.py filters `Member.email.isnotnull()` only. A member
    row whose email was cleared holds '' (Frappe writes empty Data fields as ''),
    which is not NULL, so it is counted and then appended to the Newsletter
    recipients child table as an empty address.

    advanced_segmentation.py:164-169 gets this right - it filters both
    `m.email IS NOT NULL` AND `m.email != ''`.
    """

    def setUp(self):
        super().setUp()
        self._setup_audience()

    @unittest.expectedFailure
    def test_member_with_a_blank_email_is_excluded(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        blank = self._member("blankmail")
        self._join(blank)
        frappe.db.set_value("Member", blank.name, "email", "", update_modified=False)

        self.assertEqual(self._count("all"), 0)


class TestOrganizationWideAudience(ChapterAudienceMixin, EnhancedTestCase):
    """send_organization_wide() - the largest blast radius in the app."""

    def setUp(self):
        super().setUp()
        self._setup_audience()

    def _org_count(self, filters=None):
        result = self.manager.send_organization_wide(filters=filters, test_mode=True)
        return result["recipients_count"] if result.get("success") else 0

    def test_caller_supplied_filters_cannot_override_the_opt_out(self):
        """A caller asking for opted-out members must still not get them.

        send_organization_wide() force-sets accepts_optional_communications = 1 on
        any caller-supplied filter dict. That is the privacy backstop for the
        whole organisation-wide path, so it is asserted directly.
        """
        opted_in = self._member("orgin")
        opted_out = self._member("orgout", accepts_optional_communications=0)

        filters = {
            "name": ["in", [opted_in.name, opted_out.name]],
            "accepts_optional_communications": 0,
        }
        result = self.manager.send_organization_wide(filters=filters, test_mode=True)

        self.assertEqual(result["recipients_count"], 1, "an opted-out member survived the filter override")
        self.assertEqual(filters["accepts_optional_communications"], 1)

    def test_scoped_filters_select_exactly_the_matching_members(self):
        first = self._member("orgone")
        second = self._member("orgtwo")
        self._member("orgthree")

        count = self._org_count({"name": ["in", [first.name, second.name]]})

        self.assertEqual(count, 2)

    def test_empty_audience_is_reported_as_a_failure_not_an_empty_send(self):
        result = self.manager.send_organization_wide(
            filters={"name": ["in", ["Assoc-Member-does-not-exist"]]}, test_mode=True
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "No eligible recipients")

    def test_default_filters_exclude_opted_out_members(self):
        """With no caller filters the default set must still be consent-gated."""
        opted_out = self._member("orgdefaultout", accepts_optional_communications=0)

        result = self.manager.send_organization_wide(test_mode=True)

        self.assertTrue(result["success"], "site has no opted-in members; cannot assert exclusion")
        matching = frappe.get_all(
            "Member",
            filters={
                "name": opted_out.name,
                "status": "Active",
                "accepts_optional_communications": 1,
            },
        )
        self.assertEqual(matching, [], "the opted-out member matches the default org-wide filter set")


class TestNewsletterDoctypeIsMissing(ChapterAudienceMixin, EnhancedTestCase):
    """PRODUCT BUG (highest severity here): every real send path is dead.

    Both send paths build `frappe.get_doc({"doctype": "Newsletter", ...})`
    (simplified_email_manager.py:131 and :203). The Newsletter DocType was moved
    out of Frappe core into a separate `newsletter` app in v15+, and that app is
    not installed on this bench - verified on the production-like site
    (frappe 16.19.0): frappe.db.exists("DocType", "Newsletter") is False.

    So get_doc raises DoesNotExistError, the blanket `except Exception` swallows
    it into {"success": False, "error": ...} plus an Error Log, and:
      * send_chapter_email()          - whitelisted, always fails
      * send_organization_newsletter()- whitelisted, always fails
      * newsletter_templates.send_templated_email() - delegates to both, so the
        entire templated-email feature is inert.

    Recipient *selection* still works (test_mode / preview), which is why the
    rest of this file is meaningful; only delivery is broken.
    """

    def setUp(self):
        super().setUp()
        self._setup_audience()

    def test_newsletter_doctype_is_absent_on_this_frappe_version(self):
        """Guard: if this ever becomes True, re-check the pinned test below."""
        self.assertFalse(
            frappe.db.exists("DocType", "Newsletter"),
            "Newsletter DocType now exists - the send path may work again; re-review",
        )

    @unittest.expectedFailure
    def test_sending_a_chapter_newsletter_succeeds(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        self.expectErrorLog("SimplifiedEmailManager")
        recipient = self._member("sendme")
        self._join(recipient)

        result = self.manager.send_to_chapter_segment(
            chapter_name=self.chapter.name,
            segment="all",
            subject="Coverage probe",
            content="<p>hello</p>",
        )

        self.assertTrue(result["success"], f"chapter send failed: {result.get('error')}")

    @unittest.expectedFailure
    def test_sending_an_organization_newsletter_succeeds(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        self.expectErrorLog("SimplifiedEmailManager")
        recipient = self._member("sendorg")

        result = self.manager.send_organization_wide(
            filters={"name": ["in", [recipient.name]]},
            subject="Coverage probe",
            content="<p>hello</p>",
        )

        self.assertTrue(result["success"], f"organization send failed: {result.get('error')}")
