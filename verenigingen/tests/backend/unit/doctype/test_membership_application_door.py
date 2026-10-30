"""Membership Application Door: slug rules, template checks and minimum amounts."""

import frappe

from verenigingen.tests.utils.base import VereningingenUnitTestCase


class TestMembershipApplicationDoor(VereningingenUnitTestCase):
    def _template_of(self, membership_type):
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type.name},
            "name",
        )

    def _unsaved_door(self, membership_type, **fields):
        slug = fields.pop("slug", f"deur-{frappe.generate_hash(length=8).lower()}")
        data = {
            "doctype": "Membership Application Door",
            "title": "Testdeur",
            "slug": slug,
            "membership_type": membership_type.name,
            "form_shape": "Regular",
            "monthly_dues_template": self._template_of(membership_type),
        }
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

    def test_template_must_belong_to_door_type(self):
        membership_type = self.create_test_membership_type()
        other_type = self.create_test_membership_type()
        foreign_template = self._template_of(other_type)
        self.assertTrue(foreign_template)
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(membership_type, monthly_dues_template=foreign_template).insert()
        with self.assertRaises(frappe.ValidationError):
            self._unsaved_door(
                membership_type, monthly_dues_template=None, annual_dues_template=foreign_template
            ).insert()
        self._save(self._unsaved_door(membership_type))

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
