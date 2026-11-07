"""
Real-integration tests for the chapter ``MemberManager``
``verenigingen/verenigingen/doctype/chapter/managers/member_manager.py``.

The manager owns chapter membership operations (add / join-request / approve /
reject / remove / update / list / search / export / stats). It is reached in
production via ``chapter_doc.member_manager`` (a lazily-built
``MemberManager(self)``), so every test resolves the manager that way to mirror
the real call path rather than instantiating the class directly.

Tests create real Members and Chapters via the test factory (no business-logic
mocking) and run as Administrator. Notification helpers send through the unified
EmailService and are wrapped in try/except in production, so they are exercised
indirectly via approve/reject/join and asserted only on their observable side
effects (status, history, comments) -- the email send itself is a no-op in the
test environment.
"""

import json

import frappe
from frappe.utils import today

from verenigingen.tests.utils.base import VereningingenTestCase


class TestMemberManager(VereningingenTestCase):
    """Exercise the chapter MemberManager end to end via chapter.member_manager."""

    def setUp(self):
        super().setUp()
        # Membership-history side effects are partly event-driven; run subscribers
        # inline so history rows are created deterministically within the test.
        self._prev_run_events_sync = getattr(frappe.flags, "run_events_synchronously", False)
        frappe.flags.run_events_synchronously = True

        self.chapter = self.create_test_chapter(
            chapter_name=f"MemberMgr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="MemberMgr",
            last_name="Primary",
            email=f"membermgr.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    def tearDown(self):
        frappe.flags.run_events_synchronously = self._prev_run_events_sync
        super().tearDown()

    # ------------------------------------------------------------------ helpers

    @property
    def manager(self):
        """Resolve the manager the same way production does."""
        return self.chapter.member_manager

    def _reload_chapter(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        return self.chapter

    def _make_member(self, status="Active", first="Extra"):
        return self.create_test_member(
            first_name=first,
            last_name="MemberMgr",
            email=f"membermgr.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status=status,
        )

    # ------------------------------------------------------------------ add_member

    def test_add_member_happy_path(self):
        result = self.manager.add_member(self.member.name, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "added")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "Active")
        self.assertTrue(row.enabled)
        self.assertEqual(str(row.chapter_join_date), today())

    def test_add_member_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_member("", notify=False)

    def test_add_member_nonexistent_member_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.add_member("NONEXISTENT-MEMBER-XYZ", notify=False)

    def test_add_member_already_in_chapter_is_rejected(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.add_member(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_exists")

    def test_add_member_inactive_member_is_disabled_in_chapter(self):
        # Members who are not Active should be force-disabled / Inactive in the
        # chapter regardless of the requested enabled flag.
        #
        # #1582: the row is created, but the call must NOT report success -- the
        # member is exactly as invisible to the board as if nothing had been added
        # (same contract as #1564's re-enable branch).
        suspended = self._make_member(status="Suspended", first="Suspended")
        result = self.manager.add_member(suspended.name, enabled=True, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "added_disabled")

        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

    def test_add_member_new_row_reports_disabled_outcome_for_every_non_active_status(self):
        # #1582: every status _derive_membership_status maps to (0, Inactive).
        # Real flow: create_test_member(status=...) then add_member; the row's
        # actual state is read back and must agree with the reported outcome.
        for status in ("Pending", "Suspended", "Quit", "Deceased"):
            with self.subTest(status=status):
                member = self._make_member(status=status, first=f"New{status}")
                result = self.manager.add_member(member.name, enabled=True, notify=False)
                self._reload_chapter()
                row = self.manager._find_chapter_member(member.name)
                self.assertIsNotNone(row)
                self.assertFalse(row.enabled)
                self.assertFalse(result["success"], result)
                self.assertEqual(result["action"], "added_disabled")

    def test_add_member_new_row_explicit_disabled_request_is_still_success(self):
        # Control for #1582: the caller ASKED for enabled=False on an Active
        # member, so a disabled row is the requested outcome, not a failure. A
        # fix keyed on the row's enabled flag alone would break this.
        result = self.manager.add_member(self.member.name, enabled=False, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "added")
        self._reload_chapter()
        self.assertFalse(self.manager._find_chapter_member(self.member.name).enabled)

    def test_add_member_new_row_outcome_names_status_to_a_reader(self):
        # #1582: a caller who may read the Member is told why (an unreadable caller
        # is covered in the join-request coverage tests, which need a board seat).
        suspended = self._make_member(status="Suspended", first="Disclose")
        result = self.manager.add_member(suspended.name, enabled=True, notify=False)
        self.assertIn("Suspended", result["message"])

    def test_add_member_honours_explicit_join_date(self):
        result = self.manager.add_member(self.member.name, join_date="2024-01-15", notify=False)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(str(row.chapter_join_date), "2024-01-15")

    def test_add_member_reenables_disabled_member(self):
        # First add then disable (non-permanent) so a disabled row exists.
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        self.manager.remove_member(self.member.name, leave_reason="testing", notify=False)
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertFalse(row.enabled)

        result = self.manager.add_member(self.member.name, enabled=True, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "re-enabled")
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        self.assertIsNone(row.leave_reason)

    def test_add_member_reenable_restores_status_after_termination(self):
        # #1547: reproduce through the REAL writers, not db.set_value. add_member
        # (Active) -> disable_chapter_memberships_safe (the real termination
        # writer used by MembershipTerminationRequest execution) -> add_member
        # again (the re-add path, since the row now reads enabled=0).
        from verenigingen.services.termination.termination_integration import (
            disable_chapter_memberships_safe,
        )

        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        self.assertEqual(row.status, "Active")

        # disable_chapter_memberships_safe disables EVERY enabled Chapter Member
        # row for this member, not only self.chapter's -- member creation can
        # seed a shared default-chapter membership alongside it -- so assert on
        # self.chapter's own row rather than on a specific disabled_count.
        disabled_count = disable_chapter_memberships_safe(self.member.name, today(), "termination test")
        self.assertGreaterEqual(disabled_count, 1)
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

        result = self.manager.add_member(self.member.name, enabled=True, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "re-enabled")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        # Before the fix this stayed 'Inactive': enabled=1 + status='Inactive'
        # matches neither the list- nor doc-level "member is visible" condition,
        # so the re-add silently produced an invisible member (#1547).
        self.assertEqual(row.status, "Active")

    def test_add_member_reenable_does_not_activate_non_active_member(self):
        # Opposite harm (#1547): a member whose CURRENT Member.status is not
        # Active must not come out of the re-enable branch as status='Active'.
        # A Suspended member is already force-disabled on the FIRST add_member
        # call (test_add_member_inactive_member_is_disabled_in_chapter), so a
        # second add_member call takes the re-enable branch directly.
        suspended = self._make_member(status="Suspended", first="ReenableSuspended")
        self.manager.add_member(suspended.name, enabled=True, notify=False)
        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

        result = self.manager.add_member(suspended.name, enabled=True, notify=False)
        # #1564: the return value must report what actually happened, not an
        # unconditional "re-enabled" claim. _derive_membership_status keeps this
        # row disabled/Inactive because the member is Suspended, so the branch
        # must say so rather than telling the caller it succeeded at
        # re-enabling while the member stays exactly as invisible to the board
        # as before the call.
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "not_reenabled")
        self.assertIn(suspended.status, result["message"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

    def test_assign_member_to_chapter_api_does_not_report_false_success(self):
        # #1564 outcome sweep: the real production consumer of this return
        # value is the whitelisted verenigingen.api.member_management.
        # assign_member_to_chapter (called from members_without_chapter.js's
        # "assign chapter" report button). It converts result.get("success")
        # straight into an OperationResult.ok(..., message="Member {0} has
        # been assigned to {1}") shown to the admin as a success toast.
        # Before this fix, a Suspended member whose row was already disabled
        # would report that false "assigned" success while staying invisible
        # to the board. Drive the REAL re-enable branch through add_member
        # first (not db.set_value), then hit the exact API endpoint.
        from verenigingen.api.member_management import assign_member_to_chapter as api_assign

        suspended = self._make_member(status="Suspended", first="ApiReenableSuspended")
        self.manager.add_member(suspended.name, enabled=True, notify=False)
        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)

        result = api_assign(suspended.name, self.chapter.name)
        self.assertFalse(result["success"])
        self.assertIn(suspended.status, result["error"]["message"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(suspended.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

    def test_add_member_reenable_preserves_pending_row_for_approval_to_activate(self):
        # #1547 follow-up (round 2, found by CI; round 3 rewritten per review to
        # drop the raw-SQL shortcut -- create_pending_chapter_membership followed
        # by remove_member(permanent=False) reaches enabled=0/status='Pending'
        # through REAL writers, no db.set_value/raw SQL needed at all).
        #
        # approve_application calls ChapterMembershipManager.
        # assign_member_to_chapter -> MemberManager.add_member BEFORE flipping the
        # applicant's Member.status from Pending to Active (assign_member_to_
        # chapter runs at membership_application_review.py:700; the status flip
        # happens inside create_membership_on_approval, called afterwards at line
        # ~728; the actual Pending->Active flip for the CHAPTER row happens later
        # still, at _activate_pending_chapter_memberships, line 738). Round 1's
        # unconditional derive-from-member_doc.status in the re-enable branch
        # read the PRE-approval 'Pending' status and stamped 'Inactive' over a
        # row _activate_pending_chapter_memberships depends on finding as
        # 'Pending' -- stranding it before that later, real activation step ever
        # ran. Reproduce the exact real-writer ordering the approval flow uses:
        #   create_pending_chapter_membership (real submission writer) ->
        #   remove_member(permanent=False) (real "leave chapter" writer, the
        #   writer behind the whitelisted leave_chapter endpoint,
        #   chapter.py:1165) -> assign_member_to_chapter (the real re-enable
        #   writer, member still Pending) -> Member.status flip (real .save(),
        #   mirroring create_membership_on_approval) ->
        #   activate_pending_chapter_membership (the real, later activation
        #   writer).
        from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
        from verenigingen.services.member.approval.application_helpers import (
            activate_pending_chapter_membership,
            create_pending_chapter_membership,
        )

        applicant = self._make_member(status="Pending", first="ApprovalOrdering")

        # Real writer #1: application-submission chapter assignment.
        # enabled=1, status='Pending'.
        create_pending_chapter_membership(applicant, self.chapter.name)
        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertTrue(row.enabled)
        self.assertEqual(row.status, "Pending")

        # Real writer #2: the applicant leaves the chapter before approval.
        # remove_member(permanent=False) only ever sets enabled=0 -- it does not
        # touch status -- so this leaves enabled=0, status='Pending'.
        result = self.manager.remove_member(applicant.name, permanent=False, notify=False)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Pending")

        # Real writer #3: the exact call approve_application makes
        # (via assign_member_to_chapter) BEFORE the applicant's Member.status is
        # flipped to Active. applicant.status is still "Pending" here.
        self.assertEqual(frappe.db.get_value("Member", applicant.name, "status"), "Pending")
        result = ChapterMembershipManager.assign_member_to_chapter(
            member_id=applicant.name, chapter_name=self.chapter.name
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("action"), "re-enabled")

        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertTrue(row.enabled)
        # This is the follow-up regression: round 1 alone stamped 'Inactive'
        # here, before the real activation step ever got a chance to run.
        self.assertEqual(row.status, "Pending")

        # Real writer #4: the Member.status flip create_membership_on_approval
        # performs (a real .save(), not db_set/db.set_value).
        applicant.reload()
        applicant.status = "Active"
        applicant.save()

        # Real writer #5: the exact call _activate_pending_chapter_memberships
        # makes, now that the applicant is actually Active.
        activate_pending_chapter_membership(applicant, self.chapter.name)

        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertTrue(row.enabled)
        self.assertEqual(row.status, "Active")

    def test_add_member_reenable_pending_row_for_now_suspended_member_stays_disabled(self):
        # Opposite-harm control found in round-3 review: the Pending carve-out
        # above must NOT be unconditional. A Pending row belonging to a member
        # who has since moved to Suspended (or any other non-Active/non-Pending
        # status) is no longer "mid-approval" -- re-adding it must derive
        # normally and stay disabled/Inactive, exactly like #1547's original
        # Suspended control, not be silently restored to enabled=1 just because
        # the row still says 'Pending'.
        #
        # Real writers throughout: create_pending_chapter_membership ->
        # remove_member(permanent=False) (identical setup to the test above) ->
        # a real Member.status change to Suspended (an ordinary .save(), which
        # the ORM allows) -> add_member.
        from verenigingen.services.member.approval.application_helpers import (
            create_pending_chapter_membership,
        )

        applicant = self._make_member(status="Pending", first="ReenablePendingSuspended")

        create_pending_chapter_membership(applicant, self.chapter.name)
        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertTrue(row.enabled)
        self.assertEqual(row.status, "Pending")

        result = self.manager.remove_member(applicant.name, permanent=False, notify=False)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Pending")

        # Real writer: the applicant is Suspended (not terminated via a
        # dedicated service, just an ordinary status change the ORM permits --
        # matching how the review reproduced this).
        applicant.reload()
        applicant.status = "Suspended"
        applicant.save()

        result = self.manager.add_member(applicant.name, enabled=True, notify=False)
        # #1564: same as the Suspended control above -- the row derives
        # disabled/Inactive here (member is now Suspended, the Pending
        # carve-out no longer applies), so the return value must not claim
        # "re-enabled" success.
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "not_reenabled")
        self.assertIn(applicant.status, result["message"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(applicant.name)
        # Before this guard, a Suspended member with a stale Pending row was
        # silently restored to enabled=1 just because existing_member.status
        # still read 'Pending' -- exactly the shape #1547 exists to prevent.
        self.assertFalse(row.enabled)
        self.assertEqual(row.status, "Inactive")

    # ------------------------------------------------------------------ request_to_join

    def test_request_to_join_creates_pending(self):
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "requested")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)
        self.assertEqual(row.status, "Pending")

        # Directly guard the add_membership_history(status="Pending") call: the
        # Chapter Member row above is written before it, so without this assertion
        # the kwarg-drift bug would pass undetected.
        history = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Pending",
            },
        )
        self.assertGreater(len(history), 0, "join request should append a Pending history row")

    def test_request_to_join_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.request_to_join("", notify=False)

    def test_request_to_join_notifies_active_board_without_error(self):
        # With an active board member present, the old _notify_board_of_join_request
        # read board_member.member (a nonexistent field) -> AttributeError, swallowed
        # and logged. Assert the join request notification path no longer errors.
        board_member = self.create_test_member(
            first_name="Board",
            last_name="Notify",
            email=f"board.notify.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member_name=board_member.name)
        role_name = f"BoardNotify{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "permissions_level": "Basic"}
        ).insert()
        self.add_board_member_to_chapter(
            self.chapter, volunteer, role_name, email=board_member.email
        )
        self._reload_chapter()

        self.manager.request_to_join(self.member.name, notify=True)

        errored = frappe.get_all(
            "Error Log",
            filters={"error": ["like", "%Error sending join request notification%"]},
        )
        self.assertEqual(len(errored), 0, "board notification must not error on a populated board")

    def _seat_active_board_member(self):
        """Seat one active board member with an email; return that email."""
        board_member = self.create_test_member(
            first_name="Board",
            last_name="JoinMail",
            email=f"board.joinmail.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        volunteer = self.create_test_volunteer(member_name=board_member.name)
        # #2208: the seat must belong to the board member, not an auto-built second Member.
        self.assertEqual(volunteer.member, board_member.name)
        role_name = f"BoardJoinMail{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "permissions_level": "Basic"}
        ).insert()
        self.add_board_member_to_chapter(self.chapter, volunteer, role_name, email=board_member.email)
        self._reload_chapter()
        # The row's email is fetched from the Volunteer on save, so read it back rather than
        # assuming the address we passed in.
        return [r.email for r in self.chapter.board_members if r.is_active and r.email][-1]

    def _own_join_key_row(self, enabled=1):
        """Give ``chapter_join_request_submitted`` exactly one config row with ``enabled``.

        A key with no Verenigingen Email Configuration row counts as disabled (#1959), so the
        send is skipped unless a row exists. Seed only this key (not the whole registry, which
        leaked 88 rows while singleton_backup skipped child tables, #2029; fixed in #2091) and restore the original rows afterwards.

        request_to_join commits mid-test, so the seeded row is COMMITTED; an uncommitted restore
        would then be rolled back by the class rollback. The restore therefore commits too.
        """
        from verenigingen.notification_registry import NOTIFICATION_KEYS
        from verenigingen.setup.notification_registry_setup import _registry_row

        key = "chapter_join_request_submitted"
        fields = [
            f.fieldname
            for f in frappe.get_meta("Email Notification Type").fields
            if f.fieldtype != "Section Break"
        ]
        config = frappe.get_single("Verenigingen Email Configuration")
        original = [{f: r.get(f) for f in fields} for r in config.notification_types]
        self.addCleanup(self._cleanup_config_rows, original)

        rows = [r for r in original if r["notification_key"] != key]
        rows.append({**_registry_row(key, NOTIFICATION_KEYS[key]), "enabled": enabled})
        config.set("notification_types", rows)
        config.save()

    @staticmethod
    def _cleanup_config_rows(rows):
        config = frappe.get_single("Verenigingen Email Configuration")
        config.set("notification_types", rows)
        config.save()
        # request_to_join committed the seeded row, so only a committed restore leaves the site
        # as we found it (#2029; singleton_backup would now do this too, #2159). Named _cleanup_* so the order-dependence scan records it as exempt.
        frappe.db.commit()

    @staticmethod
    def _join_mails_to(address):
        """Decoded HTML bodies of the "New Chapter Join Request" mails queued for ``address``."""
        import email

        parents = frappe.get_all("Email Queue Recipient", filters={"recipient": address}, pluck="parent")
        bodies = []
        for q in frappe.get_all("Email Queue", filters={"name": ["in", parents or [""]]}, fields=["message"]):
            msg = email.message_from_string(q.message)
            if "New Chapter Join Request" not in str(msg["Subject"]):
                continue  # the board member also gets an unrelated welcome mail when seated
            html = [
                part.get_payload(decode=True).decode("utf-8")
                for part in msg.walk()
                if part.get_content_type() == "text/html"
            ]
            bodies.append(html[0])
        return bodies

    def test_request_to_join_really_mails_the_board(self):
        """#2007: the board must actually receive the join-request mail.

        The old call used send_notification("chapter_assignment"), which is not in that
        method's map, so it returned fail("Unknown notification type") and the caller
        discarded it: no mail, no log. Drives the real request_to_join (a Pending Chapter
        Member row is written by raw SQL, so no after_insert board mail exists on this path).
        """
        self._own_join_key_row()
        board_email = self._seat_active_board_member()

        result = self.manager.request_to_join(self.member.name, notify=True)

        self.assertTrue(result["success"], result)
        mails = self._join_mails_to(board_email)
        self.assertEqual(len(mails), 1, f"board got {len(mails)} join mails")
        self.assertIn(self.chapter.name, mails[0])
        self.assertIn(self.member.full_name, mails[0])
        self.assertNotIn("join_request", mails[0], "the raw request_type slug is shown to the board")
        # The review button must point at this chapter on this site (the template needs base_url).
        # (the mail inliner percent-encodes the href)
        from urllib.parse import quote

        self.assertIn(f"{frappe.utils.get_url()}/app/chapter/{quote(self.chapter.name)}", mails[0])

    def test_two_applicants_each_reach_the_board(self):
        """#2007 F1: the per-recipient cooldown on the key must not swallow a second applicant.

        Without cooldown_scope the second request, inside the 60 minute window, is skipped.
        """
        self._own_join_key_row()
        board_email = self._seat_active_board_member()
        second = self._make_member(first="Second")

        self.assertTrue(self.manager.request_to_join(self.member.name, notify=True)["success"])
        self.assertTrue(self.manager.request_to_join(second.name, notify=True)["success"])

        mails = self._join_mails_to(board_email)
        self.assertEqual(len(mails), 2, f"board got {len(mails)} join mails for 2 applicants")
        self.assertTrue(any(self.member.full_name in m for m in mails))
        self.assertTrue(any(second.full_name in m for m in mails))

    def test_rejoin_request_also_mails_the_board(self):
        """The rejoin call site (an Inactive, still enabled row) notifies the board too.

        Real writers only: add_member records a Suspended member Inactive/disabled, then
        update_member_info(enabled=True) re-enables the row, leaving enabled=1 + Inactive.
        (Reject deletes the row, so it cannot produce this state.)
        """
        self._own_join_key_row()
        board_email = self._seat_active_board_member()
        member = self._make_member(status="Suspended", first="Rejoin")
        # #1582: the row is written, but the call reports added_disabled, not success.
        self.assertEqual(self.manager.add_member(member.name, notify=False)["action"], "added_disabled")
        self._reload_chapter()
        self.assertTrue(self.manager.update_member_info(member.name, enabled=True)["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(member.name)
        self.assertEqual((row.status, row.enabled), ("Inactive", 1), "control: the rejoin state")
        # #2021: only an Active member may request. Reinstatement is a db_set shortcut here (the
        # row state above is the part driven through real writers).
        member.db_set("status", "Active")

        result = self.manager.request_to_join(member.name, notify=True)

        self.assertEqual(result["action"], "rejoin_requested", result)
        mails = self._join_mails_to(board_email)
        self.assertEqual(len(mails), 1)
        self.assertIn(member.full_name, mails[0])

    def test_join_mail_honours_the_disabled_key(self):
        """Control for the key: a disabled ``chapter_join_request_submitted`` row sends nothing.

        Catches a send with the notification_key dropped or a different key.
        """
        self._own_join_key_row(enabled=0)
        board_email = self._seat_active_board_member()

        self.assertTrue(self.manager.request_to_join(self.member.name, notify=True)["success"])

        self.assertEqual(self._join_mails_to(board_email), [])

    def test_join_mail_skips_inactive_board_rows(self):
        """An inactive board seat gets nothing; the active one (control) does."""
        self._own_join_key_row()
        active_email = self._seat_active_board_member()
        inactive_email = self._seat_active_board_member()
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        for row in chapter.board_members:
            if row.email == inactive_email:
                row.is_active = 0
        chapter.save()
        self._reload_chapter()

        self.assertTrue(self.manager.request_to_join(self.member.name, notify=True)["success"])

        self.assertEqual(len(self._join_mails_to(active_email)), 1)
        self.assertEqual(self._join_mails_to(inactive_email), [])

    def test_join_request_board_mail_failure_is_logged_not_swallowed(self):
        """#2007: a failed send result must reach the Error Log, not vanish."""
        from unittest.mock import patch

        from verenigingen.services.communication.email_service import EmailService
        from verenigingen.utils.operation_result import OperationResult

        self._seat_active_board_member()
        # Mock justified: External Service - forces the send to report failure
        with patch.object(
            EmailService, "send_templated_email", return_value=OperationResult.fail("boom-2007")
        ):
            self.expectErrorLog("boom-2007")  # only suppresses; the assertion is below
            start = frappe.utils.now()
            self.manager.request_to_join(self.member.name, notify=True)

        logged = frappe.get_all(
            "Error Log", filters={"creation": [">=", start], "error": ["like", "%boom-2007%"]}
        )
        self.assertEqual(len(logged), 1, "the failed send result was discarded")

    def test_request_to_join_nonexistent_member_returns_failure(self):
        # request_to_join wraps its body in try/except and returns a failure dict
        # rather than raising (the throw is caught and reported).
        result = self.manager.request_to_join("NONEXISTENT-MEMBER-XYZ", notify=False)
        self.assertFalse(result["success"])

    def test_request_to_join_already_pending(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_pending")

    def test_request_to_join_already_active_member(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.request_to_join(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "already_member")

    # ------------------------------------------------------------------ approve_member_request

    def test_approve_member_request_happy_path(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name, approved_by="Administrator")
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(row.status, "Active")
        self.assertEqual(str(row.chapter_join_date), today())

    def test_approve_member_request_no_request(self):
        result = self.manager.approve_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("No membership request", result["message"])

    def test_approve_member_request_not_pending(self):
        # An already-active member is not pending and cannot be approved.
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("not pending", result["message"])

    def test_approve_member_request_promotes_row_to_active(self):
        # The join request already wrote a Pending history row;
        # ChapterMembershipHistoryManager deliberately refuses to add an "Active"
        # row while a "Pending" one exists (it warns to use update_membership_status
        # instead). So the observable, durable effect of approval is that the
        # Chapter Member row flips to Active -- assert that rather than a new row.
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.approve_member_request(self.member.name)
        self.assertTrue(result["success"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertEqual(row.status, "Active")

        # The originating Pending history row is still present (not lost on approve).
        pending = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Pending",
            },
        )
        self.assertGreater(len(pending), 0)

    # ------------------------------------------------------------------ reject_member_request

    def test_reject_member_request_happy_path(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.reject_member_request(
            self.member.name, reason="not eligible", rejected_by="Administrator"
        )
        self.assertTrue(result["success"])

        # The pending row is removed entirely on rejection.
        self._reload_chapter()
        self.assertIsNone(self.manager._find_chapter_member(self.member.name))

    def test_reject_member_request_no_request(self):
        result = self.manager.reject_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("No membership request", result["message"])

    def test_reject_member_request_not_pending(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.reject_member_request(self.member.name)
        self.assertFalse(result["success"])
        self.assertIn("not pending", result["message"])

    def test_reject_member_request_records_rejected_history(self):
        self.manager.request_to_join(self.member.name, notify=False)
        self._reload_chapter()
        self.manager.reject_member_request(self.member.name, reason="dupe")
        # "Rejected" is not a valid Chapter Membership History status; the manager
        # records a declined request as Inactive (see member_manager fix comment).
        history = frappe.get_all(
            "Chapter Membership History",
            filters={
                "parent": self.member.name,
                "parenttype": "Member",
                "chapter_name": self.chapter.name,
                "status": "Inactive",
            },
        )
        self.assertGreater(len(history), 0, "rejection should append an Inactive history row")

    # ------------------------------------------------------------------ remove_member

    def test_remove_member_disable(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.remove_member(self.member.name, leave_reason="moved away", notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "disabled")

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertIsNotNone(row)  # still present, just disabled
        self.assertFalse(row.enabled)
        self.assertEqual(row.leave_reason, "moved away")

    def test_remove_member_permanent(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        result = self.manager.remove_member(self.member.name, permanent=True, notify=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "removed")

        self._reload_chapter()
        self.assertIsNone(self.manager._find_chapter_member(self.member.name))

    def test_remove_member_requires_member_id(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.remove_member("", notify=False)

    def test_remove_member_not_in_chapter(self):
        result = self.manager.remove_member(self.member.name, notify=False)
        self.assertFalse(result["success"])
        self.assertEqual(result["action"], "not_found")

    # ------------------------------------------------------------------ update_member_info

    def test_update_member_info_disable_then_reenable(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()

        # Disable via update -> leave_reason auto-populated.
        result = self.manager.update_member_info(self.member.name, enabled=False)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "updated")
        self.assertIn("enabled status", result["changes"])

        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertFalse(row.enabled)
        self.assertTrue(row.leave_reason)

        # Re-enable via update -> leave_reason cleared.
        result = self.manager.update_member_info(self.member.name, enabled=True)
        self.assertTrue(result["success"])
        self._reload_chapter()
        row = self.manager._find_chapter_member(self.member.name)
        self.assertTrue(row.enabled)
        self.assertIsNone(row.leave_reason)

    def test_update_member_info_no_changes(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        # Member is already enabled; setting enabled=True is a no-op.
        result = self.manager.update_member_info(self.member.name, enabled=True)
        self.assertTrue(result["success"])
        self.assertEqual(result["action"], "no_changes")

    def test_update_member_info_not_in_chapter_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self.manager.update_member_info(self.member.name, enabled=False)

    # ------------------------------------------------------------------ get_members

    def test_get_members_excludes_disabled_by_default(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="Disabled")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        members = self.manager.get_members()
        ids = {m["member_id"] for m in members}
        self.assertIn(self.member.name, ids)
        self.assertNotIn(disabled.name, ids)

    def test_get_members_include_disabled(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="Disabled2")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        members = self.manager.get_members(include_disabled=True)
        ids = {m["member_id"] for m in members}
        self.assertIn(disabled.name, ids)

    def test_get_members_with_details(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        members = self.manager.get_members(with_details=True)
        row = next(m for m in members if m["member_id"] == self.member.name)
        self.assertEqual(row["email"], self.member.email)
        self.assertIn("status", row)
        self.assertEqual(row["member_name"], self.member.full_name)

    # ------------------------------------------------------------------ search_members

    def test_search_members_by_name(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        results = self.manager.search_members("MemberMgr")
        ids = {m["member_id"] for m in results}
        self.assertIn(self.member.name, ids)

    def test_search_members_no_match(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        results = self.manager.search_members("ZZZ-no-such-name-ZZZ")
        self.assertEqual(results, [])

    def test_search_members_empty_query_returns_all(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        # Empty query short-circuits to get_members().
        results = self.manager.search_members("")
        ids = {m["member_id"] for m in results}
        self.assertIn(self.member.name, ids)

    # ------------------------------------------------------------------ export_members

    def test_export_members_json(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        out = self.manager.export_members(format="json")
        data = json.loads(out)
        self.assertTrue(any(m["member_id"] == self.member.name for m in data))

    def test_export_members_csv_has_header_and_row(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        out = self.manager.export_members(format="csv")
        lines = out.splitlines()
        self.assertIn("Member ID", lines[0])
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn(self.member.name, out)

    def test_export_members_csv_empty(self):
        out = self.manager.export_members(format="csv")
        self.assertEqual(out, "No members to export")

    def test_export_members_unsupported_format_throws(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        with self.assertRaises(frappe.ValidationError):
            self.manager.export_members(format="xml")

    # ------------------------------------------------------------------ get_member_statistics

    def test_get_member_statistics_counts(self):
        self.manager.add_member(self.member.name, notify=False)
        disabled = self._make_member(first="StatDisabled")
        self._reload_chapter()
        self.manager.add_member(disabled.name, notify=False)
        self._reload_chapter()
        self.manager.update_member_info(disabled.name, enabled=False)
        self._reload_chapter()

        stats = self.manager.get_member_statistics()
        self.assertEqual(stats["total_members"], 2)
        self.assertEqual(stats["enabled_members"], 1)
        self.assertEqual(stats["disabled_members"], 1)
        # primary_members is derived from a cross-chapter "most recent enabled
        # chapter" DB query, so its exact value depends on global Chapter Member
        # state we don't own here. Assert the partition is internally consistent
        # rather than a specific count.
        self.assertEqual(
            stats["primary_members"] + stats["secondary_members"], stats["enabled_members"]
        )
        self.assertIsInstance(stats["primary_members"], int)

    # ------------------------------------------------------------------ get_summary

    def test_get_summary_includes_stats_and_recent(self):
        self.manager.add_member(self.member.name, notify=False)
        self._reload_chapter()
        summary = self.manager.get_summary()
        self.assertIn("total_members", summary)
        self.assertIn("recent_additions", summary)
        self.assertIn("recent_removals", summary)
        self.assertIn("last_updated", summary)

    # ------------------------------------------------------------------ _get_member_name

    def test_get_member_name_returns_the_members_full_name(self):
        other = self._make_member(first="NameLookup")
        self.assertEqual(self.manager._get_member_name(other.name), other.full_name)

    def test_get_member_name_falls_back_to_the_id_for_an_unknown_member(self):
        self.assertEqual(self.manager._get_member_name("MEM-DOES-NOT-EXIST-1743"), "MEM-DOES-NOT-EXIST-1743")
        # A caller passes member.get("member", ""); that must not resolve to some other row.
        self.assertEqual(self.manager._get_member_name(""), "")

    def test_get_member_name_reads_one_row_not_the_whole_member(self):
        """#1743: it used to load the whole Member (one select per child table) to read
        ``full_name``; a chapter save calls it once per added member."""
        other = self._make_member(first="NameLookupCost")
        manager = self.manager
        # Warm per-process metadata on a different member so the count is the lookup alone.
        manager._get_member_name(self.member.name)
        with self.assertQueryCount(1):
            manager._get_member_name(other.name)
