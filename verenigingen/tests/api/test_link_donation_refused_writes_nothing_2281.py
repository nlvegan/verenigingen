"""
#2281: a refused ``link_donation_to_agreement`` must write NOTHING.

A National Board Member clears the endpoint's CRITICAL gate but holds no write on Donation
or Periodic Donation Agreement. The endpoint saved the Donation through
``secure_document_operation`` (whose escalation lets such a caller write it as the system
user) BEFORE the agreement save, which is refused. The endpoint then returned
``OperationResult.fail`` with HTTP 200, so ``frappe/app.py`` COMMITTED the half-link.

Driven through the REAL WSGI app (``werkzeug.test.Client(frappe.app.application)``, README
rule 21) with token auth, in a SUBPROCESS (frappe.app.application destroys/re-inits
frappe.local per request). State is read back on a FRESH connection. The subprocess builds
and removes its own committed fixtures; the caller's role profile is assigned through the
real ``assign_role_profile_to_user`` path.

Usage:
    bench --site test_site_3 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_link_donation_refused_writes_nothing_2281
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.base import VereningingenTestCase

_PROBE = textwrap.dedent(
    """
    import json
    import frappe

    SITE = {site!r}
    frappe.init(site=SITE)
    frappe.connect()
    frappe.set_user("Administrator")

    from frappe.core.doctype.user.user import generate_keys
    from frappe.utils import now_datetime, today
    from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
    from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn

    started = now_datetime()
    created = []   # (doctype, name), deleted in reverse order
    out = {{}}

    def make_user(profile):
        email = "link2281-" + frappe.generate_hash(length=8) + "0@example.com"
        user = frappe.get_doc({{"doctype": "User", "email": email, "first_name": "Link2281",
                               "enabled": 1, "send_welcome_email": 0}}).insert(ignore_permissions=True)
        created.append(("User", email))
        assign_role_profile_to_user(email, profile)
        secret = generate_keys(email)["api_secret"]
        frappe.db.commit()
        key = frappe.db.get_value("User", email, "api_key")
        return email, "token " + key + ":" + secret

    def make_pair():
        donor = frappe.get_doc({{"doctype": "Donor", "donor_name": "Link2281 " + frappe.generate_hash(length=6),
            "donor_email": "d" + frappe.generate_hash(length=6) + "@example.com", "donor_type": "Individual",
            "is_anbi_eligible": 1, "anbi_consent": 1,
            "bsn_citizen_service_number": generate_valid_bsn()}}).insert(ignore_permissions=True)
        created.append(("Donor", donor.name))
        agreement = frappe.get_doc({{"doctype": "Periodic Donation Agreement", "donor": donor.name,
            "start_date": today(), "annual_amount": 1200, "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer", "agreement_duration_years": "5 Years (ANBI Minimum)",
            "anbi_eligible": 1, "status": "Active"}}).insert(ignore_permissions=True)
        created.append(("Periodic Donation Agreement", agreement.name))
        mop = frappe.db.exists("Mode of Payment", "Bank Transfer") or frappe.db.get_value("Mode of Payment", {{}}, "name")
        donation = frappe.get_doc({{"doctype": "Donation", "donor": donor.name, "donation_date": today(),
            "amount": 150.0, "mode_of_payment": mop, "donor_type": "Individual", "currency": "EUR", "paid": 1,
            "company": frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0],
            }}).insert(ignore_permissions=True)
        created.append(("Donation", donation.name))
        frappe.db.commit()
        return donation.name, agreement.name

    def fresh_state(donation, agreement):
        frappe.destroy(); frappe.init(site=SITE); frappe.connect()
        return {{
            "donation_link": frappe.db.get_value("Donation", donation, "periodic_donation_agreement"),
            "agreement_rows": frappe.db.count("Periodic Donation Agreement Item",
                {{"parent": agreement, "donation": donation}}),
        }}

    try:
        callers = {{"refused": make_user("Verenigingen National Board Member"),
                   "control": make_user("Verenigingen Administrator")}}
        for label, (user, header) in callers.items():
            out[label + "_can_write"] = None
        pairs = {{label: make_pair() for label in callers}}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        client = Client(frappe.app.application)
        for label, (user, header) in callers.items():
            donation, agreement = pairs[label]
            resp = client.post(
                "/api/method/verenigingen.api.periodic_donation_operations.link_donation_to_agreement",
                data={{"donation": donation, "agreement": agreement}},
                headers={{"X-Frappe-Site-Name": SITE, "Authorization": header}},
            )
            body = json.loads(resp.get_data(as_text=True))
            msg = body.get("message")
            out[label] = {{"status": resp.status_code,
                           "success": (msg or {{}}).get("success") if isinstance(msg, dict) else None,
                           "raw": resp.get_data(as_text=True)[:400]}}
            out[label].update(fresh_state(donation, agreement))

        # The refused caller must have NO write on either doctype, or the test proves nothing.
        frappe.destroy(); frappe.init(site=SITE); frappe.connect()
        user = callers["refused"][0]
        out["refused_can_write"] = {{dt: frappe.has_permission(dt, "write", user=user)
                                     for dt in ("Donation", "Periodic Donation Agreement")}}
        out["control_can_write"] = {{dt: frappe.has_permission(dt, "write", user=callers["control"][0])
                                     for dt in ("Donation", "Periodic Donation Agreement")}}
        print("RESULT" + json.dumps(out))
    finally:
        frappe.destroy(); frappe.init(site=SITE); frappe.connect(); frappe.set_user("Administrator")
        for dt, name in reversed(created):
            try:
                if dt == "Donation":
                    frappe.db.set_value("Donation", name, "periodic_donation_agreement", None)
                if dt == "Periodic Donation Agreement":
                    frappe.db.delete("Periodic Donation Agreement Item", {{"parent": name}})
                frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
                frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                print("CLEANUP_FAILED " + dt + " " + name + " " + str(e))
        frappe.db.delete("Error Log", {{"method": "Donation Linking Error", "creation": [">=", started]}})
        frappe.db.commit()
        print("LEFTOVER" + json.dumps([(dt, n) for dt, n in created if frappe.db.exists(dt, n)]))
        frappe.destroy()
    """
)


class TestRefusedDonationLinkWritesNothing2281(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        try:
            result = subprocess.run(
                [sys.executable, "-c", _PROBE.format(site=frappe.local.site)],
                cwd=os.path.join(get_bench_path(), "sites"),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            raise AssertionError(
                f"the WSGI probe did not finish within 300s; committed 'Link2281' fixtures may remain. {e.stdout}"
            ) from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def test_the_refused_caller_really_has_no_write_but_clears_the_gate(self):
        """Without these the refusal below could be a gate refusal rather than the write refusal."""
        self.assertEqual(self.out["refused_can_write"], {"Donation": False, "Periodic Donation Agreement": False})
        self.assertEqual(self.out["control_can_write"], {"Donation": True, "Periodic Donation Agreement": True})
        # Cleared the CRITICAL gate: the endpoint ran and answered (200 with success false), not a 403.
        self.assertEqual(self.out["refused"]["status"], 200, self.out["refused"])
        self.assertIs(self.out["refused"]["success"], False, self.out["refused"])

    def test_a_refused_link_leaves_the_donation_unlinked_and_the_agreement_without_a_row(self):
        refused = self.out["refused"]
        self.assertIsNone(refused["donation_link"], f"half-link persisted over HTTP: {refused}")
        self.assertEqual(refused["agreement_rows"], 0, refused)

    def test_control_a_permitted_caller_still_links_both_sides(self):
        control = self.out["control"]
        self.assertIs(control["success"], True, control)
        self.assertTrue(control["donation_link"], control)
        self.assertEqual(control["agreement_rows"], 1, control)


class TestRefusalRollsBackOnlyItsOwnWrites2281(VereningingenTestCase):
    """The rollback must be scoped to the endpoint's own writes (a savepoint), not the whole
    transaction. A full ``frappe.db.rollback()`` also passes the WSGI test above (it removes
    the Donation write just as well) but discards everything the request wrote earlier, such as
    the security decorators' audit rows. Driven in-process as the same least-privileged caller:
    a row written BEFORE the call must survive the refusal."""

    def test_work_done_before_the_refused_call_survives(self):
        from verenigingen.api.periodic_donation_operations import link_donation_to_agreement
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
        from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn

        user = self.create_test_user(
            f"link2281-{frappe.generate_hash(length=6)}0@example.com", roles=["Employee"]
        ).name
        assign_role_profile_to_user(user, "Verenigingen National Board Member")
        donor = self.create_test_donor(anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn())
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")
        donation = self.create_test_donation(donor=donor.name, amount=10.0, paid=1)
        marker = frappe.get_doc(
            {"doctype": "ToDo", "description": f"earlier-work-2281-{frappe.generate_hash(length=6)}"}
        ).insert()
        self.track_doc("ToDo", marker.name)

        with self.set_user(user):
            self.assertFalse(frappe.has_permission("Donation", "write"))
            self.expectErrorLog("Donation Linking Error")  # the endpoint logs the refusal it reports
            result = link_donation_to_agreement(donation=donation.name, agreement=agreement.name)

        self.assertIs(result["success"], False, result)
        self.assertTrue(frappe.db.exists("ToDo", marker.name), "refusal discarded earlier work")
        self.assertTrue(frappe.db.exists("Donation", donation.name))
        self.assertIsNone(frappe.db.get_value("Donation", donation.name, "periodic_donation_agreement"))
