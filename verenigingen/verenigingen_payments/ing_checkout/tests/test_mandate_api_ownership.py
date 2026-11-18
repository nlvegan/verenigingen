# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Ownership enforcement for the six whitelisted endpoints in
``ing_checkout/api/mandate.py`` (#1089).

Each took a caller-supplied member / mandate id and resolved it with no check
against the caller's own Member record. Per #1101's ruling a plain member may act
on their own record only; staff (Roles.ADMIN_ROLES) may act on a member's behalf.

Callers WITHOUT blanket doctype access: the attacker is a real "Verenigingen
Chapter Board Member" role-profile user (clears the HIGH/MEDIUM tier, holds no
admin role). ``execute_debit_for_invoice`` is CRITICAL and no non-admin profile
clears it today, so those tests open the tier gate (see
``MemberOwnershipProbeMixin._bypass_tier_gate``) to isolate the ownership check.

Existence oracle (#1328 shape): for a non-staff caller an unknown id and a
forbidden id must be indistinguishable on every channel - exception type,
message, message_log, Error Log rows, query count - and, over a real WSGI
request, HTTP status and body shape.
"""

import json
import os
import re
import subprocess
import sys
import textwrap
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.member_ownership_probe_mixin import MemberOwnershipProbeMixin
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.utils.query_counter import count_queries
from verenigingen.verenigingen_payments.ing_checkout.api import mandate as mandate_api

UNKNOWN_MANDATE = "ING-MANDATE-DOES-NOT-EXIST-1089"
UNKNOWN_MEMBER = "NONEXISTENT-MEMBER-ID-1089"


def _strip_exc_id(value):
    """Drop the per-exception random ``__frappe_exc_id`` so two refusals compare equal."""
    return re.sub(r"__frappe_exc_id[^0-9a-f]*[0-9a-f]{20,}", "EXC", json.dumps(value, sort_keys=True, default=str))


class _RecordingService:
    def __init__(self):
        self.calls = []

    def create_mandate_for_member(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"success": True}

    def execute_debit_for_invoice(self, **kwargs):
        self.calls.append(("execute", kwargs))
        return {"success": True}

    def sync_mandate_status(self, mandate_name):
        self.calls.append(("sync", mandate_name))
        return {"success": True}


class _Base(MemberOwnershipProbeMixin, EnhancedTestCase):
    def _make_mandate_for(self, member_name):
        mandate = frappe.get_doc(
            {
                "doctype": "ING Checkout Mandate",
                "mandate_id": f"MD-{frappe.generate_hash(length=10)}",
                "mandate_type": "flexible",
                "status": "Active",
                "debtor_name": "Ownership Probe",
                "debtor_iban": "NL91ABNA0417164300",
                "member": member_name,
            }
        )
        mandate.insert(ignore_permissions=True)
        self.track_doc("ING Checkout Mandate", mandate.name)
        return mandate

    def _patch_service(self):
        recorder = _RecordingService()
        patcher = patch(
            "verenigingen.verenigingen_payments.ing_checkout.services.mandate_service.get_mandate_service",
            return_value=recorder,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return recorder

    @staticmethod
    def _swallow(fn, *args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception:
            pass
        frappe.clear_messages()

    def _observe(self, fn, *args, **kwargs):
        """Everything an attacker can observe about one refused call."""
        self._swallow(fn, *args, **kwargs)  # warm caches: a cold first call issues extra queries
        errors_before = frappe.db.count("Error Log")
        frappe.clear_messages()
        with count_queries() as counter:
            try:
                result = fn(*args, **kwargs)
            except Exception as e:
                outcome = ("raised", type(e), str(e))
            else:
                outcome = ("returned", json.dumps(result, default=str, sort_keys=True))
        return {
            "outcome": outcome,
            "message_log": _strip_exc_id(frappe.get_message_log()),
            "error_logs": frappe.db.count("Error Log") - errors_before,
            "queries": len(counter.queries),
        }

    def _assert_unknown_matches_forbidden(self, fn, unknown, forbidden):
        unknown_obs = self._observe(fn, unknown)
        forbidden_obs = self._observe(fn, forbidden)
        self.assertEqual(forbidden_obs["outcome"][0], "raised", forbidden_obs)
        self.assertIs(forbidden_obs["outcome"][1], frappe.PermissionError)
        self.assertEqual(unknown_obs, forbidden_obs)


class TestMandateNameEndpointsOwnership(_Base):
    """get_mandate_status / sync_mandate_status / cancel_mandate (mandate id)."""

    def setUp(self):
        super().setUp()
        self.attacker, self.attacker_member = self._board_member_linked_user("IngMandateAttacker")
        self.victim = self.create_test_member(first_name="IngMandateVictim")
        self.victim_mandate = self._make_mandate_for(self.victim.name)
        self.own_mandate = self._make_mandate_for(self.attacker_member.name)

    def test_foreign_mandate_refused_on_every_endpoint(self):
        self._patch_service()
        with self.set_user(self.attacker):
            for fn in (
                mandate_api.get_mandate_status,
                mandate_api.sync_mandate_status,
                mandate_api.cancel_mandate,
            ):
                with self.subTest(fn=fn.__name__), self.assertRaises(frappe.PermissionError):
                    fn(self.victim_mandate.name)
        self.assertEqual(frappe.db.get_value("ING Checkout Mandate", self.victim_mandate.name, "status"), "Active")

    def test_unknown_mandate_indistinguishable_from_foreign_mandate(self):
        self._patch_service()
        for fn in (
            mandate_api.get_mandate_status,
            mandate_api.sync_mandate_status,
            mandate_api.cancel_mandate,
        ):
            with self.subTest(fn=fn.__name__), self.set_user(self.attacker):
                self._assert_unknown_matches_forbidden(fn, UNKNOWN_MANDATE, self.victim_mandate.name)

    def test_own_mandate_allowed(self):
        recorder = self._patch_service()
        with self.set_user(self.attacker):
            status = mandate_api.get_mandate_status(self.own_mandate.name)
            sync = mandate_api.sync_mandate_status(self.own_mandate.name)
        self.assertTrue(status["success"])
        self.assertEqual(status["member"], self.attacker_member.name)
        self.assertEqual(sync, {"success": True})
        self.assertEqual(recorder.calls, [("sync", self.own_mandate.name)])

    def test_mandate_without_member_refused_to_non_staff(self):
        orphan = self._make_mandate_for(None)
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                mandate_api.get_mandate_status(orphan.name)

    def test_staff_may_act_on_another_members_mandate(self):
        recorder = self._patch_service()
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            status = mandate_api.get_mandate_status(self.victim_mandate.name)
            mandate_api.sync_mandate_status(self.victim_mandate.name)
        self.assertEqual(status["member"], self.victim.name)
        self.assertEqual(recorder.calls, [("sync", self.victim_mandate.name)])

    def test_staff_still_sees_not_found_for_unknown_mandate(self):
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            result = mandate_api.get_mandate_status(UNKNOWN_MANDATE)
        self.assertEqual(result["success"], False)
        self.assertIn("Mandate not found", result["error"])


class TestMemberNameEndpointsOwnership(_Base):
    """create_mandate_for_member / get_member_mandates (member id)."""

    def setUp(self):
        super().setUp()
        self.attacker, self.attacker_member = self._board_member_linked_user("IngMemberAttacker")
        self.victim = self.create_test_member(first_name="IngMemberVictim")
        self.victim_mandate = self._make_mandate_for(self.victim.name)

    def test_foreign_member_refused(self):
        recorder = self._patch_service()
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                mandate_api.get_member_mandates(self.victim.name)
            with self.assertRaises(frappe.PermissionError):
                mandate_api.create_mandate_for_member(self.victim.name)
        self.assertEqual(recorder.calls, [])

    def test_unknown_member_indistinguishable_from_foreign_member(self):
        self._patch_service()
        for fn in (mandate_api.get_member_mandates, mandate_api.create_mandate_for_member):
            with self.subTest(fn=fn.__name__), self.set_user(self.attacker):
                self._assert_unknown_matches_forbidden(fn, UNKNOWN_MEMBER, self.victim.name)

    def test_own_member_allowed(self):
        recorder = self._patch_service()
        own = self._make_mandate_for(self.attacker_member.name)
        with self.set_user(self.attacker):
            listing = mandate_api.get_member_mandates(self.attacker_member.name)
            mandate_api.create_mandate_for_member(self.attacker_member.name)
        self.assertEqual([m["name"] for m in listing["mandates"]], [own.name])
        self.assertEqual(len(recorder.calls), 1)

    def test_staff_may_act_for_another_member(self):
        recorder = self._patch_service()
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            listing = mandate_api.get_member_mandates(self.victim.name)
            mandate_api.create_mandate_for_member(self.victim.name)
        self.assertEqual([m["name"] for m in listing["mandates"]], [self.victim_mandate.name])
        self.assertEqual(len(recorder.calls), 1)


class TestExecuteDebitOwnership(_Base):
    """execute_debit_for_invoice: CRITICAL, so the tier gate is opened."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.attacker, self.attacker_member = self._plain_member_linked_user("IngDebitAttacker")
        self.victim = self.create_test_member(first_name="IngDebitVictim")
        self.attacker_customer = self._give_customer(self.attacker_member)
        self.victim_customer = self._give_customer(self.victim)
        self.own_mandate = self._make_mandate_for(self.attacker_member.name)
        self.victim_mandate = self._make_mandate_for(self.victim.name)
        self.own_invoice = self._invoice(self.attacker_customer)
        self.victim_invoice = self._invoice(self.victim_customer)

    def _give_customer(self, member):
        customer = self.sepa.create_test_customer(customer_name=f"Cust {member.name}").name
        frappe.db.set_value("Member", member.name, "customer", customer)
        return customer

    def _invoice(self, customer):
        from frappe.utils import today

        return self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=42.0,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
        )

    def test_foreign_mandate_refused(self):
        recorder = self._patch_service()
        with self.set_user(self.attacker), self._bypass_tier_gate():
            with self.assertRaises(frappe.PermissionError):
                mandate_api.execute_debit_for_invoice(self.victim_mandate.name, self.victim_invoice.name)
        self.assertEqual(recorder.calls, [])

    def test_own_mandate_with_foreign_invoice_refused(self):
        recorder = self._patch_service()
        with self.set_user(self.attacker), self._bypass_tier_gate():
            with self.assertRaises(frappe.PermissionError):
                mandate_api.execute_debit_for_invoice(self.own_mandate.name, self.victim_invoice.name)
        self.assertEqual(recorder.calls, [])

    def test_unknown_mandate_and_unknown_pairing_indistinguishable_from_foreign(self):
        self._patch_service()
        with self.set_user(self.attacker), self._bypass_tier_gate():
            foreign = self._observe(
                mandate_api.execute_debit_for_invoice, self.victim_mandate.name, self.victim_invoice.name
            )
            unknown = self._observe(
                mandate_api.execute_debit_for_invoice, UNKNOWN_MANDATE, self.victim_invoice.name
            )
            mismatched = self._observe(
                mandate_api.execute_debit_for_invoice, self.own_mandate.name, self.victim_invoice.name
            )
        self.assertEqual(foreign["outcome"][0], "raised", foreign)
        self.assertEqual(unknown, foreign)
        self.assertEqual(mismatched["outcome"], foreign["outcome"])
        self.assertEqual(mismatched["message_log"], foreign["message_log"])

    def test_own_mandate_and_own_invoice_allowed(self):
        recorder = self._patch_service()
        with self.set_user(self.attacker), self._bypass_tier_gate():
            result = mandate_api.execute_debit_for_invoice(self.own_mandate.name, self.own_invoice.name)
        self.assertEqual(result, {"success": True})
        self.assertEqual(len(recorder.calls), 1)

    def test_staff_may_debit_another_members_invoice(self):
        recorder = self._patch_service()
        staff = self._staff_user()
        with self.set_user(staff):
            result = mandate_api.execute_debit_for_invoice(self.victim_mandate.name, self.victim_invoice.name)
        self.assertEqual(result, {"success": True})
        self.assertEqual(len(recorder.calls), 1)


class TestMandateEndpointsOverRealRequest(_Base):
    """A real WSGI request (subprocess: frappe.app.application destroys
    frappe.local per request, which would tear down this test's own)."""

    def test_unknown_matches_forbidden_over_wsgi(self):
        from frappe.utils import get_bench_path
        from frappe.utils.password import update_password

        attacker, _member = self._board_member_linked_user("IngWsgiAttacker")
        victim = self.create_test_member(first_name="IngWsgiVictim")
        victim_mandate = self._make_mandate_for(victim.name)

        password = f"Probe-{frappe.generate_hash()[:12]}!"
        update_password(attacker, password)
        # Load-bearing: the subprocess has its own DB connection and must see
        # the User, Member and mandate rows created above.
        frappe.db.commit()

        site = frappe.local.site
        script = textwrap.dedent(
            f"""
            import json
            import frappe

            frappe.init(site={site!r})
            frappe.connect()
            frappe.clear_cache()
            frappe.destroy()

            import frappe.app
            from werkzeug.test import Client

            client = Client(frappe.app.application)
            headers = {{"X-Frappe-Site-Name": {site!r}}}
            login = client.post(
                "/api/method/login",
                data={{"usr": {attacker!r}, "pwd": {password!r}}},
                headers=headers,
            )
            assert login.status_code == 200, login.get_data(as_text=True)
            cookie = "; ".join(c.split(";")[0] for c in login.headers.get_all("Set-Cookie"))

            base = "/api/method/verenigingen.verenigingen_payments.ing_checkout.api.mandate."

            def call(fn, **params):
                qs = "&".join(f"{{k}}={{v}}" for k, v in params.items())
                r = client.get(base + fn + "?" + qs, headers={{**headers, "Cookie": cookie}})
                return {{"status": r.status_code, "body": r.get_data(as_text=True)}}

            out = {{}}
            for fn in ("get_mandate_status", "sync_mandate_status", "cancel_mandate"):
                out[fn] = [
                    call(fn, mandate_name={UNKNOWN_MANDATE!r}),
                    call(fn, mandate_name={victim_mandate.name!r}),
                ]
            out["get_member_mandates"] = [
                call("get_member_mandates", member_name={UNKNOWN_MEMBER!r}),
                call("get_member_mandates", member_name={victim.name!r}),
            ]
            out["create_mandate_for_member"] = [
                call("create_mandate_for_member", member_name={UNKNOWN_MEMBER!r}),
                call("create_mandate_for_member", member_name={victim.name!r}),
            ]
            print(json.dumps(out))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=os.path.join(get_bench_path(), "sites"),
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])

        for fn, (unknown, forbidden) in out.items():
            with self.subTest(fn=fn):
                self.assertEqual(forbidden["status"], 403, forbidden)
                self.assertEqual(unknown["status"], forbidden["status"])
                unknown_body, forbidden_body = json.loads(unknown["body"]), json.loads(forbidden["body"])
                self.assertEqual(unknown_body.get("exc_type"), "PermissionError")
                self.assertEqual(unknown_body.get("exc_type"), forbidden_body.get("exc_type"))
                self.assertEqual(
                    _strip_exc_id(unknown_body.get("_server_messages")),
                    _strip_exc_id(forbidden_body.get("_server_messages")),
                )
                self.assertEqual(sorted(unknown_body), sorted(forbidden_body))
                self.assertNotIn(victim_mandate.name, forbidden["body"])
