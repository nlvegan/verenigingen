"""The Membership Application Submission is the application record: status moves only along allowed edges."""

import frappe

from verenigingen.tests.utils.application_door_fixture import ApplicationDoorMixin
from verenigingen.tests.utils.base import VereningingenUnitTestCase

DOCTYPE = "Membership Application Submission"
ALLOWED = [
    ("Unconfirmed", "Pending Review"),
    ("Unconfirmed", "Expired"),
    ("Pending Review", "Approved"),
    ("Pending Review", "Rejected"),
    ("Pending Review", "Superseded"),
]
FORBIDDEN = [
    ("Approved", "Pending Review"),
    ("Rejected", "Approved"),
    ("Unconfirmed", "Approved"),
]


class TestMembershipApplicationSubmission(ApplicationDoorMixin, VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        self.membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": self.membership_type.name},
            "name",
        )
        # The auto-made template is Annual; the door's monthly slot takes only a Monthly one.
        frappe.db.set_value("Membership Dues Schedule", template, "billing_frequency", "Monthly")
        self.door = self._door(monthly_dues_template=template)

    def _row(self, status, **extra):
        """Insert a row; the status is hand-set to stand in for earlier transitions (probe shortcut)."""
        data = {
            "doctype": DOCTYPE,
            "door": self.door.name,
            "email": f"mas.{frappe.generate_hash(length=8).lower()}@example.org",
            "payload": "{}",
        }
        data.update(extra)
        doc = frappe.get_doc(data).insert()
        self.track_doc(DOCTYPE, doc.name)
        frappe.db.set_value(DOCTYPE, doc.name, "status", status)
        return frappe.get_doc(DOCTYPE, doc.name)

    def test_allowed_transitions_persist(self):
        for source, target in ALLOWED:
            doc = self._row(source)
            doc.set_status(target)
            self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), target, (source, target))

    def test_forbidden_transition_raises(self):
        for source, target in FORBIDDEN:
            doc = self._row(source)
            with self.assertRaises(frappe.ValidationError, msg=(source, target)):
                doc.set_status(target)
            self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "status"), source)

    def test_full_form_row_needs_no_door(self):
        doc = frappe.get_doc(
            {
                "doctype": DOCTYPE,
                "source": "Full Form",
                "email": f"mas.{frappe.generate_hash(length=8).lower()}@example.org",
                "payload": "{}",
            }
        ).insert()
        self.track_doc(DOCTYPE, doc.name)
        self.assertEqual(doc.status, "Unconfirmed")
