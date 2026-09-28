# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Branch-coverage tests for verenigingen.api.membership_application_review.

Targets branches not exercised by test_approval_helpers / test_membership_approval:

- reject_membership_application full flow (status update, membership cancel,
  pending-chapter removal, invalid-status guard, invalid-template guard).
- get_user_chapter_access admin branch and member-without-board branch.
- get_pending_applications listing + chapter filter + days_overdue filter.
- _activate_pending_chapter_memberships (pending -> active flip).
- assign_member_to_chapter (no-op for empty chapter; real assignment).
- update_payment_history_for_invoice mismatch guard.

Real DB fixtures only; no business-logic mocking. @high_security_api /
@standard_api serialise results, but these endpoints return plain dicts.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.api.membership_application_review import (
    _activate_pending_chapter_memberships,
    assign_member_to_chapter,
    get_pending_applications,
    get_user_chapter_access,
    reject_membership_application,
    update_payment_history_for_invoice,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


def _grant_medium_access(email):
    """Grant MEDIUM access needed to pass the @standard_api gate.

    get_user_chapter_access is decorated @standard_api (SecurityLevel.MEDIUM);
    a sub-MEDIUM caller is denied with a raised PermissionError before the body
    runs.

    The authorization policy grants MEDIUM to "Verenigingen Volunteer" via BOTH
    the role-profile path (rule 4) and the individual-role path (rule 5). We assign
    the *role* directly — not just the role_profile_name Link — because:

      - On Frappe v16 the single `role_profile_name` Link is deprecated/cleared in
        favour of the `role_profiles` child table, so a bare `db.set_value` of
        role_profile_name silently resolves to no profiles (observed in CI:
        `user_profiles=[]` -> rule_7_deny -> PermissionError). The role-based path
        does not depend on that field.
      - Role membership is resolved through `frappe.get_roles()`, which `set_user`
        recomputes deterministically, so it is immune to the versioned
        `user_role_profiles` cache churn that other shards trigger via
        `invalidate_user_role_cache()`. The previous `delete_keys("user_role_profiles")`
        was the wrong (and order-dependent) invalidation entry point.

    Assigning the role makes rule 5 (individual_role -> MEDIUM) grant access
    regardless of role-profile cache state, fixing the full-shard order-dependence.
    """
    user = frappe.get_doc("User", email)
    if not any(r.role == "Verenigingen Volunteer" for r in user.roles):
        user.append("roles", {"role": "Verenigingen Volunteer"})
        user.save()
    frappe.db.commit()
    # Recompute the freshly-saved role set so the next set_user() sees the new role.
    frappe.clear_cache(user=email)


def _ensure_membership_type():
    if not frappe.db.exists("Item Group", "Membership"):
        frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": "Membership",
                "parent_item_group": "All Item Groups",
                "is_group": 0,
            }
        ).insert()
    name = "Review Cov Membership"
    if not frappe.db.exists("Membership Type", name):
        frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": name,
                "minimum_amount": 15,
                "role_profile": "Verenigingen Member",
            }
        ).insert()
    return name


class TestRejectMembershipApplication(EnhancedTestCase):
    """reject_membership_application: canonical rejection flow.

    Covers the status/notes update, the invalid-status / invalid-template /
    nonexistent-member guards, and the Draft-membership delete branch. The
    refund branch (process_refund) and the Lead-update branch are not
    exercised: process_refund defaults False, and this site has no Lead.member
    field (so frappe.db.exists("Lead", {"member": ...}) is inert here).
    """

    def _pending_member(self):
        member = self.create_test_member(
            first_name="RevReject",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"revreject-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", "Pending", update_modified=False)
        member.db_set("application_status", "Pending", update_modified=False)
        member.reload()
        return member

    def _make_draft_membership_with_referenced_schedule(self, member):
        """A draft Membership whose dues schedule is still named by a
        submitted Sales Invoice via membership_dues_schedule_display. Not
        committed -- reject_membership_application (the code under test)
        reads on the SAME connection within the same test, and this fixture
        relies on EnhancedTestCase's own per-test rollback/drain for cleanup
        rather than an explicit commit (#815/order_dependence ratchet: this
        helper is not named _create_*/_cleanup_*, so a bare commit here
        would not be exempt -- and even an exempt one is zero-growth-gated).
        """
        membership_type = _ensure_membership_type()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type,
                "start_date": today(),
                "status": "Draft",
            }
        )
        membership.flags.ignore_validate = True
        membership.insert(ignore_mandatory=True)

        schedule = frappe.new_doc("Membership Dues Schedule")
        schedule.schedule_name = f"REJECT-COV-{frappe.generate_hash(length=6)}"
        schedule.membership_type = membership_type
        schedule.membership = membership.name
        schedule.status = "Active"
        schedule.billing_frequency = "Annual"
        schedule.currency = "EUR"
        schedule.is_template = 0
        schedule.dues_rate = 25
        schedule.flags.ignore_validate = True
        schedule.insert(ignore_permissions=True, ignore_mandatory=True)

        company = "_Test Company"
        customer = frappe.db.get_value("Customer", {}, "name")
        item = frappe.db.get_value("Item", {"is_sales_item": 1}, "name")
        income_account = frappe.db.get_value(
            "Account",
            {
                "company": company,
                "account_type": "Income Account",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", company, "default_currency"),
            },
            "name",
        )
        cost_center = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0}, "name")
        invoice = frappe.new_doc("Sales Invoice")
        invoice.customer = customer
        invoice.company = company
        invoice.membership_dues_schedule_display = schedule.name
        invoice.set_posting_time = 1
        invoice.append(
            "items",
            {
                "item_code": item,
                "qty": 1,
                "rate": 25,
                "income_account": income_account,
                "cost_center": cost_center,
            },
        )
        invoice.insert(ignore_permissions=True)
        invoice.submit()
        return membership, schedule, invoice

    def test_reject_pending_member(self):
        member = self._pending_member()
        # send_rejection_notification renders a template; allow expected logging.
        self.expectErrorLog("Email", "Notification", "Template", "rejection")
        result = reject_membership_application(
            member.name,
            reason="Application incomplete",
            rejection_category="Incomplete",
            internal_notes="Reviewer note",
        )
        self.assertTrue(result["success"])
        self.assertFalse(result["refund_processed"])

        member.reload()
        self.assertEqual(member.application_status, "Rejected")
        self.assertEqual(member.status, "Rejected")
        # Composite review notes include category + reason.
        self.assertIn("Rejection Category: Incomplete", member.review_notes)
        self.assertIn("Application incomplete", member.review_notes)
        self.assertIn("Internal Notes: Reviewer note", member.review_notes)

    def test_reject_deletes_draft_membership(self):
        """A Draft (docstatus 0) Membership for the member is deleted on reject."""
        member = self._pending_member()
        membership_type = _ensure_membership_type()
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type,
                "start_date": today(),
                "status": "Draft",
            }
        )
        membership.flags.ignore_validate = True
        membership.insert(ignore_mandatory=True)
        membership_name = membership.name
        self.assertEqual(frappe.db.get_value("Membership", membership_name, "docstatus"), 0)

        self.expectErrorLog("Email", "Notification", "Template", "rejection")
        result = reject_membership_application(member.name, reason="Withdraw")
        self.assertTrue(result["success"])
        # The Draft membership is removed by the reject path (review.py:696-703).
        self.assertFalse(frappe.db.exists("Membership", membership_name))

    def test_reject_with_referenced_schedule_throws_clear_message(self):
        """#1264 round 2: Membership.on_trash's schedule cleanup now respects
        link-integrity (round 1 of this PR) instead of force-deleting the
        schedule. If the draft Membership being deleted on rejection has a
        dues schedule still named by a submitted Sales Invoice, the delete
        now raises LinkExistsError from inside on_trash's own cascade -- this
        test asserts the call-site catch turns that into a clear, translated,
        invoice-naming message (not a raw LinkExistsError), and that the
        rejection does not silently half-apply.

        Atomicity is verified by spying on frappe.db.commit() rather than by
        calling frappe.db.rollback() ourselves: this function's own module
        comment says "Frappe automatically commits successful transactions"
        -- i.e. only the request layer commits, and only on success -- so
        proving THIS call never invokes commit() before raising is the
        empirical check that a real request's automatic rollback-on-exception
        would leave member.save()'s status change undone. (A self-performed
        rollback would also revert this test's own fixture rows, since they
        are deliberately left uncommitted -- see
        _make_draft_membership_with_referenced_schedule.)
        """
        member = self._pending_member()
        membership, schedule, invoice = self._make_draft_membership_with_referenced_schedule(member)
        # No explicit cleanup registered here: EnhancedTestCase's own
        # captured-insert drain (_drain_captured_inserts ->
        # _remove_drained_record) already cancels-then-deletes every
        # submitted document inserted during the test, including this
        # invoice, and cleans up the schedule too -- see that method's own
        # docstring. A hand-written cleanup helper here would be redundant
        # AND -- confirmed by round 3's review -- invisible to the
        # order-dependence scanner if it lived outside a test_*.py file,
        # which is exactly the gate-evasion this round removes.

        commit_calls = []
        original_commit = frappe.db.commit
        frappe.db.commit = lambda *a, **kw: commit_calls.append(1)
        try:
            with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
                reject_membership_application(member.name, reason="Withdraw")
        finally:
            frappe.db.commit = original_commit

        self.assertIn(invoice.name, str(ctx.exception))
        self.assertEqual(
            commit_calls,
            [],
            "reject_membership_application must not commit before raising -- a "
            "real request's automatic rollback-on-exception is only atomic if "
            "nothing was committed first",
        )

        # The schedule and its invoice reference must survive -- the whole
        # point of the fix this is testing.
        self.assertTrue(frappe.db.exists("Membership Dues Schedule", schedule.name))
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", invoice.name, "membership_dues_schedule_display"),
            schedule.name,
        )
        self.assertTrue(frappe.db.exists("Membership", membership.name))

    def test_reject_approved_member_throws(self):
        member = self._pending_member()
        member.db_set("application_status", "Approved", update_modified=False)
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application(member.name, reason="too late")

    def test_invalid_email_template_throws(self):
        member = self._pending_member()
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application(
                member.name,
                reason="bad template",
                email_template="NONEXISTENT-TEMPLATE-COV-12345",
            )

    def test_nonexistent_member_throws(self):
        # _validate_member_for_review logs a security event then throws.
        with self.assertRaises(frappe.exceptions.ValidationError):
            reject_membership_application("NONEXISTENT-MEMBER-REV-12345", reason="x")

    def test_nonexistent_member_logs_a_valid_audit_event(self):
        """#1417: _validate_member_for_review used to call log_security_event()
        with event_type="invalid_member_access", which is not a valid API Audit
        Log.event_type Select option. _store_audit_event's own `except Exception`
        swallowed the resulting ValidationError and only wrote it to the Error
        Log -- so the structured audit row was silently never stored; only the
        reject_membership_application() ValidationError surfaced to the caller.
        Assert the audit row actually lands, with no error logged.
        """
        member_name = "NONEXISTENT-MEMBER-AUDIT-1417"
        with self.assertNoErrorLog():
            with self.assertRaises(frappe.exceptions.ValidationError):
                reject_membership_application(member_name, reason="x")

        row = frappe.db.get_value(
            "API Audit Log",
            {"details": ["like", f"%{member_name}%"]},
            ["event_type", "severity"],
            as_dict=True,
        )
        self.assertIsNotNone(
            row, "no API Audit Log row was stored for the nonexistent-member rejection attempt"
        )
        self.assertEqual(row.event_type, "unauthorized_access_attempt")
        self.assertEqual(row.severity, "error")


class TestRejectMembershipApplicationChapterCleanup(EnhancedTestCase):
    """#1573 round 2 (maintainer ruling, recorded on the issue and in the author
    brief's policy paragraph): once validate_chapter_permission_or_throw has
    authorized a reviewer to reject THIS application, the cleanup must remove
    ALL of the applicant's own Pending Chapter Member rows with elevated rights
    (`system_operation=True` on the underlying Chapter save), including rows in
    chapters the reviewer does not personally manage. Round 1 (edc25875a) only
    made a cleanup failure throw instead of swallow -- that caused the OPPOSITE
    harm review then reproduced through the REAL, unmocked resubmit flow: an
    applicant who resubmits with a different `selected_chapter`
    (api.membership_application._handle_existing_member Scenario 2) ends up
    Pending in TWO chapters, because create_pending_chapter_membership only
    guards against a duplicate row in the SAME chapter and nothing removes the
    OLD chapter's row on resubmit. A board member seated on only one of those
    chapters could then never reject the applicant at all -- filed separately,
    see this class's own test for the reproduction and the report for the
    cross-linked issue.
    """

    def setUp(self):
        super().setUp()
        run = frappe.generate_hash(length=6)
        self.own_chapter = self.ensure_test_chapter(f"TEST Cleanup Own {run}")
        self.other_chapter = self.ensure_test_chapter(f"TEST Cleanup Other {run}")
        self.board = self.create_test_board_member(self.own_chapter.name, permissions_level="Admin")
        self.membership_type = _ensure_membership_type()

    def _submit_application_for_chapter(self, email, chapter_name):
        from verenigingen.api.membership_application import submit_application

        result = submit_application(
            first_name="CleanupFail",
            last_name=f"Applicant{frappe.generate_hash(length=6)}",
            email=email,
            birth_date="1990-01-01",
            address_line1="123 Test Street",
            city="Amsterdam",
            postal_code="1234AB",
            country="Netherlands",
            selected_membership_type=self.membership_type,
            selected_chapter=chapter_name,
        )
        self.assertTrue(result["success"], msg=f"submit_application failed: {result}")
        return result

    def _applicant_pending_in_both_chapters_via_resubmit(self):
        """Real (unmocked) reproduction, through the actual submission API, of an
        applicant Pending in two chapters at once: two submit_application() calls
        with the SAME email and a different selected_chapter each time. No
        create_pending_chapter_membership call, no db_set of chapter state --
        both Pending rows are the ones production's own resubmit path writes.
        """
        unique = frappe.generate_hash(length=8)
        email = f"resubmit-{unique}@example.com"

        first = self._submit_application_for_chapter(email, self.own_chapter.name)
        member_name = first["data"]["member_record"]

        second = self._submit_application_for_chapter(email, self.other_chapter.name)
        self.assertEqual(
            second["data"]["member_record"],
            member_name,
            "the resubmission must reuse the SAME member record (Scenario 2), not "
            "create a second one -- otherwise this is not the resubmit scenario",
        )

        member = frappe.get_doc("Member", member_name)
        self.assertEqual(member.application_status, "Pending")

        # Precondition this whole class is about: BOTH chapters hold a real
        # Pending row after nothing but two ordinary resubmissions.
        for chapter_name in (self.own_chapter.name, self.other_chapter.name):
            self.assertEqual(
                frappe.db.get_value(
                    "Chapter Member", {"parent": chapter_name, "member": member_name}, "status"
                ),
                "Pending",
                f"setup precondition failed: {chapter_name} should hold a real Pending "
                f"row purely from the resubmit flow",
            )
        return member

    def test_board_member_can_reject_applicant_pending_in_an_unmanaged_chapter_too(self):
        """(a) The reproduction: single-chapter board member's reject must now
        succeed and leave 0 Pending Chapter Member rows anywhere for this member."""
        member = self._applicant_pending_in_both_chapters_via_resubmit()
        self.expectErrorLog("Email", "Notification", "Template", "rejection")

        with self.as_user(self.board.user):
            result = reject_membership_application(member.name, reason="elevated cleanup repro")

        self.assertTrue(
            result.get("success"), f"reject must succeed once cleanup runs elevated: {result}"
        )

        member.reload()
        self.assertEqual(member.application_status, "Rejected")

        remaining = frappe.get_all("Chapter Member", filters={"member": member.name, "status": "Pending"})
        self.assertEqual(
            remaining,
            [],
            f"a Pending Chapter Member row survived rejection: {remaining} -- elevation "
            f"must reach every one of the applicant's own Pending rows, not just the "
            f"chapter the reviewing board member happens to manage",
        )

    def test_genuine_non_permission_cleanup_failure_still_aborts_with_generic_message(self):
        """(b) Control: elevation only lifts the ACTOR's permission check. A real,
        non-permission failure while saving an EXISTING chapter must still abort
        the reject atomically, and the caller-facing message must name no chapter
        -- only the Error Log may.

        #1573 round 3: this used to reuse the "chapter no longer exists" shape as
        its stand-in for "genuine failure" -- but round 3 changed THAT shape to be
        handled (the orphan is deleted and counted as removed, see the
        TestChapterMembershipApprovalIntegration regression test), so it is no
        longer a failure at all and would silently prove nothing here. Rewritten
        to use a REAL Chapter business-rule validation failure instead:
        ChapterValidator's PostalCodeValidator genuinely rejects a range pattern
        whose start exceeds its end (postal_code_validator.py's
        `_validate_range_pattern`) -- "Range start 9999 cannot be greater than
        range end 1000". Setting other_chapter.postal_codes to "9999-1000" via a
        direct frappe.db.set_value (disclosed: this stages the SETUP precondition
        without going through Chapter.save() -- the mechanism under test is
        Chapter.validate() itself, which genuinely runs and genuinely throws when
        OUR code's cleanup save() reaches it) reproduces exactly that.
        """
        member = self._applicant_pending_in_both_chapters_via_resubmit()

        frappe.db.set_value(
            "Chapter", self.other_chapter.name, "postal_codes", "9999-1000", update_modified=False
        )

        self.expectErrorLog(
            "Chapter Removal Error",
            "Pending chapter cleanup incomplete",
            "Secure Operation Failed",
            "cannot be greater than",
        )

        commit_calls = []
        original_commit = frappe.db.commit
        frappe.db.commit = lambda *a, **kw: commit_calls.append(1)
        try:
            with self.assertErrorLog("Pending chapter cleanup incomplete"):
                with self.as_user(self.board.user):
                    with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
                        reject_membership_application(member.name, reason="genuine failure repro")
        finally:
            frappe.db.commit = original_commit

        self.assertEqual(
            commit_calls,
            [],
            "reject_membership_application must not commit before raising -- a real "
            "request's automatic rollback-on-exception is only atomic if nothing was "
            "committed first",
        )

        caller_message = str(ctx.exception)
        for name in (self.own_chapter.name, self.other_chapter.name):
            self.assertNotIn(
                name,
                caller_message,
                f"the caller-facing message must be generic and must not name {name}",
            )

        # The failure IS still recorded -- just to the Error Log, not the caller.
        # remove_pending_chapter_membership's own except-block calls
        # frappe.log_error(title="Chapter Removal Error", message=f"...{str(e)}")
        # (#1573 round 5 fixed this call's argument order -- it used to pass
        # them positionally and swapped, the #602-class trap), so `method`
        # holds the short literal title and the real validation reason lands
        # in `error` (the message) directly.
        log_row = frappe.db.get_value(
            "Error Log",
            {"method": ["like", "%Chapter Removal Error%"]},
            "error",
        )
        self.assertIn(
            "cannot be greater than",
            log_row or "",
            "the real validation reason must still reach the Error Log",
        )

        # The Pending row on the still-existing (but invalid) chapter must
        # survive -- the whole point of aborting rather than reporting success.
        self.assertEqual(
            frappe.db.get_value(
                "Chapter Member", {"parent": self.other_chapter.name, "member": member.name}, "status"
            ),
            "Pending",
            "a genuine (non-permission) cleanup failure must not silently drop the row",
        )

    def test_orphan_cleanup_is_scoped_to_this_member_and_leaves_other_members_rows_alone(self):
        """Mutant (b) control (#1573 round 3): the orphan-delete inside
        remove_pending_chapter_membership must be scoped to THIS member's own
        Pending row on THIS missing chapter -- not just the missing parent
        chapter name. A control row for a DIFFERENT member, pointing at the
        SAME orphaned chapter name, must survive our member's rejection
        untouched.
        """
        member = self._applicant_pending_in_both_chapters_via_resubmit()

        stale_chapter_name = "NONEXISTENT-CHAPTER-1573-ORPHAN-SCOPE"
        row_name = frappe.db.get_value(
            "Chapter Member", {"parent": self.other_chapter.name, "member": member.name}, "name"
        )
        frappe.db.set_value("Chapter Member", row_name, "parent", stale_chapter_name, update_modified=False)

        # A control row for an UNRELATED member, sharing the SAME orphaned
        # parent chapter name. Inserted directly (there is no real Chapter left
        # to append it through) -- the same technique
        # test_chapter_membership_approval_integration.py's own pre-existing
        # orphan regression test uses.
        other_member = self.create_test_member(
            first_name="OrphanControl",
            last_name=f"Other{frappe.generate_hash(length=6)}",
            email=f"orphan-control-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        control_row_name = frappe.generate_hash(length=10)
        frappe.db.sql(
            """INSERT INTO `tabChapter Member`
               (name, parent, parenttype, parentfield, member, status, idx, enabled)
               VALUES (%s, %s, 'Chapter', 'members', %s, 'Pending', 1, 1)""",
            (control_row_name, stale_chapter_name, other_member.name),
        )

        self.expectErrorLog("Orphaned pending chapter membership removed")

        with self.as_user(self.board.user):
            result = reject_membership_application(member.name, reason="orphan scoping repro")

        self.assertTrue(result.get("success"), f"reject must succeed once the orphan is cleaned up: {result}")

        remaining = frappe.get_all("Chapter Member", filters={"member": member.name, "status": "Pending"})
        self.assertEqual(remaining, [], f"a Pending row survived rejection: {remaining}")

        self.assertTrue(
            frappe.db.exists("Chapter Member", {"name": control_row_name}),
            "cleanup must not delete another member's row just because it shares the "
            "same (orphaned) parent chapter name",
        )

    def test_unauthorized_caller_is_still_refused_at_the_entry_gate(self):
        """(c) Control: elevation must not widen WHO may call reject at all. A
        board member seated on NEITHER of the applicant's chapters is still
        refused by validate_chapter_permission_or_throw, before any cleanup (or
        elevation) is reached, and leaves no trace."""
        member = self._applicant_pending_in_both_chapters_via_resubmit()

        outsider_chapter = self.ensure_test_chapter(f"TEST Cleanup Outsider {frappe.generate_hash(length=6)}")
        outsider = self.create_test_board_member(outsider_chapter.name, permissions_level="Admin")

        error_log_count_before = frappe.db.count("Error Log")

        with self.as_user(outsider.user):
            with self.assertRaises(frappe.PermissionError):
                reject_membership_application(member.name, reason="should be refused at entry")

        member.reload()
        self.assertEqual(
            member.application_status,
            "Pending",
            "an entry-gate refusal must not have mutated application_status",
        )
        for chapter_name in (self.own_chapter.name, self.other_chapter.name):
            self.assertEqual(
                frappe.db.get_value(
                    "Chapter Member", {"parent": chapter_name, "member": member.name}, "status"
                ),
                "Pending",
                f"an entry-gate refusal must not touch the Pending row in {chapter_name}",
            )
        self.assertEqual(
            frappe.db.count("Error Log"),
            error_log_count_before,
            "an unauthorized caller must be refused with no Error Log trace from the "
            "cleanup path -- elevation must not be reachable without first clearing "
            "the entry gate",
        )

    def test_basic_level_board_member_is_refused_at_entry_gate_despite_member_write_access(self):
        """(d) The DISCRIMINATING entry-gate control: unlike (c)'s outsider (whose
        board seat was on an unrelated chapter, so Frappe's own Member doc-level
        permission ALSO happened to deny them -- see that test's docstring), this
        caller has a real, active board seat on the applicant's OWN chapter, just
        at `permissions_level="Basic"` rather than Admin/Membership.

        - `validate_chapter_permission_or_throw` -> `get_user_manageable_chapters`
          only counts Admin/Membership seats (chapter_security.py), so this caller
          is refused at the entry gate.
        - But `member.save()`'s own permission check
          (`permissions.has_member_permission` ->
          `get_user_chapter_memberships_cached`, permissions.py:81-107) grants
          WRITE to ANY active board seat on a chapter where the applicant holds a
          row, with NO `permissions_level` filter at all.

        So for THIS caller the entry gate is the ONLY thing refusing the reject --
        if it were ever bypassed or removed, member.save() would let it through
        and the elevated cleanup would run for a caller chapter_security itself
        judged unauthorized. Confirmed by mutation (see report): RED (reject
        SUCCEEDS) with the validate_chapter_permission_or_throw call removed,
        GREEN with it restored.
        """
        member = self._applicant_pending_in_both_chapters_via_resubmit()
        basic_board = self.create_test_board_member(self.own_chapter.name, permissions_level="Basic")

        error_log_count_before = frappe.db.count("Error Log")

        with self.as_user(basic_board.user):
            with self.assertRaises(frappe.PermissionError):
                reject_membership_application(
                    member.name, reason="Basic-level board member should be refused"
                )

        member.reload()
        self.assertEqual(
            member.application_status,
            "Pending",
            "an entry-gate refusal must not have mutated application_status",
        )
        for chapter_name in (self.own_chapter.name, self.other_chapter.name):
            self.assertEqual(
                frappe.db.get_value(
                    "Chapter Member", {"parent": chapter_name, "member": member.name}, "status"
                ),
                "Pending",
                f"an entry-gate refusal must not touch the Pending row in {chapter_name}",
            )
        self.assertEqual(
            frappe.db.count("Error Log"),
            error_log_count_before,
            "a Basic-level board member must be refused with no Error Log trace",
        )


class TestGetUserChapterAccess(EnhancedTestCase):
    """get_user_chapter_access: admin vs member-without-board branches."""

    def test_admin_sees_all_chapters(self):
        # Tests run as Administrator, which holds an admin role.
        result = get_user_chapter_access()
        self.assertTrue(result["is_admin"])
        self.assertFalse(result["restrict_to_chapters"])

    def test_non_member_user_is_restricted(self):
        """A logged-in user with no Member record is restricted and flagged."""
        email = f"chapaccess-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "ChapAccess",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert()
        self.track_doc("User", user.name)
        _grant_medium_access(user.name)

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            result = get_user_chapter_access()
        finally:
            frappe.set_user(original)

        self.assertFalse(result["is_admin"])
        self.assertTrue(result["restrict_to_chapters"])
        self.assertEqual(result["chapters"], [])
        self.assertEqual(result["message"], "User is not a member")

    def test_member_without_board_access_has_no_chapters(self):
        """A member with no board positions gets restrict_to_chapters with empty list."""
        email = f"plainmember-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "PlainMember",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        )
        user.insert()
        self.track_doc("User", user.name)

        member = self.create_test_member(
            first_name="Plain",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=email,
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("user", user.name, update_modified=False)
        frappe.db.commit()
        _grant_medium_access(user.name)

        original = frappe.session.user
        try:
            frappe.set_user(user.name)
            result = get_user_chapter_access()
        finally:
            frappe.set_user(original)

        self.assertFalse(result["is_admin"])
        # No board positions -> user_chapters empty -> not restricted (len == 0).
        self.assertEqual(result["chapters"], [])
        self.assertFalse(result["restrict_to_chapters"])


class TestGetPendingApplications(EnhancedTestCase):
    """get_pending_applications: listing + filters (run as Administrator)."""

    def _pending_member(self, *, application_date=None, membership_type=None):
        member = self.create_test_member(
            first_name="Pending",
            last_name=f"App{frappe.generate_hash(length=6)}",
            email=f"pendapp-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        member.db_set("status", "Pending", update_modified=False)
        member.db_set("application_status", "Pending", update_modified=False)
        if application_date:
            member.db_set("application_date", application_date, update_modified=False)
        if membership_type:
            member.db_set("selected_membership_type", membership_type, update_modified=False)
        frappe.db.commit()
        return member

    def test_lists_pending_member(self):
        membership_type = _ensure_membership_type()
        member = self._pending_member(application_date=today(), membership_type=membership_type)
        result = get_pending_applications()
        names = [r["name"] for r in result]
        self.assertIn(member.name, names)
        row = next(r for r in result if r["name"] == member.name)
        # A today-dated application has 0 days pending (pins the getdate diff).
        self.assertEqual(row["days_pending"], 0)
        self.assertEqual(row["current_chapter_display"], "Unassigned")

    def test_days_overdue_filter_excludes_recent(self):
        recent = self._pending_member(application_date=today())
        # days_overdue=10 means application_date < today-10; a today application
        # must be excluded.
        result = get_pending_applications(days_overdue=10)
        names = [r["name"] for r in result]
        self.assertNotIn(recent.name, names)

    def test_chapter_filter_unassigned_excludes_member_with_chapter(self):
        """Pins the chapter-filter continue branch: 'Unassigned' includes a
        chapterless member but excludes one that has a Chapter Member row."""
        chapterless = self._pending_member(application_date=today())

        # Second pending member WITH an enabled Chapter Member row.
        region = frappe.get_all("Region", limit=1, pluck="name")
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Filter Chapter {frappe.generate_hash(length=6)}",
                "region": region[0] if region else None,
                "published": 1,
                "introduction": "Coverage filter chapter",
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)

        member_with_chapter = self._pending_member(application_date=today())
        chapter.append(
            "members",
            {
                "member": member_with_chapter.name,
                "status": "Active",
                "enabled": 1,
                "chapter_join_date": today(),
            },
        )
        chapter.save()
        frappe.db.commit()

        result = get_pending_applications(chapter="Unassigned")
        names = [r["name"] for r in result]
        self.assertIn(chapterless.name, names)
        # Member WITH a chapter is skipped by the "Unassigned" continue branch.
        self.assertNotIn(member_with_chapter.name, names)


class TestAssignMemberToChapter(EnhancedTestCase):
    """assign_member_to_chapter: guard for empty chapter."""

    def test_empty_chapter_is_noop(self):
        member = self.create_test_member(
            first_name="NoChapter",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"nochapter-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        # Should return without raising and without doing anything.
        self.assertIsNone(assign_member_to_chapter(member, None))
        self.assertIsNone(assign_member_to_chapter(member, ""))


class TestActivatePendingChapterMemberships(EnhancedTestCase):
    """_activate_pending_chapter_memberships: flip Pending Chapter Member rows."""

    def test_no_pending_rows_is_noop(self):
        member = self.create_test_member(
            first_name="NoPending",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"nopending-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        # No Chapter Member rows -> should complete silently.
        try:
            _activate_pending_chapter_memberships(member)
        except Exception as exc:  # pragma: no cover - defensive
            self.fail(f"_activate_pending_chapter_memberships raised: {exc}")

    def test_pending_row_is_activated(self):
        region = frappe.get_all("Region", limit=1, pluck="name")
        chapter = frappe.get_doc(
            {
                "doctype": "Chapter",
                "name": f"Cov Activate Chapter {frappe.generate_hash(length=6)}",
                "region": region[0] if region else None,
                "published": 1,
                "introduction": "Coverage activation chapter",
            }
        )
        chapter.insert()
        self.track_doc("Chapter", chapter.name)

        member = self.create_test_member(
            first_name="Pend",
            last_name=f"Chap{frappe.generate_hash(length=6)}",
            email=f"pendchap-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )

        # Add a Pending Chapter Member row directly.
        chapter.append(
            "members",
            {"member": member.name, "status": "Pending", "enabled": 1, "chapter_join_date": today()},
        )
        chapter.save()
        frappe.db.commit()

        # Sanity: the row is pending.
        pending = frappe.db.sql(
            "SELECT status FROM `tabChapter Member` WHERE member=%s AND parent=%s",
            (member.name, chapter.name),
            as_dict=True,
        )
        self.assertTrue(pending)
        self.assertEqual(pending[0].status, "Pending")

        _activate_pending_chapter_memberships(member)

        after = frappe.db.sql(
            "SELECT status FROM `tabChapter Member` WHERE member=%s AND parent=%s",
            (member.name, chapter.name),
            as_dict=True,
        )
        self.assertTrue(after)
        self.assertEqual(after[0].status, "Active")


class TestUpdatePaymentHistoryForInvoice(EnhancedTestCase):
    """update_payment_history_for_invoice: error-handling path.

    The function is a fire-and-forget background job wrapped in try/except: a
    bad member/invoice reference is logged and swallowed (no raise). We exercise
    that resilience path without needing full Sales Invoice accounting setup.
    """

    def test_nonexistent_invoice_is_logged_and_swallowed(self):
        member = self.create_test_member(
            first_name="PayHist",
            last_name=f"Member{frappe.generate_hash(length=6)}",
            email=f"payhist-{frappe.generate_hash(length=8)}@example.com",
            birth_date=add_days(today(), -365 * 30),
        )
        self.expectErrorLog("Payment History Update Error")
        # frappe.get_doc on the missing invoice raises inside the try block; the
        # function logs and returns without propagating.
        with self.assertErrorLog("Payment History Update Error"):
            self.assertIsNone(update_payment_history_for_invoice(member.name, "NONEXISTENT-SINV-COV-12345"))

    def test_nonexistent_member_is_logged_and_swallowed(self):
        self.expectErrorLog("Payment History Update Error")
        with self.assertErrorLog("Payment History Update Error"):
            self.assertIsNone(
                update_payment_history_for_invoice("NONEXISTENT-MEMBER-COV-12345", "NONEXISTENT-SINV-COV-12345")
            )


class TestApproveMembershipApplicationTerminationGuard(EnhancedTestCase):
    """#1544/#1548 follow-up: a Pending applicant can be terminated while
    still under review (validate_termination_request() does not block it),
    and approval unconditionally resets member_since to today -- which,
    per #1544's own rule, makes that termination look superseded. But this
    is NOT a genuine rejoin: a genuine rejoin's application_date is set to
    now() by update_member_from_reapplication, strictly after the
    termination it responds to; here the application predates the
    termination, so approving would silently reactivate a member who was
    terminated after they applied, with nobody having decided that should
    happen. Refuse instead of guessing the product rule."""

    def test_refuses_when_termination_postdates_application(self):
        from verenigingen.api.membership_application_review import approve_membership_application
        from verenigingen.tests.support.termination_request import execute_real_termination

        membership_type = _ensure_membership_type()
        member = self.create_test_member(
            first_name="StalePending",
            last_name="ThenTerminated",
            email=f"stale.pending.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Pending",
            application_status="Pending",
            selected_membership_type=membership_type,
        )
        application_date = add_days(today(), -10)
        frappe.db.set_value(
            "Member", member.name, "application_date", application_date, update_modified=False
        )

        # Reachable: validate_termination_request() does not block creating
        # (and executing) a termination against a still-Pending member.
        termination_date = add_days(today(), -1)
        execute_real_termination(self, member.name, termination_date)
        member.reload()
        self.assertEqual(member.status, "Quit")
        self.assertEqual(member.application_status, "Pending", "sanity: application is still open")

        with self.assertRaises(frappe.ValidationError):
            approve_membership_application(
                member_name=member.name,
                membership_type=membership_type,
                chapter=None,
            )

        member.reload()
        self.assertEqual(
            member.application_status,
            "Pending",
            "a refused approval must not have advanced application_status",
        )

    def test_approves_normally_when_application_postdates_termination(self):
        """Control: the genuine rejoin case (application_date AFTER the
        termination) must still approve normally -- the guard must not
        refuse a real, legitimate reapplication."""
        from verenigingen.api.membership_application_review import approve_membership_application
        from verenigingen.tests.support.termination_request import execute_real_termination

        membership_type = _ensure_membership_type()
        member = self.create_test_member(
            first_name="Rejoin",
            last_name="ApprovesNormally",
            email=f"rejoin.approves.{frappe.generate_hash(length=6)}@test.invalid",
            birth_date="1990-01-01",
            status="Active",
            application_status="Approved",
            selected_membership_type=membership_type,
        )
        execute_real_termination(self, member.name, add_days(today(), -100))
        member.reload()
        self.assertEqual(member.status, "Quit")

        # Reapplication AFTER the termination -- the real, positive signal.
        frappe.db.set_value(
            "Member",
            member.name,
            {"application_status": "Pending", "application_date": today()},
            update_modified=False,
        )

        result = approve_membership_application(
            member_name=member.name,
            membership_type=membership_type,
            chapter=None,
        )
        self.assertTrue(result.get("success"), result)
        member.reload()
        self.assertEqual(member.application_status, "Approved")
