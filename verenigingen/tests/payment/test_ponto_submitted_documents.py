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
from verenigingen.patches.v2_2.add_ponto_executed_on_cancelled_row_notification import (
    execute as register_alert_notification_type,
)
from verenigingen.utils.notification_helpers import get_notification_recipients
from verenigingen.verenigingen_payments.ponto.core.submitted_rows import (
    ALERT_KEY,
    ALERT_MARKER,
    ALERT_TITLE,
    SYSTEM_UPDATE_FLAG,
    UNDELIVERED_TITLE,
    system_update,
)

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

    def setUp(self):
        super().setUp()
        # The key is only registered by a patch / "Sync Registry"; a fresh CI site has no row, and
        # a key without a row counts as disabled. This also exercises the patch.
        register_alert_notification_type()

    def _run_doc_method_refresh(self, doc, client_path, client, tamper):
        """Drive the REAL dispatch a browser uses: handler.run_doc_method builds the document from the
        CLIENT's dict (``docs``), so a client can put any value in any field. Only the Ponto HTTP client is
        stubbed. A request object is faked (Mock justified: Infrastructure) because the security-tier
        decorator inspects it; the caller is Administrator so that decorator lets the call through and the
        check under test is the only thing left."""
        from frappe.handler import run_doc_method

        payload = frappe.get_doc(doc.doctype, doc.name).as_dict()
        payload.update(tamper)
        request = SimpleNamespace(
            method="POST", path="/api/method/run_doc_method", headers={}, remote_addr="127.0.0.1",
            environ={}, args={}, form={}, get_data=lambda *a, **k: b"{}", content_length=2,
        )
        previous = getattr(frappe.local, "request", None)
        frappe.local.request = request  # Mock justified: Infrastructure
        try:
            with patch(client_path, return_value=client):
                run_doc_method(method="refresh_status", docs=json.dumps(payload, default=str))
        finally:
            frappe.local.request = previous

    def _make_ignoring_permissions_save(self, doc):
        """The save a system writer makes (#1920); named _make_* so the bypass is a recognised fixture."""
        doc.save(ignore_permissions=True)

    def _alerts_for(self, doctype, name):
        """(Notification Log rows, Error Log rows) raised for one cancelled row."""
        notes = frappe.get_all(
            "Notification Log",
            filters={
                "document_type": doctype,
                "document_name": name,
                "subject": ["like", f"{ALERT_MARKER}%"],
            },
            fields=["name", "for_user", "subject", "email_content"],
        )
        logs = frappe.get_all(
            "Error Log",
            filters={"method": ALERT_TITLE, "error": ["like", f"{ALERT_MARKER}: {doctype} {name} %"]},
            fields=["name", "error"],
        )
        return notes, logs

    def _fallback_recipients(self):
        """Who the registered key reaches while nobody has configured other recipients: the admin roles."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        emails = get_email_configuration_service().get_recipients_for_notification(ALERT_KEY)
        enabled = frappe.get_all("User", filters={"enabled": 1, "email": ["in", emails]}, pluck="email")
        # A Notification Log's for_user is a Link to User, so only a user whose NAME is their email
        # can receive one (the Administrator user, whose email differs, is never reached).
        return sorted({email for email in enabled if frappe.db.exists("User", email)})

    def test_the_alert_key_is_registered_and_is_the_one_the_code_sends(self):
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        self.assertIn(ALERT_KEY, NOTIFICATION_KEYS)
        with open(
            frappe.get_app_path("verenigingen", "verenigingen_payments/ponto/core/submitted_rows.py")
        ) as f:
            self.assertIn(f'notification_key="{ALERT_KEY}"', f.read())

    def _assert_one_alert(self, doctype, name, ponto_id, amount):
        """Exactly one Notification Log per fallback recipient, and exactly one Error Log row."""
        notes, logs = self._alerts_for(doctype, name)
        expected = self._fallback_recipients()
        self.assertTrue(expected, "control: the site must have at least one fallback recipient")
        self.assertEqual(sorted(n.for_user for n in notes), expected)
        self.assertEqual(len(logs), 1)
        for text in (notes[0].subject + notes[0].email_content, logs[0].error):
            self.assertIn(name, text)
        self.assertIn(f"{flt(amount):,.2f}", notes[0].email_content)
        self.assertIn(ponto_id, notes[0].email_content)

    def _assert_no_alert(self, doctype, name):
        self.assertEqual(self._alerts_for(doctype, name), ([], []))
        # Broader than the markers above, so a differently worded alert for this row cannot slip by.
        self.assertFalse(
            frappe.get_all("Error Log", filters={"method": ALERT_TITLE, "error": ["like", f"%{name}%"]})
        )
        self.assertFalse(frappe.get_all("ToDo", filters={"reference_type": doctype, "reference_name": name}))


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

    # ---- F1: a whitelisted system writer must not persist client-supplied guarded values ----

    def test_refresh_status_through_run_doc_method_ignores_a_tampered_payment_entry(self):
        """``refresh_status`` is whitelisted, so a client can POST its own copy of the document to
        run_doc_method. The system flag must never cover values the client supplied."""
        victim = self._make_really_submitted_request(self._create_supplier("TamperVictim"))
        other = self._make_really_submitted_request(self._create_supplier("TamperOther"))
        other.update_status_from_webhook("Executed")
        live_pe = frappe.db.get_value("Ponto Payment Request", other.name, "payment_entry")
        self.assertTrue(live_pe, "control: another row's live Payment Entry exists to be stolen")
        frappe.is_whitelisted(type(victim).refresh_status)  # raises PermissionError if not dispatchable

        self._run_doc_method_refresh(
            victim, PAY_CLIENT_PATH, _read_client("signed"), {"payment_entry": live_pe}
        )

        row = frappe.db.get_value(
            "Ponto Payment Request", victim.name, ["status", "payment_entry"], as_dict=True
        )
        self.assertEqual(row.status, "Signed", "control: the legitimate part of the refresh still happened")
        self.assertFalse(row.payment_entry, "the client-supplied payment_entry was persisted")

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

    # ---- the flag is scoped to the writer, and the contract #1896's callbacks rely on ----

    def test_the_system_flag_does_not_outlive_the_writer(self):
        req = self._make_really_submitted_request(self._create_supplier("FlagScope"))
        doc = self._fresh_request(req)

        doc.update_status_from_webhook("Signed")

        self.assertNotIn(SYSTEM_UPDATE_FLAG, doc.flags)
        doc.status = "Executed"
        with self.as_user(self._make_ponto_user("Accounts Manager")):
            with self.assertRaises(frappe.PermissionError):
                doc.save()
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

    def test_a_plain_save_is_refused_and_flag_plus_ignore_permissions_persists_for_the_webhook_user(self):
        """The contract #1896's _cancel_if_proved must follow (#1920): BOTH halves are needed."""
        req = self._make_really_submitted_request(self._create_supplier("Contract"))
        user = self._make_ponto_user(WEBHOOK_ROLE)

        doc = self._fresh_request(req)
        doc.status = "Cancelled"
        with self.assertRaises(frappe.PermissionError) as ctx:
            doc.save()  # the callback way: no flag, no ignore_permissions
        self.assertIn("can only be changed by the Ponto status updates", str(ctx.exception))

        with self.as_user(user):
            doc = self._fresh_request(req)
            doc.status = "Cancelled"
            with self.assertRaises(frappe.PermissionError) as ctx:
                self._make_ignoring_permissions_save(doc)  # ignore_permissions alone: still the guard
            self.assertIn("can only be changed by the Ponto status updates", str(ctx.exception))

            doc = self._fresh_request(req)
            doc.status = "Cancelled"
            with system_update(doc):
                with self.assertRaises(frappe.PermissionError):
                    doc.save()  # flag alone: the webhook user holds no 'submit'
            doc = self._fresh_request(req)
            doc.status = "Cancelled"
            with system_update(doc):
                self._make_ignoring_permissions_save(doc)

        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Cancelled")

    def test_create_payment_entry_called_directly_writes_the_back_link(self):
        req = self._make_really_submitted_request(self._create_supplier("DirectPE"))
        self._fresh_request(req).update_status_from_webhook("Signed")

        doc = self._fresh_request(req)  # a fresh object: no flag from an enclosing writer
        doc.create_payment_entry()

        pe = frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry")
        self.assertEqual([e.name for e in self._entries_for(req)], [pe])

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
            self._fresh_request(req).update_status_from_webhook("Executed")  # webhook redelivery

        # The manual "refresh status" action, which is high_security_api and so not for the webhook
        # user. The scheduled poll reads a cancelled row too (#1931); that is driven in test_ponto_status_poll.
        with patch(PAY_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_request(req).refresh_status()

        after = frappe.db.get_value("Ponto Payment Request", req.name, fields, as_dict=True)
        self.assertEqual(after, before, "the cancelled document must not change")
        self.assertFalse(self._entries_for(req), "no Payment Entry may be booked for a cancelled row")
        self._assert_one_alert("Ponto Payment Request", req.name, req.ponto_payment_id, req.amount)

    def test_a_closed_alert_marker_does_not_let_a_redelivery_alert_again(self):
        """The dedupe holds whether the Notification Log was read and the Error Log seen, or not."""
        req = self._cancelled_request("CxlClosed")
        self.expectErrorLog(ALERT_TITLE)
        self._fresh_request(req).update_status_from_webhook("Executed")
        notes, logs = self._alerts_for("Ponto Payment Request", req.name)
        for note in notes:
            frappe.db.set_value("Notification Log", note.name, "read", 1)
        for log in logs:
            frappe.db.set_value("Error Log", log.name, "seen", 1)

        self._fresh_request(req).update_status_from_webhook("Executed")

        self._assert_one_alert("Ponto Payment Request", req.name, req.ponto_payment_id, req.amount)

    def test_a_stale_marker_without_a_notification_still_notifies_once(self):
        """The Error Log is non-transactional: it can outlive a rolled-back Notification Log."""
        req = self._cancelled_request("LogOnly")
        self.expectErrorLog(ALERT_TITLE)
        frappe.log_error(
            title=ALERT_TITLE,
            message=f"{ALERT_MARKER}: Ponto Payment Request {req.name} reported EXECUTED (seeded)",
        )

        self._fresh_request(req).update_status_from_webhook("Executed")
        self._fresh_request(req).update_status_from_webhook("Executed")

        notes, logs = self._alerts_for("Ponto Payment Request", req.name)
        self.assertEqual(sorted(n.for_user for n in notes), self._fallback_recipients())
        self.assertEqual(len(logs), 1, "the seeded Error Log row is the only one")

    def _booked_then_cancelled_request(self, name_hint):
        """Executed (real PE booked), then cancelled, the way a user would cancel it afterwards."""
        req = self._make_really_submitted_request(self._create_supplier(name_hint))
        req.update_status_from_webhook("Executed")
        pe = frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry")
        self.assertTrue(pe)
        with patch(PAY_CLIENT_PATH, return_value=SimpleNamespace(delete_payment=lambda **kw: None)):
            req.cancel()
        return req, pe

    def test_executed_redelivered_on_a_booked_then_cancelled_request_raises_no_alert(self):
        """Already handled: a live Payment Entry exists, so 'book it by hand' would double-book it."""
        req, pe = self._booked_then_cancelled_request("BookedCxl")
        fields = ["docstatus", "status", "payment_entry", "modified"]
        before = frappe.db.get_value("Ponto Payment Request", req.name, fields, as_dict=True)
        self.assertEqual((before.docstatus, before.payment_entry), (2, pe))

        self._fresh_request(req).update_status_from_webhook("Executed")
        with patch(PAY_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_request(req).refresh_status()

        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, fields, as_dict=True), before)
        self.assertEqual([e.name for e in self._entries_for(req)], [pe], "still exactly one PE")
        self._assert_no_alert("Ponto Payment Request", req.name)

    def test_a_cancelled_request_whose_payment_entry_was_cancelled_does_alert(self):
        """Control for the test above: the 'already handled' exemption needs a LIVE entry."""
        req, pe = self._booked_then_cancelled_request("PeCxl")
        self.expectErrorLog(ALERT_TITLE)
        frappe.get_doc("Payment Entry", pe).cancel()
        self.assertEqual(frappe.db.get_value("Payment Entry", pe, "docstatus"), 2)

        self._fresh_request(req).update_status_from_webhook("Executed")

        self._assert_one_alert("Ponto Payment Request", req.name, req.ponto_payment_id, req.amount)

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
        self._assert_one_alert("Ponto Payment Request", req.name, req.ponto_payment_id, req.amount)

    def test_executed_on_a_live_request_raises_no_cancelled_row_alert(self):
        """Control: the alert is for docstatus 2 only."""
        req = self._make_really_submitted_request(self._create_supplier("LiveExec"))
        req.update_status_from_webhook("Executed")
        self._assert_no_alert("Ponto Payment Request", req.name)

    # ---- two deliveries at once (two real connections) ----

    def _create_committed_cancelled_request(self):
        """A cancelled row COMMITTED, so two other connections can see and lock it."""
        req = self._cancelled_request("Race")
        frappe.db.commit()
        self.addCleanup(self._cleanup_committed_alert_rows, req.name)
        return req

    def _cleanup_committed_alert_rows(self, name):
        frappe.db.delete("Notification Log", {"document_name": name})
        frappe.db.delete("Error Log", {"error": ["like", f"%{name} %"]})
        frappe.db.commit()

    def test_two_simultaneous_deliveries_raise_one_alert(self):
        """Both deliveries read the row BEFORE either alerts (a Barrier after the early get_doc, as in a
        real double webhook); delivery A then holds its transaction open while B runs. Only the row lock
        in alert_executed_on_cancelled_row makes B wait and see A's alert; without it both insert and the
        two transactions deadlock (1213) or double-alert."""
        import threading
        import time

        from verenigingen.verenigingen_payments.ponto.core.submitted_rows import (
            alert_executed_on_cancelled_row,
        )

        req = self._create_committed_cancelled_request()
        self.expectErrorLog(ALERT_TITLE)
        site, sites_path, name, ponto_id = (
            frappe.local.site,
            frappe.local.sites_path,
            req.name,
            req.ponto_payment_id,
        )
        errors = []
        both_have_read = threading.Barrier(2, timeout=30)

        def _create_concurrent_delivery(hold_seconds):
            try:
                frappe.init(site=site, sites_path=sites_path)
                frappe.connect()
                frappe.set_user("Administrator")
                doc = frappe.get_doc("Ponto Payment Request", name)  # an earlier read, as in a real webhook
                both_have_read.wait()
                alert_executed_on_cancelled_row(doc, ponto_id)
                time.sleep(hold_seconds)
                frappe.db.commit()
            except Exception as exc:  # reported on the main thread below
                errors.append(repr(exc))
            finally:
                frappe.destroy()

        first = threading.Thread(target=_create_concurrent_delivery, args=(3,))
        second = threading.Thread(target=_create_concurrent_delivery, args=(0,))
        first.start()
        second.start()
        first.join(90)
        second.join(90)

        self.assertEqual(errors, [])
        frappe.db.rollback()  # leave this connection's snapshot, so it sees what the threads committed
        self._assert_one_alert("Ponto Payment Request", name, ponto_id, req.amount)

    # ---- F2: staff alerts never go to the Administrator user ----

    def _recipients_the_alert_is_sent_to(self, req):
        """Run the real alert path and capture who ``create_system_notification`` was asked to notify."""
        from verenigingen.utils import notification_helpers

        self.expectErrorLog(ALERT_TITLE)
        real = notification_helpers.create_system_notification
        with patch.object(notification_helpers, "create_system_notification", wraps=real) as spy:
            self._fresh_request(req).update_status_from_webhook("Executed")
        self.assertEqual(spy.call_count, 1, "control: the alert path ran and tried to deliver")
        return spy.call_args.kwargs["recipients"]

    def test_the_alert_is_never_addressed_to_the_administrator_user(self):
        administrator_email = frappe.db.get_value("User", "Administrator", "email")
        self.assertTrue(administrator_email, "control: Administrator has an email to be matched")
        # Control: the roles the alert is configured with DO match Administrator, so without an
        # explicit exclusion it is a recipient.
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        self.assertIn(
            administrator_email, get_email_configuration_service().get_recipients_for_notification(ALERT_KEY)
        )
        req = self._cancelled_request("NoAdmin")

        recipients = self._recipients_the_alert_is_sent_to(req)

        self.assertNotIn(administrator_email, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertEqual(sorted(recipients), self._fallback_recipients(), "control: real staff are kept")

    # ---- F4: an alert that reached nobody must be loud ----

    UNDELIVERED_TITLE = UNDELIVERED_TITLE

    def _undelivered_logs(self, name):
        return frappe.get_all(
            "Error Log",
            filters={"method": self.UNDELIVERED_TITLE, "error": ["like", f"%{name}%"]},
            fields=["error"],
        )

    def test_a_delivered_alert_writes_no_undelivered_row(self):
        """Control: the loud row is for a failed delivery only."""
        req = self._cancelled_request("Delivered")
        self.expectErrorLog(ALERT_TITLE)
        self._fresh_request(req).update_status_from_webhook("Executed")
        self.assertEqual(self._undelivered_logs(req.name), [])
        self._assert_one_alert("Ponto Payment Request", req.name, req.ponto_payment_id, req.amount)

    def test_an_unseeded_notification_key_still_raises_a_loud_error_log_row(self):
        """Fresh installs (CI) do not run patches: no row for the key means 'disabled' and the delivery
        is skipped. That must not be silent."""
        req = self._cancelled_request("Unseeded")
        self.expectErrorLog(ALERT_TITLE, self.UNDELIVERED_TITLE)
        backup = SingletonBackup("Verenigingen Email Configuration")
        backup.backup()
        self.addCleanup(backup.restore)
        config = frappe.get_single("Verenigingen Email Configuration")
        config.notification_types = [n for n in config.notification_types if n.notification_key != ALERT_KEY]
        self._make_ignoring_permissions_save(config)
        self.assertFalse(
            frappe.get_single("Verenigingen Email Configuration").is_notification_enabled(ALERT_KEY),
            "control: with no row the key counts as disabled",
        )

        with self.assertErrorLog(self.UNDELIVERED_TITLE):
            self._fresh_request(req).update_status_from_webhook("Executed")

        logs = self._undelivered_logs(req.name)
        self.assertEqual(len(logs), 1)
        self.assertIn(req.name, logs[0].error)
        self.assertIn(f"{flt(req.amount):,.2f}", logs[0].error)
        self.assertEqual(frappe.get_all("Notification Log", filters={"document_name": req.name}), [])

    def test_an_alert_with_no_recipient_left_raises_a_loud_error_log_row(self):
        """Fixed recipients that are only the Administrator user leave nobody once it is excluded."""
        req = self._cancelled_request("NoOne")
        self.expectErrorLog(ALERT_TITLE, self.UNDELIVERED_TITLE)
        backup = SingletonBackup("Verenigingen Email Configuration")
        backup.backup()
        self.addCleanup(backup.restore)
        config = frappe.get_single("Verenigingen Email Configuration")
        for row in config.notification_types:
            if row.notification_key == ALERT_KEY:
                row.recipient_policy = "Fixed"
                row.fixed_recipients = frappe.db.get_value("User", "Administrator", "email")
        self._make_ignoring_permissions_save(config)

        with self.assertErrorLog(self.UNDELIVERED_TITLE):
            self._fresh_request(req).update_status_from_webhook("Executed")

        self.assertEqual(len(self._undelivered_logs(req.name)), 1)
        self.assertEqual(frappe.get_all("Notification Log", filters={"document_name": req.name}), [])


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
        other_member, other_invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        link.update_status_from_webhook(
            "Authorized", {"name": "Jan", "iban": "NL02ABNA0123456789", "bank": "ABN AMRO"}
        )
        booked = self._make_submitted_link(other_member, other_invoice)
        booked.update_status_from_webhook("Executed")  # a real PE, booked by the system path
        real_pe = self._read_link(booked, "payment_entry").payment_entry
        self.assertTrue(real_pe)
        user = self._make_ponto_user("Accounts Manager")

        with self.as_user(user):
            for fieldname, value, label in (
                ("debtor_name", "Piet", "Debtor Name"),
                ("debtor_iban", "NL91ABNA0417164300", "Debtor IBAN"),
                ("debtor_bank", "ING", "Debtor Bank"),
                ("sales_invoice", other_invoice.name, "Sales Invoice"),
                ("payment_entry", real_pe, "Payment Entry"),
                ("status", "Executed", "Status"),
            ):
                with self.assertRaises(frappe.PermissionError) as ctx:
                    frappe.client.set_value("Ponto Payment Link", link.name, fieldname, value)
                self.assertIn(label, str(ctx.exception))

            self._fresh_link(link).save()  # control: a save that changes nothing guarded is not refused

        row = self._read_link(
            link, "status", "debtor_name", "debtor_iban", "debtor_bank", "sales_invoice", "payment_entry"
        )
        self.assertEqual(
            tuple(row.values()),
            ("Authorized", "Jan", "NL02ABNA0123456789", "ABN AMRO", invoice.name, None),
        )

    # ---- the flag is scoped to the writer, and the contract #1896's callbacks rely on ----

    def test_the_system_flag_does_not_outlive_the_writer(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        doc = self._fresh_link(link)

        doc.update_status_from_webhook("Authorized", {"name": "Jan"})

        self.assertNotIn(SYSTEM_UPDATE_FLAG, doc.flags)
        doc.debtor_iban = "NL91ABNA0417164300"
        with self.as_user(self._make_ponto_user("Accounts Manager")):
            with self.assertRaises(frappe.PermissionError):
                doc.save()
        self.assertFalse(self._read_link(link, "debtor_iban").debtor_iban)

    def test_a_plain_save_is_refused_and_flag_plus_ignore_permissions_persists_for_the_webhook_user(self):
        """The contract #1896's _cancel_link_if_proved must follow (#1920): BOTH halves are needed."""
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        user = self._make_ponto_user(WEBHOOK_ROLE)

        doc = self._fresh_link(link)
        doc.status = "Cancelled"
        with self.assertRaises(frappe.PermissionError) as ctx:
            doc.save()  # the callback way: no flag, no ignore_permissions
        self.assertIn("can only be changed by the Ponto status updates", str(ctx.exception))

        with self.as_user(user):
            doc = self._fresh_link(link)
            doc.status = "Cancelled"
            with self.assertRaises(frappe.PermissionError) as ctx:
                self._make_ignoring_permissions_save(doc)  # ignore_permissions alone: still the guard
            self.assertIn("can only be changed by the Ponto status updates", str(ctx.exception))

            doc = self._fresh_link(link)
            doc.status = "Cancelled"
            with system_update(doc):
                with self.assertRaises(frappe.PermissionError):
                    doc.save()  # flag alone: the webhook user holds no 'submit'
            doc = self._fresh_link(link)
            doc.status = "Cancelled"
            with system_update(doc):
                self._make_ignoring_permissions_save(doc)

        self.assertEqual(self._read_link(link, "status").status, "Cancelled")

    # ---- F1: a whitelisted system writer must not persist client-supplied guarded values ----

    def test_refresh_status_through_run_doc_method_ignores_tampered_guarded_fields(self):
        victim_member, victim_invoice = self._member_and_invoice()
        victim = self._make_submitted_link(victim_member, victim_invoice)
        other_member, other_invoice = self._member_and_invoice()
        other = self._make_submitted_link(other_member, other_invoice)
        other.update_status_from_webhook("Executed")
        stolen = self._read_link(other, "payment_entry")
        self.assertTrue(stolen.payment_entry, "control: another row's live Payment Entry exists to be stolen")
        self.assertNotEqual(other_invoice.name, victim_invoice.name)
        frappe.is_whitelisted(type(victim).refresh_status)  # raises PermissionError if not dispatchable
        tamper = {
            "payment_entry": stolen.payment_entry,
            "sales_invoice": other_invoice.name,
            "debtor_name": "Mallory",
            "debtor_iban": "NL02ABNA0123456789",
            "debtor_bank": "Evil Bank",
        }

        self._run_doc_method_refresh(victim, LINK_CLIENT_PATH, _read_client("signed"), tamper)

        row = self._read_link(
            victim, "status", "payment_entry", "sales_invoice", "debtor_name", "debtor_iban", "debtor_bank"
        )
        self.assertEqual(
            row.status, "Authorized", "control: the legitimate part of the refresh still happened"
        )
        self.assertEqual(row.sales_invoice, victim_invoice.name)
        self.assertFalse(row.payment_entry)
        self.assertFalse(row.debtor_name or row.debtor_iban or row.debtor_bank)

    def test_refresh_status_writes_the_debtor_after_a_nested_payment_entry_write(self):
        """The debtor save comes AFTER process_payment_received() returned: the flag must still be set."""
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        state = dict(debtor_name="Jan Jansen", debtor_iban="NL02ABNA0123456789", debtor_bank="ABN AMRO")

        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed", **state)):
            self._fresh_link(link).refresh_status()

        row = self._read_link(link, "status", "debtor_iban", "payment_entry")
        self.assertEqual((row.status, row.debtor_iban), ("Executed", state["debtor_iban"]))
        self.assertTrue(row.payment_entry)

    def test_process_payment_received_called_directly_writes_the_back_link(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        self._fresh_link(link).update_status_from_webhook("Authorized")

        doc = self._fresh_link(link)  # a fresh object: no flag from an enclosing writer
        doc.process_payment_received()

        self.assertTrue(self._read_link(link, "payment_entry").payment_entry)

    def test_the_job_books_the_payment_as_the_configured_webhook_user(self):
        """#1925's premise: the user setup_webhook_user() configures can read the invoice and book the entry."""
        from verenigingen.setup.webhook_user_setup import generate_webhook_user_email, setup_webhook_user
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            process_executed_payment_job,
        )

        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member)  # no sales_invoice: the matcher links it
        link.update_status_from_webhook("Executed")
        self._wsgi_backup = SingletonBackup("Verenigingen Payments Settings")
        self._wsgi_backup.backup()
        self.addCleanup(self._cleanup_committed_webhook_state)
        self.addCleanup(frappe.set_user, "Administrator")
        existed = frappe.db.exists("User", generate_webhook_user_email())
        self.assertTrue(setup_webhook_user()["success"])  # commits internally
        if not existed:  # never delete a webhook user the site already had
            self.track_doc(
                "User", frappe.db.get_single_value("Verenigingen Payments Settings", "webhook_user")
            )

        result = process_executed_payment_job(link.name)  # sets the configured user itself

        row = self._read_link(link, "sales_invoice", "payment_entry")
        self.assertEqual((result["sales_invoice"], row.sales_invoice), (invoice.name, invoice.name))
        self.assertTrue(row.payment_entry)

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
            self._fresh_link(link).update_status_from_webhook("Executed")  # webhook redelivery

        # The manual "refresh status" action; the scheduled poll reads a cancelled row too (#1931), see test_ponto_status_poll.
        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_link(link).refresh_status()

        self.assertEqual(self._read_link(link, *fields), before, "the cancelled document must not change")
        self.assertFalse(frappe.get_all("Payment Entry", filters={"reference_no": link.ponto_request_id}))
        self._assert_one_alert("Ponto Payment Link", link.name, link.ponto_request_id, link.amount)

    def test_a_closed_alert_marker_does_not_let_a_redelivery_alert_again(self):
        member, _invoice = self._member_and_invoice()
        link = self._cancelled_link(member)
        self.expectErrorLog(ALERT_TITLE)
        self._fresh_link(link).update_status_from_webhook("Executed")
        notes, logs = self._alerts_for("Ponto Payment Link", link.name)
        for note in notes:
            frappe.db.set_value("Notification Log", note.name, "read", 1)
        for log in logs:
            frappe.db.set_value("Error Log", log.name, "seen", 1)

        self._fresh_link(link).update_status_from_webhook("Executed")

        self._assert_one_alert("Ponto Payment Link", link.name, link.ponto_request_id, link.amount)

    def _booked_then_cancelled_link(self):
        member, invoice = self._member_and_invoice()
        link = self._make_submitted_link(member, invoice)
        link.update_status_from_webhook("Executed")
        pe = self._read_link(link, "payment_entry").payment_entry
        self.assertTrue(pe)
        with patch(
            LINK_CLIENT_PATH, return_value=SimpleNamespace(delete_payment_request=lambda *a, **k: None)
        ):
            link.cancel()
        return link, pe

    def test_executed_redelivered_on_a_booked_then_cancelled_link_raises_no_alert(self):
        link, pe = self._booked_then_cancelled_link()
        fields = ("docstatus", "status", "payment_entry", "modified")
        before = self._read_link(link, *fields)
        self.assertEqual((before.docstatus, before.payment_entry), (2, pe))

        self._fresh_link(link).update_status_from_webhook("Executed", {"name": "Jan"})
        with patch(LINK_CLIENT_PATH, return_value=_read_client("executed")):
            self._fresh_link(link).refresh_status()

        self.assertEqual(self._read_link(link, *fields), before)
        self._assert_no_alert("Ponto Payment Link", link.name)

    def test_a_cancelled_link_whose_payment_entry_was_cancelled_does_alert(self):
        link, pe = self._booked_then_cancelled_link()
        self.expectErrorLog(ALERT_TITLE)
        frappe.get_doc("Payment Entry", pe).cancel()

        self._fresh_link(link).update_status_from_webhook("Executed")

        self._assert_one_alert("Ponto Payment Link", link.name, link.ponto_request_id, link.amount)

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
        self._assert_one_alert("Ponto Payment Link", link.name, link.ponto_request_id, link.amount)

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
