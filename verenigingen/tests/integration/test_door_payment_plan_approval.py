"""#2127: a plan of any billing frequency, chosen on /word-lid, becomes that dues schedule at approval.

Driven through the real flow: submit_short_application as Guest -> the emailed confirm link (POST) ->
approve_application as staff. No field is set by hand to stand in for a step of that flow.
"""

import frappe

from verenigingen.api import short_application as sa
from verenigingen.services.member.application.door_plans import offered_plans
from verenigingen.services.member.application.short_application_confirm import CONFIRM_TOKEN_PURPOSE
from verenigingen.tests.integration.test_application_record_approval import IBAN, SUBMISSION, ApprovalCase
from verenigingen.utils.security.guest_return_tokens import generate_guest_return_token


class TestPlanBecomesDuesSchedule(ApprovalCase):
    def _stage_plan(self, door, plan, amount, **overrides):
        data = {
            "first_name": "Anna",
            "last_name": "Berg",
            "email": self.email,
            "address_line1": "Kerkstraat",
            "postal_code": "1234AB",
            "house_number": "12",
            "city": f"Nergenshuizen-{frappe.generate_hash(length=6)}",
            "country": "Netherlands",
            "plan": plan["id"],
            "amount": str(amount),
            "iban": IBAN,
            "bank_account_name": "A. Berg",
            "consent": "1",
            "leave_this_empty": "",
            "magazine_delivery": "Geen",
            "starter_guide_delivery": "Geen",
        }
        data.update(overrides)
        previous = frappe.session.user
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            response = sa.submit_short_application(door.name, **data)
        finally:
            frappe.set_user(previous)
        self.assertTrue(response["success"], response)
        name = frappe.get_all(SUBMISSION, {"email": self.email, "status": "Unconfirmed"}, pluck="name")[0]
        self.track_doc(SUBMISSION, name)
        token = generate_guest_return_token(CONFIRM_TOKEN_PURPOSE, name)
        self._request_from_fresh_ip()
        frappe.set_user("Guest")
        try:
            confirmed = sa.confirm_short_application(name, token)
        finally:
            frappe.set_user(previous)
        self.assertTrue(confirmed["success"], confirmed)
        return name

    def _approved_schedule(self, door, template, amount, **overrides):
        [plan] = [p for p in offered_plans(door) if p["template"] == template]
        name = self._stage_plan(door, plan, amount, **overrides)
        self.assertTrue(self._approve_as(name)["success"])
        member = frappe.db.get_value(SUBMISSION, name, "member")
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            {"member": member, "is_template": 0},
            ["billing_frequency", "dues_rate", "template_reference", "status"],
        )
        self.assertEqual(len(schedules), 1, schedules)
        return schedules[0]

    def test_a_quarterly_plan_yields_a_quarterly_dues_schedule(self):
        template = self._plan_template("Quarterly", mode="Fixed", dues_rate=30, minimum_amount=0)
        door = self._door(plans=[{"dues_template": template, "is_default": 1}])

        schedule = self._approved_schedule(door, template, 30)

        self.assertEqual(schedule.billing_frequency, "Quarterly")
        self.assertEqual(schedule.dues_rate, 30)
        self.assertEqual(schedule.template_reference, template)

    def test_a_semi_annual_flexible_plan_with_a_custom_amount_yields_that_schedule(self):
        template = self._plan_template("Semi-Annual", suggested_amount=50, allow_custom_amount=1, minimum_amount=5)
        door = self._door(plans=[{"dues_template": template, "is_default": 1}])

        schedule = self._approved_schedule(door, template, 41.5)

        self.assertEqual(schedule.billing_frequency, "Semi-Annual")
        self.assertEqual(schedule.dues_rate, 41.5)
        self.assertEqual(schedule.template_reference, template)

    def test_each_plan_of_one_door_bills_on_its_own_period(self):
        quarterly = self._plan_template("Quarterly", mode="Fixed", dues_rate=30, minimum_amount=0)
        annual = self._plan_template("Annual", mode="Income-Based", minimum_amount=20)
        door = self._door(
            plans=[{"dues_template": quarterly, "is_default": 1}, {"dues_template": annual}]
        )
        self.assertEqual(self._approved_schedule(door, annual, 77.77).billing_frequency, "Annual")

    def test_an_amount_at_the_floor_approval_applies_becomes_a_schedule_with_a_stale_template_minimum(self):
        """The plan template's own minimum (5) is below the membership type's (25), which approval also
        enforces: the floor submit applies must be the higher one, and the amount at it must reach a
        schedule (an approval-time refusal is swallowed and leaves the member with none)."""
        frappe.db.set_value("Membership Type", self.membership_type.name, "minimum_amount", 25)
        type_template = frappe.db.get_value(
            "Membership Type", self.membership_type.name, "dues_schedule_template"
        )
        frappe.db.set_value("Membership Dues Schedule", type_template, {"dues_rate": 30, "suggested_amount": 30})
        template = self._plan_template("Quarterly", suggested_amount=30, allow_custom_amount=1, minimum_amount=5)
        door = self._door(plans=[{"dues_template": template, "is_default": 1}])
        [plan] = offered_plans(door)
        self.assertEqual(plan["minimum"], 25)

        schedule = self._approved_schedule(door, template, 25)

        self.assertEqual((schedule.billing_frequency, schedule.dues_rate), ("Quarterly", 25))

    def test_a_fixed_plan_on_paper_bills_the_postal_minimum_when_it_is_above_the_rate(self):
        template = self._plan_template("Monthly", mode="Fixed", dues_rate=40, minimum_amount=0)
        door = self._door(plans=[{"dues_template": template, "is_default": 1, "postal_minimum": 60}])

        paper = self._approved_schedule(door, template, 60, magazine_delivery="Papier")

        self.assertEqual((paper.billing_frequency, paper.dues_rate), ("Monthly", 60))
