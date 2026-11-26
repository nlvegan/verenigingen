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
VALID_RSIN = "12345678"
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
        self._create_donors_and_donations()

    def _create_donors_and_donations(self):
        self.donation_date = "2031-03-01"  # a window no other fixture on the site uses
        self.fixture = []  # (doctype, name) pairs, donations first
        self.agreements = {}
        for kind, field, value in (
            ("Individual", "bsn_citizen_service_number", VALID_BSN),
            ("Organization", "rsin_organization_tax_number", VALID_RSIN),
        ):
            donor = self.create_test_donor(donor_type=kind, **{field: value})
            agreement = f"ANBI-{frappe.generate_hash(length=6)}"
            donation = self.create_test_donation(
                donor=donor.name,
                amount=42.0,
                anbi_agreement_number=agreement,
                anbi_agreement_date=frappe.utils.today(),
                donation_date=self.donation_date,
                paid=1,
            )
            self.agreements[kind] = agreement
            self.fixture += [("Donation", donation.name), ("Donor", donor.name)]
        self.fixture.sort(key=lambda x: x[0] != "Donation")
        frappe.db.commit()  # the WSGI child is another DB connection

    def _cleanup_fixture(self):
        frappe.db.rollback()
        for doctype, name in self.fixture:
            if frappe.db.exists(doctype, name):
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _report(self, flag):
        """Return (data, {"Individual": row, "Organization": row}, raw response body)."""
        case = {
            "name": "r",
            "endpoint": ANBI_ENDPOINT,
            "login": {"usr": self.admin, "pwd": self.password},
            "csrf": "valid",
            "json": {"from_date": self.donation_date, "to_date": self.donation_date, "include_bsn": flag},
        }
        response = run_wsgi_cases(case)["r"]
        result = operation_result(response)
        self.assertTrue(result["success"], result)
        rows = {}
        for kind, agreement in self.agreements.items():
            ours = [d for d in result["data"]["donations"] if d["anbi_agreement_number"] == agreement]
            self.assertEqual(len(ours), 1, result)  # a real row for the wrong behaviour to find
            rows[kind] = ours[0]
        return result["data"], rows, response["body"]

    def test_false_flag_strings_do_not_return_the_bsn_or_rsin(self):
        """"0"/"false"/0 and an unrecognised string must not decrypt either identifier."""
        for flag in ("0", "false", 0, "maybe"):
            data, rows, body = self._report(flag)
            for row in rows.values():
                self.assertNotIn("bsn", row, flag)
                self.assertNotIn("rsin", row, flag)
            # The raw body: no field name or value can carry it anywhere else either.
            self.assertNotIn(VALID_BSN, body, flag)
            self.assertNotIn(VALID_RSIN, body, flag)
            self.assertIs(data["summary"]["includes_tax_ids"], False, flag)

    def test_true_flag_strings_still_return_the_bsn_and_rsin(self):
        """Control: "1" / "true" still enable the export, so the false cases above can fail."""
        for flag in ("1", "true"):
            data, rows, body = self._report(flag)
            self.assertEqual(rows["Individual"].get("bsn"), VALID_BSN, flag)
            self.assertEqual(rows["Organization"].get("rsin"), VALID_RSIN, flag)
            self.assertIn(VALID_BSN, body)
            self.assertIn(VALID_RSIN, body)
            self.assertIs(data["summary"]["includes_tax_ids"], True, flag)

    # No refused-caller case: every role with Donation read also has Donor read (measured on
    # test_site_5, DocPerm + Custom DocPerm, permlevel 0), so "may read donations but not donors"
    # does not exist, and a caller without Donor read is refused earlier, by the Donation check.


class TestCleanupDryRunOverHttp(_schedule_tests.TestScheduleMaintenance, CommittedLoginUsersMixin, VereningingenTestCase):
    """Borrows the schedule fixtures from test_schedule_maintenance (functions, not its tests)."""

    # The borrowed class's tests must not be collected a second time under this class.
    for _name in [n for n in vars(_schedule_tests.TestScheduleMaintenance) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        # The Administrator profile passes @high_security_api and carries Accounts Manager.
        self.user = self._create_login_users(maint="Verenigingen Administrator")["maint"]
        self._orphan_types = []
        self.addCleanup(self._cleanup_orphan_schedules)

    def _cleanup_orphan_schedules(self):
        """Remove what _create_orphan committed: each fixture's schedules (the type's auto-made
        Template included), then the Membership Types themselves."""
        frappe.db.rollback()
        for mtype in self._orphan_types:
            for name in frappe.get_all(
                "Membership Dues Schedule", filters={"membership_type": mtype}, pluck="name"
            ):
                frappe.delete_doc("Membership Dues Schedule", name, force=True, ignore_permissions=True)
            if frappe.db.exists("Membership Type", mtype):
                frappe.delete_doc("Membership Type", mtype, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_orphan(self):
        schedule, _m, mtype = self._make_active_schedule()
        self._orphan_types.append(mtype.name)
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
