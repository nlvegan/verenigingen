"""Typed text in these staff/member/donor mail bodies is HTML-escaped (#2307, sibling of #2214).

Each test drives the REAL sender and reads the Email Queue body it produced (``frappe.sendmail``
strips ``<script>`` but keeps benign markup, so a raw ``<i>``/``<a>`` tag in a body is live):

* payment reminder fallback HTML     ``send_payment_reminder_email`` (template missing)
* periodic donation renewal reminder ``send_renewal_reminders``
* expulsion governance mails (2)     ``ExpulsionReportEntry.notify_governance_team`` / ``send_reversal_notification``
* expense approval mail              ``notify_expense_approvers``
* SEPA batch validation alert        ``SEPAXMLAdapter._send_validation_alert``
* payment alert mails (3)            ``PaymentAlertService.send_{overpayment,payment_entry_failure,reconciliation}_alert``
* board-membership-ended message     ``VolunteerSyncService._notify_board_membership_change``

Every typed field of a mail is hostile in the same run, so escaping only some of them fails.

Probe shortcuts (declared, per the dispatch brief): Member/Employee/Donor name validators refuse or
re-fetch markup, so the hostile value is written with ``db.set_value`` (member first_name, employee_name,
agreement donor_name) or hand-assigned on an in-memory doc (expulsion entry, expense claim); the senders
themselves are unmodified. The board-membership message goes through ``notify_administrators``, which
delivers via a Notification Log row: that test reads the row's ``email_content`` (the body the mail is
rendered from) rather than an Email Queue row.

Run:
    bench --site test_site_7 run-tests --app verenigingen --module verenigingen.tests.test_mail_body_escaping_2307
"""

import email
from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.tests.fixtures.dutch_validation_helpers import generate_valid_bsn
from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.reminder_mail_state import clear_email_cooldowns, ensure_outgoing_email_account
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows

CONFIG = "Verenigingen Email Configuration"


def hostile(tag):
    """A typed value carrying benign (sanitiser-surviving) markup, and its escaped form."""
    raw = f"<i>{tag}</i>"
    return raw, f"&lt;i&gt;{tag}&lt;/i&gt;"


class MailBodyEscapingBase(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self.prior_user = frappe.session.user
        self.addCleanup(frappe.set_user, self.prior_user)
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        ensure_outgoing_email_account(self)
        ensure_notification_registry_rows()
        clear_email_cooldowns()
        frappe.db.set_single_value(CONFIG, "master_email_enabled", 1)
        self.token = frappe.generate_hash(length=6)
        self._baseline = {}
        # Mock justified: the SMTP transport. Email Queue rows are still written (and read below);
        # without this a later commit in the same process tries a real SMTP send for them.
        send = patch("frappe.email.doctype.email_queue.email_queue.EmailQueue.send")
        send.start()
        self.addCleanup(send.stop)

    def mark(self, recipient):
        """Ignore mails already queued to ``recipient`` (e.g. an activation mail sent by the fixture)."""
        self._baseline[recipient] = frappe.db.count("Email Queue Recipient", {"recipient": recipient})

    def key(self, key, policy="Fixed", **fields):
        _put_key_row(key, policy, cooldown_minutes=0, **fields)

    def html_to(self, recipient):
        """The HTML body of the single queued mail to ``recipient``, from <body> on (the <title> repeats the subject)."""
        parents = frappe.get_all(
            "Email Queue Recipient", filters={"recipient": recipient}, pluck="parent", order_by="creation"
        )[self._baseline.get(recipient, 0) :]
        raws = frappe.get_all("Email Queue", filters={"name": ["in", parents or [""]]}, pluck="message")
        self.assertEqual(len(raws), 1, f"expected exactly one mail to {recipient}, got {len(raws)}")
        html = "".join(
            part.get_payload(decode=True).decode()
            for part in email.message_from_string(raws[0]).walk()
            if part.get_content_type() == "text/html"
        )
        return html.split("<body", 1)[1]

    def assert_escaped(self, body, *tags, live):
        """``tags`` arrive escaped; ``live`` (the sender's OWN markup) still arrives as markup, so escaping the
        whole body (the plausible wrong fix) fails too."""
        self.assertIn(live, body, "the sender's own markup must stay live")
        for tag in tags:
            raw, escaped = hostile(tag)
            self.assertIn(escaped, body, f"{tag} not escaped")
            self.assertNotIn(f"<i>{tag}", body, f"{tag} arrived as live markup")


class TestControl(VereningingenTestCase):
    def test_control_hostile_value_is_live_markup_without_escaping(self):
        """Control: the sanitiser keeps this markup, so a raw interpolation would be caught by the tests below."""
        raw, escaped = hostile("ctl")
        body = frappe.utils.sanitize_html(f"<p>{raw}</p>")
        self.assertIn("<i>ctl</i>", body)
        self.assertNotIn(escaped, body)


class TestPaymentReminderFallback(MailBodyEscapingBase):
    def test_ampersand_and_apostrophe_survive_exactly_once_escaped(self):
        """A real-looking name: `&` becomes a single `&amp;` (never `&amp;amp;`) and the apostrophe stays readable."""
        import html

        from verenigingen.api.payment_processing import send_payment_reminder_email

        name = "D'Arcy Van 't Hof & Zn <i>amp</i>"
        email_addr = f"amp-2307-{self.token}@example.org"
        member = self.create_test_member(
            first_name="Amp", last_name=f"Amp{self.token}", email=email_addr, birth_date="1990-01-01"
        )
        self.key("payment_reminder_friendly", "Document-Field")
        if frappe.db.exists("Email Template", "payment_reminder_friendly"):
            frappe.delete_doc("Email Template", "payment_reminder_friendly", force=True)
        info = {"overdue_count": 1, "total_overdue": 10, "days_overdue": 3, "membership_type": name}
        self.assertTrue(send_payment_reminder_email(member.name, payment_info=info))
        body = self.html_to(email_addr)
        self.assertIn("D'Arcy Van 't Hof &amp; Zn &lt;i&gt;amp&lt;/i&gt;", body)  # apostrophes readable, & escaped once
        self.assertNotIn("&amp;amp;", body)
        self.assertNotIn("<i>amp", body)
        self.assertIn(name, html.unescape(body), "the name must read back exactly after unescaping")


    def test_fallback_html_escapes_member_and_message_text(self):
        from verenigingen.api.payment_processing import send_payment_reminder_email

        email_addr = f"rem-2307-{self.token}@example.org"
        member = self.create_test_member(
            first_name="Rem", last_name=f"Rem{self.token}", email=email_addr, birth_date="1990-01-01"
        )
        frappe.db.set_value("Member", member.name, "first_name", hostile("fname")[0])
        self.key("payment_reminder_friendly", "Document-Field")
        # The fallback runs when the stock template is missing (send_payment_reminder_email's TEMPLATE_NOT_FOUND branch).
        if frappe.db.exists("Email Template", "payment_reminder_friendly"):
            frappe.delete_doc("Email Template", "payment_reminder_friendly", force=True)
        info = {
            "overdue_count": 1,
            "total_overdue": 10,
            "days_overdue": 3,
            "membership_type": hostile("mtype")[0],
        }
        outcome = send_payment_reminder_email(
            member.name,
            reminder_type="Friendly Reminder",
            custom_message=hostile("custmsg")[0],
            payment_info=info,
        )
        self.assertTrue(outcome, f"reminder must really be sent: {outcome}")
        self.assert_escaped(self.html_to(email_addr), "fname", "mtype", "custmsg", live="<h4>Payment Details:</h4>")


class TestRenewalReminder(MailBodyEscapingBase):
    def test_renewal_reminder_escapes_donor_name(self):
        from verenigingen.api.periodic_donation_operations import send_renewal_reminders

        self.key("periodic_donation_expiry", "Document-Field")
        donor = self.create_test_donor(
            donor_type="Individual", anbi_consent=1, bsn_citizen_service_number=generate_valid_bsn()
        )
        agreement = self.create_anbi_compliant_agreement(donor=donor.name, status="Active")
        frappe.db.set_value(
            "Periodic Donation Agreement",
            agreement.name,
            {"end_date": add_days(today(), 30), "donor_name": hostile("donor")[0]},
        )
        self.mark(donor.donor_email)
        result = send_renewal_reminders(days_before_expiry=90)
        self.assertGreaterEqual(result["data"]["sent_count"], 1, result)
        self.assert_escaped(self.html_to(donor.donor_email), "donor", live="<strong>To continue your support")


class TestExpulsionMails(MailBodyEscapingBase):
    def _entry(self):
        entry = frappe.new_doc("Expulsion Report Entry")
        entry.update(
            {
                "member_name": hostile("mname")[0],
                "member_id": hostile("mid")[0],
                "expulsion_type": hostile("etype")[0],
                "expulsion_date": today(),
                "chapter_involved": hostile("chap")[0],
                "initiated_by": hostile("init")[0],
                "approved_by": hostile("appr")[0],
                "reversal_date": today(),
                "reversal_reason": hostile("revr")[0],
            }
        )
        self.to = f"gov-2307-{self.token}@example.org"
        self.key("expulsion_report_submitted", fixed_recipients=self.to)
        return entry

    def test_new_entry_mail_escapes_typed_text(self):
        self._entry().notify_governance_team()
        self.assert_escaped(self.html_to(self.to), "mname", "mid", "etype", "chap", "init", "appr", live="<h3>Expulsion Details</h3>")

    def test_reversal_mail_escapes_typed_text(self):
        self._entry().send_reversal_notification()
        self.assert_escaped(self.html_to(self.to), "mname", "revr", live="<h3>Reversal Details</h3>")


class TestExpenseApprovalMail(MailBodyEscapingBase):
    def test_approval_mail_escapes_employee_and_description(self):
        from verenigingen.services.volunteer import expense_handlers as eh

        company = "_Test Company" if frappe.db.exists("Company", "_Test Company") else None
        if not company:
            self.skipTest("No Company available")
        approver = f"approver-2307-{self.token}@example.org"
        self.create_test_user(approver, roles=["Expense Approver"])
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Exp{self.token}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
                "expense_approver": approver,
            }
        ).insert()
        self.track_doc("Employee", employee.name)
        frappe.db.set_value("Employee", employee.name, "employee_name", hostile("empn")[0])
        claim = frappe.new_doc("Expense Claim")
        claim.update(
            {
                "name": f"EXP-2307-{self.token}",
                "employee": employee.name,
                "company": company,
                "posting_date": today(),
                "total_claimed_amount": 9,
            }
        )
        claim.append("expenses", {"description": hostile("expd")[0], "amount": 9})
        self.key("expense_approval_request", "Document-Field")
        eh.notify_expense_approvers(claim)
        self.assert_escaped(self.html_to(approver), "empn", "expd", live="Expense Details:</h3>")


class TestSepaValidationAlert(MailBodyEscapingBase):
    def test_validation_alert_escapes_invoice_and_reason(self):
        from verenigingen.verenigingen_payments.services.sepa_xml_adapter import (
            BatchValidationSummary,
            SEPAXMLAdapter,
        )

        to = f"sepa-2307-{self.token}@example.org"
        old = frappe.db.get_single_value("Verenigingen Settings", "stuck_schedule_notification_emails")
        self.addCleanup(frappe.db.set_single_value, "Verenigingen Settings", "stuck_schedule_notification_emails", old)
        frappe.db.set_single_value("Verenigingen Settings", "stuck_schedule_notification_emails", to)
        summary = BatchValidationSummary(total_invoices=1)
        summary.add_skipped(hostile("inv")[0], hostile("reason")[0])
        SEPAXMLAdapter()._send_validation_alert(hostile("batch")[0], summary)
        self.assert_escaped(self.html_to(to), "inv", "reason", "batch", live="<h3>SEPA XML Generation Alert</h3>")


class TestPaymentAlertMails(MailBodyEscapingBase):
    def setUp(self):
        super().setUp()
        from verenigingen.verenigingen_payments.utils.payment_alert_service import PaymentAlertService

        self.to = f"pay-2307-{self.token}@example.org"
        self.svc = PaymentAlertService()
        self.svc._recipients_cache = [self.to]  # the documented recipients seam (hooks are empty on test sites)
        for key in ("payment_alert_overpayment", "payment_alert_failure", "payment_alert_reconciliation"):
            self.key(key, fixed_recipients=self.to)

    def test_reconciliation_alert_escapes_typed_text(self):
        self.svc.send_reconciliation_alert(
            hostile("src")[0], hostile("txn")[0], hostile("issue")[0], hostile("det")[0]
        )
        self.assert_escaped(self.html_to(self.to), "src", "txn", "issue", "det", live="<strong>Transaction ID:</strong>")

    def test_failure_alert_escapes_typed_text(self):
        self.svc.send_payment_entry_failure_alert(
            source=hostile("src")[0],
            transaction_id=hostile("txn")[0],
            reference_name=hostile("ref")[0],
            amount=1,
            error_message=hostile("err")[0],
        )
        self.assert_escaped(self.html_to(self.to), "src", "txn", "ref", "err", live="<strong>Payment Entry creation failed.</strong>")

    def test_overpayment_alert_escapes_typed_text(self):
        self.svc.send_overpayment_alert(
            source=hostile("src")[0],
            transaction_id=hostile("txn")[0],
            reference_name=hostile("ref")[0],
            amount_paid=12,
            amount_due=10,
        )
        self.assert_escaped(self.html_to(self.to), "src", "txn", "ref", live="<strong>Overpayment:</strong>")


class TestBoardMembershipEndedMessage(MailBodyEscapingBase):
    def test_message_escapes_member_and_chapter_text(self):
        from verenigingen.mijnrood_sync.services.event_application.volunteer_sync_service import (
            get_volunteer_sync_service,
        )

        recipient = f"board-2307-{self.token}@example.org"
        self.create_test_user(recipient, roles=["System Manager"])
        self.key("chapter_board_removed", fixed_recipients=recipient)
        get_volunteer_sync_service()._notify_board_membership_change(hostile("mem")[0], [hostile("chp")[0]])
        content = frappe.get_all(
            "Notification Log", filters={"for_user": recipient}, pluck="email_content"
        )
        self.assertEqual(len(content), 1, "one notification must have been created")
        self.assert_escaped(content[0], "mem", "chp", live="<p>MijnRood sync ended")
