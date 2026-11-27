"""
#1682: Employee.expense_approver and Department approvers refresh when a Financial seat
changes, not only on the daily scheduler.

Fixtures are real documents. Seats are written through their real writers (Chapter save,
standalone Chapter Board Member save/delete, Chapter Role save). The approver is read from
Employee / Department, never from the service, so the persisted state is what is asserted.
Direct writes (stated, not hidden): ``Volunteer.email`` and ``Volunteer.employee_id`` via
``db.set_value`` (the same shortcut the #1650 tests use for the e-mail), a hand-set
``Employee.expense_approver`` for the control, and the national-chapter setting (a config input).

The national-chapter and Chapter Role refreshes are ENQUEUED (a national seat feeds every
volunteer). CI has no RQ workers, so these tests capture the ``frappe.enqueue`` call, assert it
was made after commit under a job id, and run the queued method directly.
"""

from contextlib import contextmanager
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

OUR_JOBS = "verenigingen.services.volunteer.native_expense_helpers."


class TestExpenseApproverRefreshOnSeatChange(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._pin_national_chapter(None)
        self.chapter = self.ensure_test_chapter(f"Ref{frappe.generate_hash(length=6)}")
        self.role = self._chapter_role_at_level("Financial")
        self.claimant, self.employee = self._claimant_in(self.chapter.name)
        self._ensure_board_department()
        self.treasurer, self.treasurer_user = self._user_backed_volunteer("t1")

    # ------------------------------------------------------------------ helpers
    def _pin_national_chapter(self, chapter_name):
        previous = frappe.db.get_single_value("Verenigingen Settings", "national_board_chapter")
        frappe.db.set_single_value("Verenigingen Settings", "national_board_chapter", chapter_name)
        self.addCleanup(
            frappe.db.set_single_value, "Verenigingen Settings", "national_board_chapter", previous
        )

    def _chapter_role_at_level(self, level):
        name = f"Ref{level}{frappe.generate_hash(length=6)}"
        return self.factory.ensure_chapter_role(name, {"permissions_level": level}).name

    def _user_backed_volunteer(self, prefix):
        user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        member = self.create_test_member(first_name="Ref", last_name=prefix, birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        frappe.db.set_value("Volunteer", volunteer.name, "email", user.email, update_modified=False)
        return volunteer, user

    def _claimant_in(self, chapter_name):
        member = self.create_test_member(first_name="RefClaim", last_name="Er", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        chapter = frappe.get_doc("Chapter", chapter_name)
        chapter.append("members", {"member": member.name, "enabled": 1})
        chapter.save()
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        company = get_eur_test_company()
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Ref{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert()
        self._track_test_document("Employee", employee.name, priority=2)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee.name, update_modified=False)
        return volunteer, employee

    def _ensure_board_department(self):
        """The Board department the sync writes to (a chapter's own is not always created).

        Built in the company the sync resolves departments in (Verenigingen
        Settings.company), not the claimant Employee's: the lookup is
        company-scoped since #2551, so a same-named department elsewhere is
        never the target.
        """
        name = f"Chapter {self.chapter.name} Board"
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if frappe.db.exists("Department", {"department_name": name, "company": company}):
            return
        dept = frappe.get_doc(
            {
                "doctype": "Department",
                "department_name": name,
                "company": company,
                "parent_department": "All Departments",
            }
        ).insert()
        self._track_test_document("Department", dept.name, priority=2)

    def _seat_volunteer_on_chapter(self, volunteer_name, role=None, chapter_name=None):
        chapter = frappe.get_doc("Chapter", chapter_name or self.chapter.name)
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer_name,
                "chapter_role": role or self.role,
                "from_date": frappe.utils.today(),
                "is_active": 1,
            },
        )
        chapter.save()

    def _seat_row_name(self, volunteer_name):
        return frappe.db.get_value(
            "Chapter Board Member", {"parent": self.chapter.name, "volunteer": volunteer_name}, "name"
        )


    @contextmanager
    def _captured_enqueues(self):
        """Capture ``frappe.enqueue`` calls instead of queueing them (CI has no workers).

        The refresh jobs are registered as after-commit callbacks (#2553), so nothing is
        enqueued until the commit fires them. The tests never commit, so this takes OUR
        callbacks out of ``frappe.db.after_commit`` and runs them: on exit, or earlier through
        ``self._fire_our_commit_callbacks()`` to place a step between registration and commit.
        Other after-commit callbacks are left where they are.
        """
        jobs = []
        real_enqueue = frappe.enqueue

        def capture(method, *args, **kwargs):
            if isinstance(method, str) and method.startswith(OUR_JOBS):
                jobs.append((method, kwargs))
            else:
                return real_enqueue(method, *args, **kwargs)

        # Mock justified: a queue boundary. The queued method is run directly by
        # _run_enqueued, so the work under test is real; only the transport is replaced.
        with patch.object(frappe, "enqueue", capture):
            # Callbacks registered earlier (fixture setup) belong to no step under test.
            self._callbacks_before = list(frappe.db.after_commit._functions)
            try:
                yield jobs
            finally:
                self._fire_our_commit_callbacks()

    def _fire_our_commit_callbacks(self):
        """What the commit does with this feature's callbacks, and only these."""
        from verenigingen.services.volunteer import native_expense_helpers as helpers

        pending = frappe.db.after_commit._functions
        ours = [
            cb
            for cb in pending
            if getattr(cb, "func", None) is helpers._enqueue_unless_queued
            and cb not in self._callbacks_before
        ]
        for callback in ours:
            pending.remove(callback)
        for callback in ours:
            callback()

    def _run_enqueued(self, jobs):
        for method, kwargs in jobs:
            self.assertTrue(kwargs.get("job_id"), "enqueued under a dedup job id")
            call_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k
                not in ("queue", "timeout", "job_id", "enqueue_after_commit", "now", "deduplicate", "job_name")
            }
            (frappe.get_attr(method) if isinstance(method, str) else method)(**call_kwargs)

    def _national_chapter(self):
        national = self.ensure_test_chapter(f"RefNat{frappe.generate_hash(length=6)}")
        self._pin_national_chapter(national.name)
        return national

    def _seat_national(self, volunteer_name, national, jobs, role=None):
        with self._captured_enqueues() as captured:
            self._seat_volunteer_on_chapter(volunteer_name, role=role, chapter_name=national.name)
        jobs.extend(captured)
        self._run_enqueued(captured)

    def _employee_approver(self):
        return frappe.db.get_value("Employee", self.employee.name, "expense_approver")

    def _dept_approvers(self):
        from verenigingen.utils.department_hierarchy import DepartmentHierarchyManager

        dept = DepartmentHierarchyManager()._resolve_department_name(f"Chapter {self.chapter.name} Board")
        self.assertTrue(dept, "the Board department the sync targets exists")
        return frappe.get_all("Department Approver", filters={"parent": dept}, pluck="approver")

    def _run_daily_refresh(self):
        """The scheduler's own writer, to establish the state a day-old approver would have."""
        from verenigingen.services.volunteer.native_expense_helpers import update_employee_approver

        update_employee_approver(self.claimant.name)

    def _seated_treasurer(self):
        """Seat the treasurer and make the approver current through the DAILY path, so a
        later assertion cannot pass on anything the seat-change refresh did when seating."""
        self._seat_volunteer_on_chapter(self.treasurer.name)
        self._run_daily_refresh()
        self.assertEqual(self._employee_approver(), self.treasurer_user.email, "precondition: approver current")

    # -------------------------------------------------------------------- tests
    def test_seating_a_financial_seat_sets_the_approver_at_once(self):
        self._seat_volunteer_on_chapter(self.treasurer.name)
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)
        self.assertEqual(self._dept_approvers(), [self.treasurer_user.email])

    def test_ending_the_seat_in_a_chapter_save_clears_the_stale_approver(self):
        self._seated_treasurer()
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        for row in chapter.board_members:
            if row.volunteer == self.treasurer.name:
                row.is_active = 0
        chapter.save()
        self.assertIsNone(self._employee_approver() or None)
        self.assertNotIn(self.treasurer_user.email, self._dept_approvers())

    def test_removing_the_seat_row_in_a_chapter_save_clears_it(self):
        self._seated_treasurer()
        chapter = frappe.get_doc("Chapter", self.chapter.name)
        chapter.board_members = [r for r in chapter.board_members if r.volunteer != self.treasurer.name]
        chapter.save()
        self.assertIsNone(self._employee_approver() or None)

    def test_standalone_row_end_and_delete_clear_it(self):
        for label, end in (
            ("deactivate", lambda r: self._end_seat_standalone(r)),
            ("delete", lambda r: frappe.delete_doc("Chapter Board Member", r)),
        ):
            with self.subTest(label):
                volunteer, user = self._user_backed_volunteer(label[:3])
                self._write_employee_approver(None)
                self._seat_volunteer_on_chapter(volunteer.name)
                self._run_daily_refresh()
                self.assertEqual(self._employee_approver(), user.email)
                end(self._seat_row_name(volunteer.name))
                self.assertIsNone(self._employee_approver() or None)

    def _end_seat_standalone(self, row_name):
        row = frappe.get_doc("Chapter Board Member", row_name)
        row.is_active = 0
        row.to_date = frappe.utils.today()
        row.save()

    def _write_employee_approver(self, user):
        frappe.db.set_value("Employee", self.employee.name, "expense_approver", user)

    def test_chapter_role_losing_financial_level_clears_it(self):
        self._seated_treasurer()
        with self._captured_enqueues() as jobs:
            role = frappe.get_doc("Chapter Role", self.role)
            role.permissions_level = "Admin"
            role.save()
        self.assertEqual(len(jobs), 1, "one job for the role, however many chapters hold it")
        self._run_enqueued(jobs)
        self.assertIsNone(self._employee_approver() or None)

    def test_second_financial_seat_takes_over_when_the_first_ends(self):
        second, second_user = self._user_backed_volunteer("t2")
        self._seat_volunteer_on_chapter(self.treasurer.name)
        self._seat_volunteer_on_chapter(second.name)
        self._run_daily_refresh()
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)
        self._end_seat_standalone(self._seat_row_name(self.treasurer.name))
        self.assertEqual(self._employee_approver(), second_user.email)

    def test_hand_set_approver_survives_a_seat_ending(self):
        """Control: a value that is not the departing seat holder is left alone (#1650)."""
        _other, other_user = self._user_backed_volunteer("hand")
        self._seat_volunteer_on_chapter(self.treasurer.name)
        self._write_employee_approver(other_user.email)
        self._end_seat_standalone(self._seat_row_name(self.treasurer.name))
        self.assertEqual(self._employee_approver(), other_user.email)

    def test_another_chapters_seat_ending_does_not_touch_this_claimant(self):
        """Control: the refresh is scoped to the chapter whose seat changed."""
        self._seated_treasurer()
        other_chapter = self.ensure_test_chapter(f"RefOther{frappe.generate_hash(length=6)}")
        other_vol, _u = self._user_backed_volunteer("oth")
        self._seat_volunteer_on_chapter(other_vol.name, chapter_name=other_chapter.name)
        row = frappe.db.get_value(
            "Chapter Board Member", {"parent": other_chapter.name, "volunteer": other_vol.name}, "name"
        )
        self._end_seat_standalone(row)
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)

    def test_a_chapter_admin_without_employee_write_still_refreshes(self):
        """The writer is a board admin, who has no Employee/Department write."""
        self._seated_treasurer()
        admin = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        user = getattr(admin, "user", None) or getattr(admin, "email", None)
        caller = frappe.session.user
        frappe.set_user(user)
        try:
            self.assertFalse(frappe.has_permission("Employee", "write", doc=self.employee.name))
            self._end_seat_standalone(self._seat_row_name(self.treasurer.name))
        finally:
            frappe.set_user(caller)
        self.assertIsNone(self._employee_approver() or None)

    # ----------------------------------------------------- review round 2 (#1682)
    def test_a_deadlock_at_the_employee_write_propagates(self):
        """An injected 1213 at the Employee write must not be logged and swallowed."""
        from frappe.exceptions import QueryDeadlockError

        from verenigingen.utils import secure_operations

        self._seated_treasurer()
        real = secure_operations._execute_document_operation

        def deadlock_on_employee(doc, operation, *args, **kwargs):
            if doc.doctype == "Employee":
                raise QueryDeadlockError("injected 1213")
            return real(doc, operation, *args, **kwargs)

        row = self._seat_row_name(self.treasurer.name)
        # Mock justified: a real deadlock cannot be provoked deterministically; the
        # fault is injected at the one Employee write, everything else is real.
        with patch.object(secure_operations, "_execute_document_operation", deadlock_on_employee):
            with self.assertRaises(QueryDeadlockError):
                self._end_seat_standalone(row)

    def test_a_basic_seat_change_does_not_clear_a_hand_set_approver(self):
        """The holder of a Basic seat was never a financial approver: hand-set stays."""
        other, other_user = self._user_backed_volunteer("basic")
        basic = self._chapter_role_at_level("Basic")
        other_basic = self._chapter_role_at_level("Basic")

        self._write_employee_approver(other_user.email)
        self._seat_volunteer_on_chapter(other.name, role=basic)
        self.assertEqual(self._employee_approver(), other_user.email, "adding a Basic seat")

        chapter = frappe.get_doc("Chapter", self.chapter.name)
        for row in chapter.board_members:
            if row.volunteer == other.name:
                row.chapter_role = other_basic
        chapter.save()
        self.assertEqual(self._employee_approver(), other_user.email, "re-roling a Basic seat")

        self._end_seat_standalone(self._seat_row_name(other.name))
        self.assertEqual(self._employee_approver(), other_user.email, "ending a Basic seat")

    def test_deleting_a_basic_seat_row_does_not_clear_a_hand_set_approver(self):
        """Delete-route control: the delete path must also tell a Financial seat from a Basic one."""
        other, other_user = self._user_backed_volunteer("bdel")
        self._seat_volunteer_on_chapter(other.name, role=self._chapter_role_at_level("Basic"))
        self._write_employee_approver(other_user.email)
        frappe.delete_doc("Chapter Board Member", self._seat_row_name(other.name))
        self.assertEqual(self._employee_approver(), other_user.email)

    def test_a_role_change_between_non_financial_levels_keeps_a_hand_set_approver(self):
        other, other_user = self._user_backed_volunteer("rolebasic")
        role = self._chapter_role_at_level("Basic")
        self._seat_volunteer_on_chapter(other.name, role=role)
        self._write_employee_approver(other_user.email)
        with self._captured_enqueues() as jobs:
            doc = frappe.get_doc("Chapter Role", role)
            doc.permissions_level = "Admin"
            doc.save()
        self._run_enqueued(jobs)
        self.assertEqual(self._employee_approver(), other_user.email)

    def test_a_new_national_seat_reaches_a_claimant_outside_the_national_chapter(self):
        """The national seat feeds everyone: a claimant in another chapter, with no approver."""
        national = self._national_chapter()
        self.assertIsNone(self._employee_approver() or None)
        jobs = []
        self._seat_national(self.treasurer.name, national, jobs)
        self.assertEqual(len(jobs), 1, "the national case is enqueued, not run inside the save")
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)

    def test_the_national_seat_ending_moves_or_clears_an_outside_claimant(self):
        national = self._national_chapter()
        second, second_user = self._user_backed_volunteer("n2")
        jobs = []
        self._seat_national(self.treasurer.name, national, jobs)
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)

        def end_national_seat(volunteer):
            with self._captured_enqueues() as captured:
                row = frappe.db.get_value(
                    "Chapter Board Member", {"parent": national.name, "volunteer": volunteer.name}, "name"
                )
                self._end_seat_standalone(row)
            self.assertEqual(len(captured), 1)
            self._run_enqueued(captured)

        self._seat_national(second.name, national, jobs)
        end_national_seat(self.treasurer)
        self.assertEqual(self._employee_approver(), second_user.email, "moves to the other seat")
        end_national_seat(second)
        self.assertIsNone(self._employee_approver() or None, "no financial seat left: unassigned")

    def test_a_chapter_treasurers_own_claim_falls_back_to_the_national_seat(self):
        """The approver is the volunteer's own computation, not the changed chapter's treasurer."""
        national = self._national_chapter()
        national_vol, national_user = self._user_backed_volunteer("nt")
        self._seat_national(national_vol.name, national, [])
        # The treasurer of the claimant's chapter is also a claimant (own Employee).
        treasurer_employee = self._employee_for(self.treasurer)
        self._seat_volunteer_on_chapter(self.treasurer.name)
        self.assertEqual(
            frappe.db.get_value("Employee", treasurer_employee, "expense_approver"),
            national_user.email,
            "self-approval is refused: the treasurer's own claim goes to the national seat",
        )
        self.assertEqual(self._employee_approver(), self.treasurer_user.email, "the chapter's claimant")

    def _employee_for(self, volunteer):
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Ref{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": self.employee.company,
            }
        ).insert()
        self._track_test_document("Employee", employee.name, priority=2)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", employee.name, update_modified=False)
        return employee.name

    def test_an_identical_queued_job_is_not_enqueued_twice(self):
        national = self._national_chapter()
        with patch("verenigingen.services.volunteer.native_expense_helpers._job_is_queued", return_value=True):
            # Mock justified: the queue's own state (a job already waiting under this id).
            with self._captured_enqueues() as jobs:
                self._seat_volunteer_on_chapter(self.treasurer.name, chapter_name=national.name)
        self.assertEqual(jobs, [])

    def test_fed_volunteer_lookup_costs_the_same_for_one_volunteer_or_four(self):
        """One query for the whole chapter, not one exists()+get_value() per volunteer."""
        from verenigingen.services.volunteer import native_expense_helpers as helpers

        def count_queries():
            real = frappe.db.sql
            calls = []

            def counting(*args, **kwargs):
                calls.append(1)
                return real(*args, **kwargs)

            # Mock justified: a counting wrapper that still runs the real query.
            with patch.object(frappe.db, "sql", counting):
                fed = helpers._volunteers_fed_by_chapter(self.chapter.name, set())
            return len(calls), fed

        few, fed_few = count_queries()
        self.assertIn(self.claimant.name, fed_few)
        for index in range(3):
            volunteer, _employee = self._claimant_in(self.chapter.name)
        many, fed_many = count_queries()
        self.assertGreaterEqual(len(fed_many), len(fed_few) + 3)
        self.assertEqual(many, few)
        self.assertLessEqual(few, 2, "the join, plus at most a cold read of the national chapter setting")

    def _fed_after_row_state_2704(self, state):
        """Is the claimant fed by the chapter once their row is in ``state`` (real writers)?"""
        from verenigingen.events.subscribers.member_subscribers import _update_chapter_membership_status
        from verenigingen.services.volunteer import native_expense_helpers as helpers

        member = self.create_test_member(first_name="Fed2704", last_name="Er", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        employee = self._employee_for(volunteer)
        chapter = self.ensure_test_chapter(f"Fed2704{state}{frappe.generate_hash(length=4)}")
        if state == "pending":
            frappe.get_doc("Chapter", chapter.name).member_manager.request_to_join(member.name, notify=False)
        else:
            chapter_doc = frappe.get_doc("Chapter", chapter.name)
            chapter_doc.append("members", {"member": member.name, "enabled": 1})
            chapter_doc.save()
        if state == "suspended":
            _update_chapter_membership_status(member, "Suspended")
        elif state == "removed":
            frappe.get_doc("Chapter", chapter.name).member_manager.remove_member(
                member.name, leave_reason="left", notify=False
            )
        row = frappe.db.get_value(
            "Chapter Member", {"parent": chapter.name, "member": member.name}, ["enabled", "status"], as_dict=True
        )
        self.assertEqual(row.enabled, 0 if state == "removed" else 1, f"fixture: {state} row {row}")
        self.assertTrue(employee)
        return volunteer.name in helpers._volunteers_fed_by_chapter(chapter.name, set())

    def test_an_active_row_feeds_the_claimant_control(self):
        self.assertTrue(self._fed_after_row_state_2704("active"))

    def test_a_pending_row_does_not_feed_the_claimant(self):
        self.assertFalse(self._fed_after_row_state_2704("pending"))

    def test_a_suspended_row_does_not_feed_the_claimant(self):
        """enabled=1, status=Inactive: an enabled-only filter would still include them."""
        self.assertFalse(self._fed_after_row_state_2704("suspended"))

    def test_a_removed_row_does_not_feed_the_claimant(self):
        self.assertFalse(self._fed_after_row_state_2704("removed"))

    # ------------------------------------------------------------- #2553 residuals
    def _swap_seat_holder_in_chapter_save(self, row_name, new_volunteer_name, chapter_name=None):
        """The REAL Chapter save: reassign an existing active row to another volunteer."""
        chapter = frappe.get_doc("Chapter", chapter_name or self.chapter.name)
        for row in chapter.board_members:
            if row.name == row_name:
                row.volunteer = new_volunteer_name
        chapter.save()

    def test_swapping_the_volunteer_on_a_financial_row_in_a_chapter_save_moves_the_approver(self):
        """#2553 item 2: the old holder must not stay approver; the new one becomes it."""
        second, second_user = self._user_backed_volunteer("sw2")
        self._seated_treasurer()
        row_name = self._seat_row_name(self.treasurer.name)
        self._swap_seat_holder_in_chapter_save(row_name, second.name)
        self.assertEqual(self._employee_approver(), second_user.email)
        self.assertEqual(self._dept_approvers(), [second_user.email])

    def test_swapping_to_a_volunteer_with_no_user_clears_the_old_approver(self):
        """The new holder cannot approve (no user), so the old holder's approver is cleared."""
        member = self.create_test_member(first_name="Ref", last_name="NoUser", birth_date="1990-01-01")
        no_user = self.create_test_volunteer(member_name=member.name)
        frappe.db.set_value("Volunteer", no_user.name, {"email": None, "personal_email": None})
        self._seated_treasurer()
        self._swap_seat_holder_in_chapter_save(self._seat_row_name(self.treasurer.name), no_user.name)
        self.assertIsNone(self._employee_approver() or None)
        self.assertNotIn(self.treasurer_user.email, self._dept_approvers())

    def test_swapping_a_basic_row_does_not_clear_a_hand_set_approver(self):
        """Control: a Basic seat was never a financial approver, so a swap leaves a hand-set one."""
        other, other_user = self._user_backed_volunteer("swb")
        second, _second_user = self._user_backed_volunteer("swb2")
        self._seat_volunteer_on_chapter(other.name, role=self._chapter_role_at_level("Basic"))
        self._write_employee_approver(other_user.email)
        self._swap_seat_holder_in_chapter_save(self._seat_row_name(other.name), second.name)
        self.assertEqual(self._employee_approver(), other_user.email)

    def test_the_swap_ends_the_old_holders_assignment_and_starts_the_new_ones(self):
        """The same hole carried the assignment history: both holders are handled.

        (The board role itself is not asserted: this fixture chapter configures no board role
        profile, so even an ordinary seating grants none here.)"""
        second, _second_user = self._user_backed_volunteer("swh")
        self._seat_volunteer_on_chapter(self.treasurer.name)
        row_name = self._seat_row_name(self.treasurer.name)
        self._swap_seat_holder_in_chapter_save(row_name, second.name)

        def assignments(volunteer):
            return frappe.get_all(
                "Volunteer Assignment",
                filters={"parent": volunteer, "reference_doctype": "Chapter", "reference_name": self.chapter.name},
                fields=["status", "end_date"],
            )

        self.assertTrue(assignments(second.name), "new holder has an assignment")
        new_member = frappe.db.get_value("Volunteer", second.name, "member")
        self.assertTrue(
            frappe.db.exists("Chapter Member", {"parent": self.chapter.name, "member": new_member}),
            "the new holder is seated as a chapter member",
        )
        old_holder = assignments(self.treasurer.name)
        self.assertTrue(old_holder, "the old holder had an assignment to end")
        self.assertTrue(all(a.status != "Active" for a in old_holder))

    def test_a_chapter_admin_without_employee_write_can_swap_a_financial_holder(self):
        """Least-privileged real caller (a Chapter Admin board member) saves the swap.

        The new holder has no user, so no approver is SET and no role has to be granted: a
        Chapter Admin cannot grant the Expense Approver role (no User write), and a swap to a
        holder with a user then leaves the old approver in place. That is a separate defect,
        reported with #2553 (measured: it applies to a plain new Financial seat as well)."""
        member = self.create_test_member(first_name="Ref", last_name="AdmNoUser", birth_date="1990-01-01")
        no_user = self.create_test_volunteer(member_name=member.name)
        frappe.db.set_value("Volunteer", no_user.name, {"email": None, "personal_email": None})
        self._seated_treasurer()
        admin = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        user = getattr(admin, "user", None) or getattr(admin, "email", None)
        row_name = self._seat_row_name(self.treasurer.name)
        caller = frappe.session.user
        frappe.set_user(user)
        try:
            self.assertFalse(frappe.has_permission("Employee", "write", doc=self.employee.name))
            self._swap_seat_holder_in_chapter_save(row_name, no_user.name)
        finally:
            frappe.set_user(caller)
        self.assertIsNone(self._employee_approver() or None)

    def test_a_job_that_started_before_the_commit_does_not_suppress_the_enqueue(self):
        """#2553 item 1. T1 queued job J; T2 (uncommitted) registers while J still waits; a
        worker starts J (it reads pre-T2 state) before T2 commits. T2's change must be
        enqueued: the queued-check belongs AFTER the commit, where J's state is final.

        Probe shortcut (stated): ``_job_is_queued`` is stubbed to model Redis's view at each
        moment. CI has no RQ workers and this bench's workers run develop's code, so the
        interleaving is driven by hand and the queued method is run directly afterwards."""
        national = self._national_chapter()
        queue_state = {"j_is_queued": True}
        # Mock justified: the queue's own state, moved between registration and commit.
        with patch(
            "verenigingen.services.volunteer.native_expense_helpers._job_is_queued",
            side_effect=lambda job_id: queue_state["j_is_queued"],
        ):
            with self._captured_enqueues() as jobs:
                self._seat_volunteer_on_chapter(self.treasurer.name, chapter_name=national.name)
                self.assertEqual(jobs, [], "nothing is enqueued before the commit fires")
                queue_state["j_is_queued"] = False  # the worker started J
                self._fire_our_commit_callbacks()
                self.assertEqual(len(jobs), 1, "T2's change is enqueued after J started")
        self._run_enqueued(jobs)
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)

    def test_a_job_still_waiting_at_commit_time_is_not_enqueued_again(self):
        """Control: J still QUEUED when T2's commit fires will read T2's committed state, so
        the dedup still holds. (Fails a fix that simply drops the dedup.)"""
        national = self._national_chapter()
        # Mock justified: the queue's own state (J waits under this id at commit time).
        with patch(
            "verenigingen.services.volunteer.native_expense_helpers._job_is_queued", return_value=True
        ):
            with self._captured_enqueues() as jobs:
                self._seat_volunteer_on_chapter(self.treasurer.name, chapter_name=national.name)
        self.assertEqual(jobs, [])

    # ----------------------------------------------------- #2683: the role grant as a Chapter Admin
    def _as_chapter_admin(self):
        """A real Chapter Admin board member (no User/Employee write); returns their user."""
        admin = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        user = getattr(admin, "user", None) or getattr(admin, "email", None)
        caller = frappe.session.user
        frappe.set_user(user)
        self.addCleanup(frappe.set_user, caller)
        self.assertFalse(frappe.has_permission("Employee", "write", doc=self.employee.name))
        self.assertFalse(frappe.has_permission("User", "write", doc=self.treasurer_user.name))
        return caller

    def _treasurer_roles(self, user):
        return frappe.get_all("Has Role", filters={"parent": user.name, "parenttype": "User"}, pluck="role")

    def test_a_chapter_admin_seating_a_financial_holder_sets_the_approver_2683(self):
        """Real flow: a Chapter Admin's Chapter save adds the new Financial seat (#2683).

        The approver (and the Expense Approver role it needs) is derived from the seat, so
        the grant must not depend on the saver's own User write."""
        self.assertNotIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
        caller = self._as_chapter_admin()
        self._seat_volunteer_on_chapter(self.treasurer.name)
        frappe.set_user(caller)
        self.assertEqual(self._employee_approver(), self.treasurer_user.email)
        self.assertIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
        self.assertEqual(self._dept_approvers(), [self.treasurer_user.email])

    def test_a_chapter_admin_swapping_in_a_holder_with_a_user_moves_the_approver_2683(self):
        """The swap #2553 item 2 reported: the old approver must be replaced, not left."""
        second, second_user = self._user_backed_volunteer("sw3")
        self._seated_treasurer()
        row_name = self._seat_row_name(self.treasurer.name)
        caller = self._as_chapter_admin()
        self._swap_seat_holder_in_chapter_save(row_name, second.name)
        frappe.set_user(caller)
        self.assertEqual(self._employee_approver(), second_user.email)
        self.assertIn("Expense Approver", self._treasurer_roles(second_user))

    def test_a_chapter_admin_seating_a_basic_holder_grants_no_approver_role_2683(self):
        """Control: the grant follows a FINANCIAL seat only. A Basic seat held by a volunteer
        with a real user, saved by the same caller, gets neither role nor approver."""
        basic_role = self._chapter_role_at_level("Basic")
        caller = self._as_chapter_admin()
        self._seat_volunteer_on_chapter(self.treasurer.name, role=basic_role)
        frappe.set_user(caller)
        self.assertNotIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
        self.assertIsNone(self._employee_approver() or None)

    # Discriminators (security review of #2683): each grant site is needed on its own. The two
    # sites are department_hierarchy (Department Approver sync) and expense_approver_service
    # (per-claimant refresh); the cases below leave only one of them able to grant.
    def test_the_department_sync_alone_grants_the_role_when_no_claimant_is_fed_2683(self):
        """No volunteer with an Employee is fed by the chapter, so only the department-approver
        path can grant: dropping system_operation there must redden this."""
        frappe.db.set_value("Volunteer", self.claimant.name, "employee_id", None, update_modified=False)
        self.assertNotIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
        caller = self._as_chapter_admin()
        self._seat_volunteer_on_chapter(self.treasurer.name)
        frappe.set_user(caller)
        self.assertIn("Expense Approver", self._treasurer_roles(self.treasurer_user))

    def test_the_service_alone_grants_the_second_treasurer_the_claimant_is_excluded_from_2683(self):
        """The claimant is itself a user-backed Financial holder: the department path grants the
        first holder, so the second treasurer's role can only come from the per-claimant service
        path. Dropping system_operation there must redden this."""
        first_user = self.factory.create_user_with_roles(roles=["Verenigingen Volunteer"])
        frappe.db.set_value("Volunteer", self.claimant.name, "email", first_user.email, update_modified=False)
        self._seat_volunteer_on_chapter(self.claimant.name)
        self.assertIn("Expense Approver", self._treasurer_roles(first_user))
        self.assertNotIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
        caller = self._as_chapter_admin()
        self._seat_volunteer_on_chapter(self.treasurer.name)
        frappe.set_user(caller)
        self.assertIn("Expense Approver", self._treasurer_roles(self.treasurer_user))
