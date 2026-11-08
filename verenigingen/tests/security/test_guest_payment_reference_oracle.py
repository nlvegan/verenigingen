"""Guest payment endpoints must not reveal whether a payment reference exists (#2045).

``mollie_checkout.make_payment`` and ``hooks.api.initiate_payment`` are both
``allow_guest=True`` and resolve a caller-supplied ``(reference_doctype, reference name)``.
Measured on develop for make_payment (real WSGI POST as Guest): an unknown Donation and an
existing one the caller does not own differ in ``_server_messages`` ("Donation X not found" vs
"Payment reference not found"), in the Error Log text and in query count (6 vs 31).

The WSGI test drives a real Guest POST in a subprocess (its own DB connection, committed
fixtures) and compares EVERY channel between the unknown and the forbidden reference: HTTP
status, body, ``_server_messages``, Error Log rows, query count, gateway calls. Only the Mollie
gateway factory is stubbed, so a refusal that reached it would be visible.
"""

import json
import os
import re
import subprocess
import sys
from unittest.mock import patch

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
    donor = frappe.get_doc({"doctype": "Donor", "donor_name": "Oracle Probe", "donor_type": "Individual",
        "donor_email": owner_email, "currency": "EUR"})
    donor.flags.ignore_customer_sync = True
    donor.insert()
    donation = frappe.get_doc({"doctype": "Donation", "donor": donor.name, "donation_date": frappe.utils.today(),
        "amount": 10.0, "mode_of_payment": "Mollie", "status": "One-time", "donation_purpose_type": "General",
        "paid": 0}).insert()
    plan_payment = frappe.get_doc({"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 5.0,
        "currency": "EUR", "status": "Pending"})
    plan_payment.insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
    member = frappe.get_doc({"doctype": "Member", "first_name": "Oracle", "last_name": "Probe",
        "email": "member." + uuid.uuid4().hex[:8] + "@example.com"})
    member.flags.ignore_customer_sync = True
    member.insert(ignore_permissions=True)
    created = {"donor": donor.name, "donation": donation.name, "plan_payment": plan_payment.name,
               "member": member.name}
    frappe.db.commit()
    frappe.destroy()

    import frappe.app
    from frappe.database.database import Database
    from werkzeug.test import Client
    from verenigingen.utils.security.rate_limit_engine import RateLimitEngine, RateLimitResult
    # initiate_payment's per-IP rule allows ~5 calls a window, after which EVERY case is a uniform 403:
    # that would make the comparison below vacuous, so the throttle (not the code under test) is stubbed.
    unthrottled = RateLimitResult(allowed=True, current_count=1, max_calls=999, period_seconds=60,
                                  limit_type="probe", reason="")
    client = Client(frappe.app.application, use_cookies=False)
    headers = {"X-Frappe-Site-Name": SITE}

    def error_log_rows():
        frappe.init(site=SITE); frappe.connect()
        rows = {r[0]: (r[1], r[2]) for r in frappe.db.sql("select name, method, error from `tabError Log`")}
        frappe.destroy()
        return rows

    gateway = MagicMock()
    gateway.process_payment.return_value = {"status": "redirect_required",
        "payment_url": "https://pay.mollie.test/x", "payment_id": "tr_stub"}
    real_sql = Database.sql
    counter = {"n": 0}
    def counting_sql(self, *a, **kw):
        counter["n"] += 1
        return real_sql(self, *a, **kw)

    unknown = "DON-NOPE-" + uuid.uuid4().hex[:6]
    stranger = "stranger@example.com"
    mk = lambda ref_dt, name, email: ("make_payment", {
        "data": json.dumps({"payer_email": email, "payer_name": "X", "amount": 1, "currency": "EUR"}),
        "reference_doctype": ref_dt, "reference_docname": name})
    ip = lambda ref_dt, name, email: ("initiate_payment", {
        "method": "mollie", "amount": 1, "reference_doctype": ref_dt, "reference_name": name,
        "payer_email": email, "payer_name": "X"})
    paths = {
        "make_payment": "/api/method/verenigingen.verenigingen_payments.templates.pages.mollie_checkout.make_payment",
        "initiate_payment": "/api/method/verenigingen.verenigingen_payments.hooks.api.initiate_payment",
    }
    cases = {}
    for build, tag in ((mk, "mk"), (ip, "ip")):
        cases[tag + "_don_unknown"] = (build("Donation", unknown, stranger), unknown)
        cases[tag + "_don_forbidden"] = (build("Donation", donation.name, stranger), donation.name)
        cases[tag + "_don_forbidden_noemail"] = (build("Donation", donation.name, ""), donation.name)
        cases[tag + "_don_unknown_noemail"] = (build("Donation", unknown, ""), unknown)
        cases[tag + "_ppp_unknown"] = (build("Payment Plan Payment", "PPP-NOPE-1", stranger), "PPP-NOPE-1")
        cases[tag + "_ppp_forbidden"] = (build("Payment Plan Payment", plan_payment.name, stranger), plan_payment.name)
        cases[tag + "_member_unknown"] = (build("Member", "MEM-NOPE-1", stranger), "MEM-NOPE-1")
        cases[tag + "_member_existing"] = (build("Member", member.name, stranger), member.name)
    cases["ip_don_owner"] = (ip("Donation", donation.name, owner_email), donation.name)
    cases["mk_don_owner"] = (mk("Donation", donation.name, owner_email), donation.name)

    out = {}
    # Warm-up: the first request on a cold process fills Redis/meta caches (thousands of queries).
    with patch("verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway",
               return_value=gateway), patch.object(RateLimitEngine, "check_rate_limit", return_value=unthrottled):
        # Every doctype both endpoints read gets one request, or its first meta load lands in a measured case.
        for warm in ("mk_don_unknown", "ip_don_unknown", "mk_ppp_unknown", "ip_ppp_unknown",
                     "mk_member_unknown", "ip_member_unknown"):
            endpoint, form = cases[warm][0]
            client.post(paths[endpoint], data=form, headers=headers)
    for key, ((endpoint, form), ref_name) in cases.items():
        before = error_log_rows()
        gateway.reset_mock()
        counter["n"] = 0
        with patch("verenigingen.verenigingen_payments.utils.payment_gateways.PaymentGatewayFactory.get_gateway",
                   return_value=gateway), patch.object(Database, "sql", counting_sql), \
             patch.object(RateLimitEngine, "check_rate_limit", return_value=unthrottled):
            r = client.post(paths[endpoint], data=form, headers=headers)
        queries = counter["n"]
        after = error_log_rows()
        body = r.get_data(as_text=True)
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {}
        # __frappe_exc_id is a fresh random id on every request; it says nothing about the reference.
        norm = lambda s: re.sub(r"[0-9a-f]{40,}", "<ID>", (s or "").replace(ref_name, "<REF>"))
        # The rate-limit headers legitimately count down per request; they say nothing about the reference.
        parsed.pop("headers", None)
        body = json.dumps(parsed, sort_keys=True) if parsed else body
        out[key] = {
            "status": r.status_code,
            "body": norm(body),
            "server_messages": norm(parsed.get("_server_messages") or ""),
            "error_logs": sorted((norm(m), norm(e)) for n, (m, e) in after.items() if n not in before),
            "gateway_calls": gateway.process_payment.call_count + gateway.get_payment_status.call_count,
            "queries": queries,
        }
    print("RESULT" + json.dumps(out))
finally:
    frappe.init(site=SITE)
    frappe.connect()
    for dt, key in (("Payment Plan Payment", "plan_payment"), ("Donation", "donation"), ("Donor", "donor"),
                    ("Member", "member")):
        if created.get(key):
            # One failing delete must not strand the rest; the LEFTOVER line below reports what stayed.
            try:
                frappe.delete_doc(dt, created[key], force=True, ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                print("CLEANUP_FAILED " + dt + " " + str(e))
    left = [(dt, created[k]) for dt, k in (("Payment Plan Payment", "plan_payment"), ("Donation", "donation"),
            ("Donor", "donor"), ("Member", "member")) if created.get(k) and frappe.db.exists(dt, created[k])]
    print("LEFTOVER" + json.dumps(left))
    frappe.destroy()
"""

# Channels compared between an unknown and an existing-but-not-owned reference.
_CHANNELS = ("status", "body", "server_messages", "error_logs", "gateway_calls", "queries")


class TestGuestPaymentReferenceOracle(EnhancedTestCase):
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
                "the WSGI probe subprocess did not finish within 300s; its committed fixtures "
                f"(Donor/Donation/Payment Plan Payment/Member 'Oracle Probe') may remain. stdout: {e.stdout}"
            ) from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def _assert_same_on_every_channel(self, a, b):
        for channel in _CHANNELS:
            with self.subTest(a=a, b=b, channel=channel):
                self.assertEqual(self.out[a][channel], self.out[b][channel])

    def test_every_refusal_is_a_refusal_that_never_reached_the_gateway(self):
        """Control: refusals really refuse (and say so identically); the owner is let through."""
        for key, case in self.out.items():
            if key.endswith("_owner"):
                continue
            with self.subTest(case=key):
                self.assertEqual(case["gateway_calls"], 0)
                self.assertNotIn("pay.mollie.test", case["body"])
        owner = self.out["mk_don_owner"]
        self.assertIn("pay.mollie.test", owner["body"])
        self.assertEqual(owner["gateway_calls"], 1)
        # initiate_payment's owner gets past the ownership check; what follows depends on whether this
        # site has Mollie configured ("not available" in CI, a stubbed redirect on a configured bench).
        # A fixture that could not reach the owner path would make the refusals above prove nothing.
        self.assertNotIn("Payment reference not found", self.out["ip_don_owner"]["body"])
        self.assertRegex(self.out["ip_don_owner"]["body"], r"is not available|Redirecting to payment provider")

    def test_make_payment_unknown_donation_matches_forbidden_donation(self):
        self._assert_same_on_every_channel("mk_don_unknown", "mk_don_forbidden")
        self._assert_same_on_every_channel("mk_don_unknown_noemail", "mk_don_forbidden_noemail")

    def test_make_payment_unknown_plan_payment_matches_forbidden_plan_payment(self):
        self._assert_same_on_every_channel("mk_ppp_unknown", "mk_ppp_forbidden")

    def test_make_payment_disallowed_doctype_unknown_matches_existing(self):
        self._assert_same_on_every_channel("mk_member_unknown", "mk_member_existing")

    def test_initiate_payment_unknown_donation_matches_forbidden_donation(self):
        self._assert_same_on_every_channel("ip_don_unknown", "ip_don_forbidden")
        self._assert_same_on_every_channel("ip_don_unknown_noemail", "ip_don_forbidden_noemail")

    def test_initiate_payment_unknown_plan_payment_matches_forbidden_plan_payment(self):
        self._assert_same_on_every_channel("ip_ppp_unknown", "ip_ppp_forbidden")

    def test_initiate_payment_disallowed_doctype_unknown_matches_existing(self):
        self._assert_same_on_every_channel("ip_member_unknown", "ip_member_existing")

    def test_no_refusal_leaks_a_name_or_existence_message(self):
        """No channel carries the caller's name back, nor 'not found' wording for the unknown one."""
        for key, case in self.out.items():
            if key.endswith("_owner"):
                continue
            with self.subTest(case=key):
                for channel in ("body", "server_messages"):
                    self.assertNotRegex(case[channel], r"(?i)DON-NOPE|does not exist|Donation .* not found")
                self.assertTrue(re.search(r"Payment reference not found|Payment processing failed",
                                          case["body"]), case["body"])


class TestOwnedReferenceLookup(EnhancedTestCase):
    """The lookup itself, for the shapes the WSGI fixture cannot build cheaply."""

    def _query_count(self, doctype, name, email):
        from frappe.database.database import Database

        from verenigingen.verenigingen_payments.utils.reference_ownership import (
            PaymentReferenceRefused,
            load_owned_reference,
        )

        real_sql = Database.sql
        counter = {"n": 0}

        def counting_sql(db, *args, **kwargs):
            counter["n"] += 1
            return real_sql(db, *args, **kwargs)

        with self.as_user("Guest"):
            with patch.object(Database, "sql", counting_sql):
                with self.assertRaises(PaymentReferenceRefused) as ctx:
                    load_owned_reference(doctype, name, email)
        return counter["n"], str(ctx.exception), len(frappe.local.message_log)

    def _assert_unknown_matches_existing(self, doctype, existing_name, unknown_name):
        self._query_count(doctype, existing_name, "stranger@example.com")  # warm caches
        existing = self._query_count(doctype, existing_name, "stranger@example.com")
        unknown = self._query_count(doctype, unknown_name, "stranger@example.com")
        self.assertEqual(existing, unknown)
        self.assertEqual(existing[1], "Payment reference not found")

    def test_payment_plan_payment_with_a_member_costs_the_same_as_an_unknown_one(self):
        member = self.create_test_member()
        plan_payment = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 5.0,
             "currency": "EUR", "status": "Pending", "member": member.name}
        )
        plan_payment.insert(ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", plan_payment.name)
        self._assert_unknown_matches_existing("Payment Plan Payment", plan_payment.name, "PPP-NOPE-1")

    def test_the_members_own_email_proves_ownership_of_a_plan_payment(self):
        """Control: the Member lookup is real, not a stub that always refuses."""
        from verenigingen.verenigingen_payments.utils.reference_ownership import load_owned_reference

        member = self.create_test_member()
        plan_payment = frappe.get_doc(
            {"doctype": "Payment Plan Payment", "installment_number": 1, "amount": 5.0,
             "currency": "EUR", "status": "Pending", "member": member.name}
        )
        plan_payment.insert(ignore_mandatory=True, ignore_links=True)
        self.track_doc("Payment Plan Payment", plan_payment.name)
        doc = load_owned_reference("Payment Plan Payment", plan_payment.name, f" {member.email.upper()} ")
        self.assertEqual(doc.name, plan_payment.name)

    def test_sales_invoice_costs_the_same_as_an_unknown_one(self):
        member = self.create_test_member()
        invoice = self.create_test_sales_invoice(member.name)
        self.track_doc("Sales Invoice", invoice.name)
        self._assert_unknown_matches_existing("Sales Invoice", invoice.name, "ACC-SINV-NOPE-1")

    def test_a_filter_dict_as_the_name_is_refused_not_read_as_filters(self):
        """get_value reads a dict name as filters: {"donor_email": "%"} must not match a real Donation."""
        from verenigingen.verenigingen_payments.utils.reference_ownership import _owner_email_on_file

        self.assertEqual(_owner_email_on_file("Donation", {"name": ["like", "%"]}), "")


class TestTrimMessageLog(EnhancedTestCase):
    """frappe.throw queues its text BEFORE raising, so catching the exception leaves it for the client."""

    def test_drops_what_was_queued_since_the_mark_and_keeps_what_came_before(self):
        from verenigingen.verenigingen_payments.utils.reference_ownership import trim_message_log

        frappe.msgprint("queued-before-the-call")
        mark = len(frappe.local.message_log)
        with self.assertRaises(frappe.ValidationError):
            frappe.throw("existence-hint-xyz")
        self.assertEqual(len(frappe.local.message_log), mark + 1)

        trim_message_log(mark)

        self.assertEqual(len(frappe.local.message_log), mark)
        self.assertIn("queued-before-the-call", frappe.local.message_log[-1]["message"])
