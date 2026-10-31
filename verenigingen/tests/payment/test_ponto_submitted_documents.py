# Copyright (c) 2026, Verenigingen
"""Ponto Payment Request / Payment Link on a REALLY SUBMITTED document -- #1907.

Both doctypes are submittable and production submits them (``before_submit`` calls
Ponto and moves the row to Pending / Pending Authorization). Every earlier Ponto test
inserted at docstatus 0 and set the status by hand, so none of them saw that Frappe
refuses to change a non-``allow_on_submit`` field on a docstatus-1 row
(``UpdateAfterSubmitError``). These tests drive ``Document.submit()`` for real; only the
Ponto HTTP client is stubbed (the call ``before_submit`` makes), and every later step --
the webhook/refresh status write, debtor details, the Payment Entry and its back-link --
runs unmocked.

Usage:
    bench --site test_site_7 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_submitted_documents
"""

import json
import subprocess
import sys
import textwrap
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.utils import flt, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup
from verenigingen.tests.payment.test_ponto_payment_entry_creation import _ensure_ponto_clearing_account
from verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe import (
    PAY_CLIENT_PATH,
    _PontoPaymentRequestFixtures,
)
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.ponto.core.submitted_rows import ALERT_MARKER, ALERT_TITLE

LINK_CLIENT_PATH = (
    "verenigingen.verenigingen_payments.ponto.clients.betaalverzoek_client.get_betaalverzoek_client"
)


WEBHOOK_ROLE = "Verenigingen Webhook User"


class _PontoUsers:
    """Real, non-Administrator users for the permission tests (#1907 ruling A, #1920)."""

    def _make_ponto_user(self, role):
        user = frappe.new_doc("User")
        user.email = f"ponto-{frappe.generate_hash(length=10)}@example.com"
        user.first_name = "Ponto Tester"
        user.send_welcome_email = 0
        user.enabled = 1
        user.append("roles", {"role": role})
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user.name

    def _alerts_for(self, doctype, name):
        """(ToDo rows, Error Log rows) raised for one cancelled row."""
        todos = frappe.get_all(
            "ToDo",
            filters={
                "reference_type": doctype,
                "reference_name": name,
                "description": ["like", f"{ALERT_MARKER}%"],
            },
        )
        logs = frappe.get_all("Error Log", filters={"method": ALERT_TITLE, "error": ["like", f"%{name}%"]})
        return todos, logs


def _create_client(ponto_id):
    """Stand-in for the Ponto client ``before_submit`` calls: ONLY the HTTP boundary."""
    created = SimpleNamespace(id=ponto_id, redirect_link=f"https://ponto.example/sign/{ponto_id}")
    return SimpleNamespace(create_payment=lambda **kw: created, create_payment_request=lambda **kw: created)


def _read_client(status, **extra):
    """Stand-in for the Ponto client a refresh reads the current state from."""
    state = SimpleNamespace(status=status, **extra)
    return SimpleNamespace(get_payment=lambda **kw: state, get_payment_request=lambda *a, **kw: state)


class TestSubmittedPontoPaymentRequest(_PontoUsers, _PontoPaymentRequestFixtures, EnhancedTestCase):
    """A Request that went through the real submit() lifecycle."""

    def _make_really_submitted_request(self, supplier, amount=42.0):
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = self.TEST_PONTO_ACCOUNT_ID
        req.amount = amount
        req.currency = "EUR"
        req.creditor_name = supplier.supplier_name
        req.creditor_iban = "NL91ABNA0417164300"
        req.remittance_info = "Test payment #1907"
        req.reference_doctype = "Supplier"
        req.reference_name = supplier.name
        req.insert(ignore_permissions=True)
        self.factory.track_document("Ponto Payment Request", req.name, priority=6)
        with patch(
            PAY_CLIENT_PATH, return_value=_create_client(f"ponto_pay_{frappe.generate_hash(length=8)}")
        ):
            req.submit()
        self.assertEqual(
            (req.docstatus, req.status), (1, "Pending"), "fixture must be a really submitted row"
        )
        return req

    def _entries_for(self, req):
        return frappe.get_all("Payment Entry", filters={"reference_no": req.name, "docstatus": 1})

    def test_webhook_moves_a_really_submitted_request_pending_signed_executed(self):
        req = self._make_really_submitted_request(self._create_supplier("Hook"))

        req.update_status_from_webhook("Signed")
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

        req.update_status_from_webhook("Executed")
        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Executed")
        self.assertTrue(row.payment_entry, "the Payment Entry must be written back on the submitted row")
        self.assertEqual([e.name for e in self._entries_for(req)], [row.payment_entry], "exactly one PE")

    def test_refresh_status_moves_a_really_submitted_request_pending_signed_executed(self):
        req = self._make_really_submitted_request(self._create_supplier("Poll"))

        with patch(PAY_CLIENT_PATH, return_value=_read_client("signed")):
            self.assertEqual(req.refresh_status()["status"], "Signed")
        with patch(PAY_CLIENT_PATH, return_value=_read_client("executed")):
            self.assertEqual(req.refresh_status()["status"], "Executed")

        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Executed")
        self.assertEqual([e.name for e in self._entries_for(req)], [row.payment_entry], "exactly one PE")

    def test_fields_that_are_not_allowed_on_submit_stay_refused(self):
        """Control: the change is not 'everything is editable after submit'."""
        req = self._make_really_submitted_request(self._create_supplier("Ctl"))
        req.amount = 1.0
        with self.assertRaises(frappe.UpdateAfterSubmitError) as ctx:
            req.save()
        self.assertIn("Amount", str(ctx.exception))
        self.assertEqual(flt(frappe.db.get_value("Ponto Payment Request", req.name, "amount")), 42.0)

    def test_cancelling_a_really_submitted_request_still_works(self):
        """Cancel is not an update-after-submit and must keep working.

        Not asserted: ``status == "Cancelled"`` afterwards. ``on_cancel`` sets it in memory
        only, after docstatus 2 was written, so the row keeps "Pending" -- measured on
        develop and unchanged here; filed separately.
        """
        req = self._make_really_submitted_request(self._create_supplier("Cxl"))
        with patch(PAY_CLIENT_PATH, return_value=SimpleNamespace(delete_payment=lambda **kw: None)):
            req.cancel()
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "docstatus"), 2)

    # ---- #1920: the system writers must work as the webhook user, not only as Administrator ----

    def _fresh_request(self, req):
        return frappe.get_doc("Ponto Payment Request", req.name)

    def test_webhook_user_moves_a_submitted_request_through_the_webhook_method(self):
        req = self._make_really_submitted_request(self._create_supplier("WhUser"))
        user = self._make_ponto_user(WEBHOOK_ROLE)

        with self.as_user(user):
            self._fresh_request(req).update_status_from_webhook("Signed")
            self._fresh_request(req).update_status_from_webhook("Executed")

        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Executed")
        self.assertEqual([e.name for e in self._entries_for(req)], [row.payment_entry], "exactly one PE")

    # ---- #1907 ruling A: only system code may change the money-path fields after submit ----

    def test_accounts_manager_cannot_edit_status_or_payment_entry_by_hand(self):
        req = self._make_really_submitted_request(self._create_supplier("AMan"))
        other = self._make_really_submitted_request(self._create_supplier("AManOther"))
        other.update_status_from_webhook("Executed")  # a real PE, booked by the system path
        real_pe = frappe.db.get_value("Ponto Payment Request", other.name, "payment_entry")
        self.assertTrue(real_pe)
        user = self._make_ponto_user("Accounts Manager")

        with self.as_user(user):
            for fieldname, value, label in (
                ("status", "Executed", "Status"),
                ("payment_entry", real_pe, "Payment Entry"),
            ):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    frappe.client.set_value("Ponto Payment Request", req.name, fieldname, value)
                self.assertIn(label, str(ctx.exception))

            control = self._fresh_request(req)  # control: a save that changes nothing guarded is not refused
            control.save()

        row = frappe.db.get_value(
            "Ponto Payment Request", req.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual((row.status, row.payment_entry), ("Pending", None))

    # ---- #1848: Ponto says Executed for a row cancelled here ----

    def _cancelled_request(self, name_hint):
        req = self._make_really_submitted_request(self._create_supplier(name_hint))
        with patch(PAY_CLIENT_PATH, return_value=SimpleNamespace(delete_payment=lambda **kw: None)):
            req.cancel()
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "docstatus"), 2)
        return req

    def test_executed_on_a_cancelled_request_alerts_once_and_leaves_it_alone(self):
        req = self._cancelled_request("CxlExec")
        self.expectErrorLog(ALERT_TITLE)
        user = self._make_ponto_user(WEBHOOK_ROLE)
        fields = ["docstatus", "status", "payment_entry", "modified"]
        before = frappe.db.get_value("Ponto Payment Request", req.name, fields, as_dict=True)

        with self.as_user(user):
            self._fresh_request(req).update_status_from_webhook("Executed")
            after_first = len(self._alerts_for("Ponto Payment Request", req.name)[0])
            self._fresh_request(req).update_status_from_webhook("Executed")  # webhook redelivery

        # The poll tick: the scheduler runs refresh_status as Administrator (it is high_security_api,
        # which refuses the webhook user).
        with patch(PAY_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_request(req).refresh_status()

        after = frappe.db.get_value("Ponto Payment Request", req.name, fields, as_dict=True)
        self.assertEqual(after, before, "the cancelled document must not change")
        self.assertFalse(self._entries_for(req), "no Payment Entry may be booked for a cancelled row")
        todos, logs = self._alerts_for("Ponto Payment Request", req.name)
        self.assertEqual((after_first, len(todos), len(logs)), (1, 1, 1))
        self.assertIn(
            str(flt(req.amount)), todos and frappe.db.get_value("ToDo", todos[0].name, "description")
        )
        self.assertIn(req.ponto_payment_id, frappe.db.get_value("ToDo", todos[0].name, "description"))

    def test_the_webhook_handler_reports_a_cancelled_request_as_refused(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        req = self._cancelled_request("CxlHandler")
        self.expectErrorLog(ALERT_TITLE)
        event = {"data": {"id": req.ponto_payment_id, "attributes": {"status": "executed"}}}

        result = handle_payment_request_closed(event)

        self.assertEqual([r["name"] for r in result["refused_requests"]], [req.name])
        self.assertFalse(result["updated_requests"])
        self.assertEqual(len(self._alerts_for("Ponto Payment Request", req.name)[0]), 1)

    def test_executed_on_a_live_request_raises_no_cancelled_row_alert(self):
        """Control: the alert is for docstatus 2 only."""
        req = self._make_really_submitted_request(self._create_supplier("LiveExec"))
        req.update_status_from_webhook("Executed")
        self.assertEqual(self._alerts_for("Ponto Payment Request", req.name), ([], []))


class TestSubmittedPontoPaymentLink(_PontoUsers, EnhancedTestCase):
    """A Link that went through the real submit() lifecycle."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.ponto_account = _ensure_ponto_clearing_account(cls.company)  # commits itself

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.sepa = SEPATestDataFactory(
            seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True
        )

    def _member_and_invoice(self, amount=30.0):
        member = self.sepa.create_test_member(first_name="Ponto1907")
        if not member.customer:
            customer = self.sepa.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
            member.reload()
        invoice = self.sepa.create_test_sales_invoice(
            customer=member.customer,
            grand_total=amount,
            status="Unpaid",
            company=self.company,
            posting_date=today(),
            due_date=today(),
            is_membership_invoice=1,
            submit=True,
        )
        return member, invoice

    def _make_submitted_link(self, member, invoice=None, amount=30.0):
        link = frappe.new_doc("Ponto Payment Link")
        link.payment_type = "One-Time"
        link.amount = amount
        link.currency = "EUR"
        link.description = "Contributie 2026"
        link.creditor_name = "Vereniging Test"
        link.creditor_iban = "NL91ABNA0417164300"
        link.member = member.name
        if invoice:
            link.sales_invoice = invoice.name
        link.insert(ignore_permissions=True)
        self.track_doc("Ponto Payment Link", link.name)
        with patch(
            LINK_CLIENT_PATH, return_value=_create_client(f"ponto_req_{frappe.generate_hash(length=8)}")
        ):
            link.submit()
        self.assertEqual((link.docstatus, link.status), (1, "Pending Authorization"))
        return link

    def _read_link(self, link, *fields):
        return frappe.db.get_value("Ponto Payment Link", link.name, list(fields), as_dict=True)

    def test_webhook_authorizes_with_debtor_then_executes_with_invoice_and_payment_entry(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        debtor = {"name": "Jan Jansen", "iban": "NL02ABNA0123456789", "bank": "ABN AMRO"}

        link.update_status_from_webhook("Authorized", debtor)
        row = self._read_link(link, "status", "debtor_name", "debtor_iban", "debtor_bank")
        self.assertEqual(row.status, "Authorized")
        self.assertEqual((row.debtor_name, row.debtor_iban, row.debtor_bank), tuple(debtor.values()))

        link.update_status_from_webhook("Executed")
        row = self._read_link(link, "status", "sales_invoice", "payment_entry")
        self.assertEqual(row.status, "Executed")
        self.assertEqual(row.sales_invoice, invoice.name)
        self.assertTrue(row.payment_entry, "the Payment Entry must be written back on the submitted row")
        entries = frappe.get_all(
            "Payment Entry", filters={"reference_no": link.ponto_request_id, "docstatus": 1}
        )
        self.assertEqual([e.name for e in entries], [row.payment_entry], "exactly one PE")

    def test_refresh_status_writes_debtor_details_on_a_submitted_link(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        state = dict(debtor_name="Jan Jansen", debtor_iban="NL02ABNA0123456789", debtor_bank="ABN AMRO")

        with patch(LINK_CLIENT_PATH, return_value=_read_client("signed", **state)):
            self.assertEqual(link.refresh_status()["status"], "Authorized")

        row = self._read_link(link, "status", "debtor_name", "debtor_iban", "debtor_bank")
        self.assertEqual(
            (row.status, row.debtor_name, row.debtor_iban, row.debtor_bank),
            ("Authorized", *state.values()),
        )

    def test_refresh_status_executes_and_links_the_payment_entry(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)

        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed")):
            self.assertEqual(link.refresh_status()["status"], "Executed")

        row = self._read_link(link, "status", "payment_entry")
        self.assertEqual(row.status, "Executed")
        entries = frappe.get_all(
            "Payment Entry", filters={"reference_no": link.ponto_request_id, "docstatus": 1}
        )
        self.assertEqual([e.name for e in entries], [row.payment_entry], "exactly one PE")

    def test_executed_job_matches_the_invoice_and_writes_both_links(self):
        """The webhook's async path: the invoice matcher writes ``sales_invoice`` AFTER submit."""
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import _process_executed_payment

        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member)  # no sales_invoice yet
        link.update_status_from_webhook("Executed")

        result = _process_executed_payment(frappe.get_doc("Ponto Payment Link", link.name))

        row = self._read_link(link, "sales_invoice", "payment_entry")
        self.assertEqual(result["sales_invoice"], invoice.name)
        self.assertEqual(row.sales_invoice, invoice.name)
        self.assertTrue(row.payment_entry)

    def test_fields_that_are_not_allowed_on_submit_stay_refused(self):
        """Control: ``amount`` is not marked ``allow_on_submit``, so it stays refused."""
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        link.amount = 1.0
        with self.assertRaises(frappe.UpdateAfterSubmitError) as ctx:
            link.save()
        self.assertIn("Amount", str(ctx.exception))
        self.assertEqual(flt(self._read_link(link, "amount").amount), 30.0)

    # ---- #1920: the system writers must work as the webhook user, not only as Administrator ----

    def _fresh_link(self, link):
        return frappe.get_doc("Ponto Payment Link", link.name)

    def test_webhook_user_authorizes_a_submitted_link_with_debtor_details(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        user = self._make_ponto_user(WEBHOOK_ROLE)
        debtor = {"name": "Jan Jansen", "iban": "NL02ABNA0123456789", "bank": "ABN AMRO"}

        with self.as_user(user):
            self._fresh_link(link).update_status_from_webhook("Authorized", debtor)

        row = self._read_link(link, "status", "debtor_name", "debtor_iban", "debtor_bank")
        self.assertEqual(
            (row.status, row.debtor_name, row.debtor_iban, row.debtor_bank),
            ("Authorized", *debtor.values()),
        )

    # ---- #1907 ruling A ----

    def test_accounts_manager_cannot_edit_the_system_fields_by_hand(self):
        member, invoice = self._member_and_invoice()
        _, other_invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        link.update_status_from_webhook("Authorized", {"name": "Jan", "iban": "NL02ABNA0123456789"})
        user = self._make_ponto_user("Accounts Manager")

        with self.as_user(user):
            for fieldname, value, label in (
                ("debtor_iban", "NL91ABNA0417164300", "Debtor IBAN"),
                ("sales_invoice", other_invoice.name, "Sales Invoice"),
                ("status", "Executed", "Status"),
            ):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    frappe.client.set_value("Ponto Payment Link", link.name, fieldname, value)
                self.assertIn(label, str(ctx.exception))

            self._fresh_link(link).save()  # control: a save that changes nothing guarded is not refused

        row = self._read_link(link, "status", "debtor_iban", "sales_invoice")
        self.assertEqual(
            (row.status, row.debtor_iban, row.sales_invoice),
            ("Authorized", "NL02ABNA0123456789", invoice.name),
        )

    # ---- #1848 ----

    def _cancelled_link(self, member, invoice=None):
        link = self._make_submitted_link(member, invoice)
        with patch(
            LINK_CLIENT_PATH, return_value=SimpleNamespace(delete_payment_request=lambda *a, **k: None)
        ):
            link.cancel()
        self.assertEqual(self._read_link(link, "docstatus").docstatus, 2)
        return link

    def test_executed_on_a_cancelled_link_alerts_once_and_leaves_it_alone(self):
        member, invoice = self._member_and_invoice()
        link = self._cancelled_link(member, invoice)
        self.expectErrorLog(ALERT_TITLE)
        user = self._make_ponto_user(WEBHOOK_ROLE)
        fields = ("docstatus", "status", "payment_entry", "sales_invoice", "modified")
        before = self._read_link(link, *fields)

        with self.as_user(user):
            self._fresh_link(link).update_status_from_webhook("Executed", {"name": "Jan"})
            after_first = len(self._alerts_for("Ponto Payment Link", link.name)[0])
            self._fresh_link(link).update_status_from_webhook("Executed")  # webhook redelivery

        # The poll tick runs as the scheduler's user (refresh_status is high_security_api).
        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_link(link).refresh_status()

        self.assertEqual(self._read_link(link, *fields), before, "the cancelled document must not change")
        self.assertFalse(frappe.get_all("Payment Entry", filters={"reference_no": link.ponto_request_id}))
        todos, logs = self._alerts_for("Ponto Payment Link", link.name)
        self.assertEqual((after_first, len(todos), len(logs)), (1, 1, 1))
        text = frappe.db.get_value("ToDo", todos[0].name, "description")
        self.assertIn(f"{flt(link.amount):,.2f}", text)
        self.assertIn(link.ponto_request_id, text)

    def test_the_webhook_handler_reports_a_cancelled_link_as_refused(self):
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_initiation_closed,
        )

        member, _invoice = self._member_and_invoice()
        link = self._cancelled_link(member)
        self.expectErrorLog(ALERT_TITLE)
        event = {"data": {"id": link.ponto_request_id, "attributes": {"status": "executed"}}}

        result = handle_payment_initiation_closed(event)

        self.assertEqual([r["name"] for r in result["refused_links"]], [link.name])
        self.assertFalse(result["updated_links"])
        self.assertEqual(len(self._alerts_for("Ponto Payment Link", link.name)[0]), 1)

    # ---- README rule 21: a real WSGI webhook, as Guest, read back on a fresh connection ----

    def _create_committed_webhook_state(self):
        """Commit what a SEPARATE process must see: the settings that let an unsigned webhook in, and the rows."""
        self._wsgi_backup = SingletonBackup("Ponto Settings", "Verenigingen Payments Settings")
        self._wsgi_backup.backup()
        self.addCleanup(self._cleanup_committed_webhook_state)
        frappe.db.set_single_value("Ponto Settings", {"enable_webhooks": 1, "require_webhook_signature": 0})
        frappe.db.set_single_value(
            "Verenigingen Payments Settings", "webhook_user", self._make_ponto_user(WEBHOOK_ROLE)
        )
        frappe.db.commit()

    def _cleanup_committed_webhook_state(self):
        self._wsgi_backup.restore()
        frappe.db.commit()

    def test_real_wsgi_webhook_authorizes_a_submitted_link_with_debtor_details(self):
        from frappe.utils import get_bench_path

        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        self._create_committed_webhook_state()
        payload = {
            "data": {
                "type": "pontoConnect.paymentInitiationRequest.statusUpdated",
                "id": link.ponto_request_id,
                "attributes": {
                    "status": "signed",
                    "debtorName": "Jan Jansen",
                    "debtorAccountReference": "NL02ABNA0123456789",
                    "debtorAgent": "ABN AMRO",
                },
            }
        }
        site = frappe.local.site
        script = textwrap.dedent(f"""
            import json
            import frappe

            frappe.init(site={site!r})
            frappe.connect()
            frappe.clear_cache()
            frappe.destroy()

            import frappe.app
            from werkzeug.test import Client

            client = Client(frappe.app.application)
            resp = client.post(
                "/api/method/verenigingen.verenigingen_payments.ponto.api.webhook.handle_ponto_webhook",
                data={json.dumps(payload)!r},
                content_type="application/json",
                headers={{"X-Frappe-Site-Name": {site!r}}},
            )

            frappe.init(site={site!r})
            frappe.connect()
            row = frappe.db.get_value(
                "Ponto Payment Link",
                {link.name!r},
                ["status", "docstatus", "debtor_name", "debtor_iban", "debtor_bank"],
                as_dict=True,
            )
            print(json.dumps({{"http": resp.status_code, "row": row}}, default=str))
            """)

        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=f"{get_bench_path()}/sites",
            capture_output=True,
            text=True,
            timeout=120,
        )

        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        out = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(out["http"], 200, out)
        self.assertEqual(
            out["row"],
            {
                "status": "Authorized",
                "docstatus": 1,
                "debtor_name": "Jan Jansen",
                "debtor_iban": "NL02ABNA0123456789",
                "debtor_bank": "ABN AMRO",
            },
        )
