# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Ownership enforcement for the id-taking whitelisted endpoints in
``ing_checkout/api/payment.py`` (#2814, sibling of #1089).

``get_payment_status(transaction_id)`` returned the payer's IBAN and name for ANY Pay.nl order id,
and ``create_ideal_payment(reference_doctype, reference_name, ...)`` opened a payment against any
reference document. Per #1101 a plain member may act on their own records only; staff
(Roles.ADMIN_ROLES) may act on a member's behalf.

The attacker is a real "Verenigingen Chapter Board Member" role-profile user: it clears the
MEDIUM tier of ``get_payment_status`` and the HIGH tier of ``create_ideal_payment`` and holds no
admin role, so the ownership check is the only thing that can refuse it. An unknown id and a
forbidden id must be indistinguishable on every channel (#1328): exception type, message,
message_log, Error Log rows, query count, and over a real WSGI request the HTTP status and body.
"""

import json
import os
import subprocess
import sys
import textwrap
from functools import partial
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.doctype.ing_checkout_transaction.ing_checkout_transaction import (
    get_or_create_transaction,
)
from verenigingen.verenigingen_payments.ing_checkout.api import payment as payment_api
from verenigingen.verenigingen_payments.ing_checkout.tests import test_mandate_api_ownership as mandate_ownership

UNKNOWN_ORDER = "EX-0000-0000-2814"
UNKNOWN_INVOICE = "ACC-SINV-DOES-NOT-EXIST-2814"
PAYER_IBAN = "NL91ABNA0417164300"


class _Pay2814Base(mandate_ownership._Base):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )
        self.attacker, self.attacker_member = self._board_member_linked_user("IngPayAttacker")
        self.victim = self.create_test_member(first_name="IngPayVictim")
        self.attacker_customer = self._ing2814_give_customer(self.attacker_member)
        self.victim_customer = self._ing2814_give_customer(self.victim)
        self.own_invoice = self._ing2814_invoice(self.attacker_customer)
        self.victim_invoice = self._ing2814_invoice(self.victim_customer)
        self.own_order = self._ing2814_order("OWN", "Sales Invoice", self.own_invoice.name)
        self.victim_order = self._ing2814_order("VICTIM", "Sales Invoice", self.victim_invoice.name)
        self.fake_client = MagicMock()
        self.fake_client.get_order.return_value = {
            "status": {"code": 100, "action": "PAID"},
            "payments": [{"customerMethod": {"iban": PAYER_IBAN, "name": "Victim Payer"}}],
        }
        patcher = patch.object(payment_api, "get_client", return_value=self.fake_client)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _ing2814_give_customer(self, member):
        customer = self.sepa.create_test_customer(customer_name=f"Cust {member.name}").name
        frappe.db.set_value("Member", member.name, "customer", customer)
        return customer

    def _ing2814_invoice(self, customer):
        from frappe.utils import today

        return self.sepa.create_test_sales_invoice(
            customer=customer,
            grand_total=42.0,
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
        )

    def _ing2814_plan_payment(self, member_name):
        """A Payment Plan Payment owned by `member_name`.

        Probe shortcut: no parent Payment Plan exists (`payment_plan` is mandatory), so mandatory
        and link validation are skipped; only the `member` link matters to the owner rule.
        """
        with self.set_user("Administrator"):
            row = frappe.get_doc(
                {
                    "doctype": "Payment Plan Payment",
                    "installment_number": 1,
                    "amount": 5.0,
                    "member": member_name,
                    "status": "Pending",
                }
            )
            row.flags.ignore_mandatory = True
            row.flags.ignore_links = True
            row.insert()
        self.track_doc("Payment Plan Payment", row.name)
        return row

    def _ing2814_order(self, label, reference_doctype, reference_name):
        order_id = f"EX-{label}-{frappe.generate_hash(length=8)}"
        txn = get_or_create_transaction(
            transaction_id=order_id,
            reference_doctype=reference_doctype,
            reference_name=reference_name,
            amount=42.0,
        )
        self.track_doc("ING Checkout Transaction", txn.name)
        return order_id


class TestGetPaymentStatusOwnership(_Pay2814Base):
    def test_foreign_order_refused_and_pay_nl_not_called(self):
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                payment_api.get_payment_status(self.victim_order)
        self.fake_client.get_order.assert_not_called()

    def test_unknown_order_indistinguishable_from_foreign_order(self):
        with self.set_user(self.attacker):
            unknown = self._observe(payment_api.get_payment_status, UNKNOWN_ORDER)
            forbidden = self._observe(payment_api.get_payment_status, self.victim_order)
        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertIs(forbidden["outcome"][1], frappe.PermissionError)
        self.assertEqual(unknown, forbidden)

    def test_own_order_allowed(self):
        with self.set_user(self.attacker):
            result = payment_api.get_payment_status(self.own_order)
        self.assertTrue(result["success"])
        self.assertTrue(result["paid"])
        self.assertEqual(result["customer_iban"], PAYER_IBAN)
        self.fake_client.get_order.assert_called_once_with(self.own_order)

    def test_order_on_an_unmapped_reference_doctype_refused_to_non_staff(self):
        """Fail closed: a real order row whose reference is a Customer has no owner rule."""
        order = self._ing2814_order("CUST", "Customer", self.attacker_customer)
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                payment_api.get_payment_status(order)
        self.fake_client.get_order.assert_not_called()

    def test_unknown_order_indistinguishable_from_foreign_member_referenced_order(self):
        order = self._ing2814_order("MEM", "Member", self.victim.name)
        with self.set_user(self.attacker):
            unknown = self._observe(payment_api.get_payment_status, UNKNOWN_ORDER)
            forbidden = self._observe(payment_api.get_payment_status, order)
        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertEqual(unknown, forbidden)

    def test_unknown_order_indistinguishable_from_foreign_plan_payment_order(self):
        order = self._ing2814_order("PPP", "Payment Plan Payment", self._ing2814_plan_payment(self.victim.name).name)
        with self.set_user(self.attacker):
            unknown = self._observe(payment_api.get_payment_status, UNKNOWN_ORDER)
            forbidden = self._observe(payment_api.get_payment_status, order)
        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertEqual(unknown, forbidden)

    def test_plan_payment_order_owner_allowed_and_foreign_refused(self):
        own = self._ing2814_order("PPPOWN", "Payment Plan Payment", self._ing2814_plan_payment(self.attacker_member.name).name)
        foreign = self._ing2814_order("PPPFOR", "Payment Plan Payment", self._ing2814_plan_payment(self.victim.name).name)
        with self.set_user(self.attacker):
            self.assertTrue(payment_api.get_payment_status(own)["success"])
            with self.assertRaises(frappe.PermissionError):
                payment_api.get_payment_status(foreign)
        self.fake_client.get_order.assert_called_once_with(own)

    def test_recorded_limitation_members_sharing_a_customer_share_orders_2493(self):
        """RECORDED LIMITATION (#2493), not endorsed behaviour.

        The Sales Invoice owner rule is `invoice.customer == caller Member.customer`, the same
        rule mandate.py uses. A second Member linked to the victim's Customer therefore reads the
        victim's order status. #2493 owns the decision; if it changes the rule, update this test.
        """
        frappe.db.set_value("Member", self.attacker_member.name, "customer", self.victim_customer)
        with self.set_user(self.attacker):
            result = payment_api.get_payment_status(self.victim_order)
        self.assertEqual(result["customer_iban"], PAYER_IBAN)

    def test_staff_may_read_another_members_order(self):
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            result = payment_api.get_payment_status(self.victim_order)
        self.assertTrue(result["success"])
        self.assertEqual(result["customer_iban"], PAYER_IBAN)

    def test_staff_unknown_order_is_not_refused(self):
        """Staff are not subject to the ownership gate: an unknown id reaches Pay.nl as before."""
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            payment_api.get_payment_status(UNKNOWN_ORDER)
        self.fake_client.get_order.assert_called_once_with(UNKNOWN_ORDER)


class TestCreateIdealPaymentOwnership(_Pay2814Base):
    def setUp(self):
        super().setUp()
        order_patcher = patch.object(payment_api, "create_ideal_order", return_value={"success": True})
        self.create_order = order_patcher.start()
        self.addCleanup(order_patcher.stop)

    def _create(self, doctype, name):
        return payment_api.create_ideal_payment(doctype, name, 42.0, "probe")

    def test_foreign_invoice_refused_and_no_order_created(self):
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                self._create("Sales Invoice", self.victim_invoice.name)
        self.create_order.assert_not_called()

    def test_foreign_member_reference_refused(self):
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                self._create("Member", self.victim.name)
        self.create_order.assert_not_called()

    def test_unknown_invoice_indistinguishable_from_foreign_invoice(self):
        with self.set_user(self.attacker):
            unknown = self._observe(partial(self._create, "Sales Invoice"), UNKNOWN_INVOICE)
            forbidden = self._observe(partial(self._create, "Sales Invoice"), self.victim_invoice.name)
        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertIs(forbidden["outcome"][1], frappe.PermissionError)
        self.assertEqual(unknown, forbidden)

    def test_unknown_member_indistinguishable_from_foreign_member(self):
        with self.set_user(self.attacker):
            unknown = self._observe(partial(self._create, "Member"), "NONEXISTENT-MEMBER-2814")
            forbidden = self._observe(partial(self._create, "Member"), self.victim.name)
        self.assertEqual(forbidden["outcome"][0], "raised", forbidden)
        self.assertEqual(unknown, forbidden)

    def test_unmapped_reference_doctype_refused_to_non_staff(self):
        """Fail closed: a real Customer row, but Customer has no owner rule."""
        with self.set_user(self.attacker):
            with self.assertRaises(frappe.PermissionError):
                self._create("Customer", self.attacker_customer)
        self.create_order.assert_not_called()

    def test_own_invoice_allowed(self):
        with self.set_user(self.attacker):
            result = self._create("Sales Invoice", self.own_invoice.name)
        self.assertEqual(result, {"success": True})
        self.create_order.assert_called_once_with("Sales Invoice", self.own_invoice.name, 42.0, "probe")

    def test_plan_payment_reference_owner_allowed_and_foreign_refused(self):
        own = self._ing2814_plan_payment(self.attacker_member.name)
        foreign = self._ing2814_plan_payment(self.victim.name)
        with self.set_user(self.attacker):
            self.assertEqual(self._create("Payment Plan Payment", own.name), {"success": True})
            with self.assertRaises(frappe.PermissionError):
                self._create("Payment Plan Payment", foreign.name)
        self.create_order.assert_called_once()

    def test_own_member_reference_allowed(self):
        with self.set_user(self.attacker):
            result = self._create("Member", self.attacker_member.name)
        self.assertEqual(result, {"success": True})
        self.create_order.assert_called_once()

    def test_staff_may_create_for_another_members_invoice(self):
        staff = self._staff_user(role="Verenigingen Staff")
        with self.set_user(staff):
            result = self._create("Sales Invoice", self.victim_invoice.name)
        self.assertEqual(result, {"success": True})
        self.create_order.assert_called_once()


class TestPaymentEndpointsOverRealRequest(_Pay2814Base):
    """A real WSGI request in a subprocess (frappe.app.application destroys frappe.local)."""

    def test_unknown_matches_forbidden_over_wsgi(self):
        from frappe.utils import get_bench_path

        password = self._create_committed_login(self.attacker)
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
                data={{"usr": {self.attacker!r}, "pwd": {password!r}}},
                headers=headers,
            )
            assert login.status_code == 200, login.get_data(as_text=True)
            cookie = "; ".join(c.split(";")[0] for c in login.headers.get_all("Set-Cookie"))

            base = "/api/method/verenigingen.verenigingen_payments.ing_checkout.api.payment."

            def call(fn, **params):
                qs = "&".join(f"{{k}}={{v}}" for k, v in params.items())
                r = client.get(base + fn + "?" + qs, headers={{**headers, "Cookie": cookie}})
                return {{"status": r.status_code, "body": r.get_data(as_text=True)}}

            def ideal(name):
                return call(
                    "create_ideal_payment",
                    reference_doctype="Sales Invoice",
                    reference_name=name,
                    amount="42.0",
                    description="probe",
                )

            print(json.dumps({{
                "get_payment_status": [
                    call("get_payment_status", transaction_id={UNKNOWN_ORDER!r}),
                    call("get_payment_status", transaction_id={self.victim_order!r}),
                ],
                "create_ideal_payment": [ideal({UNKNOWN_INVOICE!r}), ideal({self.victim_invoice.name!r})],
            }}))
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
                self.assertEqual(
                    mandate_ownership._strip_exc_id(unknown["body"]),
                    mandate_ownership._strip_exc_id(forbidden["body"]),
                )
