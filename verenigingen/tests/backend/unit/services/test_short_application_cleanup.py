"""Daily expiry and purge of membership applications (#1765).

Probe shortcuts, stated: `creation` and `modified` are backdated with db.set_value(update_modified=False),
standing in for the passage of time (nothing else can age a row), and a row is moved to a status with
`status=` on insert or `db_set`, standing in for the confirm / review flow. The job is found and run
through the scheduler hook, not imported, so a registration that points nowhere fails here.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from verenigingen.services.member.application import application_record
from verenigingen.services.member.application import short_application_confirm as sac
from verenigingen.tests.utils.base import VereningingenUnitTestCase

JOB = "verenigingen.services.member.application.application_record.expire_and_purge_applications"
FINISHED = ("Unconfirmed", "Expired", "Rejected", "Superseded")
KEPT = ("Approved", "Pending Review")


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

    def _submission_row(self, age, status="Unconfirmed", modified_age=None):
        """Insert a submission; backdate `creation` by `age` and `modified` by `modified_age` (default: `age`)."""
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
            sac.SUBMISSION,
            doc.name,
            {
                "creation": add_to_date(now_datetime(), **age),
                "modified": add_to_date(now_datetime(), **(modified_age or age)),
            },
            update_modified=False,
        )
        return doc.name

    def _submission_status(self, name):
        return frappe.db.get_value(sac.SUBMISSION, name, "status")

    def _run_the_scheduled_job(self):
        daily = frappe.get_hooks("scheduler_events")["daily"]
        self.assertIn(JOB, daily)
        return frappe.get_attr(JOB)()

    def test_old_unconfirmed_expire_and_ancient_ones_are_deleted(self):
        fresh = self._submission_row({"days": -1})
        stale = self._submission_row({"days": -8})
        ancient = self._submission_row({"days": -31})
        ancient_expired = self._submission_row({"days": -31}, status="Expired")

        result = self._run_the_scheduled_job()

        self.assertEqual(self._submission_status(fresh), "Unconfirmed")
        self.assertEqual(self._submission_status(stale), "Expired")
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, ancient))
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, ancient_expired))
        self.assertGreaterEqual(result["expired"], 1)
        self.assertGreaterEqual(result["deleted"], 2)

    def test_purge_deletes_old_rejected_keeps_approved_and_pending(self):
        """The 30-day ruling: finished rows go 30 days after they were last touched; Approved is kept
        (it is the record of what the member submitted) and Pending Review waits for a reviewer."""
        thirty_one, twenty_nine = {"days": -31}, {"days": -29}
        old = {status: self._submission_row(thirty_one, status=status) for status in FINISHED + KEPT}
        recent = {status: self._submission_row(twenty_nine, status=status) for status in FINISHED + KEPT}

        self._run_the_scheduled_job()

        for status in FINISHED:
            self.assertFalse(frappe.db.exists(sac.SUBMISSION, old[status]), f"31 days old {status} kept")
        for status in KEPT:
            self.assertEqual(self._submission_status(old[status]), status)
        for status, name in recent.items():  # 29 days: nothing is purged yet (Unconfirmed expires at 7)
            self.assertTrue(frappe.db.exists(sac.SUBMISSION, name), f"29 days old {status} deleted")

    def test_the_purge_clock_is_modified_not_creation(self):
        """A row rejected recently is kept however old the application is; one untouched for 31 days goes
        however recently it was created."""
        long_ago, recently, lapsed = {"days": -90}, {"days": -2}, {"days": -31}
        old_application_just_rejected = self._submission_row(long_ago, status="Pending Review", modified_age=recently)
        frappe.get_doc(sac.SUBMISSION, old_application_just_rejected).set_status("Rejected")  # the real write
        new_application_long_untouched = self._submission_row(recently, status="Rejected", modified_age=lapsed)

        self._run_the_scheduled_job()

        self.assertEqual(self._submission_status(old_application_just_rejected), "Rejected")
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, new_application_long_untouched))

    def test_boundaries_are_exact(self):
        just_inside_expiry = self._submission_row({"days": -sac.EXPIRY_DAYS, "minutes": 1})
        just_past_expiry = self._submission_row({"days": -sac.EXPIRY_DAYS, "minutes": -1})
        just_inside_purge = self._submission_row({"days": -sac.PURGE_DAYS, "minutes": 1}, status="Rejected")
        just_past_purge = self._submission_row({"days": -sac.PURGE_DAYS, "minutes": -1}, status="Rejected")

        self._run_the_scheduled_job()

        self.assertEqual(self._submission_status(just_inside_expiry), "Unconfirmed")
        self.assertEqual(self._submission_status(just_past_expiry), "Expired")
        self.assertEqual(self._submission_status(just_inside_purge), "Rejected")
        self.assertFalse(frappe.db.exists(sac.SUBMISSION, just_past_purge))

    def test_constants_are_seven_and_thirty_days(self):
        self.assertEqual((sac.EXPIRY_DAYS, sac.PURGE_DAYS), (7, 30))

    def test_job_is_registered_daily_and_the_old_one_is_gone(self):
        self.assertIn(JOB, frappe.get_hooks("scheduler_events")["daily"])
        self.assertEqual(frappe.get_attr(JOB), application_record.expire_and_purge_applications)
        self.assertFalse(hasattr(sac, "expire_and_purge_submissions"))
        stale = [h for h in frappe.get_hooks("scheduler_events")["daily"] if "expire_and_purge_submissions" in h]
        self.assertEqual(stale, [])
