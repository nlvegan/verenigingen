"""
#2304 (class of #2281): an endpoint that answers a failure with ``OperationResult.fail``
(HTTP 200) must not leave the writes it made before the failure behind, because
``frappe/app.py`` COMMITS a 200 response.

Two measured instances, each driven through the REAL WSGI app (README rule 21) with token
auth in a SUBPROCESS, and read back on a FRESH connection:

* ``unlink_donor_customer(remove_customer=1)``: saves the Donor (customer cleared) and clears
  ``Customer.donor``, THEN ``Customer.delete()`` raises PermissionError for the plain
  "Verenigingen Administrator" (no role in that profile may delete a Customer; the
  endpoint is ADMIN-tier, so this caller reaches it). The half-unlink was committed.
* ``update_anbi_consent(consent=0, reason=...)``: writes the "consent withdrawn" audit Comment
  (``add_comment`` ignores permissions), THEN ``donor.save()`` is refused because the stored
  e-mail address no longer validates (legacy data, set by ``db.set_value``). The trail claimed a
  withdrawal that never happened.

Controls: a clean pair on the same endpoint still gets the full write.

Usage:
    bench --site test_site_5 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_operationresult_fail_partial_write_2304
"""

import json
import os
import subprocess
import sys
import textwrap

import frappe
from frappe.utils import get_bench_path

from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
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
    from frappe.utils import now_datetime
    from verenigingen.setup.role_profile_setup import assign_role_profile_to_user
    from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn

    started = now_datetime()
    created = []   # (doctype, name), deleted in reverse order
    out = {{}}

    def make_user(profile, extra_role=None):
        email = "half2304-" + frappe.generate_hash(length=8) + "0@example.com"
        frappe.get_doc({{"doctype": "User", "email": email, "first_name": "Half2304",
                        "enabled": 1, "send_welcome_email": 0}}).insert(ignore_permissions=True)
        created.append(("User", email))
        created.append(("Notification Settings", email))
        assign_role_profile_to_user(email, profile)
        if extra_role:
            frappe.get_doc("User", email).add_roles(extra_role)
        secret = generate_keys(email)["api_secret"]
        frappe.db.commit()
        key = frappe.db.get_value("User", email, "api_key")
        return email, "token " + key + ":" + secret

    def make_donor(consent=1):
        donor = frappe.get_doc({{"doctype": "Donor", "donor_name": "Half2304 " + frappe.generate_hash(length=6),
            "donor_email": "d" + frappe.generate_hash(length=6) + "@example.com", "donor_type": "Individual",
            "is_anbi_eligible": 1, "anbi_consent": consent,
            "bsn_citizen_service_number": generate_valid_bsn()}}).insert(ignore_permissions=True)
        created.append(("Donor", donor.name))
        # Donor.insert also creates a Customer named after the donor; it outlives the Donor.
        customer = frappe.db.get_value("Donor", donor.name, "customer") or frappe.db.get_value(
            "Customer", {{"customer_name": donor.donor_name}})
        if customer:
            created.append(("Customer", customer))
            if frappe.db.exists("Contact", customer + "-" + customer):
                created.append(("Contact", customer + "-" + customer))
        frappe.db.commit()
        return donor.name, customer

    def post(client, header, method, **data):
        resp = client.post("/api/method/verenigingen.api." + method, data=data,
                           headers={{"X-Frappe-Site-Name": SITE, "Authorization": header}})
        body = json.loads(resp.get_data(as_text=True))
        msg = body.get("message")
        return {{"status": resp.status_code,
                "success": msg.get("success") if isinstance(msg, dict) else None,
                "detail": (msg.get("errors") or msg.get("message") or msg.get("error")) if isinstance(msg, dict) else str(body)[-300:]}}

    def fresh():
        frappe.destroy(); frappe.init(site=SITE); frappe.connect()

    def withdrawal_comments(donor):
        return frappe.db.count("Comment", {{"reference_doctype": "Donor", "reference_name": donor,
                                           "content": ["like", "ANBI consent withdrawn%"]}})

    try:
        admin = make_user("Verenigingen Administrator")

        # unlink: the admin may not delete the Customer (remove_customer=1); without it there is no delete
        blocked_donor, blocked_customer = make_donor()
        frappe.db.set_value("Customer", blocked_customer, "donor", blocked_donor)
        free_donor, free_customer = make_donor()
        frappe.db.set_value("Customer", free_customer, "donor", free_donor)
        # anbi consent: the refused donor's stored e-mail no longer validates on save
        refused_donor, _unused = make_donor()
        frappe.db.set_value("Donor", refused_donor, "donor_email", "not-an-email")
        control_donor, _unused = make_donor()
        frappe.db.commit()
        out["pre"] = {{"blocked_customer": blocked_customer,
                      "blocked_link": frappe.db.get_value("Donor", blocked_donor, "customer"),
                      "free_link": frappe.db.get_value("Donor", free_donor, "customer")}}
        frappe.destroy()

        import frappe.app
        from werkzeug.test import Client
        client = Client(frappe.app.application)

        out["unlink_blocked"] = post(client, admin[1], "donor_customer_management.unlink_donor_customer",
                                     donor_name=blocked_donor, remove_customer=1)
        out["unlink_control"] = post(client, admin[1], "donor_customer_management.unlink_donor_customer",
                                     donor_name=free_donor)
        out["consent_refused"] = post(client, admin[1], "anbi_operations.update_anbi_consent",
                                      donor=refused_donor, consent="0", reason="withdrawn by 2304 probe")
        out["consent_control"] = post(client, admin[1], "anbi_operations.update_anbi_consent",
                                      donor=control_donor, consent="0", reason="withdrawn by 2304 probe")

        fresh()
        out["unlink_blocked"].update({{
            "donor_customer": frappe.db.get_value("Donor", blocked_donor, "customer"),
            "customer_donor": frappe.db.get_value("Customer", blocked_customer, "donor"),
            "customer_exists": bool(frappe.db.exists("Customer", blocked_customer))}})
        out["unlink_control"].update({{
            "donor_customer": frappe.db.get_value("Donor", free_donor, "customer"),
            "customer_donor": frappe.db.get_value("Customer", free_customer, "donor")}})
        out["consent_refused"].update({{
            "consent": frappe.db.get_value("Donor", refused_donor, "anbi_consent"),
            "comments": withdrawal_comments(refused_donor)}})
        out["consent_control"].update({{
            "consent": frappe.db.get_value("Donor", control_donor, "anbi_consent"),
            "comments": withdrawal_comments(control_donor)}})
        out["admin_can_delete_customer"] = bool(frappe.has_permission("Customer", "delete", user=admin[0]))
        out["refused_email"] = frappe.db.get_value("Donor", refused_donor, "donor_email")
        print("RESULT" + json.dumps(out))
    finally:
        frappe.destroy(); frappe.init(site=SITE); frappe.connect(); frappe.set_user("Administrator")
        users = [n for dt, n in created if dt == "User"]
        for contact in frappe.get_all("Contact", filters={{"email_id": ["in", users]}}, pluck="name"):
            created.append(("Contact", contact))
        # Donor.customer / Customer.donor back-links would block the deletes: null them first.
        for dt, name in created:
            if dt == "Donor" and frappe.db.exists("Donor", name):
                frappe.db.set_value("Donor", name, "customer", None)
            if dt == "Customer" and frappe.db.exists("Customer", name):
                frappe.db.set_value("Customer", name, "donor", None)
        frappe.db.commit()
        for dt, name in sorted(reversed(created), key=lambda row: row[0] == "Contact"):
            if dt == "Notification Settings":
                continue  # deleted with its User; listed only so its leftovers are scoped
            try:
                if frappe.db.exists(dt, name):
                    frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
                    frappe.db.commit()
            except Exception as e:
                frappe.db.rollback()
                print("CLEANUP_FAILED " + dt + " " + name + " " + str(e))
        frappe.db.delete("Error Log", {{"method": ["in", ["Donor Customer Sync Error", "ANBI Consent Update Error"]],
                                       "creation": [">=", started]}})
        frappe.db.commit()
        # Rows the deletes and the requests leave behind, removed by the names this probe created.
        subjects = [dt + " " + n for dt, n in created]
        def residue():
            return {{
                "API Audit Log": frappe.get_all("API Audit Log", filters={{"user": ["in", users + ["Administrator"]],
                    "creation": [">=", started]}}, pluck="name"),
                "Version": [r for dt, n in created for r in frappe.get_all("Version",
                    filters={{"ref_doctype": dt, "docname": n, "creation": [">=", started]}}, pluck="name")],
                "Comment": frappe.get_all("Comment", filters={{"comment_type": "Deleted",
                    "subject": ["in", subjects], "creation": [">=", started]}}, pluck="name") + [
                    r for dt, n in created for r in frappe.get_all("Comment",
                    filters={{"reference_doctype": dt, "reference_name": n, "creation": [">=", started]}},
                    pluck="name")],
                "Deleted Document": [r for dt, n in created for r in frappe.get_all("Deleted Document",
                    filters={{"deleted_doctype": dt, "deleted_name": n, "creation": [">=", started]}},
                    pluck="name")],
            }}
        for dt, names in residue().items():
            if names:
                frappe.db.delete(dt, {{"name": ["in", names]}})
        frappe.db.commit()
        left = [(dt, n) for dt, n in created if frappe.db.exists(dt, n)]
        print("LEFTOVER" + json.dumps(left + [(dt, len(v)) for dt, v in residue().items() if v]))
        frappe.destroy()
    """
)


class TestOperationResultFailPartialWrite2304(EnhancedTestCase):
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
                f"the WSGI probe did not finish within 300s; committed 'Half2304' fixtures may remain. {e.stdout}"
            ) from e
        if result.returncode != 0:
            raise AssertionError(result.stdout + "\n" + result.stderr)
        lines = result.stdout.splitlines()
        cls.out = json.loads(next(x for x in lines if x.startswith("RESULT"))[len("RESULT") :])
        cls.leftover = next(x for x in lines if x.startswith("LEFTOVER"))[len("LEFTOVER") :]

    def test_probe_cleaned_up_after_itself(self):
        self.assertEqual(self.leftover, "[]")

    def test_the_fixtures_make_the_failures_real(self):
        """Each refusal below must be the one under test: the blocked unlink really had a linked
        Customer to lose and its caller really lacks Customer delete, and
        the refused consent donor really carries an address that fails validation. Both
        callers cleared the gate: the endpoint answered with a 200 failure, not a 403."""
        self.assertEqual(self.out["pre"]["blocked_link"], self.out["pre"]["blocked_customer"])
        self.assertTrue(self.out["pre"]["free_link"])
        self.assertFalse(self.out["admin_can_delete_customer"])
        self.assertEqual(self.out["refused_email"], "not-an-email")
        for key in ("unlink_blocked", "consent_refused"):
            self.assertEqual(self.out[key]["status"], 200, self.out[key])
            self.assertIs(self.out[key]["success"], False, self.out[key])

    def test_a_refused_customer_delete_leaves_the_donor_still_linked(self):
        blocked = self.out["unlink_blocked"]
        self.assertTrue(blocked["customer_exists"], blocked)
        self.assertEqual(
            blocked["donor_customer"], self.out["pre"]["blocked_customer"], f"half-unlink persisted: {blocked}"
        )
        self.assertTrue(blocked["customer_donor"], f"Customer.donor cleared by a failed unlink: {blocked}")

    def test_control_an_unlink_that_needs_no_delete_still_unlinks_both_sides(self):
        control = self.out["unlink_control"]
        self.assertIs(control["success"], True, control)
        self.assertFalse(control["donor_customer"], control)
        self.assertFalse(control["customer_donor"], control)

    def test_a_refused_consent_withdrawal_writes_no_audit_comment(self):
        refused = self.out["consent_refused"]
        self.assertEqual(refused["comments"], 0, f"audit comment for a withdrawal that never happened: {refused}")
        self.assertEqual(refused["consent"], 1, refused)

    def test_control_a_permitted_withdrawal_still_records_comment_and_consent(self):
        control = self.out["consent_control"]
        self.assertIs(control["success"], True, control)
        self.assertEqual(control["comments"], 1, control)
        self.assertEqual(control["consent"], 0, control)


class TestRollbackIsScopedAndDeadlockPropagates2304(VereningingenTestCase):
    """In-process pins for the two parts of the fix that the WSGI test above cannot see (the
    shape of 87bdfb4ba for #2281).

    * Earlier work survives: a full ``frappe.db.rollback()`` passes the WSGI test too (it removes
      the half-write just as well) but discards everything the request wrote before the call.
    * A deadlock (1213) has already destroyed the transaction and its savepoints, so the endpoint
      must re-raise it, not answer ``OperationResult.fail`` or ROLLBACK TO a dead savepoint.
      A single test transaction cannot produce a real deadlock, so it is injected at the write."""

    def _admin_user(self):
        from verenigingen.setup.role_profile_setup import assign_role_profile_to_user

        user = self.create_test_user(
            f"half2304-{frappe.generate_hash(length=6)}0@example.com", roles=["Employee"]
        ).name
        assign_role_profile_to_user(user, "Verenigingen Administrator")
        return user

    def _linked_donor(self):
        # Donor->Customer sync is gated off in tests unless this flag is set (as in test_donor_customer_api).
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Half2304 {frappe.generate_hash(length=6)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"h{frappe.generate_hash(length=6)}@example.com"
        donor.flags.enable_customer_sync_in_test = True
        donor.save()
        donor.reload()
        self.track_doc("Donor", donor.name)
        customer = donor.customer
        if customer:
            self.track_doc("Customer", customer)
        self.assertTrue(customer, "Donor.insert is expected to create and link a Customer")
        frappe.db.set_value("Customer", customer, "donor", donor.name)
        return donor, customer

    def _marker(self):
        marker = frappe.get_doc(
            {"doctype": "ToDo", "description": f"earlier-work-2304-{frappe.generate_hash(length=6)}"}
        ).insert()
        self.track_doc("ToDo", marker.name)
        return marker.name

    def test_unlink_refusal_keeps_earlier_work_and_undoes_its_own(self):
        from verenigingen.api.donor_customer_management import unlink_donor_customer

        user = self._admin_user()
        donor, customer = self._linked_donor()
        marker = self._marker()
        with self.set_user(user):
            self.assertFalse(frappe.has_permission("Customer", "delete"))
            self.expectErrorLog("Donor Customer Unlink Error")
            result = unlink_donor_customer(donor_name=donor.name, remove_customer=1)
        self.assertIs(result["success"], False, result)
        self.assertTrue(frappe.db.exists("ToDo", marker), "refusal discarded earlier work")
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "customer"), customer)

    def test_unlink_deadlock_propagates(self):
        from unittest import mock

        from verenigingen.api import donor_customer_management as ops

        donor, _customer = self._linked_donor()
        # Mock justified: injects the DB-level deadlock a single test transaction cannot produce.
        with mock.patch.object(
            frappe.model.document.Document, "delete", side_effect=frappe.QueryDeadlockError("1213")
        ), mock.patch.object(ops, "rollback_to_savepoint", wraps=ops.rollback_to_savepoint) as rollback:
            with self.assertRaises(frappe.QueryDeadlockError):
                ops.unlink_donor_customer(donor_name=donor.name, remove_customer=1)
        rollback.assert_not_called()

    def test_consent_refusal_keeps_earlier_work_and_undoes_its_own(self):
        from verenigingen.api.anbi_operations import update_anbi_consent

        user = self._admin_user()
        donor = self.create_test_donor(anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn())
        # Hand-set legacy state: Donor.validate rejects this address on every real insert/save.
        frappe.db.set_value("Donor", donor.name, "donor_email", "not-an-email")
        marker = self._marker()
        with self.set_user(user):
            self.expectErrorLog("ANBI Consent Update Error")
            result = update_anbi_consent(donor=donor.name, consent="0", reason="2304 earlier-work pin")
        self.assertIs(result["success"], False, result)
        self.assertTrue(frappe.db.exists("ToDo", marker), "refusal discarded earlier work")
        self.assertEqual(frappe.db.get_value("Donor", donor.name, "anbi_consent"), 1)
        self.assertEqual(
            frappe.db.count(
                "Comment",
                {"reference_doctype": "Donor", "reference_name": donor.name, "content": ["like", "ANBI consent withdrawn%"]},
            ),
            0,
        )

    def test_consent_deadlock_propagates(self):
        from unittest import mock

        from verenigingen.api import anbi_operations as ops
        from verenigingen.verenigingen.doctype.donor.donor import Donor

        donor = self.create_test_donor(anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn())
        # Mock justified: injects the DB-level deadlock a single test transaction cannot produce.
        with mock.patch.object(Donor, "save", side_effect=frappe.QueryDeadlockError("1213")), mock.patch.object(
            ops, "rollback_to_savepoint", wraps=ops.rollback_to_savepoint
        ) as rollback:
            with self.assertRaises(frappe.QueryDeadlockError):
                ops.update_anbi_consent(donor=donor.name, consent="0", reason="x")
        rollback.assert_not_called()
