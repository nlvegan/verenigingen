"""Daily expiry and purge of unconfirmed short-application submissions."""

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.services.member.application import short_application_confirm as sac
from verenigingen.tests.utils.base import VereningingenUnitTestCase

JOB = "verenigingen.services.member.application.short_application_confirm.expire_and_purge_submissions"


class TestShortApplicationCleanup(VereningingenUnitTestCase):
    def setUp(self):
        super().setUp()
        membership_type = self.create_test_membership_type()
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": membership_type.name},
            "name",
        )
        # The auto-made template is Annual; the door's monthly slot takes only a Monthly one.
        frappe.db.set_value("Membership Dues Schedule", template, "billing_frequency", "Monthly")
        door = frappe.get_doc(
            {
                "doctype": "Membership Application Door",
                "title": "Testdeur",
                "slug": f"deur-{frappe.generate_hash(length=8).lower()}",
                "membership_type": membership_type.name,
                "form_shape": "Regular",
                "monthly_dues_template": template,
                "enabled": 1,
            }
        ).insert()
        self.track_doc("Membership Application Door", door.name)
        self.door = door.name

    def _submission_row(self, age, status="Unconfirmed"):
        """Insert a submission and backdate its creation by `age` (a timedelta-style dict)."""
        doc = frappe.get_doc(
            {
                "doctype": sac.SUBMISSION,
                "door": self.door,
                "email": f"cleanup.{frappe.generate_hash(length=8).lower()}@example.org",
                "status": status,
                "payload": "{}",
            }
        ).insert()
        self.track_doc(sac.SUBMISSION, doc.name)
        frappe.db.set_value(
            sac.SUBMISSION, doc.name, "creation", add_to_date(now_datetime(), **age), update_modified=False
        )
        return doc.name

    def _submission_status(self, name):
        return frappe.db.get_value(sac.SUBMISSION, name, "status")

    def test_old_unconfirmed_expire_and_ancient_ones_are_deleted(self):
        fresh = self._submission_row({"days": -1})
        stale = self._submission_row({"days": -8})
        ancient = self._submission_row({"days": -31})
        ancient_expired = self._submission_row({"days": -31}, status="Expired")

        result = sac.expire_and_purge_submissions()

        self.assertEqual(self._submission_status(fresh), "Unconfirmed")
        self.assertEqual(self._submission_status(stale), "Expired")
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, ancient))
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, ancient_expired))
        self.assertGreaterEqual(result["expired"], 1)
        self.assertGreaterEqual(result["deleted"], 2)

    def test_confirmed_rows_are_never_deleted(self):
        confirmed = self._submission_row({"days": -40}, status="Confirmed")
        sac.expire_and_purge_submissions()
        self.assertEqual(self._submission_status(confirmed), "Confirmed")

    def test_boundaries_are_exact(self):
        just_inside_expiry = self._submission_row({"days": -sac.EXPIRY_DAYS, "minutes": 1})
        just_past_expiry = self._submission_row({"days": -sac.EXPIRY_DAYS, "minutes": -1})
        just_inside_purge = self._submission_row({"days": -sac.PURGE_DAYS, "minutes": 1}, status="Expired")
        just_past_purge = self._submission_row({"days": -sac.PURGE_DAYS, "minutes": -1}, status="Expired")

        sac.expire_and_purge_submissions()

        self.assertEqual(self._submission_status(just_inside_expiry), "Unconfirmed")
        self.assertEqual(self._submission_status(just_past_expiry), "Expired")
        self.assertEqual(self._submission_status(just_inside_purge), "Expired")
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, just_past_purge))

    def test_constants_are_seven_and_thirty_days(self):
        self.assertEqual((sac.EXPIRY_DAYS, sac.PURGE_DAYS), (7, 30))

    def test_job_is_registered_daily(self):
        self.assertIn(JOB, frappe.get_hooks("scheduler_events")["daily"])
