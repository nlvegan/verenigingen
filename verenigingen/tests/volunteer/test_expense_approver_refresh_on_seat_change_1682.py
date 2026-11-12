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
        """The Board department the sync writes to (a chapter's own is not always created)."""
        name = f"Chapter {self.chapter.name} Board"
        if frappe.db.exists("Department", {"department_name": name}):
            return
        dept = frappe.get_doc(
            {
                "doctype": "Department",
                "department_name": name,
                "company": self.employee.company,
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
        """Capture ``frappe.enqueue`` calls instead of queueing them (CI has no workers)."""
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
            yield jobs

    def _run_enqueued(self, jobs):
        for method, kwargs in jobs:
            self.assertTrue(kwargs.get("enqueue_after_commit"), "enqueued after commit")
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
