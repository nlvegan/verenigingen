"""Membership Application Door: slug rules, template checks and minimum amounts."""

import frappe

from verenigingen.tests.utils.base import VereningingenUnitTestCase


class TestMembershipApplicationDoor(VereningingenUnitTestCase):
    def _template_of(self, membership_type, frequency="Monthly"):
        """The type's auto-made template, set to `frequency` so it fits the slot it goes in."""
        # By the type's link, not a filter: a second template of the type would match one too.
        name = frappe.db.get_value("Membership Type", membership_type.name, "dues_schedule_template")
        frappe.db.set_value("Membership Dues Schedule", name, "billing_frequency", frequency)
        return name

    def _second_template(self, membership_type, frequency):
        """Another template of the same type, with its own billing frequency."""
        template = frappe.copy_doc(frappe.get_doc("Membership Dues Schedule", self._template_of(membership_type)))
        template.schedule_name = f"Second {frappe.generate_hash(length=6)}"
        template.billing_frequency = frequency
        template.insert()
        self.track_doc("Membership Dues Schedule", template.name)
        return template.name

    def _unsaved_door(self, membership_type, **fields):
        slug = fields.pop("slug", f"deur-{frappe.generate_hash(length=8).lower()}")
        data = {
            "doctype": "Membership Application Door",
            "title": "Testdeur",
            "slug": slug,
            "membership_type": membership_type.name,
            "form_shape": "Regular",
        }
        if "monthly_dues_template" not in fields:
            data["monthly_dues_template"] = self._template_of(membership_type)
        data.update(fields)
        return frappe.get_doc(data)

    def _save(self, door):
        door.insert()
        self.track_doc("Membership Application Door", door.name)
        return door

    def test_slug_must_be_lowercase_url_safe(self):
        membership_type = self.create_test_membership_type()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, slug="Student Leden").insert()
        door = self._save(self._unsaved_door(membership_type, slug="student-leden"))
        self.assertEqual(door.name, "student-leden")

    def test_slug_bevestig_is_reserved(self):
        membership_type = self.create_test_membership_type()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, slug="bevestig").insert()

    def test_door_cannot_be_renamed_past_slug_validation(self):
        membership_type = self.create_test_membership_type()
        door = self._save(self._unsaved_door(membership_type))
        with self.assertRaises(frappe.ValidationError):
            frappe.rename_doc("Membership Application Door", door.name, "bevestig")
        self.assertTrue(frappe.db.exists("Membership Application Door", door.name))
        self.assertFalse(frappe.db.exists("Membership Application Door", "bevestig"))

    def test_template_must_belong_to_door_type(self):
        membership_type = self.create_test_membership_type()
        other_type = self.create_test_membership_type()
        foreign_template = self._template_of(other_type)
        self.assertTrue(foreign_template)
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, monthly_dues_template=foreign_template).insert()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(
                membership_type,
                monthly_dues_template=None,
                annual_dues_template=self._template_of(other_type, "Annual"),
            ).insert()
        self._save(self._unsaved_door(membership_type))

    def test_template_frequency_must_match_its_slot(self):
        membership_type = self.create_test_membership_type()
        monthly = self._template_of(membership_type, "Monthly")
        annual = self._second_template(membership_type, "Annual")
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, monthly_dues_template=annual).insert()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(
                membership_type, monthly_dues_template=None, annual_dues_template=monthly
            ).insert()
        door = self._save(
            self._unsaved_door(membership_type, monthly_dues_template=monthly, annual_dues_template=annual)
        )
        self.assertEqual((door.monthly_dues_template, door.annual_dues_template), (monthly, annual))

    def test_amount_option_needs_a_template_for_its_frequency(self):
        membership_type = self.create_test_membership_type()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(
                membership_type, amount_options=[{"frequency": "Annual", "amount": 60}]
            ).insert()
        door = self._save(
            self._unsaved_door(membership_type, amount_options=[{"frequency": "Monthly", "amount": 10}])
        )
        self.assertEqual([row.amount for row in door.amount_options], [10])

    def test_amount_option_below_template_minimum_refused(self):
        membership_type = self.create_test_membership_type()
        template = self._template_of(membership_type)
        minimum = 4.0
        frappe.db.set_value("Membership Dues Schedule", template, "minimum_amount", minimum)
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(
                membership_type, amount_options=[{"frequency": "Monthly", "amount": minimum - 0.5}]
            ).insert()
        door = self._save(
            self._unsaved_door(membership_type, amount_options=[{"frequency": "Monthly", "amount": minimum}])
        )
        self.assertEqual([row.amount for row in door.amount_options], [minimum])

    def test_non_template_schedule_refused(self):
        membership_type = self.create_test_membership_type()
        member = self.create_test_member()
        # A Cancelled instance schedule skips the active-membership check.
        schedule = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"Instance-{frappe.generate_hash(length=6)}",
                "member": member.name,
                "membership_type": membership_type.name,
                "dues_rate": 15,
                "billing_frequency": "Monthly",
                "status": "Cancelled",
                "is_template": 0,
            }
        ).insert()
        self.track_doc("Membership Dues Schedule", schedule.name)
        self.assertEqual(schedule.membership_type, membership_type.name)
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, monthly_dues_template=schedule.name).insert()

    def test_regular_door_needs_at_least_one_template(self):
        membership_type = self.create_test_membership_type()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, monthly_dues_template=None).insert()
        self._save(self._unsaved_door(membership_type, form_shape="Housemate", monthly_dues_template=None))

    def test_minimum_for_uses_postal_minimum_only_when_postal(self):
        membership_type = self.create_test_membership_type()
        template_name = self._template_of(membership_type)
        template_minimum = 2.5
        frappe.db.set_value("Membership Dues Schedule", template_name, "minimum_amount", template_minimum)
        door = self._unsaved_door(membership_type, postal_minimum_monthly=template_minimum + 0.5)
        self.assertEqual(door.minimum_for("Monthly", False), template_minimum)
        self.assertEqual(door.minimum_for("Monthly", True), template_minimum + 0.5)
        # A postal minimum below the template minimum never lowers it.
        door.postal_minimum_monthly = template_minimum - 1
        self.assertEqual(door.minimum_for("Monthly", True), template_minimum)
        # No annual template: nothing to derive a minimum from.
        self.assertEqual(door.minimum_for("Annual", False), 0)

    def test_hidden_and_get_template_for(self):
        membership_type = self.create_test_membership_type()
        door = self._unsaved_door(
            membership_type, hidden_questions=[{"question": "mobile_no"}, {"question": "birth_year"}]
        )
        self.assertEqual(door.hidden(), {"mobile_no", "birth_year"})
        self.assertEqual(door.get_template_for("Monthly"), self._template_of(membership_type))
        self.assertIsNone(door.get_template_for("Annual"))

    def test_a_template_in_a_door_slot_cannot_change_frequency(self):
        """A slot was checked when the door was saved; changing the template under it afterwards
        would bill the applicant's chosen amount on another period."""
        membership_type = self.create_test_membership_type()
        door = self._save(self._unsaved_door(membership_type))
        template = frappe.get_doc("Membership Dues Schedule", door.monthly_dues_template)
        template.billing_frequency = "Annual"
        with self.assertRaisesRegex(frappe.ValidationError, "application door"):
            template.save()

    def test_a_template_in_a_door_slot_keeps_its_other_fields_editable(self):
        membership_type = self.create_test_membership_type()
        door = self._save(self._unsaved_door(membership_type))
        template = frappe.get_doc("Membership Dues Schedule", door.monthly_dues_template)
        template.minimum_amount = (template.minimum_amount or 0) + 1
        template.save()  # opposite harm: only the frequency is frozen

    def test_a_template_no_door_uses_can_still_change_frequency(self):
        membership_type = self.create_test_membership_type()
        template = frappe.get_doc("Membership Dues Schedule", self._second_template(membership_type, "Monthly"))
        template.billing_frequency = "Annual"
        template.save()
        self.assertEqual(frappe.db.get_value("Membership Dues Schedule", template.name, "billing_frequency"), "Annual")
