"""
Integration coverage for ``services/volunteer/expense_handlers.py``.

Exercises the Expense Claim doc-event handlers:
  * ``update_member_expense_history`` (on_submit) — resolve Employee -> Volunteer
    -> Member and queue an expense-history update, plus its no-employee /
    no-volunteer / no-member early-returns.
  * ``on_expense_claim_cancel`` (on_cancel) — the same resolution chain queuing a
    history *removal*, plus early-returns.
  * ``notify_expense_approvers`` (on_submit) — approver resolution priority
    (employee.expense_approver -> Department Approver -> Verenigingen
    Administrator role fallback), the EmailService send boundary, and the
    no-approver no-op.
  * ``_get_expense_description`` — empty / single / 3-item-truncation branches.
  * ``_build_expense_approval_message`` — HTML interpolation.

Every handler wraps its body in ``try/except`` + ``frappe.log_error`` and
swallows, so a naive "did not raise" smoke test cannot fail even when the
product is broken. Two hardening techniques (mirrored from
``tests/events/test_team_events_coverage.py``) are used:

1. ``self.assertNoErrorLog()`` around happy / no-op paths — ``frappe.log_error``
   commits independently of the test transaction, so a swallowed exception flips
   a silent green pass into a real failure.
2. Real side-effect assertions — the batch-processor queue call (captured at its
   source as an infra boundary), the EmailService send boundary, the resolved
   recipient/subject/notification_key.

The EmailService factory and the batch-processor queue functions are the ONLY
boundaries patched (never product logic). Patching the email factory also
bypasses the test-site "email disabled" short-circuit so the handler's reaching
of the send boundary is observable.

This module is distinct from ``tests/events/test_expense_events_coverage.py``,
which covers the separate ``events/`` emitter+subscriber chain, not these
doc-event handlers.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import today

from verenigingen.services.volunteer import expense_handlers as eh
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

EMAIL_FACTORY = "verenigingen.services.communication.email_service.get_email_service"
QUEUE_UPDATE = "verenigingen.utils.financial_history_batch_processor.queue_expense_update"
QUEUE_REMOVAL = "verenigingen.utils.financial_history_batch_processor.queue_expense_removal"


class TestExpenseHandlersCoverage(EnhancedTestCase):
    """Real integration coverage for expense_handlers doc-event handlers."""

    # ------------------------------------------------------------------ helpers
    @contextmanager
    def _patch_email_service(self):
        """Patch the EmailService factory boundary; returns a MagicMock service.

        ``send_simple_email`` returns a truthy ``result`` with ``.success = True``
        so the handler walks the success log branch.
        """
        service = MagicMock(name="EmailService")
        service.send_simple_email.return_value = MagicMock(success=True, error_message=None)
        with patch(EMAIL_FACTORY, return_value=service):
            yield service

    def _company(self):
        return (
            "_Test Company"
            if frappe.db.exists("Company", "_Test Company")
            else (frappe.get_all("Company", limit=1, pluck="name") or [None])[0]
        )

    def _accounts(self, company):
        expense = frappe.db.get_value(
            "Account", {"account_type": "Expense Account", "company": company, "is_group": 0}, "name"
        )
        payable = frappe.db.get_value(
            "Account", {"account_type": "Payable", "company": company, "is_group": 0}, "name"
        )
        return expense, payable

    def _make_user(self, prefix="approver"):
        """Create a real, tracked, enabled User account (factory helper)."""
        email = f"{prefix}.{frappe.generate_hash(length=8)}@example.invalid"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": prefix.title(),
                "last_name": "Approver",
                "send_welcome_email": 0,
                "enabled": 1,
            }
        )
        user.insert(ignore_permissions=True)
        self._track_test_document("User", user.name, priority=2)
        return user

    def _make_employee(self, company, *, expense_approver=None, department=None, name_hint="EH"):
        """Create a minimal real Employee (no expense_approver by default)."""
        emp = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"{name_hint}{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        )
        if expense_approver:
            emp.expense_approver = expense_approver
        if department:
            emp.department = department
        emp.insert(ignore_permissions=True)
        self._track_test_document("Employee", emp.name, priority=2)
        return emp

    def _make_volunteer_member_employee(self, *, expense_approver=None, department=None):
        """Member + Volunteer (linked to Employee via employee_id) + Employee."""
        company = self._company()
        if not company:
            self.skipTest("No Company available")
        member = self.create_test_member(first_name="EHist", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = self._make_employee(company, expense_approver=expense_approver, department=department)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        volunteer.reload()
        return member, volunteer, emp, company

    def _make_expense_claim(self, employee, company, *, expenses=None):
        expense_acct, payable = self._accounts(company)
        if not expense_acct or not payable:
            self.skipTest("No expense/payable accounts available")
        if expenses is None:
            expenses = [
                {
                    "expense_type": "Food",
                    "amount": 9.0,
                    "sanctioned_amount": 9.0,
                    "expense_date": today(),
                    "default_account": expense_acct,
                    "description": "Train ticket",
                }
            ]
        else:
            for row in expenses:
                row.setdefault("default_account", expense_acct)
        ec = frappe.get_doc(
            {
                "doctype": "Expense Claim",
                "employee": employee.name,
                "company": company,
                "custom_organization_type": "National",
                "posting_date": today(),
                "currency": "EUR",
                "exchange_rate": 1,
                "payable_account": payable,
                "expenses": expenses,
            }
        )
        ec.insert(ignore_permissions=True)
        self._track_test_document("Expense Claim", ec.name, priority=1)
        return ec

    def _make_department(self, company, approver_user):
        """Create a Department with a single expense approver (tier-2 fallback)."""
        dept = frappe.get_doc(
            {
                "doctype": "Department",
                "department_name": f"EH Dept {frappe.generate_hash(length=6)}",
                "company": company,
                "expense_approvers": [{"approver": approver_user}],
            }
        )
        dept.insert(ignore_permissions=True)
        self._track_test_document("Department", dept.name, priority=3)
        return dept

    # ==================================================================
    # update_member_expense_history
    # ==================================================================
    def test_update_history_queues_for_volunteer_claim(self):
        """A claim whose employee -> volunteer -> member resolves queues an update."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)

        with patch(QUEUE_UPDATE) as q:
            with self.assertNoErrorLog():
                eh.update_member_expense_history(ec)
            q.assert_called_once_with(member.name, ec.name)

    def test_update_history_no_employee_noop(self):
        """No employee on the claim -> early return, no queue, no error."""
        fake = frappe._dict(name="EC-noemp", employee=None)
        with patch(QUEUE_UPDATE) as q:
            with self.assertNoErrorLog():
                self.assertIsNone(eh.update_member_expense_history(fake))
            q.assert_not_called()

    def test_update_history_employee_not_volunteer_noop(self):
        """An employee with no linked Volunteer -> early return, no queue."""
        company = self._company()
        if not company:
            self.skipTest("No Company")
        emp = self._make_employee(company)  # no Volunteer points at this employee
        ec = self._make_expense_claim(emp, company)
        with patch(QUEUE_UPDATE) as q:
            with self.assertNoErrorLog():
                eh.update_member_expense_history(ec)
            q.assert_not_called()

    def test_update_history_volunteer_without_member_noop(self):
        """Volunteer exists but is not linked to a Member -> early return, no queue."""
        company = self._company()
        if not company:
            self.skipTest("No Company")
        # Volunteer created without a member link.
        volunteer = self.create_test_volunteer(member_name=None)
        # create_test_volunteer may auto-create a member; force the no-member branch.
        frappe.db.set_value("Volunteer", volunteer.name, "member", None, update_modified=False)
        emp = self._make_employee(company)
        frappe.db.set_value("Volunteer", volunteer.name, "employee_id", emp.name, update_modified=False)
        ec = self._make_expense_claim(emp, company)
        with patch(QUEUE_UPDATE) as q:
            with self.assertNoErrorLog():
                eh.update_member_expense_history(ec)
            q.assert_not_called()

    def test_update_history_swallows_and_logs_on_failure(self):
        """If queue_expense_update raises, the handler logs and does NOT propagate."""
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)
        self.expectErrorLog("Expense History Queue Error")
        with patch(QUEUE_UPDATE, side_effect=RuntimeError("boom")):
            # Must NOT raise — the expense-claim submission must not fail.
            self.assertIsNone(eh.update_member_expense_history(ec))

    # ==================================================================
    # on_expense_claim_cancel
    # ==================================================================
    def test_cancel_queues_removal_for_volunteer_claim(self):
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)
        with patch(QUEUE_REMOVAL) as q:
            with self.assertNoErrorLog():
                eh.on_expense_claim_cancel(ec)
            q.assert_called_once_with(member.name, ec.name)

    def test_cancel_no_employee_noop(self):
        fake = frappe._dict(name="EC-noemp", employee=None)
        with patch(QUEUE_REMOVAL) as q:
            with self.assertNoErrorLog():
                self.assertIsNone(eh.on_expense_claim_cancel(fake))
            q.assert_not_called()

    def test_cancel_employee_not_volunteer_noop(self):
        company = self._company()
        if not company:
            self.skipTest("No Company")
        emp = self._make_employee(company)
        ec = self._make_expense_claim(emp, company)
        with patch(QUEUE_REMOVAL) as q:
            with self.assertNoErrorLog():
                eh.on_expense_claim_cancel(ec)
            q.assert_not_called()

    def test_cancel_swallows_and_logs_on_failure(self):
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        ec = self._make_expense_claim(emp, company)
        self.expectErrorLog("Expense History Removal Error")
        with patch(QUEUE_REMOVAL, side_effect=RuntimeError("boom")):
            self.assertIsNone(eh.on_expense_claim_cancel(ec))

    # ==================================================================
    # notify_expense_approvers
    # ==================================================================
    def test_notify_uses_employee_expense_approver(self):
        """employee.expense_approver (priority 1) drives the recipient."""
        approver = self._make_user("emp-approver")
        member, volunteer, emp, company = self._make_volunteer_member_employee(
            expense_approver=approver.name
        )
        ec = self._make_expense_claim(emp, company)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                eh.notify_expense_approvers(ec)
            svc.send_simple_email.assert_called_once()
            kwargs = svc.send_simple_email.call_args.kwargs
            self.assertEqual(kwargs.get("recipients"), [approver.email])
            self.assertEqual(kwargs.get("notification_key"), "expense_approval_request")
            self.assertEqual(kwargs.get("reference_doctype"), "Expense Claim")
            self.assertEqual(kwargs.get("reference_name"), ec.name)
            self.assertIn(ec.name, kwargs.get("subject", ""))

    def test_notify_admin_role_fallback_resolves_approver(self):
        """REGRESSION: with no employee approver and no department approver, the
        final fallback must resolve a 'Verenigingen Administrator' user and reach
        the send boundary.

        Before the typo fix the role filter queried the misspelled
        'Vereinigingen Administrator' (which exists nowhere), so this branch was
        dead and an approver-less expense notified NOBODY. This test fails on the
        old code (no send) and passes after the fix.
        """
        # Sanity: the real role exists and has at least one user — the fallback
        # has something to resolve to.
        self.assertTrue(frappe.db.exists("Role", "Verenigingen Administrator"))
        admin_with_email = frappe.db.sql(
            """
            SELECT hr.parent
            FROM `tabHas Role` hr
            JOIN `tabUser` u ON u.name = hr.parent
            WHERE hr.role = 'Verenigingen Administrator'
              AND hr.parenttype = 'User'
              AND u.email IS NOT NULL AND u.email != ''
            LIMIT 1
            """
        )
        if not admin_with_email:
            self.skipTest("No 'Verenigingen Administrator' user with an email on this site")

        # Employee with NO expense_approver and NO department -> falls through to
        # the role fallback.
        member, volunteer, emp, company = self._make_volunteer_member_employee()
        self.assertFalse(emp.expense_approver)
        self.assertFalse(emp.department)
        ec = self._make_expense_claim(emp, company)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                eh.notify_expense_approvers(ec)
            svc.send_simple_email.assert_called_once()
            recipients = svc.send_simple_email.call_args.kwargs.get("recipients")
            self.assertEqual(len(recipients), 1)
            # The recipient must be a real email belonging to a user holding the
            # (correctly-spelled) Verenigingen Administrator role.
            recipient_user = frappe.db.get_value("User", {"email": recipients[0]}, "name")
            self.assertIsNotNone(recipient_user, recipients)
            self.assertTrue(
                frappe.db.exists(
                    "Has Role",
                    {"parent": recipient_user, "role": "Verenigingen Administrator", "parenttype": "User"},
                ),
                "fallback recipient must hold the Verenigingen Administrator role",
            )

    def test_notify_department_approver_fallback(self):
        """No employee approver, but the employee's Department has an expense
        approver -> that department approver is used (priority 2)."""
        company = self._company()
        if not company:
            self.skipTest("No Company")
        dept_approver = self._make_user("dept-approver")
        dept = self._make_department(company, dept_approver.name)

        member = self.create_test_member(first_name="Dept", last_name="Member", birth_date="1990-01-01")
        volunteer = self.create_test_volunteer(member_name=member.name)
        emp = self._make_employee(company, department=dept.name)
        volunteer.db_set("employee_id", emp.name, update_modified=False)
        ec = self._make_expense_claim(emp, company)

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                eh.notify_expense_approvers(ec)
            svc.send_simple_email.assert_called_once()
            self.assertEqual(
                svc.send_simple_email.call_args.kwargs.get("recipients"), [dept_approver.email]
            )

    def test_notify_no_employee_noop(self):
        fake = frappe._dict(name="EC-noemp", employee=None)
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                self.assertIsNone(eh.notify_expense_approvers(fake))
            svc.send_simple_email.assert_not_called()

    def test_notify_no_approver_resolved_noop(self):
        """If NO approver can be resolved at all, the handler warns and returns —
        no send, no Error Log.

        All three resolution tiers must be empty: the employee has no
        expense_approver and no department, and the admin-role fallback finds no
        user. veg11 has many ``Verenigingen Administrator`` users, so we empty
        that tier *inside this test's transaction* (FrappeTestCase rolls it back),
        making the genuine no-op branch deterministic on any site rather than a
        perpetual skip.
        """
        company = self._company()
        if not company:
            self.skipTest("No Company")
        # Transaction-local: removes the tier-3 fallback for this test only; the
        # FrappeTestCase rollback restores every Has Role row at tearDown.
        frappe.db.delete("Has Role", {"role": "Verenigingen Administrator", "parenttype": "User"})
        emp = self._make_employee(company)  # no expense_approver, no department
        ec = self._make_expense_claim(emp, company)
        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                self.assertIsNone(eh.notify_expense_approvers(ec))
            svc.send_simple_email.assert_not_called()

    def test_notify_swallows_and_logs_on_failure(self):
        """If the EmailService send raises, the handler logs and does not propagate."""
        approver = self._make_user("boom-approver")
        member, volunteer, emp, company = self._make_volunteer_member_employee(
            expense_approver=approver.name
        )
        ec = self._make_expense_claim(emp, company)
        self.expectErrorLog("Expense Approval Notification Error")
        svc = MagicMock(name="EmailService")
        svc.send_simple_email.side_effect = RuntimeError("smtp down")
        with patch(EMAIL_FACTORY, return_value=svc):
            self.assertIsNone(eh.notify_expense_approvers(ec))

    def test_notify_context_includes_company_currency_and_member(self):
        """The email context carries the resolved member, volunteer and the
        company default currency."""
        approver = self._make_user("ctx-approver")
        member, volunteer, emp, company = self._make_volunteer_member_employee(
            expense_approver=approver.name
        )
        ec = self._make_expense_claim(emp, company)
        company_currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"

        with self._patch_email_service() as svc:
            with self.assertNoErrorLog():
                eh.notify_expense_approvers(ec)
            # message is HTML built from context; assert the currency and ids made it.
            message = svc.send_simple_email.call_args.kwargs.get("message", "")
            self.assertIn(ec.name, message)
            self.assertIn(company_currency, message)

    # ==================================================================
    # _get_expense_description
    # ==================================================================
    def test_description_empty_expenses(self):
        fake = frappe._dict(expenses=[])
        self.assertEqual(eh._get_expense_description(fake), "No description provided")

    def test_description_single_item(self):
        fake = frappe._dict(expenses=[frappe._dict(description="Train ticket")])
        self.assertEqual(eh._get_expense_description(fake), "Train ticket")

    def test_description_truncates_to_three_items(self):
        """Only the first 3 item descriptions are listed; the rest collapse into a
        '... and N more items' suffix."""
        fake = frappe._dict(
            expenses=[frappe._dict(description=f"Item {i}") for i in range(5)]
        )
        desc = eh._get_expense_description(fake)
        self.assertIn("Item 0", desc)
        self.assertIn("Item 1", desc)
        self.assertIn("Item 2", desc)
        self.assertNotIn("Item 3", desc)
        self.assertIn("and 2 more items", desc)

    def test_description_long_text_clipped_to_50_chars(self):
        long_text = "X" * 80
        fake = frappe._dict(expenses=[frappe._dict(description=long_text)])
        desc = eh._get_expense_description(fake)
        self.assertEqual(desc, "X" * 50)

    def test_description_items_without_description_fall_back(self):
        """If the (<=3) items all have blank descriptions, the empty-join fallback
        message is returned."""
        fake = frappe._dict(expenses=[frappe._dict(description=""), frappe._dict(description=None)])
        self.assertEqual(eh._get_expense_description(fake), "No description provided")

    # ==================================================================
    # _build_expense_approval_message
    # ==================================================================
    def test_build_message_interpolates_context(self):
        context = {
            "expense_id": "EC-XYZ-1",
            "employee_name": "Jane Doe",
            "amount": 42.5,
            "currency": "EUR",
            "expense_date": "2025-01-01",
            "description": "Train; Hotel",
            "review_url": "https://example.invalid/app/expense-claim/EC-XYZ-1",
        }
        html = eh._build_expense_approval_message(context)
        self.assertIn("EC-XYZ-1", html)
        self.assertIn("Jane Doe", html)
        self.assertIn("EUR 42.5", html)
        self.assertIn("2025-01-01", html)
        self.assertIn("Train; Hotel", html)
        self.assertIn("https://example.invalid/app/expense-claim/EC-XYZ-1", html)
