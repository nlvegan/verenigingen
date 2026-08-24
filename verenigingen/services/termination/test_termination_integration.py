"""
Integration coverage for verenigingen/services/termination/termination_integration.py

These are the module-level `*_safe` helpers that perform individual steps of a
member termination / suspension. Each helper has defensive error handling and
must NOT raise on missing / invalid input — it should return its documented
result/flag instead. Tests create real Member/Customer/Volunteer/Membership/
Invoice/Chapter/Team docs via the ORM and assert real DB state afterwards.

SEPA mandate cancellation is covered only lightly (happy path + not-found) on
purpose — the SEPA/payments domain is owned elsewhere.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.services.termination import termination_integration as ti
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTerminationIntegration(EnhancedTestCase):
    # ------------------------------------------------------------------
    # helpers (names allow ignore_permissions / set_user per test_quality_enforcer)
    # ------------------------------------------------------------------
    def _make_member(self, status="Active", **kwargs):
        member = self.create_test_member(first_name="TermInt", last_name=f"M{self.uid}", **kwargs)
        if status != "Active":
            frappe.db.set_value("Member", member.name, "status", status)
            member.reload()
        return member

    def _make_customer_for_member(self, member):
        member = frappe.get_doc("Member", member.name)
        if not member.customer:
            member.create_customer()
            member.reload()
        return member.customer

    def _make_volunteer(self, member):
        return self.create_test_volunteer(member_name=member.name)

    def _make_user(self, member, enabled=1):
        """Create a User and link it to the member."""
        email = f"termint-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "TermInt",
                "last_name": "User",
                "enabled": enabled,
                "send_welcome_email": 0,
            }
        )
        user.insert(ignore_permissions=True)
        frappe.db.set_value("Member", member.name, "user", email)
        return user

    def _make_chapter_role(self):
        name = f"TI Role {frappe.generate_hash(length=6)}"
        role = frappe.get_doc(
            {
                "doctype": "Chapter Role",
                "role_name": name,
                "permissions_level": "Basic",
                "is_active": 1,
            }
        )
        role.insert(ignore_permissions=True)
        return role.name

    def _make_chapter_with_board(self, member, volunteer):
        """Create a Chapter with an active board position for the volunteer."""
        chapter = self.create_test_chapter(
            chapter_name=f"TI Chapter {frappe.generate_hash(length=6)}",
            region="Test Region TI",
        )
        chapter = frappe.get_doc("Chapter", chapter.name)
        role = self._make_chapter_role()
        chapter.append(
            "board_members",
            {
                "volunteer": volunteer.name,
                "chapter_role": role,
                "from_date": today(),
                "is_active": 1,
            },
        )
        chapter.save(ignore_permissions=True)
        return chapter

    def _make_chapter_with_member(self, member):
        chapter = self.create_test_chapter(
            chapter_name=f"TI ChapMem {frappe.generate_hash(length=6)}",
            region="Test Region TI",
        )
        chapter = frappe.get_doc("Chapter", chapter.name)
        chapter.append(
            "members",
            {
                "member": member.name,
                "chapter_join_date": today(),
                "enabled": 1,
                "status": "Active",
            },
        )
        chapter.save(ignore_permissions=True)
        return chapter

    def _as_admin(self):
        frappe.set_user("Administrator")

    # ==================================================================
    # cancel_membership_safe / cancel_dues_schedule_safe
    # ==================================================================
    def test_cancel_membership_safe_cancels_submitted_membership(self):
        member = self._make_member()
        membership = self.create_test_membership(member_name=member.name)
        result = ti.cancel_membership_safe(membership.name, cancellation_reason="test")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Membership", membership.name, "status"), "Cancelled")

    def test_cancel_membership_safe_idempotent_when_already_cancelled(self):
        member = self._make_member()
        membership = self.create_test_membership(member_name=member.name)
        ti.cancel_membership_safe(membership.name)
        # second call should be a no-op True
        self.assertTrue(ti.cancel_membership_safe(membership.name))

    def test_cancel_membership_safe_missing_membership_returns_false(self):
        self.assertFalse(ti.cancel_membership_safe("NONEXISTENT-MEMBERSHIP-XYZ"))

    def test_cancel_dues_schedule_safe_cancels_active_schedule(self):
        member = self._make_member()
        # Dues schedule validation requires an active membership for the member.
        self.create_test_membership(member_name=member.name)
        schedule = self.create_test_dues_schedule(member.name)
        result = ti.cancel_dues_schedule_safe(schedule.name)
        self.assertTrue(result)
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"),
            "Cancelled",
        )

    def test_cancel_dues_schedule_safe_missing_returns_false(self):
        self.assertFalse(ti.cancel_dues_schedule_safe("NONEXISTENT-DUES-XYZ"))

    # ==================================================================
    # cancel_sepa_mandate_safe — light coverage only
    # ==================================================================
    def test_cancel_sepa_mandate_safe_missing_returns_false(self):
        self.assertFalse(ti.cancel_sepa_mandate_safe("NONEXISTENT-MANDATE-XYZ"))

    def test_cancel_sepa_mandate_safe_happy_path(self):
        member = self._make_member()
        mandate = self.create_test_sepa_mandate(member_name=member.name)
        result = ti.cancel_sepa_mandate_safe(mandate.name, reason="member terminated")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "status"), "Cancelled")
        self.assertEqual(frappe.db.get_value("SEPA Mandate", mandate.name, "is_active"), 0)

    # ==================================================================
    # update_customer_safe
    # ==================================================================
    def test_update_customer_safe_appends_note(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        result = ti.update_customer_safe(customer, "TERMINATION NOTE 123")
        self.assertTrue(result)
        details = frappe.db.get_value("Customer", customer, "customer_details") or ""
        self.assertIn("TERMINATION NOTE 123", details)

    def test_update_customer_safe_disciplinary_disables(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        result = ti.update_customer_safe(customer, "disciplinary", disable_for_disciplinary=True)
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Customer", customer, "disabled"), 1)

    def test_update_customer_safe_missing_returns_false(self):
        self.assertFalse(ti.update_customer_safe("NONEXISTENT-CUSTOMER", "note"))

    # ==================================================================
    # update_invoice_safe / cancel_outstanding_invoices_safe
    # ==================================================================
    def test_update_invoice_safe_appends_remark(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        invoice = self.create_test_sales_invoice(customer)
        invoice.submit()
        result = ti.update_invoice_safe(invoice.name, "INV TERM NOTE 999")
        self.assertTrue(result)
        remarks = frappe.db.get_value("Sales Invoice", invoice.name, "remarks") or ""
        self.assertIn("INV TERM NOTE 999", remarks)

    def test_update_invoice_safe_missing_returns_false(self):
        self.assertFalse(ti.update_invoice_safe("NONEXISTENT-INV", "note"))

    def test_cancel_outstanding_invoices_safe_cancels_submitted(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        invoice = self.create_test_sales_invoice(customer)
        invoice.submit()
        # ensure it is outstanding/unpaid
        self.assertIn(
            frappe.db.get_value("Sales Invoice", invoice.name, "status"),
            ["Unpaid", "Overdue", "Partially Paid"],
        )
        result = ti.cancel_outstanding_invoices_safe(customer, "terminated")
        self.assertEqual(result["invoices_cancelled"], 1)
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 2)

    def test_cancel_outstanding_invoices_safe_no_invoices(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        result = ti.cancel_outstanding_invoices_safe(customer)
        self.assertEqual(result["invoices_cancelled"], 0)
        self.assertEqual(result["invoices_deleted"], 0)
        self.assertEqual(result["errors"], [])

    # ==================================================================
    # cancel_future_invoices_safe
    # ==================================================================
    def test_cancel_future_invoices_safe_returns_structured_result(self):
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        result = ti.cancel_future_invoices_safe(customer, today())
        # Regardless of whether the custom coverage field exists, must return the
        # documented dict shape and never raise.
        self.assertIn("invoices_cancelled", result)
        self.assertIn("invoices_deleted", result)
        self.assertIn("errors", result)

    def test_cancel_future_invoices_safe_cancels_future_when_field_exists(self):
        if not frappe.db.exists(
            "Custom Field",
            {"dt": "Sales Invoice", "fieldname": "custom_coverage_start_date"},
        ):
            self.skipTest("custom_coverage_start_date not configured on this site")
        member = self._make_member()
        customer = self._make_customer_for_member(member)
        invoice = self.create_test_sales_invoice(customer)
        # Set coverage fields while still a draft, then submit.
        invoice.db_set("custom_coverage_start_date", add_days(today(), 30))
        invoice.db_set("custom_coverage_end_date", add_days(today(), 60))
        invoice.reload()
        invoice.submit()
        result = ti.cancel_future_invoices_safe(customer, today())
        self.assertEqual(result["invoices_cancelled"], 1)
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice.name, "docstatus"), 2)

    # ==================================================================
    # update_member_status_safe
    # ==================================================================
    def test_update_member_status_safe_voluntary_to_quit(self):
        member = self._make_member()
        result = ti.update_member_status_safe(member.name, "Voluntary", today())
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")
        self.assertEqual(
            str(frappe.db.get_value("Member", member.name, "member_end_date")),
            today(),
        )

    def test_update_member_status_safe_deceased(self):
        member = self._make_member()
        result = ti.update_member_status_safe(member.name, "Deceased", today())
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Deceased")

    def test_update_member_status_safe_expulsion_to_banned(self):
        member = self._make_member()
        result = ti.update_member_status_safe(member.name, "Expulsion", today())
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Banned")

    def test_update_member_status_safe_unknown_type_defaults_quit(self):
        member = self._make_member()
        result = ti.update_member_status_safe(member.name, "SomethingElse", today())
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")

    def test_update_member_status_safe_missing_returns_false(self):
        self.assertFalse(ti.update_member_status_safe("NONEXISTENT-MEMBER", "Voluntary", today()))

    # ==================================================================
    # end_board_positions_safe
    # ==================================================================
    def test_end_board_positions_safe_ends_active_position(self):
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        chapter = self._make_chapter_with_board(member, volunteer)
        ended = ti.end_board_positions_safe(member.name, today(), "terminated")
        self.assertEqual(ended, 1)
        chapter.reload()
        board = chapter.board_members[0]
        self.assertEqual(board.is_active, 0)
        self.assertEqual(str(board.to_date), today())

    def test_end_board_positions_safe_no_volunteer_returns_zero(self):
        member = self._make_member()
        self.assertEqual(ti.end_board_positions_safe(member.name, today(), "x"), 0)

    def test_end_board_positions_safe_missing_member_returns_zero(self):
        self.assertEqual(ti.end_board_positions_safe("NONEXISTENT-MEMBER", today(), "x"), 0)

    # ==================================================================
    # disable_chapter_memberships_safe
    # ==================================================================
    def test_disable_chapter_memberships_safe_disables_member(self):
        member = self._make_member()
        chapter = self._make_chapter_with_member(member)
        disabled = ti.disable_chapter_memberships_safe(member.name, today(), "terminated")
        self.assertEqual(disabled, 1)
        chapter.reload()
        cm = chapter.members[0]
        self.assertEqual(cm.enabled, 0)
        self.assertEqual(cm.status, "Inactive")

    def test_disable_chapter_memberships_safe_none_returns_zero(self):
        member = self._make_member()
        self.assertEqual(ti.disable_chapter_memberships_safe(member.name, today(), "x"), 0)

    # ==================================================================
    # suspend_team_memberships_safe
    # ==================================================================
    def test_suspend_team_memberships_safe_no_volunteer_returns_zero(self):
        member = self._make_member()
        self.assertEqual(ti.suspend_team_memberships_safe(member.name, today(), "x"), 0)

    def test_suspend_team_memberships_safe_removes_team_lead(self):
        member = self._make_member()
        user = self._make_user(member)
        team = self.create_test_team(team_lead=user.name)
        affected = ti.suspend_team_memberships_safe(member.name, today(), "terminated")
        # team-lead removal does not increment teams_affected, but team_lead is cleared
        self.assertIsNone(frappe.db.get_value("Team", team.name, "team_lead") or None)

    def test_suspend_team_memberships_safe_missing_member_returns_zero(self):
        self.assertEqual(ti.suspend_team_memberships_safe("NONEXISTENT-MEMBER", today(), "x"), 0)

    def _add_team_membership(self, volunteer, team=None, team_role_name="Team Member"):
        """Append an active Team Member row for the volunteer and return (team, row_name)."""
        # Adding a Team Member triggers the Team controller's assignment-history /
        # notification hooks, which log (and swallow) "Team ... not found" errors
        # against the not-yet-committed team. That is unrelated to the termination
        # logic under test, so allow it past the Error Log guard.
        self.expectErrorLog(
            "Team Assignment History Error",
            "Team Notification Error",
            "Team Event Emission Error",
        )
        if team is None:
            team = self.create_test_team()
        team_role = self.ensure_team_role(team_role_name)
        team_doc = frappe.get_doc("Team", team.name)
        team_doc.append(
            "team_members",
            {
                "volunteer": volunteer.name,
                "team_role": team_role.name,
                "from_date": today(),
                "is_active": 1,
                "status": "Active",
            },
        )
        team_doc.save()
        return team, team_doc.team_members[-1].name

    def test_suspend_team_memberships_safe_soft_disables_not_deletes(self):
        """Suspending must NOT physically delete Team Member rows (otherwise they can
        never be restored). It should soft-disable them so unsuspend can re-enable."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        team, row_name = self._add_team_membership(volunteer)

        affected = ti.suspend_team_memberships_safe(member.name, today(), "suspended")
        self.assertEqual(affected, 1)

        # The row must still exist (not deleted) ...
        self.assertTrue(frappe.db.exists("Team Member", row_name))
        # ... and be soft-disabled.
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "is_active"), 0)
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "status"), "Inactive")
        self.assertEqual(str(frappe.db.get_value("Team Member", row_name, "to_date")), today())

    def test_suspend_unsuspend_team_round_trip_restores_membership(self):
        """End-to-end: suspending then unsuspending a member with restore_teams=True
        restores the active team membership."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        team, row_name = self._add_team_membership(volunteer)

        suspend_result = ti.suspend_member_safe(member.name, "policy", suspend_teams=True)
        self.assertTrue(suspend_result["success"])
        self.assertEqual(suspend_result["teams_suspended"], 1)
        # Soft-disabled during suspension.
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "is_active"), 0)

        unsuspend_result = ti.unsuspend_member_safe(member.name, "appeal upheld", restore_teams=True)
        self.assertTrue(unsuspend_result["success"])
        self.assertEqual(unsuspend_result.get("teams_restored"), 1)
        # Membership restored to active.
        self.assertTrue(frappe.db.exists("Team Member", row_name))
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "is_active"), 1)
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "status"), "Active")

    def test_unsuspend_member_safe_restore_teams_false_leaves_teams_disabled(self):
        """With restore_teams=False the suspended team rows stay disabled."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        team, row_name = self._add_team_membership(volunteer)

        ti.suspend_member_safe(member.name, "policy", suspend_teams=True)
        result = ti.unsuspend_member_safe(member.name, "appeal", restore_teams=False)
        self.assertTrue(result["success"])
        self.assertEqual(result.get("teams_restored", 0), 0)
        self.assertEqual(frappe.db.get_value("Team Member", row_name, "is_active"), 0)

    def test_restore_only_touches_rows_suspension_disabled(self):
        """A row that was already inactive *before* suspension (no suspension marker)
        must NOT be reactivated on unsuspend — only suspension-disabled rows restore."""
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        team, active_row = self._add_team_membership(volunteer)
        # A second membership that is already inactive (legitimately) before suspension.
        _, preinactive_row = self._add_team_membership(volunteer, team=team)
        frappe.db.set_value(
            "Team Member",
            preinactive_row,
            {"is_active": 0, "status": "Inactive"},
            update_modified=False,
        )

        ti.suspend_member_safe(member.name, "policy", suspend_teams=True)
        # Only the previously-active row gets suspended/marked.
        self.assertEqual(frappe.db.get_value("Team Member", active_row, "is_active"), 0)
        self.assertEqual(frappe.db.get_value("Team Member", preinactive_row, "is_active"), 0)

        result = ti.unsuspend_member_safe(member.name, "appeal", restore_teams=True)
        self.assertTrue(result["success"])
        # Exactly one row restored (the one suspension disabled); the pre-inactive
        # row carries no marker and stays inactive.
        self.assertEqual(result.get("teams_restored"), 1)
        self.assertEqual(frappe.db.get_value("Team Member", active_row, "is_active"), 1)
        self.assertEqual(frappe.db.get_value("Team Member", preinactive_row, "is_active"), 0)

    # ==================================================================
    # deactivate_user_account_safe / reactivate_user_account_safe
    # ==================================================================
    def test_deactivate_user_account_safe_disables_user(self):
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        result = ti.deactivate_user_account_safe(member.name, "Voluntary", "left")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)

    def test_deactivate_user_account_safe_no_user_returns_true(self):
        member = self._make_member()
        self.assertTrue(ti.deactivate_user_account_safe(member.name, "Voluntary", "left"))

    def test_reactivate_user_account_safe_enables_user(self):
        member = self._make_member()
        user = self._make_user(member, enabled=0)
        result = ti.reactivate_user_account_safe(member.name, "appeal")
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

    def test_reactivate_user_account_safe_no_user_returns_true(self):
        member = self._make_member()
        self.assertTrue(ti.reactivate_user_account_safe(member.name, "appeal"))

    # ==================================================================
    # suspend_member_safe / unsuspend_member_safe
    # ==================================================================
    def test_suspend_member_safe_changes_status(self):
        member = self._make_member()
        result = ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        self.assertTrue(result["success"])
        self.assertTrue(result["member_suspended"])
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Suspended")

    def test_suspend_member_safe_already_suspended_noop(self):
        member = self._make_member(status="Suspended")
        result = ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        self.assertFalse(result["member_suspended"])
        self.assertTrue(any("already suspended" in a for a in result["actions_taken"]))

    def test_suspend_member_safe_suspends_user(self):
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        result = ti.suspend_member_safe(member.name, "policy", suspend_user=True, suspend_teams=False)
        self.assertTrue(result["user_suspended"])
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)

    def test_suspend_member_safe_missing_member(self):
        result = ti.suspend_member_safe("NONEXISTENT-MEMBER", "policy")
        self.assertFalse(result["success"])

    def test_unsuspend_member_safe_restores_status(self):
        member = self._make_member()
        ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        result = ti.unsuspend_member_safe(member.name, "appeal upheld")
        self.assertTrue(result["success"])
        self.assertTrue(result["member_unsuspended"])
        # pre-suspension status was Active -> restored to Active
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Active")

    def test_unsuspend_member_safe_not_suspended_returns_error(self):
        member = self._make_member()
        result = ti.unsuspend_member_safe(member.name, "appeal")
        self.assertFalse(result["success"])
        self.assertIn("not suspended", result["error"])

    def test_unsuspend_member_safe_reactivates_user(self):
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)
        result = ti.unsuspend_member_safe(member.name, "appeal")
        self.assertTrue(result["user_unsuspended"])
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 1)

    # ==================================================================
    # terminate_volunteer_records_safe
    # ==================================================================
    def test_terminate_volunteer_records_safe_sets_inactive(self):
        member = self._make_member()
        volunteer = self._make_volunteer(member)
        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["volunteers_terminated"], 1)
        self.assertEqual(frappe.db.get_value("Volunteer", volunteer.name, "status"), "Inactive")
        note = frappe.db.get_value("Volunteer", volunteer.name, "note") or ""
        self.assertIn("Inactive reason", note)

    def test_terminate_volunteer_records_safe_none_returns_zero(self):
        member = self._make_member()
        result = ti.terminate_volunteer_records_safe(member.name, "Voluntary", today(), "x")
        self.assertEqual(result["volunteers_terminated"], 0)

    def test_terminate_volunteer_records_safe_missing_member(self):
        result = ti.terminate_volunteer_records_safe("NONEXISTENT-MEMBER", "Voluntary", today(), "x")
        self.assertEqual(result["volunteers_terminated"], 0)

    # ==================================================================
    # terminate_employee_records_safe
    # ==================================================================
    def test_terminate_employee_records_safe_no_employee_returns_zero(self):
        member = self._make_member()
        result = ti.terminate_employee_records_safe(member.name, "Voluntary", today(), "x")
        self.assertEqual(result["employees_terminated"], 0)
        self.assertEqual(result["errors"], [])

    def test_terminate_employee_records_safe_missing_member(self):
        result = ti.terminate_employee_records_safe("NONEXISTENT-MEMBER", "Voluntary", today(), "x")
        self.assertEqual(result["employees_terminated"], 0)

    # ==================================================================
    # get_member_suspension_status
    # ==================================================================
    def test_get_member_suspension_status_active_member(self):
        member = self._make_member()
        status = ti.get_member_suspension_status(member.name)
        self.assertFalse(status["is_suspended"])
        self.assertEqual(status["member_status"], "Active")
        self.assertFalse(status["can_unsuspend"])

    def test_get_member_suspension_status_suspended_member(self):
        member = self._make_member()
        ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        status = ti.get_member_suspension_status(member.name)
        self.assertTrue(status["is_suspended"])
        self.assertEqual(status["member_status"], "Suspended")
        self.assertTrue(status["can_unsuspend"])
        self.assertEqual(status["pre_suspension_status"], "Active")

    def test_get_member_suspension_status_missing_member_returns_safe_dict(self):
        status = ti.get_member_suspension_status("NONEXISTENT-MEMBER")
        self.assertIn("error", status)
        self.assertFalse(status["is_suspended"])
        self.assertFalse(status["can_unsuspend"])

    def test_get_member_suspension_status_reports_disabled_user(self):
        """user_suspended reflects a disabled linked user account."""
        member = self._make_member()
        user = self._make_user(member, enabled=0)
        status = ti.get_member_suspension_status(member.name)
        self.assertTrue(status["user_suspended"])
        self.assertEqual(status["member_status"], "Active")

    # ==================================================================
    # cancel_dues_schedule_safe — docstatus==2 inconsistency branch
    # ==================================================================
    def test_cancel_dues_schedule_safe_docstatus2_inconsistency(self):
        """A schedule with docstatus=2 but a non-Cancelled status is repaired
        directly to Cancelled (data-inconsistency branch)."""
        member = self._make_member()
        self.create_test_membership(member_name=member.name)
        schedule = self.create_test_dues_schedule(member.name)
        # Force the inconsistent state the branch is designed to repair.
        frappe.db.set_value(
            "Membership Dues Schedule",
            schedule.name,
            {"docstatus": 2, "status": "Active"},
            update_modified=False,
        )
        result = ti.cancel_dues_schedule_safe(schedule.name)
        self.assertTrue(result)
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"),
            "Cancelled",
        )

    def test_cancel_dues_schedule_safe_already_cancelled_idempotent(self):
        member = self._make_member()
        self.create_test_membership(member_name=member.name)
        schedule = self.create_test_dues_schedule(member.name)
        ti.cancel_dues_schedule_safe(schedule.name)
        # second call is a no-op True and must leave the status Cancelled
        self.assertTrue(ti.cancel_dues_schedule_safe(schedule.name))
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", schedule.name, "status"),
            "Cancelled",
        )

    # ==================================================================
    # deactivate_user_account_safe — disciplinary disable path
    # ==================================================================
    def test_deactivate_user_account_safe_disciplinary_clears_roles(self):
        """Disciplinary termination (not suspend_only) disables the user and
        strips all but essential roles for audit purposes."""
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        # Give the user a non-essential role so we can prove it gets stripped.
        user_doc = frappe.get_doc("User", user.name)
        user_doc.append("roles", {"role": "Verenigingen Member"})
        user_doc.save()
        result = ti.deactivate_user_account_safe(
            member.name, "Disciplinary Action", "policy breach", suspend_only=False
        )
        self.assertTrue(result)
        self.assertEqual(frappe.db.get_value("User", user.name, "enabled"), 0)
        user_doc.reload()
        remaining = {r.role for r in user_doc.roles}
        self.assertNotIn("Verenigingen Member", remaining)

    def test_deactivate_user_account_safe_disciplinary_suspend_only_keeps_roles(self):
        """suspend_only=True even for a disciplinary type only disables (does not
        clear roles)."""
        member = self._make_member()
        user = self._make_user(member, enabled=1)
        user_doc = frappe.get_doc("User", user.name)
        user_doc.append("roles", {"role": "Verenigingen Member"})
        user_doc.save()
        result = ti.deactivate_user_account_safe(
            member.name, "Disciplinary Action", "breach", suspend_only=True
        )
        self.assertTrue(result)
        user_doc.reload()
        self.assertIn("Verenigingen Member", {r.role for r in user_doc.roles})

    # ==================================================================
    # unsuspend_member_safe — restore non-Active pre-suspension status
    # ==================================================================
    def test_unsuspend_member_safe_restores_pre_suspension_status_from_notes(self):
        """The pre-suspension status recorded in notes is restored on unsuspend
        (not the default 'Active')."""
        member = self._make_member()
        # Suspend from a non-Active status so restore must read it from notes.
        frappe.db.set_value("Member", member.name, "status", "Quit")
        member.reload()
        ti.suspend_member_safe(member.name, "policy", suspend_teams=False)
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Suspended")
        result = ti.unsuspend_member_safe(member.name, "appeal upheld")
        self.assertTrue(result["success"])
        self.assertEqual(frappe.db.get_value("Member", member.name, "status"), "Quit")

    # ==================================================================
    # terminate_employee_records_safe — actual employee update branches
    # ==================================================================
    def _make_employee_for_member(self, member, user_email):
        # The harness-OWNED company, by name -- not a scan. The chain this replaces fell
        # back to `get_value("Company", {"default_currency": "EUR"}, "name")`, which is the
        # NEWEST EUR company (`db.get_value` defaults to `creation DESC`), i.e. whatever a
        # co-tenant suite created last. Pinned in
        # test_termination_integration_extra_coverage.test_get_company_never_borrows_by_currency.
        company = self._get_test_company()
        emp = frappe.new_doc("Employee")
        emp.first_name = "TermInt"
        emp.last_name = "Emp"
        emp.employee_name = "TermInt Emp"
        emp.user_id = user_email
        emp.company = company
        emp.date_of_birth = "1990-01-01"
        emp.date_of_joining = today()
        emp.gender = "Other"
        emp.status = "Active"
        emp.insert()
        return emp

    def test_terminate_employee_records_safe_deceased_sets_left(self):
        member = self._make_member()
        user = self._make_user(member)
        emp = self._make_employee_for_member(member, user.name)
        result = ti.terminate_employee_records_safe(member.name, "Deceased", today(), "passed away")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Deceased")
        self.assertEqual(str(emp.relieving_date), today())

    def test_terminate_employee_records_safe_voluntary_resignation(self):
        member = self._make_member()
        user = self._make_user(member)
        emp = self._make_employee_for_member(member, user.name)
        result = ti.terminate_employee_records_safe(member.name, "Voluntary", today(), "left")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.status, "Left")
        self.assertEqual(emp.reason_for_leaving, "Resignation")

    def test_terminate_employee_records_safe_disciplinary_quit(self):
        member = self._make_member()
        user = self._make_user(member)
        emp = self._make_employee_for_member(member, user.name)
        result = ti.terminate_employee_records_safe(member.name, "Disciplinary Action", today(), "breach")
        self.assertEqual(result["employees_terminated"], 1)
        emp.reload()
        self.assertEqual(emp.reason_for_leaving, "Quit")
