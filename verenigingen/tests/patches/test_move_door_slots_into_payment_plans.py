"""#2127: the patch moves each door's Monthly/Annual slots, postal minimums and amount options into plans.

Probe shortcut, stated: an old-shape door is built by inserting the (now hidden) legacy fields with the
door's validation skipped, because the new validation refuses a Regular door without plans. That is the
shape such a door has in the database before the patch; the patch is then run through its own execute().
"""

import frappe

from verenigingen.patches.v2_2.move_door_slots_into_payment_plans import execute
from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

DOOR = "Membership Application Door"


class TestMoveDoorSlotsIntoPaymentPlans(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        self.monthly = self._plan_template("Monthly")
        self.annual = self._plan_template("Annual")

    def _old_shape_door(self, **legacy):
        door = frappe.get_doc(
            {
                "doctype": DOOR,
                "title": "Oude deur",
                "slug": f"oud-{frappe.generate_hash(length=8).lower()}",
                "membership_type": self.membership_type.name,
                "form_shape": "Regular",
                "enabled": 1,
            }
            | legacy
        )
        door.flags.ignore_validate = True
        door.insert()
        self.track_doc(DOOR, door.name)
        plan_rows = frappe.db.count("Membership Application Door Plan", {"parent": door.name})  # doctype-ok: new in #2127
        self.assertEqual(plan_rows, 0)
        return door.name

    def _plans(self, door):
        return [
            (row.dues_template, int(row.is_default), row.postal_minimum)
            for row in frappe.get_doc(DOOR, door).plans
        ]

    def _options(self, door):
        return [(row.dues_template, row.amount) for row in frappe.get_doc(DOOR, door).amount_options]

    def test_both_slots_become_plans_and_monthly_is_the_default(self):
        door = self._old_shape_door(
            monthly_dues_template=self.monthly,
            annual_dues_template=self.annual,
            postal_minimum_monthly=4,
            postal_minimum_annual=40,
            amount_options=[
                {"frequency": "Annual", "amount": 60},
                {"frequency": "Monthly", "amount": 6},
                {"frequency": "Monthly", "amount": 9},
            ],
        )

        execute()

        self.assertEqual(self._plans(door), [(self.monthly, 1, 4), (self.annual, 0, 40)])
        self.assertEqual(
            sorted(self._options(door)), sorted([(self.annual, 60), (self.monthly, 6), (self.monthly, 9)])
        )

    def test_a_door_with_only_an_annual_slot_defaults_to_it(self):
        door = self._old_shape_door(annual_dues_template=self.annual, postal_minimum_annual=25)
        execute()
        self.assertEqual(self._plans(door), [(self.annual, 1, 25)])

    def test_a_door_with_only_a_monthly_slot_defaults_to_it(self):
        door = self._old_shape_door(monthly_dues_template=self.monthly)
        execute()
        self.assertEqual(self._plans(door), [(self.monthly, 1, 0)])

    def test_the_migrated_door_is_a_valid_door(self):
        door = self._old_shape_door(
            monthly_dues_template=self.monthly,
            annual_dues_template=self.annual,
            amount_options=[{"frequency": "Monthly", "amount": 6}],
        )
        execute()
        migrated = frappe.get_doc(DOOR, door)
        migrated.save()  # real validation: one default, no duplicates, presets name a plan
        self.assertEqual(len(migrated.plans), 2)

    def test_running_it_again_changes_nothing(self):
        door = self._old_shape_door(
            monthly_dues_template=self.monthly,
            annual_dues_template=self.annual,
            amount_options=[{"frequency": "Annual", "amount": 60}],
        )
        execute()
        first = (self._plans(door), self._options(door))
        execute()
        self.assertEqual((self._plans(door), self._options(door)), first)

    def test_a_door_that_already_has_plans_is_left_alone(self):
        """A door an admin has already moved to plans keeps its choices, even if its hidden legacy
        fields still name templates."""
        door = self._old_shape_door(monthly_dues_template=self.monthly)
        doc = frappe.get_doc(DOOR, door)
        doc.append("plans", {"dues_template": self.annual, "is_default": 1, "postal_minimum": 7})
        doc.flags.ignore_validate = True
        doc.save()
        execute()
        self.assertEqual(self._plans(door), [(self.annual, 1, 7)])

    def test_a_door_without_slots_gets_no_plans_and_no_error(self):
        door = self._old_shape_door(form_shape="Housemate")
        execute()
        self.assertEqual(self._plans(door), [])

    def test_an_amount_option_for_a_frequency_the_door_never_offered_is_dropped(self):
        door = self._old_shape_door(
            monthly_dues_template=self.monthly, amount_options=[{"frequency": "Annual", "amount": 60}]
        )
        execute()
        self.assertEqual(self._options(door), [])
        self.assertEqual(self._plans(door), [(self.monthly, 1, 0)])
