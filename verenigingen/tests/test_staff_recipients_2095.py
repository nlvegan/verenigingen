"""
Non-SEPA staff alerts never reach Administrator, user names or disabled users (#2095).

Eleven senders built their recipients from a raw ``Has Role`` query. Each is driven here through its
real code path, with Administrator holding the queried roles and an email, one enabled holder (the
control: it must still be reached) and one disabled holder.

Mock justification: the EmailService factory is the outgoing-mail boundary; recipient resolution runs
against real Users, real Has Role rows and the real Verenigingen Email Configuration. One seam is
stubbed for lack of the thing itself: the orphaned-records query (needs broken data). The security
monitor inserts a "Security Alert" row that no shipped DocType backs, so the test builds a throwaway one.

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.test_staff_recipients_2095
"""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.payment.test_sepa_literal_recipients import (
    _put_key_row,
    _restore_rows,
    _snapshot_rows,
)
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.utils.constants import Roles

CONFIG = "Verenigingen Email Configuration"
SOURCE = "verenigingen.services.communication.email_service.get_email_service"
ROLES = [
    Roles.SYSTEM_MANAGER,
    Roles.VERENIGINGEN_ADMIN,
    Roles.FINANCIAL_MANAGER,
    Roles.VERENIGINGEN_STAFF,
]
KEYS = (
    "contribution_sync_failed",
    "contact_request_escalated",
    "expulsion_report_submitted",
    "expense_approval_request",
    "payment_plan_request",
    "system_stuck_schedules",
    "security_policy_digest",
    "business_logic_alert",
    "audit_alert",
)
MODULES = (
    "verenigingen.verenigingen.doctype.member_contact_request.member_contact_request",
    "verenigingen.verenigingen.doctype.member_contact_request.contact_request_automation",
    "verenigingen.verenigingen.doctype.expulsion_report_entry.expulsion_report_entry",
    "verenigingen.utils.security.security_monitoring",
)


class _Mail:
    """Records the recipients of every send on the patched EmailService."""

    def __init__(self):
        self.service = MagicMock(name="EmailService")
        self.service.send_email.return_value = {"success": True}
        self.service.send_templated_email.return_value = {"success": True}
        self.service.send_simple_email.return_value = MagicMock(success=True, error_message=None)

    @property
    def recipients(self):
        out = []
        for name in ("send_email", "send_templated_email", "send_simple_email"):
            for call in getattr(self.service, name).call_args_list:
                out.extend(call.kwargs.get("recipients") or [])
        return out


class TestStaffRecipients2095(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        # No row for any of the keys: the resolver falls to the default roles each sender names.
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key not in KEYS])
        config.save()
        frappe.db.set_single_value(CONFIG, "admin_notification_emails", "")

        old_email = frappe.db.get_value("User", "Administrator", "email")
        self.addCleanup(frappe.db.set_value, "User", "Administrator", "email", old_email, update_modified=False)
        self.admin_email = "administrator-2095@example.org"
        frappe.db.set_value("User", "Administrator", "email", self.admin_email, update_modified=False)
        admin = frappe.get_doc("User", "Administrator")
        held = {r.role for r in admin.roles}
        for role in ROLES:
            if role not in held:
                admin.append("roles", {"role": role})
        admin.save(ignore_permissions=True)
        self.addCleanup(
            frappe.db.delete, "Has Role", {"parent": "Administrator", "role": ["in", [r for r in ROLES if r not in held]]}
        )

        suffix = frappe.generate_hash(length=5)
        self.holder = f"holder-2095-{suffix}@example.org"
        self.create_test_user(self.holder, roles=ROLES)
        self.gone = f"gone-2095-{suffix}@example.org"
        self.create_test_user(self.gone, roles=ROLES, enabled=0)
        # Holds only System Manager: reached by senders whose default roles include it, never by the others.
        self.sm_only = f"smonly-2095-{suffix}@example.org"
        self.create_test_user(self.sm_only, roles=[Roles.SYSTEM_MANAGER])

    @contextmanager
    def mail(self):
        mail = _Mail()
        with ExitStack() as stack:
            stack.enter_context(patch(SOURCE, return_value=mail.service))
            for module in MODULES:  # modules that bind the factory at import time
                stack.enter_context(patch(f"{module}.get_email_service", return_value=mail.service))
            yield mail

    def check(self, mail, default_excludes_system_manager=False):
        recipients = mail.recipients
        self.assertTrue(recipients, "the alert must still be sent when staff resolve")
        self.assertIn(self.holder, recipients)  # control: a real enabled holder is reached
        self.assertNotIn(self.gone, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.holder.split("@")[0], recipients)  # emails, not user names
        self.assertTrue(all("@" in r for r in recipients), recipients)
        if default_excludes_system_manager:  # the sender's own default roles, not a blanket System Manager list
            self.assertNotIn(self.sm_only, recipients)

    def _membership_and_member(self):
        token = frappe.generate_hash(length=8)
        member = self.create_test_member(
            first_name="Rcp", last_name=f"T{token}", email=f"rcp-{token}@example.com", birth_date="1990-01-01"
        )
        return self.create_test_membership(member_name=member.name), member

    def test_amendment_sync_issue(self):
        from verenigingen.verenigingen_payments.mollie.events import amendment_events

        membership, member = self._membership_and_member()
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": membership.name,
                "member": member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 30.0,
                "reason": "recipients 2095",
                "status": "Applied",
            }
        ).insert()
        with self.mail() as mail:
            amendment_events.notify_administrators_of_sync_issue(amendment, {"status": "error", "message": "x"})
        self.check(mail)

    def test_amendment_request_sync_failure(self):
        from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
            ContributionAmendmentRequest,
        )

        membership, member = self._membership_and_member()
        stand_in = SimpleNamespace(
            name="CAR-2095", membership=membership.name, amendment_type="Fee Change", requested_amount=None
        )
        self.expectErrorLog("Mollie Sync Failed")  # the handler logs the failure it reports, by design
        with self.mail() as mail:
            ContributionAmendmentRequest.handle_mollie_sync_failure(stand_in, "boom")
        self.check(mail)

    def _contact_request(self, urgency):
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            MemberContactRequest,
        )

        return MemberContactRequest.get_notification_recipients(SimpleNamespace(urgency=urgency))

    def test_contact_request_recipients_normal_and_urgent(self):
        for urgency in ("Normal", "Urgent"):
            recipients = self._contact_request(urgency)
            self.assertIn(self.holder, recipients, urgency)
            self.assertNotIn(self.gone, recipients, urgency)
            self.assertNotIn(self.admin_email, recipients, urgency)
            self.assertNotIn("Administrator", recipients, urgency)
            self.assertTrue(all("@" in r for r in recipients), recipients)
        self.assertNotIn(self.sm_only, self._contact_request("Normal"))  # urgent adds System Managers, normal does not
        self.assertIn(self.sm_only, self._contact_request("Urgent"))

    def test_contact_request_escalation(self):
        from verenigingen.verenigingen.doctype.member_contact_request import contact_request_automation as cra

        request = frappe._dict(
            name="MCR-2095", subject="s", member_name="m", assigned_to=None, request_date="2026-01-01", urgency="High"
        )
        with self.mail() as mail:
            try:
                cra.escalate_contact_request(request, 3)
            except frappe.DoesNotExistError:
                pass  # the stand-in request has no row for the escalation NOTE, written after the mail went out
        self.check(mail, default_excludes_system_manager=True)

    def test_expense_approver_fallback_reaches_every_holder(self):
        from verenigingen.services.volunteer import expense_handlers as eh

        company = get_eur_test_company()
        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "first_name": f"Rcp{frappe.generate_hash(length=5)}",
                "gender": "Other",
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2020-01-01",
                "status": "Active",
                "company": company,
            }
        ).insert()
        self._track_test_document("Employee", employee.name, priority=2)
        second = f"holder2-2095-{frappe.generate_hash(length=5)}@example.org"
        self.create_test_user(second, roles=ROLES)
        claim = frappe._dict(
            name="EXP-2095",
            employee=employee.name,
            company=company,
            total_claimed_amount=9,
            posting_date="2026-01-01",
            expenses=[],
        )
        with self.mail() as mail:
            eh.notify_expense_approvers(claim)
        self.check(mail, default_excludes_system_manager=True)
        self.assertIn(second, mail.recipients)  # every holder, not an arbitrary first one

    def test_payment_plan_request(self):
        from verenigingen.api.payment_plan_management import send_payment_plan_request_notification

        _, member = self._membership_and_member()
        plan = frappe._dict(
            name="PP-2095",
            member=member.name,
            total_amount=100,
            frequency="Monthly",
            number_of_installments=4,
            installment_amount=25,
            reason="r",
        )
        with self.mail() as mail:
            send_payment_plan_request_notification(plan)
        self.check(mail)

    def test_orphaned_records_report(self):
        from verenigingen.verenigingen.doctype.membership import scheduler

        row = {"record_type": "Membership", "document": "M-1", "status": "Active", "issue": "i"}
        with self.mail() as mail, patch.object(scheduler, "_get_orphaned_records_data", return_value=[row]):
            frappe.db.set_single_value("Verenigingen Settings", "orphaned_report_recipients", "")
            scheduler.notify_about_orphaned_records()
        self.check(mail, default_excludes_system_manager=True)

    def test_security_policy_digest(self):
        from verenigingen.verenigingen.doctype.critical_operation_rule import critical_operation_rule as cor

        change = {
            "operation_name": "op",
            "operation_type": "t",
            "security_level": "critical",
            "changed_by": "u",
            "changed_at": "now",
            "enabled_status": "Yes",
        }
        import json

        frappe.cache().delete_value("security_policy_change_queue")
        frappe.cache().lpush("security_policy_change_queue", json.dumps(change))
        self.addCleanup(frappe.cache().delete_value, "security_policy_change_queue")
        real_get_value = frappe.db.get_value

        def get_value(doctype, *args, **kwargs):
            # Mock justified: the digest skips itself when the site has no default outgoing account.
            if doctype == "Email Account":
                return ("Default", "outgoing@example.org", 1)
            return real_get_value(doctype, *args, **kwargs)

        with self.mail() as mail, patch.object(frappe.db, "get_value", side_effect=get_value):
            cor.send_security_policy_change_digest()
        self.check(mail)

    def test_critical_operation_rule_admin_emails(self):
        from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
            CriticalOperationRule,
        )

        emails = CriticalOperationRule._get_admin_emails(SimpleNamespace())
        self.assertIn(self.holder, emails)
        self.assertNotIn(self.gone, emails)
        self.assertNotIn(self.admin_email, emails)

    def test_business_rule_security_alert(self):
        from verenigingen.utils.security import security_monitoring as sm

        alert = {
            "type": "t",
            "severity": "HIGH",
            "user": "u",
            "message": "m",
            "timestamp": "2026-01-01 00:00:00",
        }
        monitor = SimpleNamespace(detect_business_rule_anomalies=lambda: [alert])
        self._ensure_security_alert_doctype()
        with self.mail() as mail, patch.object(sm, "get_security_monitor", return_value=monitor):
            sm.run_business_rule_monitoring()
        self.check(mail)

    def _ensure_security_alert_doctype(self):
        """The sender inserts a "Security Alert" row first, and that DocType is not shipped (so the
        sender is unreachable on a real site today). Build a throwaway custom one for the test."""
        if frappe.db.exists("DocType", "Security Alert"):
            return
        fields = [
            {"fieldname": f, "fieldtype": t, "label": f}
            for f, t in (
                ("alert_type", "Data"),
                ("severity", "Data"),
                ("user", "Data"),
                ("message", "Small Text"),
                ("detected_at", "Data"),
                ("alert_data", "Long Text"),
            )
        ]
        frappe.get_doc(
            {
                "doctype": "DocType",
                "name": "Security Alert",
                "module": "Verenigingen",
                "custom": 1,
                "fields": fields,
                "permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1}],
            }
        ).insert(ignore_permissions=True)
        self.addCleanup(frappe.delete_doc, "DocType", "Security Alert", force=True, ignore_permissions=True)

    def test_audit_alert(self):
        from verenigingen.utils.security.audit_logging import SEPAAuditLogger

        with self.mail() as mail:
            SEPAAuditLogger._send_security_notification(None, "m", "event", 1)
        self.check(mail)

    def _expulsion(self):
        return frappe.new_doc("Expulsion Report Entry").update(
            {"member_name": "M", "member_id": "x", "expulsion_type": "t", "expulsion_date": "2026-01-01"}
        )

    def test_expulsion_governance_mails(self):
        for send in ("notify_governance_team", "send_reversal_notification"):
            with self.mail() as mail:
                getattr(self._expulsion(), send)()
            self.check(mail, default_excludes_system_manager=True)

    def test_a_configured_key_wins_over_the_role_holders(self):
        """Key-first: a Fixed row on the key is the audience, not the enabled role holders."""
        from verenigingen.api.payment_plan_management import send_payment_plan_request_notification

        _, member = self._membership_and_member()
        plan = frappe._dict(
            name="PP-2095", member=member.name, total_amount=100, frequency="Monthly",
            number_of_installments=4, installment_amount=25, reason="r",
        )
        _put_key_row("payment_plan_request", "Fixed", fixed_recipients="board-2095@example.org")
        with self.mail() as mail:
            send_payment_plan_request_notification(plan)
        self.assertEqual(mail.recipients, ["board-2095@example.org"])
        self.assertNotIn(self.holder, mail.recipients)  # control: the holder exists and would otherwise be reached
        _put_key_row("contact_request_escalated", "Fixed", fixed_recipients="board-2095@example.org")
        self.assertEqual(self._contact_request("Urgent"), ["board-2095@example.org"])
