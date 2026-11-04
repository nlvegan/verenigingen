# -*- coding: utf-8 -*-
"""
#1900 B1: two staff retrying the same failed approval invoice AT THE SAME TIME must create ONE invoice and
send ONE mail, and the loser must be refused.

A real two-connection test: each worker thread has its own ``frappe.init`` + connection (Frappe's session
is thread-local). Worker T1 sleeps inside the invoice creation while it holds the retry lock; T2
starts 1.5 s later and has to wait for it. A state check done as a plain read under REPEATABLE READ would
see the snapshot from before T1 committed, and T2 would create a second invoice.

The data has to be COMMITTED for the workers' connections to see it, so the fixture commits inside
``_create_*`` / ``_cleanup_*`` helpers (the sanctioned shape for a fixture commit) and removes what it
committed afterwards. PROBE SHORTCUT, stated: invoicing is broken for the approval by pointing Verenigingen
Settings at a company that does not exist, as test_approval_invoice_period does.

BENCH NOTE: the committed approval enqueues the applicant's account creation. On this bench the RQ workers
then pick it up and may create a User after teardown; CI has no workers, so nothing of the kind happens there.
"""

import threading
import time
from unittest.mock import patch

import frappe

from verenigingen.api.membership_application_review import approve_application, retry_application_invoice
from verenigingen.services.communication.email_service import EmailService
from verenigingen.services.member.approval import application_payments
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.setup import ensure_member_test_masters

HOLD_SECONDS = 3.0
SECOND_STARTS_AFTER = 1.5


class TestConcurrentInvoiceRetry(ApprovalCase):
    def setUp(self):
        super().setUp()
        ensure_member_test_masters()
        self.site = frappe.local.site
        self.committed_members = []

    def tearDown(self):
        self._cleanup_committed_rows()
        super().tearDown()

    def _create_committed_failed_approval(self):
        """(application, member) approved with a failed invoice, invoicing fixed again, all committed."""
        application = self._stage_and_confirm()
        original = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 1900")
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        try:
            response = self._approve_as(
                application,
                membership_type=self.membership_type.name,
                chapter=self.chapter.name,
                create_invoice=True,
            )
        finally:
            frappe.db.set_single_value("Verenigingen Settings", "company", original)
        self.assertTrue(response["invoice_failed"], response)
        self.committed_members.append(response["member"])
        frappe.db.commit()
        return application, response["member"]

    def _cleanup_committed_rows(self):
        """Remove the Sales Invoices the workers committed (cancelled first), then the Member."""
        for member in self.committed_members:
            customer = frappe.db.get_value("Member", member, "customer")
            for name in frappe.get_all("Sales Invoice", {"customer": customer}, pluck="name") if customer else []:
                try:
                    doc = frappe.get_doc("Sales Invoice", name)
                    if doc.docstatus == 1:
                        doc.cancel()
                    frappe.delete_doc("Sales Invoice", name, force=True)
                except Exception as error:  # swallow-ok: best-effort teardown of a committed fixture
                    print(f"cleanup of {name} failed: {error}")
            try:
                if frappe.db.exists("Member", member):
                    frappe.delete_doc("Member", member, force=True)
            except Exception as error:  # swallow-ok: best-effort teardown of a committed fixture
                print(f"cleanup of {member} failed: {error}")
        frappe.db.commit()

    def test_two_retries_at_once_create_one_invoice_and_one_mail(self):
        application, member = self._create_committed_failed_approval()
        customer = frappe.db.get_value("Member", member, "customer")
        admin = self.admin_user.email
        site = self.site
        mails, outcomes, held = [], {}, []
        real_secure = application_payments.secure_document_operation
        real_send = EmailService._send_email_internal

        def _create_after_midop_commit(*args, **kwargs):
            if threading.current_thread().name == "T1" and not held:
                held.append(True)
                # PROBE SHORTCUT, stated: the services commit mid-operation (see approve_application's
                # docstring), which releases any row lock T1 took. A commit here stands in for that, so
                # only an advisory lock (GET_LOCK, which a commit does not release) still holds T2 back.
                frappe.db.commit()
                time.sleep(HOLD_SECONDS)  # T1 holds the retry lock while T2 arrives
            return real_secure(*args, **kwargs)

        def spy_send(service, *args, **kwargs):
            mails.append(kwargs)
            return real_send(service, *args, **kwargs)

        def _create_request_worker(name, delay):
            time.sleep(delay)
            frappe.init(site=site, force=True)
            frappe.connect()
            frappe.set_user(admin)
            try:
                outcomes[name] = retry_application_invoice(application)
                frappe.db.commit()
            except Exception as error:
                frappe.db.rollback()
                outcomes[name] = error
            finally:
                frappe.destroy()

        # Mock justified: spy on the mail boundary; and a delay (plus a commit) at the secure-operation wrapper
        # the invoice insert goes through, which still runs the real operation
        with patch.object(EmailService, "_send_email_internal", spy_send), patch.object(
            application_payments, "secure_document_operation", _create_after_midop_commit
        ):
            threads = [
                threading.Thread(target=_create_request_worker, args=("first", 0), name="T1"),
                threading.Thread(target=_create_request_worker, args=("second", SECOND_STARTS_AFTER), name="T2"),
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=90)

        frappe.db.rollback()  # end this connection's old snapshot before reading what the workers committed
        invoices = frappe.get_all("Sales Invoice", {"customer": customer, "docstatus": 1}, pluck="name")
        applicant_mails = [m for m in mails if m.get("recipients") and self.email in m["recipients"]]
        self.assertEqual(len(invoices), 1, f"exactly one invoice. outcomes: {outcomes}")
        self.assertEqual(len(applicant_mails), 1, f"exactly one mail. outcomes: {outcomes}")
        self.assertIsInstance(outcomes["second"], frappe.ValidationError, f"the loser is refused: {outcomes}")
        self.assertTrue(outcomes["first"]["invoice"], outcomes)
