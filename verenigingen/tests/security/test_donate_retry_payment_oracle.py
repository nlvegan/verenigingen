"""donate.retry_payment must not reveal to a Guest whether a Donation exists (#2097).

Measured on develop (real Guest WSGI POST): an unknown Donation id and an existing one with a
wrong or blank ``donor_email`` differed in ``_server_messages`` ("Donation DON-.. not found" vs
"Donation not found"), in the Error Log text and in query count (3 vs 9).

The probe runs in a subprocess (own DB connection, committed fixtures) and compares EVERY channel
between the unknown and the forbidden Donation: HTTP status, body, ``_server_messages``, Error Log
rows, query count and Mollie calls. Only ``process_mollie_payment`` is stubbed, so a refusal that
reached it would be visible, and the owner control proves the fixture can get past the guard.
"""

import json
import os
import re
import subprocess
import sys

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

_PROBE = r"""
import json, re, sys, uuid
from unittest.mock import MagicMock, patch
import frappe

SITE = sys.argv[1]
frappe.init(site=SITE)
frappe.connect()
created = {}
owner_email = "owner." + uuid.uuid4().hex[:8] + "@example.com"
try:
    donor = frappe.get_doc({"doctype": "Donor", "donor_name": "Retry Probe", "donor_type": "Individual",
        "donor_email": owner_email, "currency": "EUR"})
    donor.flags.ignore_customer_sync = True
    donor.insert()
    donation = frappe.get_doc({"doctype": "Donation", "donor": donor.name, "donation_date": frappe.utils.today(),
        "amount": 10.0, "mode_of_payment": "Mollie", "status": "One-time", "donation_purpose_type": "General",
        "paid": 0}).insert()
    created = {"donor": donor.name, "donation": donation.name}
    frappe.db.commit()
    frappe.destroy()

    import frappe.app
    from frappe.database.database import Database
    from werkzeug.test import Client
    from verenigingen.utils.security.rate_limit_engine import RateLimitEngine, RateLimitResult
    from verenigingen.services.donation.public_donation_service import PublicDonationService
    # The per-IP throttle would turn every later case into a uniform 403 and make the comparison vacuous.
    unthrottled = RateLimitResult(allowed=True, current_count=1, max_calls=999, period_seconds=60,
                                  limit_type="probe", reason="")
    client = Client(frappe.app.application, use_cookies=False)
    headers = {"X-Frappe-Site-Name": SITE}
    path = "/api/method/verenigingen.templates.pages.donate.retry_payment"

    def error_log_rows():
        frappe.init(site=SITE); frappe.connect()
        rows = {r[0]: (r[1], r[2]) for r in frappe.db.sql("select name, method, error from `tabError Log`")}
        frappe.destroy()
        return rows

    mollie = MagicMock(return_value={"status": "redirect_required", "payment_url": "https://pay.mollie.test/x"})
    real_sql = Database.sql
    counter = {"n": 0}
    def counting_sql(self, *a, **kw):
        counter["n"] += 1
        return real_sql(self, *a, **kw)

    unknown = "DON-NOPE-" + uuid.uuid4().hex[:6]
    cases = {
        "unknown": (unknown, "stranger@example.com"),
        "forbidden": (donation.name, "stranger@example.com"),
        "unknown_noemail": (unknown, ""),
        "forbidden_noemail": (donation.name, ""),
        "owner": (donation.name, owner_email),
        "owner_padded_upper": (donation.name, "  " + owner_email.upper() + "  "),
    }
    out = {}
    with patch.object(PublicDonationService, "process_mollie_payment", mollie), \
         patch.object(RateLimitEngine, "check_rate_limit", return_value=unthrottled):
        # Warm-up: the first request on a cold process fills Redis/meta caches.
        for name, email in (cases["unknown"], cases["forbidden"], cases["owner"], cases["owner_padded_upper"]):
            client.post(path, data={"donation_id": name, "donor_email": email}, headers=headers)
        for key, (name, email) in cases.items():
            before = error_log_rows()
            mollie.reset_mock()
            counter["n"] = 0
            with patch.object(Database, "sql", counting_sql):
                r = client.post(path, data={"donation_id": name, "donor_email": email}, headers=headers)
            queries = counter["n"]
            after = error_log_rows()
            body = r.get_data(as_text=True)
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {}
            norm = lambda s: re.sub(r"[0-9a-f]{40,}", "<ID>", (s or "").replace(name, "<REF>"))
            parsed.pop("headers", None)
            body = json.dumps(parsed, sort_keys=True) if parsed else body
            out[key] = {
                "status": r.status_code,
                "body": norm(body),
                "server_messages": norm(parsed.get("_server_messages") or ""),
                "error_logs": sorted((norm(m), norm(e)) for n, (m, e) in after.items() if n not in before),
                "mollie_calls": mollie.call_count,
                "queries": queries,
                "location": r.headers.get("Location", ""),
            }
    print("RESULT" + json.dumps(out))
finally:
    frappe.init(site=SITE)
    frappe.connect()
    for dt, key in (("Donation", "donation"), ("Donor", "donor")):
        if created.get(key):
            try:
                frappe.delete_doc(dt, created[key], force=True, ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                print("CLEANUP_FAILED " + dt + " " + str(e))
    left = [(dt, created[k]) for dt, k in (("Donation", "donation"), ("Donor", "donor"))
            if created.get(k) and frappe.db.exists(dt, created[k])]
    print("LEFTOVER" + json.dumps(left))
    frappe.destroy()
"""

_CHANNELS = ("status", "body", "server_messages", "error_logs", "mollie_calls", "queries")


class TestDonateRetryPaymentOracle(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            result = subprocess.run(
                [sys.executable, "-c", _PROBE, frappe.local.site],
                cwd=os.path.join(get_bench_path(), "sites"),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            raise AssertionError(
                "the WSGI probe did not finish within 300s; committed 'Retry Probe' Donor/Donation "
                f"may remain. stdout: {e.stdout}"
            ) from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def _assert_same(self, a, b):
        for channel in _CHANNELS:
            with self.subTest(a=a, b=b, channel=channel):
                self.assertEqual(self.out[a][channel], self.out[b][channel])

    def test_unknown_donation_matches_forbidden_donation_on_every_channel(self):
        self._assert_same("unknown", "forbidden")

    def test_unknown_matches_forbidden_when_no_email_is_supplied(self):
        self._assert_same("unknown_noemail", "forbidden_noemail")

    def test_refusals_never_reach_mollie_and_the_owner_does(self):
        """Control: refusals really refuse, and the fixture can get past the guard."""
        for key in ("unknown", "forbidden", "unknown_noemail", "forbidden_noemail"):
            with self.subTest(case=key):
                self.assertEqual(self.out[key]["mollie_calls"], 0)
                self.assertNotIn("pay.mollie.test", self.out[key]["location"])
        for key in ("owner", "owner_padded_upper"):
            with self.subTest(case=key):
                self.assertEqual(self.out[key]["mollie_calls"], 1)
                self.assertEqual(self.out[key]["status"], 302)
                self.assertIn("pay.mollie.test", self.out[key]["location"])

    def test_no_refusal_carries_an_existence_message(self):
        for key in ("unknown", "forbidden", "unknown_noemail", "forbidden_noemail"):
            with self.subTest(case=key):
                for channel in ("body", "server_messages"):
                    self.assertNotRegex(self.out[key][channel], r"(?i)DON-NOPE|not found|does not exist")
                    self.assertIn("Unable to retry payment", self.out[key][channel])
                for _method, error in self.out[key]["error_logs"]:
                    self.assertNotRegex(error, r"(?i)does not exist")


class TestRequireDonorEmailOnFile(EnhancedTestCase):
    """Direct call: the request layer may trim the email before the service sees it, so the
    service's own strip()/lower() is only observable here."""

    def test_padded_upper_case_owner_email_is_accepted_and_a_stranger_refused(self):
        from verenigingen.services.donation.public_donation_service import PublicDonationService

        donor = frappe.get_doc(
            {
                "doctype": "Donor",
                "donor_name": "Retry Direct",
                "donor_type": "Individual",
                "donor_email": "retry.direct@example.com",
                "currency": "EUR",
            }
        )
        donor.flags.ignore_customer_sync = True
        donor.insert()
        self.track_doc("Donor", donor.name)
        donation = frappe.get_doc(
            {
                "doctype": "Donation",
                "donor": donor.name,
                "donation_date": frappe.utils.today(),
                "amount": 10.0,
                "mode_of_payment": "Mollie",
                "status": "One-time",
                "donation_purpose_type": "General",
                "paid": 0,
            }
        ).insert()
        self.track_doc("Donation", donation.name)

        check = PublicDonationService._require_donor_email_on_file
        check(donation.name, "  RETRY.Direct@Example.COM  ")
        with self.assertRaises(frappe.ValidationError):
            check(donation.name, "stranger@example.com")
