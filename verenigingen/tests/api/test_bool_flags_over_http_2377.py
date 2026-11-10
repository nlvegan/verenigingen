"""
#2377: whitelisted endpoints that test a boolean flag with a bare ``if <arg>:``.

Over HTTP the flag arrives as a string and ``"0"`` / ``"false"`` are truthy in Python. Each test
sends the flag through the real WSGI app (``wsgi_http_session``) so the string reaches the endpoint
exactly as a browser form or ``frappe.call`` would deliver it.

* ``generate_anbi_report(include_bsn="0")`` returned decrypted BSN/RSIN nobody asked for.
* ``cleanup_orphaned_schedules(dry_run="false")`` could not be asked for a real run, and the
  fix must not turn an unrecognised value into one (the destructive direction).
* ``get_member_*(structured_response="0")`` returned the structured shape.
* ``send_overdue_payment_reminders`` has the same shape for ``send_to_chapters`` and
  ``include_payment_link``; it needs a live overdue report and a mail harness, so its test lives
  in ``tests/payment/test_payment_reminder_outcomes.py`` and passes the strings HTTP delivers.

Fixtures are committed because the WSGI child is another DB connection; removed afterwards.

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_bool_flags_over_http_2377
"""

import json

import frappe

from verenigingen.tests.api import test_schedule_maintenance as _schedule_tests
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)
from verenigingen.tests.utils.base import VereningingenTestCase

VALID_BSN = "123456782"  # eleven-proof valid
ANBI_ENDPOINT = api_path("verenigingen.api.anbi_operations.generate_anbi_report")
CLEANUP_ENDPOINT = api_path("verenigingen.api.schedule_maintenance.cleanup_orphaned_schedules")
CHAPTER_ENDPOINTS = {
    "current": api_path("verenigingen.api.member.chapter_api.get_member_current_chapters"),
    "names": api_path("verenigingen.api.member.chapter_api.get_member_chapter_names"),
    "html": api_path("verenigingen.api.member.chapter_api.get_member_chapter_display_html"),
}


class TestAnbiIncludeBsnOverHttp(CommittedLoginUsersMixin, VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self._create_login_users(admin="Verenigingen Administrator")["admin"]
        self.addCleanup(self._cleanup_fixture)
        self._create_donor_and_donation()

    def _create_donor_and_donation(self):
        self.donation_date = "2031-03-01"  # a window no other fixture on the site uses
        donor = self.create_test_donor(donor_type="Individual", bsn_citizen_service_number=VALID_BSN)
        self.donor = donor.name
        self.agreement = f"ANBI-{frappe.generate_hash(length=6)}"
        self.donation = self.create_test_donation(
            donor=donor.name,
            amount=42.0,
            anbi_agreement_number=self.agreement,
            anbi_agreement_date=frappe.utils.today(),
            donation_date=self.donation_date,
            paid=1,
        ).name
        frappe.db.commit()  # the WSGI child is another DB connection

    def _cleanup_fixture(self):
        frappe.db.rollback()
        for doctype, name in (("Donation", self.donation), ("Donor", self.donor)):
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _report(self, flag):
        case = {
            "name": "r",
            "endpoint": ANBI_ENDPOINT,
            "login": {"usr": self.admin, "pwd": self.password},
            "csrf": "valid",
            "json": {"from_date": self.donation_date, "to_date": self.donation_date, "include_bsn": flag},
        }
        result = operation_result(run_wsgi_cases(case)["r"])
        self.assertTrue(result["success"], result)
        ours = [d for d in result["data"]["donations"] if d["anbi_agreement_number"] == self.agreement]
        self.assertEqual(len(ours), 1, result)  # a real row for the wrong behaviour to find
        return result["data"], ours[0]

    def test_false_flag_strings_do_not_return_the_bsn(self):
        """"0"/"false"/0 and an unrecognised string must not decrypt the BSN."""
        for flag in ("0", "false", 0, "maybe"):
            data, row = self._report(flag)
            self.assertNotIn("bsn", row, flag)
            self.assertFalse(data["summary"]["includes_tax_ids"], flag)

    def test_true_flag_strings_still_return_the_bsn(self):
        """Control: "1" / "true" still enable the export, so the false cases above can fail."""
        for flag in ("1", "true"):
            data, row = self._report(flag)
            self.assertEqual(row.get("bsn"), VALID_BSN, flag)
            self.assertTrue(data["summary"]["includes_tax_ids"], flag)


class TestCleanupDryRunOverHttp(_schedule_tests.TestScheduleMaintenance, CommittedLoginUsersMixin, VereningingenTestCase):
    """Borrows the schedule fixtures from test_schedule_maintenance (functions, not its tests)."""

    # The borrowed class's tests must not be collected a second time under this class.
    for _name in [n for n in vars(_schedule_tests.TestScheduleMaintenance) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def setUp(self):
        VereningingenTestCase.setUp(self)
        # The Administrator profile passes @high_security_api and carries Accounts Manager.
        self.user = self._create_login_users(maint="Verenigingen Administrator")["maint"]

    def _create_orphan(self):
        schedule, _m, _t = self._make_active_schedule()
        self._persist_orphaned_member(schedule.name)
        frappe.db.commit()  # the WSGI child is another DB connection
        return schedule.name

    def _cleanup(self, flag):
        case = {
            "name": "c",
            "endpoint": CLEANUP_ENDPOINT,
            "login": {"usr": self.user, "pwd": self.password},
            "csrf": "valid",
            "json": {"issue_type": "orphaned_members", "dry_run": flag},
        }
        return operation_result(run_wsgi_cases(case)["c"])

    def _status(self, name):
        frappe.db.rollback()  # fresh snapshot of what the child committed
        return frappe.db.get_value("Membership Dues Schedule", name, "status")

    def test_unrecognised_dry_run_stays_a_dry_run(self):
        """Garbage must not be read as "False": cbool alone turns it into a destructive run."""
        for flag in ("maybe", "", None, "true", "1"):
            name = self._create_orphan()
            result = self._cleanup(flag)
            self.assertTrue(result["success"], (flag, result))
            self.assertTrue(result["data"]["dry_run"], (flag, result))
            self.assertEqual(self._status(name), "Active", flag)

    def test_false_strings_really_run(self):
        """"false"/"0"/0/False request the real run (a string could never ask for it before)."""
        for flag in ("false", "0", 0, False):
            name = self._create_orphan()
            result = self._cleanup(flag)
            self.assertTrue(result["success"], (flag, result))
            self.assertFalse(result["data"]["dry_run"], (flag, result))
            self.assertEqual(self._status(name), "Cancelled", flag)


class TestStructuredResponseOverHttp(CommittedLoginUsersMixin, VereningingenTestCase):
    def test_false_strings_return_the_plain_shape_and_true_the_structured_one(self):
        user = self._create_login_users(member="Verenigingen Administrator")["member"]
        cases = []
        for key, endpoint in CHAPTER_ENDPOINTS.items():
            for flag in ("0", "false", "1", "true"):
                cases.append(
                    {
                        "name": f"{key}-{flag}",
                        "endpoint": endpoint,
                        "login": {"usr": user, "pwd": self.password},
                        "csrf": "valid",
                        # An empty member_name returns before any lookup, in the requested shape.
                        "json": {"member_name": "", "structured_response": flag},
                    }
                )
        out = run_wsgi_cases(*cases)
        for name, response in out.items():
            self.assertEqual(response["status"], 200, (name, response))
            message = json.loads(response["body"])["message"]
            structured = isinstance(message, dict) and message.get("success") is True
            self.assertEqual(structured, name.endswith(("-1", "-true")), (name, message))
