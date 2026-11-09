"""Membership Application Door: slug rules, payment plan rules and amount presets."""

import frappe

from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase


class TestMembershipApplicationDoor(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        self.monthly = self._plan_template("Monthly")

    def _unsaved_door(self, membership_type=None, **fields):
        membership_type = membership_type or self.membership_type
        data = {
            "doctype": "Membership Application Door",
            "title": "Testdeur",
            "slug": fields.pop("slug", f"deur-{frappe.generate_hash(length=8).lower()}"),
            "membership_type": membership_type.name,
            "form_shape": "Regular",
        }
        if "plans" not in fields:
            data["plans"] = [{"dues_template": self.monthly, "is_default": 1}]
        data.update(fields)
        return frappe.get_doc(data)

    def _save(self, door):
        door.insert()
        self.track_doc("Membership Application Door", door.name)
        return door

    def test_slug_must_be_lowercase_url_safe(self):
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(slug="Student Leden").insert()
        door = self._save(self._unsaved_door(slug="student-leden"))
        self.assertEqual(door.name, "student-leden")

    def test_slug_bevestig_is_reserved(self):
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(slug="bevestig").insert()

    def test_door_cannot_be_renamed_past_slug_validation(self):
        door = self._save(self._unsaved_door())
        with self.assertRaises(frappe.ValidationError):
            frappe.rename_doc("Membership Application Door", door.name, "bevestig")
        self.assertTrue(frappe.db.exists("Membership Application Door", door.name))
        self.assertFalse(frappe.db.exists("Membership Application Door", "bevestig"))

    def test_template_must_belong_to_door_type(self):
        other_type = self.create_test_membership_type()
        foreign = frappe.db.get_value("Membership Type", other_type.name, "dues_schedule_template")
        self.assertTrue(foreign)
        with self.assertRaisesRegex(frappe.ValidationError, "different membership type"):
            self._unsaved_door(plans=[{"dues_template": foreign, "is_default": 1}]).insert()
        # Control: the same row is fine for the type that owns the template.
        door = self._unsaved_door(other_type, plans=[{"dues_template": foreign, "is_default": 1}])
        self.assertTrue(self._save(door).name)

    def test_a_plan_may_have_any_billing_frequency(self):
        quarterly = self._plan_template("Quarterly")
        semi = self._plan_template("Semi-Annual")
        door = self._save(
            self._unsaved_door(
                plans=[
                    {"dues_template": self.monthly, "is_default": 1},
                    {"dues_template": quarterly},
                    {"dues_template": semi},
                ]
            )
        )
        self.assertEqual(len(door.plans), 3)

    def test_exactly_one_plan_is_the_default(self):
        quarterly = self._plan_template("Quarterly")
        for label, plans in (
            ("none", [{"dues_template": self.monthly}, {"dues_template": quarterly}]),
            ("two", [{"dues_template": self.monthly, "is_default": 1}, {"dues_template": quarterly, "is_default": 1}]),
            ("single, unmarked", [{"dues_template": self.monthly}]),
        ):
            with self.subTest(label), self.assertRaisesRegex(frappe.ValidationError, "exactly one default"):
                self._unsaved_door(plans=plans).insert()
        # Control: one default among several passes.
        self._save(
            self._unsaved_door(
                plans=[{"dues_template": self.monthly}, {"dues_template": quarterly, "is_default": 1}]
            )
        )

    def test_a_template_is_offered_once(self):
        with self.assertRaisesRegex(frappe.ValidationError, "more than once"):
            self._unsaved_door(
                plans=[
                    {"dues_template": self.monthly, "is_default": 1},
                    {"dues_template": self.monthly, "label": "Again"},
                ]
            ).insert()

    def test_non_template_schedule_refused(self):
        member = self.create_test_member()
        # A Cancelled instance schedule skips the active-membership check.
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Instance-{frappe.generate_hash(length=6)}",
                "member": member.name,
                "membership_type": self.membership_type.name,
                "dues_rate": 15,
                "billing_frequency": "Monthly",
                "status": "Cancelled",
                "is_template": 0,
            }
        ).insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        with self.assertRaisesRegex(frappe.ValidationError, "not a dues schedule template"):
            self._unsaved_door(plans=[{"dues_template": schedule.name, "is_default": 1}]).insert()

    def test_a_fixed_template_needs_a_rate(self):
        unrated = self._plan_template("Monthly", mode="Fixed", dues_rate=0)
        with self.assertRaisesRegex(frappe.ValidationError, "no rate"):
            self._unsaved_door(plans=[{"dues_template": unrated, "is_default": 1}]).insert()

    def test_regular_door_needs_at_least_one_plan(self):
        with self.assertRaisesRegex(frappe.ValidationError, "at least one payment plan"):
            self._unsaved_door(plans=[]).insert()
        self._save(self._unsaved_door(form_shape="Housemate", plans=[]))

    def test_amount_option_must_name_a_template_of_one_of_the_plans(self):
        other = self._plan_template("Annual")
        with self.assertRaisesRegex(frappe.ValidationError, "template of one of the payment plans"):
            self._unsaved_door(amount_options=[{"dues_template": other, "amount": 60}]).insert()
        door = self._save(self._unsaved_door(amount_options=[{"dues_template": self.monthly, "amount": 10}]))
        self.assertEqual([row.amount for row in door.amount_options], [10])

    def test_amount_option_below_template_minimum_refused(self):
        minimum = frappe.db.get_value("Membership Dues Schedule", self.monthly, "minimum_amount")
        self.assertTrue(minimum)
        with self.assertRaisesRegex(frappe.ValidationError, "below the template minimum"):
            self._unsaved_door(amount_options=[{"dues_template": self.monthly, "amount": minimum - 0.5}]).insert()
        door = self._save(self._unsaved_door(amount_options=[{"dues_template": self.monthly, "amount": minimum}]))
        self.assertEqual([row.amount for row in door.amount_options], [minimum])

    def test_hidden_questions(self):
        door = self._unsaved_door(hidden_questions=[{"question": "mobile_no"}, {"question": "birth_year"}])
        self.assertEqual(door.hidden(), {"mobile_no", "birth_year"})

    def test_a_template_in_a_door_plan_cannot_change_frequency(self):
        """A plan names its template; changing the template's period under it afterwards would bill the
        applicant's chosen amount on another period."""
        door = self._save(self._unsaved_door())
        template = frappe.get_doc("Membership Dues Schedule", door.plans[0].dues_template)
        template.billing_frequency = "Annual"
        with self.assertRaisesRegex(frappe.ValidationError, "application door"):
            template.save()

    def test_a_template_in_a_door_plan_keeps_its_other_fields_editable(self):
        door = self._save(self._unsaved_door())
        template = frappe.get_doc("Membership Dues Schedule", door.plans[0].dues_template)
        template.minimum_amount = (template.minimum_amount or 0) + 1
        template.save()  # opposite harm: only the frequency is frozen

    def test_a_template_no_door_uses_can_still_change_frequency(self):
        template = frappe.get_doc("Membership Dues Schedule", self._plan_template("Monthly"))
        template.billing_frequency = "Annual"
        template.save()
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", template.name, "billing_frequency"), "Annual"
        )

    def test_a_template_only_settled_applications_chose_can_still_change_frequency(self):
        """Only an application still waiting for approval freezes the period: Approved, Rejected and
        Active members (including imported ones) must not lock a template forever."""
        template = self._plan_template("Monthly")
        member = self.create_test_member()
        for status in ("Approved", "Rejected", "Active"):
            with self.subTest(status):
                frappe.db.set_value(
                    "Member", member.name, {"application_status": status, "application_dues_schedule": template}
                )
                doc = frappe.get_doc("Membership Dues Schedule", template)
                doc.billing_frequency = "Annual" if doc.billing_frequency == "Monthly" else "Monthly"
                doc.save()
