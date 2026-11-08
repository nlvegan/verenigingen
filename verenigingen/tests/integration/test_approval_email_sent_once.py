# -*- coding: utf-8 -*-
"""
#2041: an applicant is mailed the approval mail ONCE, however the Account Creation Request (ACR) finishes.

Driven through the real flow: submit_application -> confirm -> approve_application (as the least-privileged
real caller, a chapter board member, and as admin) -> the real account-creation pipeline
(``process_account_creation_request``, run inline as the queued job would) -> and, for the desk-edit path,
a real ``doc.save()`` of the ACR into Completed. The mail boundary is spied, not stubbed (as
test_approval_without_invoice). Stand-ins, stated: the queued job is run inline instead of by an RQ worker;
the desk-edit test flips an already-Completed ACR back to Processing with a db write and saves it Completed
again, to reach ``on_update`` the way a desk edit would.
"""

from unittest.mock import patch

import frappe

from verenigingen.api.membership_application_review import (
    retry_application_invoice,
    update_payment_history_for_invoice,
)
from verenigingen.services.communication.email_service import EmailService
from verenigingen.services.member.account.account_creation_api import process_account_creation_request
from verenigingen.tests.integration import test_approval_without_invoice as without_invoice
from verenigingen.tests.integration.test_application_record_approval import ApprovalCase
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    ensure_outgoing_email_account,
)


class TestApprovalMailSentOnce(ApprovalCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        without_invoice.TestApprovalWithoutInvoice._require_approval_notification_enabled(self)
        self.mails = []

    def _spy(self):
        # The key's stock 60-minute cooldown (a per-recipient Redis key) would hide a second send for an hour,
        # so it is cleared before every action: a duplicate must be prevented by the code, not by a timer.
        clear_email_cooldowns()
        real = EmailService._send_email_internal
        mails = self.mails

        def spy(service, *args, **kw):
            result = real(service, *args, **kw)
            mails.append((kw, result))
            return result

        # Mock justified: spy on the mail boundary; the real service (and template render) still runs
        return patch.object(EmailService, "_send_email_internal", spy)

    def _applicant_mails(self):
        return [kw for kw, _ in self.mails if self.email in (kw.get("recipients") or [])]

    def _handed_to_frappe_sendmail(self):
        """What reached `frappe.sendmail` for this applicant. The harness captures that call, so no Email Queue
        row is ever written in a test run; this is the nearest observable to the queue."""
        # Only mail about the Member: the confirmation mail (an Application) and Frappe's own welcome mail
        # (no reference) are not the approval mail.
        return [
            m
            for m in self.captured_emails
            if self.email in (m["recipients"] or []) and m["kwargs"].get("reference_doctype") == "Member"
        ]

    def _approve_with_mail(self, application, user=None, **kwargs):
        kwargs.setdefault("membership_type", self.membership_type.name)
        kwargs.setdefault("chapter", self.chapter.name)
        with self._spy():
            return self._approve_as(application, user=user, send_mail=True, **kwargs)

    def _acr_of(self, member):
        names = frappe.get_all(
            "Account Creation Request", {"source_record": member, "request_type": "Member"}, pluck="name"
        )
        self.assertEqual(len(names), 1, "approval queued exactly one ACR")
        self.track_doc("Account Creation Request", names[0])
        return names[0]

    def _run_payment_history_job(self, response):
        """The queued job approval enqueues (it is what puts the invoice into the member's payment history,
        which is where the ACR looks for it), run inline."""
        update_payment_history_for_invoice(response["member"], response["invoice"])

    def _run_pipeline(self, acr):
        # The job entry point sets process-wide flags a worker would drop with its process; restore them so
        # the next test's guest submit is not treated as an import.
        flags = ("in_background_job", "bulk_account_creation", "in_import")
        before = {flag: frappe.flags.get(flag) for flag in flags}
        self.addCleanup(lambda: [frappe.flags.update({flag: value}) for flag, value in before.items()])
        with self._spy():
            result = process_account_creation_request(acr)
        self.assertTrue(result["success"], result)
        self.assertEqual(frappe.db.get_value("Account Creation Request", acr, "status"), "Completed")

    def _complete_by_desk_save(self, acr):
        """A desk edit into Completed: the one path that reaches ACR.on_update (develop mailed from there)."""
        frappe.db.set_value("Account Creation Request", acr, "status", "Processing")
        doc = frappe.get_doc("Account Creation Request", acr)
        doc.status = "Completed"
        with self._spy(), self.as_user(self.admin_user.email):
            doc.save()

    def _assert_one_mail(self, why):
        """One mail reached the applicant, counted at the mail service AND at frappe.sendmail."""
        self.assertEqual(len(self._applicant_mails()), 1, why)
        self.assertEqual(len(self._handed_to_frappe_sendmail()), 1, f"{why} (frappe.sendmail)")

    def _finish_account_creation(self, response, invoiced=True):
        """The queued jobs run inline, then the ACR is completed the two ways it can be: the pipeline's own
        `mark_completed` (a db write) and a desk save into Completed (the only path that reaches `on_update`)."""
        acr = self._acr_of(response["member"])
        if invoiced:
            self._run_payment_history_job(response)
        self._run_pipeline(acr)
        self._complete_by_desk_save(acr)

    def test_board_member_approval_sends_one_mail_and_is_not_followed_by_a_second(self):
        """Least-privileged caller. A board member's approval is refused an ACR (ACR_QUEUE_REFUSED, #1930),
        so this proves the approval's own count; the ACR paths are driven as admin below."""
        board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        application = self._stage_and_confirm()
        response = self._approve_with_mail(application, user=board.user, create_invoice=True)
        self.assertTrue(response["invoice"], response)
        self._assert_one_mail("approval sent its mail")

    def test_invoiced_approval_then_account_creation_completes_sends_one_mail(self):
        application = self._stage_and_confirm()
        response = self._approve_with_mail(application, create_invoice=True)
        self.assertTrue(response["invoice"], response)
        self._assert_one_mail("control: approval sent its mail")

        self._finish_account_creation(response)

        self._assert_one_mail("completing the ACR sent no second approval mail")

    def test_approval_without_invoice_then_account_creation_completes_sends_one_mail(self):
        application = self._stage_and_confirm()
        response = self._approve_with_mail(application, create_invoice=False)
        self.assertFalse(response["invoice"], response)
        self._assert_one_mail("control: approval sent its mail without a link")

        self._finish_account_creation(response, invoiced=False)

        self._assert_one_mail("completing the ACR sent no second mail")

    def test_staff_retry_sends_the_held_mail_once_and_the_acr_adds_none(self):
        """The #1900 path: invoice failed -> mail held -> staff retry sends it WITH the link. The ACR completing
        afterwards (its payment history now holds the invoice) must not send it again."""
        application = self._stage_and_confirm()
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        frappe.db.set_single_value("Verenigingen Settings", "company", "No Such Company 2041")
        self.expectErrorLog(
            "Membership Invoice Creation Failed",
            "Membership Invoice Security",
            "BTW Tax Exemption Error",
            "Secure Operation Failed",
        )
        response = self._approve_with_mail(application, create_invoice=True)
        self.assertTrue(response["invoice_failed"], response)
        self.assertEqual(self._applicant_mails(), [], "control: the held mail has not gone out")
        frappe.db.set_single_value("Verenigingen Settings", "company", company)

        with self._spy(), self.as_user(self.admin_user.email):
            retried = retry_application_invoice(application)
        self.assertTrue(retried["invoice"], retried)
        self._assert_one_mail("the retry sent the held mail")

        self._finish_account_creation({"member": response["member"], "invoice": retried["invoice"]})

        self._assert_one_mail("completing the ACR sent no second copy of the held mail")
