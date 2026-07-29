#!/usr/bin/env python3
"""
Recipient-set correctness tests for verenigingen.email.advanced_segmentation.

WHY THIS FILE EXISTS
--------------------
`AdvancedSegmentationManager` decides *who receives marketing email*. A wrong
recipient set is a privacy incident, not merely a bug: it can mail members who
opted out, members who quit/were banned, or members of a chapter they no longer
belong to. So every test here asserts the **exact** recipient set for a cohort
that this test created, including the members that MUST be excluded.

ISOLATION STRATEGY
------------------
The production queries scan the whole `tabMember` table and cannot be scoped, so
absolute counts are meaningless on a shared test site. Each test therefore
builds a cohort whose email local-parts all carry a per-test marker, and asserts
on `set(my cohort emails present in the result)`. Anything the cohort contains
but the result omits (and vice-versa) fails the test. Pre-existing site members
are invisible to the assertion, but every member this test created is accounted
for.

PRODUCT BUGS PINNED HERE
------------------------
Bugs found while writing these tests are pinned with @unittest.expectedFailure
(house pattern, cf. tests/payment/test_sepa_utilities.py): the test asserts the
CORRECT behaviour, so it goes green-as-expected-failure today and turns into a
loud "unexpected success" the moment the product is fixed.
"""

import unittest

import frappe
from frappe.utils import add_days, add_years

from verenigingen.email.advanced_segmentation import AdvancedSegmentationManager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class SegmentationCohortMixin:
    """Builds an email-marked member cohort and asserts on exact recipient sets."""

    def _setup_cohort(self):
        self.marker = f"seg{self.uid}"
        self.chapter = self.create_test_chapter(chapter_name=f"Seg Chapter {self.uid}")
        self.other_chapter = self.create_test_chapter(chapter_name=f"Seg Other Chapter {self.uid}")
        self.cohort_emails = set()

    def _email(self, tag):
        # Digits in the last 5 chars of the local part stop the factory from
        # appending its own uniqueness suffix, so the address stays predictable.
        return f"{tag}.{self.marker}@example.com"

    def _db_today(self):
        """The date MariaDB's CURDATE() returns, NOT frappe.utils.today().

        advanced_segmentation builds its age and board-term predicates from
        CURDATE()/NOW(), i.e. the DATABASE session clock, while the rest of the
        app works in the site time zone via frappe.utils.today(). Those two can
        differ by a day around midnight, which silently shifts every "exactly N
        years old today" / "term ends today" boundary. Boundary fixtures below
        are therefore anchored to the clock the query actually uses.
        """
        return frappe.db.sql("SELECT CURDATE()")[0][0]

    def _member(self, tag, chapter=None, **kwargs):
        """Create a cohort member. `accepts_optional_communications` is explicit.

        Frappe v16 does not apply DocType field defaults on raw get_doc().insert()
        (only at the form layer), so the JSON default of 1 is NOT persisted by the
        factory - it must be passed for every member whose opt-in state matters.
        """
        email = self._email(tag)
        kwargs.setdefault("accepts_optional_communications", 1)
        member = self.create_test_member(
            first_name=tag.replace(".", "").title(),
            last_name=f"Seg{self.uid}",
            email=email,
            **kwargs,
        )
        self.assertEqual(
            member.email, email, "factory mangled the cohort email; marker filtering would break"
        )
        self.cohort_emails.add(email)
        return member

    def _join_chapter(self, member, chapter=None, enabled=1):
        chapter = chapter or self.chapter
        chapter.append("members", {"member": member.name, "enabled": enabled})
        chapter.save()
        return chapter

    def _mine(self, result):
        """The subset of THIS test's cohort present in a segmentation result."""
        self.assertTrue(result.get("success"), f"segment query failed: {result.get('error')}")
        return {r["email"] for r in result["recipients"] if r["email"] in self.cohort_emails}


class TestSegmentBaseEligibility(SegmentationCohortMixin, EnhancedTestCase):
    """The four base conditions every built-in segment must enforce.

    base_conditions in _get_built_in_segment_recipients gate EVERY segment:
    status Active, email present, email non-empty, and opted in to optional
    communications. These are the privacy-critical filters.
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def test_opted_out_member_is_never_a_recipient(self):
        """accepts_optional_communications = 0 must exclude the member. Privacy-critical."""
        opted_in = self._member("optin")
        opted_out = self._member("optout", accepts_optional_communications=0)

        result = self.manager.get_segment_recipients("new_members")

        self.assertEqual(
            self._mine(result),
            {opted_in.email},
            "an opted-out member was included in a segment recipient list",
        )
        self.assertNotIn(opted_out.email, {r["email"] for r in result["recipients"]})

    def test_consent_flag_can_never_be_null(self):
        """Guard for the 'unset consent' branch elsewhere in the email module.

        SimplifiedEmailManager.send_to_chapter_segment('all') has an
        `accepts_optional_communications.isnull()` arm documented as
        "NULL (default/not set) = include", i.e. it would mail a member whose
        consent was never recorded. That arm is unreachable: the field is a
        Check, which MariaDB stores NOT NULL. If this test ever starts failing,
        that permissive arm becomes live and must be re-reviewed - it would mail
        people on an absent consent record.
        """
        # Assert the schema property directly. An earlier version wrapped a raw
        # UPDATE ... = NULL in assertRaises(Exception), which would also have passed
        # on a typo, a missing table or any unrelated SQL error — it proved nothing
        # about the column.
        nullable = frappe.db.sql("""
            SELECT IS_NULLABLE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'tabMember'
              AND COLUMN_NAME = 'accepts_optional_communications'
            """)
        self.assertTrue(nullable, "accepts_optional_communications column not found on tabMember")
        self.assertEqual(
            nullable[0][0],
            "NO",
            "accepts_optional_communications became nullable — the permissive "
            "isnull() arm in SimplifiedEmailManager is now live and would mail "
            "members whose consent was never recorded. Re-review it.",
        )

    def test_non_active_statuses_are_excluded(self):
        """Only status == 'Active' may be mailed; Quit/Expired/Suspended/Banned may not."""
        active = self._member("statusactive")
        excluded = {}
        for status in ("Quit", "Expired", "Suspended", "Banned", "Deceased"):
            m = self._member(f"status{status.lower()}")
            frappe.db.set_value("Member", m.name, "status", status, update_modified=False)
            excluded[status] = m.email

        result = self.manager.get_segment_recipients("new_members")
        mine = self._mine(result)

        self.assertEqual(
            mine,
            {active.email},
            f"non-Active members leaked into the recipient set: {mine - {active.email}}",
        )

    def test_blank_and_null_emails_are_excluded(self):
        """Members without a usable address must not produce empty recipients."""
        good = self._member("hasemail")
        blank = self._member("blankemail")
        frappe.db.set_value("Member", blank.name, "email", "", update_modified=False)
        nulled = self._member("nullemail")
        frappe.db.set_value("Member", nulled.name, "email", None, update_modified=False)

        result = self.manager.get_segment_recipients("new_members")

        self.assertEqual(self._mine(result), {good.email})
        self.assertNotIn("", [r["email"] for r in result["recipients"]])
        self.assertNotIn(None, [r["email"] for r in result["recipients"]])

    def test_chapter_filter_excludes_other_chapters_and_disabled_memberships(self):
        """chapter_name must restrict to *enabled* Chapter Member rows of that chapter."""
        in_chapter = self._member("inchapter")
        self._join_chapter(in_chapter)

        left_chapter = self._member("leftchapter")
        self._join_chapter(left_chapter, enabled=0)

        other_chapter_member = self._member("otherchapter")
        self._join_chapter(other_chapter_member, chapter=self.other_chapter)

        no_chapter = self._member("nochapter")

        result = self.manager.get_segment_recipients("new_members", chapter_name=self.chapter.name)
        mine = self._mine(result)

        self.assertEqual(
            mine,
            {in_chapter.email},
            "chapter-scoped segment must exclude disabled memberships, other chapters "
            f"and chapter-less members; got extras {mine - {in_chapter.email}}",
        )
        self.assertNotIn(left_chapter.email, mine)
        self.assertNotIn(other_chapter_member.email, mine)
        self.assertNotIn(no_chapter.email, mine)

    def test_unknown_segment_id_returns_error_not_everyone(self):
        """A typo'd / removed segment id must NOT silently fall back to mailing all."""
        self._member("unknownseg")

        result = self.manager.get_segment_recipients("does_not_exist")

        self.assertFalse(result["success"])
        self.assertNotIn("recipients", result)


class TestSegmentMembershipRules(SegmentationCohortMixin, EnhancedTestCase):
    """Per-segment membership logic and its boundary conditions."""

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def _backdate_creation(self, member, days_ago):
        frappe.db.sql(
            "UPDATE `tabMember` SET creation = DATE_SUB(NOW(), INTERVAL %s DAY) WHERE name = %s",
            (days_ago, member.name),
        )

    def test_new_members_boundary_is_30_days(self):
        """'New Members (Last 30 Days)' includes day 29, excludes day 31."""
        fresh = self._member("new0")
        day29 = self._member("new29")
        self._backdate_creation(day29, 29)
        day31 = self._member("new31")
        self._backdate_creation(day31, 31)

        result = self.manager.get_segment_recipients("new_members")

        self.assertEqual(self._mine(result), {fresh.email, day29.email})

    def test_long_term_members_boundary_is_two_years(self):
        """'Long-term Members (>2 Years)' includes 2y+1d old, excludes 2y-1d old."""
        just_under = self._member("lt729")
        self._backdate_creation(just_under, 365 * 2 - 2)
        just_over = self._member("lt732")
        self._backdate_creation(just_over, 365 * 2 + 3)

        result = self.manager.get_segment_recipients("long_term_members")

        self.assertEqual(self._mine(result), {just_over.email})

    def test_new_and_long_term_segments_are_disjoint(self):
        """No member may be simultaneously 'new' and 'long-term'."""
        self._member("disjointnew")
        old = self._member("disjointold")
        self._backdate_creation(old, 365 * 3)

        new_emails = self._mine(self.manager.get_segment_recipients("new_members"))
        long_emails = self._mine(self.manager.get_segment_recipients("long_term_members"))

        self.assertEqual(new_emails & long_emails, set())

    def test_volunteers_only_requires_an_active_volunteer_record(self):
        """Members with no volunteer record, or an inactive one, are excluded."""
        active_vol_member = self._member("volactive")
        self.create_test_volunteer(member_name=active_vol_member.name, status="Active")

        inactive_vol_member = self._member("volinactive")
        self.create_test_volunteer(member_name=inactive_vol_member.name, status="Inactive")

        plain_member = self._member("volnone")

        result = self.manager.get_segment_recipients("volunteers_only")
        mine = self._mine(result)

        self.assertEqual(
            mine,
            {active_vol_member.email},
            f"unexpected volunteers segment membership; extras {mine - {active_vol_member.email}}",
        )
        self.assertNotIn(inactive_vol_member.email, mine)
        self.assertNotIn(plain_member.email, mine)

    def test_volunteer_opt_out_still_wins(self):
        """An opted-out member who volunteers must still not receive segment mail."""
        opted_out_vol = self._member("volooptout", accepts_optional_communications=0)
        self.create_test_volunteer(member_name=opted_out_vol.name, status="Active")

        result = self.manager.get_segment_recipients("volunteers_only")

        self.assertNotIn(opted_out_vol.email, {r["email"] for r in result["recipients"]})

    def test_board_members_only_respects_is_active_and_term_end(self):
        """Board segment: active open-ended term in, expired term out, inactive row out."""
        current = self._member("boardcurrent")
        current_vol = self.create_test_volunteer(member_name=current.name, status="Active")

        expired = self._member("boardexpired")
        expired_vol = self.create_test_volunteer(member_name=expired.name, status="Active")

        deactivated = self._member("boarddeactivated")
        deactivated_vol = self.create_test_volunteer(member_name=deactivated.name, status="Active")

        plain_vol_member = self._member("boardnone")
        self.create_test_volunteer(member_name=plain_vol_member.name, status="Active")

        role = self._ensure_chapter_role()
        db_today = self._db_today()
        self.chapter.append(
            "board_members",
            {"volunteer": current_vol.name, "chapter_role": role, "from_date": db_today, "is_active": 1},
        )
        self.chapter.append(
            "board_members",
            {
                "volunteer": expired_vol.name,
                "chapter_role": role,
                "from_date": add_years(db_today, -2),
                "to_date": add_days(db_today, -1),
                "is_active": 1,
            },
        )
        self.chapter.append(
            "board_members",
            {
                "volunteer": deactivated_vol.name,
                "chapter_role": role,
                "from_date": add_years(db_today, -2),
                "is_active": 0,
            },
        )
        self.chapter.save()

        result = self.manager.get_segment_recipients("board_members_only")
        mine = self._mine(result)

        self.assertEqual(
            mine,
            {current.email},
            "board segment must contain only the current, non-expired, active board member; "
            f"got extras {mine - {current.email}}",
        )

    def _ensure_chapter_role(self):
        role_name = "Segmentation Test Board Role"
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
            return role.name
        return role_name

    def test_young_members_age_boundary_is_exclusive_at_35(self):
        """'Under 35' includes a 34-year-old, excludes someone who turned 35 today."""
        db_today = self._db_today()
        younger = self._member("age34", birth_date=add_days(add_years(db_today, -34), -1))
        exactly_35 = self._member("age35", birth_date=add_years(db_today, -35))
        older = self._member("age40", birth_date=add_years(db_today, -40))

        result = self.manager.get_segment_recipients("young_members")
        mine = self._mine(result)

        self.assertEqual(mine, {younger.email})
        self.assertNotIn(exactly_35.email, mine)
        self.assertNotIn(older.email, mine)

    def test_senior_members_age_boundary_is_inclusive_at_55(self):
        """'55+' includes someone who turned 55 today, excludes a 54-year-old."""
        db_today = self._db_today()
        exactly_55 = self._member("age55", birth_date=add_years(db_today, -55))
        older = self._member("age60", birth_date=add_years(db_today, -60))
        younger = self._member("age54", birth_date=add_days(add_years(db_today, -54), 1))

        result = self.manager.get_segment_recipients("senior_members")
        mine = self._mine(result)

        self.assertEqual(mine, {exactly_55.email, older.email})
        self.assertNotIn(younger.email, mine)

    def test_age_segments_exclude_members_without_a_birth_date(self):
        """Unknown age must not be silently bucketed into an age segment."""
        # The factory assigns a random 18-70y birth_date by default (and rejects
        # birth_date=None at creation), so clear it after the fact to model a
        # member whose age is genuinely unknown.
        no_dob = self._member("agenone")
        frappe.db.set_value("Member", no_dob.name, "birth_date", None, update_modified=False)
        known = self._member("ageknown", birth_date=add_years(self._db_today(), -60))

        result = self.manager.get_segment_recipients("senior_members")

        self.assertEqual(self._mine(result), {known.email})
        self.assertNotIn(no_dob.email, {r["email"] for r in result["recipients"]})


class TestSegmentDonationHistoryBug(SegmentationCohortMixin, EnhancedTestCase):
    """PRODUCT BUG: donor/non-donor segments join Donation.donor against tabMember.

    verenigingen/email/advanced_segmentation.py:271-303 builds:

        EXISTS (SELECT 1 FROM `tabDonation` d WHERE d.donor = m.name AND d.docstatus = 1)

    where `m` is `tabMember`. But `Donation.donor` is a Link to **Donor**
    (verenigingen/verenigingen/doctype/donation/donation.json), whose names are
    `DN-YY-NNNNN`, never `Assoc-Member-...`. The predicate is therefore always
    false, which means:
      * the "Donors" segment is ALWAYS EMPTY - donors never get donor mail;
      * the "Non-Donors" segment contains EVERY opted-in active member,
        including actual donors, who then get "please start donating" mail.

    The correct join goes through Donor.member (Donor has a `member` Link field):
        EXISTS (SELECT 1 FROM `tabDonation` d
                INNER JOIN `tabDonor` dn ON d.donor = dn.name
                WHERE dn.member = m.name AND d.docstatus = 1)
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def _make_donor_member(self, tag):
        member = self._member(tag)
        donor = self.create_test_donor(donor_name=f"Donor {tag}", donor_type="Individual")
        donor.member = member.name
        donor.save()
        donation = self.create_test_donation(donor=donor.name, amount=25.0)
        if donation.docstatus == 0:
            donation.submit()
        return member

    @unittest.expectedFailure
    def test_donors_segment_contains_members_who_donated(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        donor_member = self._make_donor_member("donoryes")
        self._member("donorno")

        result = self.manager.get_segment_recipients("donors")

        self.assertEqual(self._mine(result), {donor_member.email})

    @unittest.expectedFailure
    def test_non_donors_segment_excludes_members_who_donated(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        donor_member = self._make_donor_member("nondonoryes")
        non_donor = self._member("nondonorno")

        result = self.manager.get_segment_recipients("non_donors")
        mine = self._mine(result)

        self.assertIn(non_donor.email, mine)
        self.assertNotIn(donor_member.email, mine, "an existing donor was targeted as a 'Non-Donor'")


class TestUnimplementedSegmentsMailEveryone(SegmentationCohortMixin, EnhancedTestCase):
    """PRODUCT BUG: three advertised segments have no query branch and mail everyone.

    _get_built_in_segments() advertises `urban_members` (query_type
    "postal_code_type"), `event_attendees` ("event_attendance") and
    `inactive_members` ("activity_level") through the whitelisted
    get_available_segments() endpoint, so an administrator can pick them in the
    UI. But _get_built_in_segment_recipients (advanced_segmentation.py:188-339)
    has no branch for any of those three query types, so they fall through to the
    `else:` "Default fallback - all active members" at line 328.

    Result: picking "Inactive Members" or "Recent Event Attendees" silently mails
    the ENTIRE opted-in active membership. Unlike the "engagement" branch, this
    fallback carries no comment marking it as a placeholder.

    Correct behaviour: an unimplemented segment must return
    {"success": False, ...} (as _get_custom_segment_recipients already does for
    custom segments) rather than a full-membership blast.
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def test_unimplemented_segments_are_advertised_to_admins(self):
        """Guard: the bug matters only because these ids are user-selectable."""
        from verenigingen.email.advanced_segmentation import get_available_segments

        advertised = {s["id"] for s in get_available_segments()["segments"]}

        self.assertTrue(
            {"urban_members", "event_attendees", "inactive_members"} <= advertised,
            "unimplemented segments are no longer advertised - update this test",
        )

    @unittest.expectedFailure
    def test_inactive_members_segment_does_not_return_active_members(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        just_joined = self._member("inactivebug")

        result = self.manager.get_segment_recipients("inactive_members")

        self.assertNotIn(
            just_joined.email,
            {r["email"] for r in result.get("recipients", [])},
            "'Inactive Members' returned a member created seconds ago",
        )

    @unittest.expectedFailure
    def test_event_attendees_segment_does_not_return_non_attendees(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        never_attended = self._member("eventbug")

        result = self.manager.get_segment_recipients("event_attendees")

        self.assertNotIn(
            never_attended.email,
            {r["email"] for r in result.get("recipients", [])},
            "'Recent Event Attendees' returned a member with no event attendance",
        )

    @unittest.expectedFailure
    def test_engagement_segments_are_not_identical(self):
        """EXPECTED FAILURE - 'highly engaged' and 'low engagement' return the same set.

        Both engagement segments run the identical unfiltered query
        (advanced_segmentation.py:188-200), so re-engagement mail addressed to
        low-engagement members also goes to the most engaged ones.
        """
        self._member("engage")

        high = self._mine(self.manager.get_segment_recipients("highly_engaged"))
        low = self._mine(self.manager.get_segment_recipients("low_engagement"))

        self.assertNotEqual(high, low, "opposite engagement segments produced identical recipients")


class TestDuplicateRecipientsBug(SegmentationCohortMixin, EnhancedTestCase):
    """PRODUCT BUG: role-based segments emit one row per role, not per person.

    The volunteer and board queries (advanced_segmentation.py:231-269) SELECT
    DISTINCT over member columns PLUS role columns (`v.volunteer_name` /
    `cbm.chapter_role, cbm.parent`), and their outer INNER JOINs carry NO
    filtering - all the gating lives in an EXISTS subquery. So a member holding
    two board seats produces two recipient rows with the same address.

    Consequences:
      * the address is added to the Newsletter recipients table twice, so the
        member receives the mail twice;
      * `recipients_count` over-reports the audience size, and
        analyze_segment_overlap() divides by that inflated number, so its
        overlap/uniqueness percentages are wrong.

    Worse, because the outer join is unfiltered, the EXPIRED board row is emitted
    too: the payload advertises a chapter_role for a term that already ended.
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def _chapter_role(self, role_name="Segmentation Test Board Role"):
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

    @unittest.expectedFailure
    def test_member_with_two_board_seats_is_listed_once(self):
        """EXPECTED FAILURE - product bug, see class docstring."""
        member = self._member("dupboard")
        volunteer = self.create_test_volunteer(member_name=member.name, status="Active")
        role = self._chapter_role()

        db_today = self._db_today()
        self.chapter.append(
            "board_members",
            {"volunteer": volunteer.name, "chapter_role": role, "from_date": db_today, "is_active": 1},
        )
        self.chapter.save()
        self.other_chapter.append(
            "board_members",
            {"volunteer": volunteer.name, "chapter_role": role, "from_date": db_today, "is_active": 1},
        )
        self.other_chapter.save()

        result = self.manager.get_segment_recipients("board_members_only")
        occurrences = [r for r in result["recipients"] if r["email"] == member.email]

        self.assertEqual(
            len(occurrences), 1, "a member with two board seats appears once per seat in the mailing list"
        )

    @unittest.expectedFailure
    def test_expired_board_seat_is_not_emitted_alongside_the_current_one(self):
        """EXPECTED FAILURE - product bug, see class docstring.

        The member legitimately belongs to the segment (they hold a current
        seat), but the unfiltered outer join also emits their ENDED term, so the
        recipient payload carries a chapter_role the member no longer holds.
        """
        member = self._member("dupexpired")
        volunteer = self.create_test_volunteer(member_name=member.name, status="Active")
        current_role = self._chapter_role("Segmentation Test Current Role")
        former_role = self._chapter_role("Segmentation Test Former Role")

        db_today = self._db_today()
        self.chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": current_role,
                "from_date": db_today,
                "is_active": 1,
            },
        )
        self.chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": former_role,
                "from_date": add_years(db_today, -3),
                "to_date": add_days(db_today, -1),
                "is_active": 1,
            },
        )
        self.chapter.save()

        result = self.manager.get_segment_recipients("board_members_only")
        occurrences = [r for r in result["recipients"] if r["email"] == member.email]

        self.assertEqual(len(occurrences), 1, "an ended board term produced an extra recipient row")
        self.assertEqual(
            occurrences[0]["chapter_role"],
            current_role,
            "recipient payload advertises a board role whose term already ended",
        )


class TestSegmentCombination(SegmentationCohortMixin, EnhancedTestCase):
    """Set algebra over segments - the operation that builds ad-hoc audiences.

    Every call here is chapter-scoped to this test's own chapter, so the
    assertions are on the EXACT recipient set, not a subset of a shared site.
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def _chapter_member(self, tag, **kwargs):
        member = self._member(tag, **kwargs)
        self._join_chapter(member)
        return member

    def _build_new_volunteer_cohort(self):
        """new+volunteer, new-only, volunteer-only(old)."""
        self.both = self._chapter_member("combboth")
        self.create_test_volunteer(member_name=self.both.name, status="Active")

        self.new_only = self._chapter_member("combnew")

        self.vol_only = self._chapter_member("combvol")
        self.create_test_volunteer(member_name=self.vol_only.name, status="Active")
        frappe.db.sql(
            "UPDATE `tabMember` SET creation = DATE_SUB(NOW(), INTERVAL 200 DAY) WHERE name = %s",
            (self.vol_only.name,),
        )

    def _combine(self, segment_ids, operation):
        return self.manager.create_segment_combination(segment_ids, operation, self.chapter.name)

    def _emails(self, result):
        self.assertTrue(result.get("success"), result.get("error"))
        return {r["email"] for r in result["recipients"]}

    def test_intersection_returns_only_members_in_every_segment(self):
        self._build_new_volunteer_cohort()

        result = self._combine(["new_members", "volunteers_only"], "intersection")

        self.assertEqual(self._emails(result), {self.both.email})

    def test_union_returns_members_in_any_segment(self):
        self._build_new_volunteer_cohort()

        result = self._combine(["new_members", "volunteers_only"], "union")

        self.assertEqual(self._emails(result), {self.both.email, self.new_only.email, self.vol_only.email})

    def test_exclusion_subtracts_later_segments_from_the_first(self):
        """new_members MINUS volunteers_only keeps the non-volunteer new member only."""
        self._build_new_volunteer_cohort()

        result = self._combine(["new_members", "volunteers_only"], "exclusion")

        emails = self._emails(result)
        self.assertEqual(emails, {self.new_only.email})
        self.assertNotIn(self.both.email, emails, "exclusion kept a member present in the excluded segment")

    def test_combined_recipients_have_no_duplicate_addresses(self):
        """A union must not mail the same address twice."""
        self._build_new_volunteer_cohort()

        result = self._combine(["new_members", "volunteers_only"], "union")

        emails = [r["email"] for r in result["recipients"]]
        self.assertEqual(len(emails), len(set(emails)), "duplicate recipients in combined segment")

    def test_exclusion_requires_two_segments(self):
        result = self._combine(["new_members"], "exclusion")

        self.assertFalse(result["success"])
        self.assertIn("at least 2", result["error"])

    def test_unknown_operation_is_rejected_rather_than_defaulting(self):
        """An unrecognised operation must not silently fall back to union/all."""
        self._chapter_member("combbadop")

        result = self._combine(["new_members", "volunteers_only"], "difference")

        self.assertFalse(result["success"])
        self.assertNotIn("recipients", result)

    def test_empty_segment_list_is_rejected(self):
        result = self._combine([], "union")

        self.assertFalse(result["success"])

    def test_invalid_segment_id_aborts_the_whole_combination(self):
        """A bad id must not be silently dropped, leaving a broader audience."""
        self._chapter_member("combbadid")

        result = self._combine(["new_members", "nope_not_a_segment"], "union")

        self.assertFalse(result["success"])
        self.assertIn("nope_not_a_segment", result["error"])

    def test_combination_honours_the_opt_out(self):
        """Set algebra must never reintroduce an opted-out member."""
        opted_out = self._chapter_member("combooptout", accepts_optional_communications=0)
        self.create_test_volunteer(member_name=opted_out.name, status="Active")
        kept = self._chapter_member("combokay")

        for operation in ("union", "intersection"):
            with self.subTest(operation=operation):
                result = self._combine(["new_members", "volunteers_only"], operation)
                self.assertNotIn(opted_out.email, self._emails(result))

        self.assertIn(kept.email, self._emails(self._combine(["new_members", "volunteers_only"], "union")))


class TestSegmentOverlapAnalysis(SegmentationCohortMixin, EnhancedTestCase):
    """Overlap analysis drives audience-sizing decisions; the maths must be right.

    Chapter-scoped like TestSegmentCombination, so the numbers below are exact.
    """

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def _chapter_member(self, tag, **kwargs):
        member = self._member(tag, **kwargs)
        self._join_chapter(member)
        return member

    def _analyze(self, segment_ids):
        return self.manager.analyze_segment_overlap(segment_ids, self.chapter.name)

    def test_requires_at_least_two_segments(self):
        result = self._analyze(["new_members"])

        self.assertFalse(result["success"])

    def test_self_overlap_is_always_total(self):
        self._chapter_member("ovself")

        result = self._analyze(["new_members", "volunteers_only"])

        self.assertTrue(result["success"], result.get("error"))
        for seg_id in ("new_members", "volunteers_only"):
            self.assertEqual(result["overlap_matrix"][seg_id][seg_id]["percentage"], 100.0)

    def test_overlap_counts_are_symmetric_and_exact(self):
        """|A intersect B| == |B intersect A|, and equals the one shared member."""
        overlapper = self._chapter_member("ovboth")
        self.create_test_volunteer(member_name=overlapper.name, status="Active")
        self._chapter_member("ovnew")

        result = self._analyze(["new_members", "volunteers_only"])

        a_b = result["overlap_matrix"]["new_members"]["volunteers_only"]["count"]
        b_a = result["overlap_matrix"]["volunteers_only"]["new_members"]["count"]
        self.assertEqual(a_b, b_a)
        self.assertEqual(a_b, 1)

    def test_unique_and_overlapping_counts_sum_to_the_segment_size(self):
        """Every member of a segment is either unique to it or shared with the other."""
        shared = self._chapter_member("ovshared")
        self.create_test_volunteer(member_name=shared.name, status="Active")
        self._chapter_member("ovonlynew")

        result = self._analyze(["new_members", "volunteers_only"])

        self.assertEqual(result["segments"]["new_members"]["count"], 2)
        self.assertEqual(result["segments"]["volunteers_only"]["count"], 1)
        for seg_id, other in (("new_members", "volunteers_only"), ("volunteers_only", "new_members")):
            total = result["segments"][seg_id]["count"]
            unique = result["unique_members"][seg_id]["count"]
            overlap = result["overlap_matrix"][seg_id][other]["count"]
            self.assertEqual(unique + overlap, total, f"{seg_id}: unique+overlap != segment size")

    def test_total_unique_members_is_the_union_size(self):
        shared = self._chapter_member("ovunionshared")
        self.create_test_volunteer(member_name=shared.name, status="Active")
        self._chapter_member("ovunionnew")

        overlap = self._analyze(["new_members", "volunteers_only"])
        union = self.manager.create_segment_combination(
            ["new_members", "volunteers_only"], "union", self.chapter.name
        )

        self.assertEqual(overlap["total_unique_members"], 2)
        self.assertEqual(overlap["total_unique_members"], union["recipients_count"])


class TestSegmentSuggestions(SegmentationCohortMixin, EnhancedTestCase):
    """get_segment_suggestions() must not divide by zero or invent proportions."""

    def setUp(self):
        super().setUp()
        self._setup_cohort()
        self.manager = AdvancedSegmentationManager()

    def test_empty_chapter_yields_stats_without_dividing_by_zero(self):
        """A brand-new chapter has zero eligible members; suggestions must still work."""
        result = self.manager.get_segment_suggestions(self.chapter.name)

        self.assertTrue(result["success"], result.get("error"))
        self.assertEqual(result["chapter_stats"]["total_members"], 0)
        # The two always-on engagement suggestions remain, none of the ratio ones fire.
        suggested = {s["segment_id"] for s in result["suggestions"]}
        self.assertEqual(suggested, {"highly_engaged", "low_engagement"})

    def test_chapter_stats_count_only_opted_in_active_members(self):
        """The stats query applies the same consent/status gate as the segments."""
        counted = self._member("sugcounted")
        self._join_chapter(counted)

        opted_out = self._member("sugoptout", accepts_optional_communications=0)
        self._join_chapter(opted_out)

        quit_member = self._member("sugquit")
        frappe.db.set_value("Member", quit_member.name, "status", "Quit", update_modified=False)
        self._join_chapter(quit_member)

        result = self.manager.get_segment_suggestions(self.chapter.name)

        self.assertEqual(
            result["chapter_stats"]["total_members"],
            1,
            "chapter stats counted an opted-out or non-active member",
        )

    def test_new_member_suggestion_fires_for_a_freshly_populated_chapter(self):
        """All members brand new => >10% new => the new_members suggestion appears."""
        for tag in ("sugnew1", "sugnew2"):
            self._join_chapter(self._member(tag))

        result = self.manager.get_segment_suggestions(self.chapter.name)

        suggested = {s["segment_id"] for s in result["suggestions"]}
        self.assertIn("new_members", suggested)
        self.assertEqual(result["chapter_stats"]["new_members"], 2)

    def test_volunteer_suggestion_reflects_actual_volunteer_count(self):
        volunteer_member = self._member("sugvol")
        self.create_test_volunteer(member_name=volunteer_member.name, status="Active")
        self._join_chapter(volunteer_member)

        result = self.manager.get_segment_suggestions(self.chapter.name)

        self.assertEqual(result["chapter_stats"]["volunteers"], 1)
        self.assertIn("volunteers_only", {s["segment_id"] for s in result["suggestions"]})
