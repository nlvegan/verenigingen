"""
Non-SEPA staff alerts never reach Administrator, user names or disabled users (#2095).

Eleven senders built their recipients from a raw ``Has Role`` query. Each is driven here through its
real code path, with Administrator holding the queried roles and an email, one enabled holder (the
control: it must still be reached) and one disabled holder. Maintainer ruling: each alert keeps the
audience it had before, so users holding ONE role each pin who is and is not reached.

Every test runs twice: with no row for the key (the sender's own default roles apply) and with the row a
migrated site really has, seeded from the registry (``TestSeededRowAudiences``). The second is the state
that matters: a seeded row always exists, and the resolver uses it before any default.

Mock justification: the EmailService factory is the outgoing-mail boundary; recipient resolution runs
against real Users, real Has Role rows and the real Verenigingen Email Configuration. One seam is
stubbed for lack of the thing itself: the orphaned-records query (needs broken data). The security
monitor inserts a "Security Alert" row that no shipped DocType backs (#689), so only that insert is
stubbed; creating the DocType would CREATE TABLE, which commits the test's setUp for good.

Run:
    bench --site test_site_6 run-tests --app verenigingen --module verenigingen.tests.test_staff_recipients_2095
"""

import importlib
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
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
    "contribution_amendment_sync_failed",
    "contact_request_escalated",
    "contact_request_new",
    "contact_request_urgent",
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
    seed_rows = False  # True: seed the keys' rows from the registry, as a migrated site has them

    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)
        # No row for any of the keys: the resolver falls to the default roles each sender names.
        config = frappe.get_single(CONFIG)
        config.set("notification_types", [r for r in config.notification_types if r.notification_key not in KEYS])
        config.save()
        if self.seed_rows:
            ensure_notification_registry_rows()
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
        # One role each: who is reached pins each alert's audience.
        self.sm_only = f"smonly-2095-{suffix}@example.org"
        self.create_test_user(self.sm_only, roles=[Roles.SYSTEM_MANAGER])
        self.va_only = f"vaonly-2095-{suffix}@example.org"
        self.create_test_user(self.va_only, roles=[Roles.VERENIGINGEN_ADMIN])
        self.fm_only = f"fmonly-2095-{suffix}@example.org"
        self.create_test_user(self.fm_only, roles=[Roles.FINANCIAL_MANAGER])
        self.staff_only = f"staffonly-2095-{suffix}@example.org"
        self.create_test_user(self.staff_only, roles=[Roles.VERENIGINGEN_STAFF])

    @contextmanager
    def mail(self):
        mail = _Mail()
        for module in MODULES:
            # Import BEFORE patching SOURCE: a module first imported under that patch binds the mock
            # as its get_email_service, and the per-module patch below would restore the mock (#2437).
            importlib.import_module(module)
        with ExitStack() as stack:
            stack.enter_context(patch(SOURCE, return_value=mail.service))
            for module in MODULES:  # modules that bind the factory at import time
                stack.enter_context(patch(f"{module}.get_email_service", return_value=mail.service))
            yield mail

    def audience(self, recipients, reaches, misses):
        """Who an alert reaches, by their ONE role: the audience the alert had before #2095."""
        for who in reaches:
            self.assertIn(getattr(self, who), recipients, f"{who} must be reached: {recipients}")
        for who in misses:
            self.assertNotIn(getattr(self, who), recipients, f"{who} must not be reached: {recipients}")

    def check(self, mail, reaches=(), misses=()):
        recipients = mail.recipients
        self.assertTrue(recipients, "the alert must still be sent when staff resolve")
        self.assertIn(self.holder, recipients)  # control: a real enabled holder is reached
        self.assertNotIn(self.gone, recipients)
        self.assertNotIn(self.admin_email, recipients)
        self.assertNotIn("Administrator", recipients)
        self.assertNotIn(self.holder.split("@")[0], recipients)  # emails, not user names
        self.assertTrue(all("@" in r for r in recipients), recipients)
        self.audience(recipients, reaches, misses)

    def test_mail_leaves_no_mock_behind_in_a_module_first_imported_under_it(self):
        """#2437: a module first imported INSIDE mail() binds the patched factory at import time.

        patch(SOURCE) is entered before the per-module patches, and a per-module patch imports its
        module on entry. A module nobody had imported yet therefore ran ``from email_service import
        get_email_service`` against the mock, patch saved THAT as the original, and restored it on
        exit: the mock stayed for the rest of the process and silenced every later test of the module
        (shard 9 of the queue build 42926880094).
        """
        import sys

        saved = {m: sys.modules.pop(m) for m in MODULES if m in sys.modules}
        parent_attrs = {}
        for m in saved:
            parent_name, _, leaf = m.rpartition(".")
            parent_attrs[m] = (sys.modules[parent_name], leaf, getattr(sys.modules[parent_name], leaf, None))
            if hasattr(sys.modules[parent_name], leaf):
                delattr(sys.modules[parent_name], leaf)
        try:
            with self.mail():
                pass
            # Every loaded module, not just MODULES: any binder first imported under the patch is poisoned.
            leaked = sorted(
                name
                for name, mod in list(sys.modules.items())
                if mod is not None
                and isinstance(getattr(mod, "__dict__", {}).get("get_email_service"), MagicMock)
            )
        finally:
            for m in MODULES:
                sys.modules.pop(m, None)
            for m, mod in saved.items():
                sys.modules[m] = mod
                parent, leaf, attr = parent_attrs[m]
                setattr(parent, leaf, attr)
        self.assertEqual(leaked, [], "mail() left a MagicMock as get_email_service in these modules")

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
        # System Manager + Verenigingen Administrator + Financial Manager, as before.
        self.check(mail, reaches=("sm_only", "va_only", "fm_only"), misses=("staff_only",))

    def test_amendment_request_sync_failure(self):
        from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
            ContributionAmendmentRequest,
        )

        membership, member = self._membership_and_member()
        stand_in = SimpleNamespace(
            name="CAR-2095", membership=membership.name, amendment_type="Fee Change", requested_amount=None
        )
        self.expectErrorLog("Mollie Sync Failed")  # the handler logs the failure it reports, by design
        # handle_mollie_sync_failure commits (contribution_amendment_request.py ~444); un-patched,
        # that commit made this test's setUp (key rows deleted, Administrator email rewritten)
        # permanent on the site, and later modules in a shard then skipped those alerts (#2095 review).
        with self.mail() as mail, patch.object(frappe.db, "commit"):
            ContributionAmendmentRequest.handle_mollie_sync_failure(stand_in, "boom")
        # The request's own alert never included finance: System Manager + Verenigingen Administrator.
        self.check(mail, reaches=("sm_only", "va_only"), misses=("fm_only", "staff_only"))

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
            self.audience(recipients, ("va_only",), ("fm_only", "staff_only"))
        # Urgent adds System Managers, normal does not.
        self.audience(self._contact_request("Normal"), (), ("sm_only",))
        self.audience(self._contact_request("Urgent"), ("sm_only",), ())

    def test_contact_request_notification_uses_the_key_of_its_urgency(self):
        """The mail is sent (and its key row gated) on the urgency's own key, not on the escalation key."""
        from verenigingen.verenigingen.doctype.member_contact_request.member_contact_request import (
            contact_request_key,
        )

        self.assertEqual(contact_request_key("Urgent"), "contact_request_urgent")
        for urgency in ("Normal", "High", "Low", None):
            self.assertEqual(contact_request_key(urgency), "contact_request_new", urgency)

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
        self.check(mail, reaches=("va_only",), misses=("sm_only", "fm_only", "staff_only"))

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
        self.check(mail, reaches=("va_only",), misses=("sm_only", "fm_only", "staff_only"))
        self.assertIn(second, mail.recipients)  # every holder, not an arbitrary first one
        # The WHOLE holder set, so a pick-first mutant cannot pass: enabled Verenigingen Administrators
        # with an email, Administrator excluded.
        holders = frappe.db.sql(
            """
            SELECT DISTINCT u.email FROM `tabHas Role` hr JOIN `tabUser` u ON u.name = hr.parent
            WHERE hr.role = %s AND hr.parenttype = 'User' AND u.enabled = 1
                AND u.name != 'Administrator' AND IFNULL(u.email, '') != ''
            """,
            (Roles.VERENIGINGEN_ADMIN,),
            pluck=True,
        )
        self.assertGreater(len(holders), 2, "control: more than one holder exists")
        self.assertEqual(set(mail.recipients), set(holders))

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
        # Unchanged audience: the admin pair, never finance or staff alone.
        self.check(mail, reaches=("sm_only", "va_only"), misses=("fm_only", "staff_only"))

    def test_orphaned_records_report(self):
        from verenigingen.verenigingen.doctype.membership import scheduler

        row = {"record_type": "Membership", "document": "M-1", "status": "Active", "issue": "i"}
        with self.mail() as mail, patch.object(scheduler, "_get_orphaned_records_data", return_value=[row]):
            frappe.db.set_single_value("Verenigingen Settings", "orphaned_report_recipients", "")
            scheduler.notify_about_orphaned_records()
        self.check(mail, reaches=("staff_only",), misses=("sm_only", "va_only", "fm_only"))

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
        self.check(mail, reaches=("sm_only",), misses=("va_only", "fm_only", "staff_only"))

    def test_critical_operation_rule_admin_emails(self):
        from verenigingen.verenigingen.doctype.critical_operation_rule.critical_operation_rule import (
            CriticalOperationRule,
        )

        emails = CriticalOperationRule._get_admin_emails(SimpleNamespace())
        self.assertIn(self.holder, emails)
        self.assertNotIn(self.gone, emails)
        self.assertNotIn(self.admin_email, emails)
        self.audience(emails, ("sm_only",), ("va_only", "fm_only", "staff_only"))

    def test_business_rule_security_alert_is_unreachable_today(self):
        """The sender inserts a "Security Alert" row first, and no such DocType ships (#689), so on a real
        site that insert raises, the job logs and swallows it, and the mail is never reached. That is the
        behaviour pinned here; the key's audience is pinned on the row itself (seeded class). Creating the
        DocType in a test would CREATE TABLE, which commits the test's setUp permanently."""
        from verenigingen.utils.security import security_monitoring as sm

        self.assertFalse(frappe.db.exists("DocType", "Security Alert"), "control: the DocType really is absent")
        alert = {"type": "t", "severity": "HIGH", "user": "u", "message": "m", "timestamp": "2026-01-01 00:00:00"}
        monitor = SimpleNamespace(detect_business_rule_anomalies=lambda: [alert])
        self.expectErrorLog("Business Rule Monitoring Failed")
        with self.mail() as mail, patch.object(sm, "get_security_monitor", return_value=monitor):
            sm.run_business_rule_monitoring()
        self.assertEqual(mail.recipients, [])

    def test_audit_alert(self):
        from verenigingen.utils.security.audit_logging import SEPAAuditLogger

        with self.mail() as mail:
            SEPAAuditLogger._send_security_notification(None, "m", "event", 1)
        self.check(mail, reaches=("sm_only", "va_only"), misses=("fm_only", "staff_only"))

    def _expulsion(self):
        return frappe.new_doc("Expulsion Report Entry").update(
            {"member_name": "M", "member_id": "x", "expulsion_type": "t", "expulsion_date": "2026-01-01"}
        )

    def test_expulsion_governance_mails(self):
        for send in ("notify_governance_team", "send_reversal_notification"):
            with self.mail() as mail:
                getattr(self._expulsion(), send)()
            self.check(mail, reaches=("va_only",), misses=("sm_only", "fm_only", "staff_only"))

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
        _put_key_row("contact_request_urgent", "Fixed", fixed_recipients="board-2095@example.org")
        self.assertEqual(self._contact_request("Urgent"), ["board-2095@example.org"])
        # Each urgency has its own key: a row on one does not steer the other.
        self.assertNotIn("board-2095@example.org", self._contact_request("Normal"))


class TestSeededRowAudiences(TestStaffRecipients2095):
    """Every test above again, against the row a migrated site really has: seeded from the registry.

    On a seeded site the key-first resolver uses the key's row before any default, so this is the state
    that decides who gets mail. A site with no row for a key never happens after migrate.
    """

    seed_rows = True

    def test_the_seeded_rows_carry_the_registry_roles(self):
        """Control for the whole class: the rows are really there, and really are the registry's."""
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        rows = {r.notification_key: r for r in frappe.get_single(CONFIG).notification_types}
        for key, roles in EXPECTED_SEEDED_ROLES.items():
            self.assertIn(key, rows, key)
            self.assertEqual(rows[key].recipient_policy, "Role-Based", key)
            self.assertEqual(set(rows[key].recipient_roles.split(", ")), roles, key)
            self.assertEqual(
                set((NOTIFICATION_KEYS[key].get("recipient_roles") or ", ".join(Roles.ADMIN_PAIR)).split(", ")),
                roles,
                key,
            )

    def test_business_logic_alert_row_reaches_system_managers_only(self):
        """Its sender is unreachable (#689), so pin the key's own row: what it resolves to once reached."""
        from verenigingen.utils.notification_helpers import resolve_admin_recipients

        recipients = resolve_admin_recipients(
            notification_key="business_logic_alert",
            default_roles=[Roles.SYSTEM_MANAGER],
            exclude_users=("Administrator",),
            key_first=True,
        )
        self.audience(recipients, ("sm_only",), ("va_only", "fm_only", "staff_only"))
        self.assertNotIn(self.admin_email, recipients)

    def test_stock_row_then_patch_then_the_sender_keeps_the_old_audience(self):
        """The migrated-site path: the stock admin-pair row, the patch, the real sender (expense approvals)."""
        _put_key_row("expense_approval_request", "Role-Based", recipient_roles=STOCK_ROLES)
        importlib.import_module(PATCH).execute()
        frappe.clear_document_cache(CONFIG, CONFIG)
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
        claim = frappe._dict(
            name="EXP-2095b",
            employee=employee.name,
            company=company,
            total_claimed_amount=9,
            posting_date="2026-01-01",
            expenses=[],
        )
        with self.mail() as mail:
            eh.notify_expense_approvers(claim)
        self.check(mail, reaches=("va_only",), misses=("sm_only", "fm_only", "staff_only"))


STOCK_ROLES = "System Manager, Verenigingen Administrator"
PATCH = "verenigingen.patches.v2_2.restore_staff_alert_audiences_2095"
VA, SM, STAFF = Roles.VERENIGINGEN_ADMIN, Roles.SYSTEM_MANAGER, Roles.VERENIGINGEN_STAFF
EXPECTED_SEEDED_ROLES = {
    "expense_approval_request": {VA},
    "business_logic_alert": {SM},
    "security_policy_digest": {SM},
    "expulsion_report_submitted": {VA},
    "system_stuck_schedules": {STAFF},
    "contact_request_escalated": {VA},
    "contact_request_new": {VA},
    "contact_request_urgent": {VA, SM},
    "contribution_amendment_sync_failed": {SM, VA, Roles.FINANCIAL_MANAGER},
    "contribution_sync_failed": {SM, VA},
    "payment_plan_request": {SM, VA},
    "audit_alert": {SM, VA},
}
PATCHED = {k: next(iter(v)) for k, v in EXPECTED_SEEDED_ROLES.items() if len(v) == 1 and k in (
    "expense_approval_request", "business_logic_alert", "security_policy_digest",
    "expulsion_report_submitted", "system_stuck_schedules", "contact_request_escalated",
)}


class TestRestoreAudiencesPatch(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        rows = _snapshot_rows()
        self.addCleanup(_restore_rows, rows)

    def _row(self, key):
        frappe.clear_document_cache(CONFIG, CONFIG)
        return next(r for r in frappe.get_single(CONFIG).notification_types if r.notification_key == key)

    def _run(self):
        importlib.import_module(PATCH).execute()

    def test_every_stock_row_moves_to_its_keys_old_audience(self):
        for key in PATCHED:
            _put_key_row(key, "Role-Based", recipient_roles=STOCK_ROLES)
        self._run()
        for key, role in PATCHED.items():
            self.assertEqual(self._row(key).recipient_roles, role, key)

    def test_the_reversed_stock_order_moves_too(self):
        _put_key_row("business_logic_alert", "Role-Based", recipient_roles="Verenigingen Administrator, System Manager")
        self._run()
        self.assertEqual(self._row("business_logic_alert").recipient_roles, SM)

    def test_a_customised_row_is_left_alone(self):
        _put_key_row("expense_approval_request", "Role-Based", recipient_roles="Expense Approver, Verenigingen Administrator")
        _put_key_row("system_stuck_schedules", "Role-Based", recipient_roles=STOCK_ROLES)  # control: this one moves
        self._run()
        self.assertEqual(self._row("expense_approval_request").recipient_roles, "Expense Approver, Verenigingen Administrator")
        self.assertEqual(self._row("system_stuck_schedules").recipient_roles, STAFF)

    def test_a_fixed_row_is_left_alone(self):
        _put_key_row("security_policy_digest", "Fixed", recipient_roles=STOCK_ROLES, fixed_recipients="board-2095@example.org")
        self._run()
        row = self._row("security_policy_digest")
        self.assertEqual((row.recipient_policy, row.recipient_roles), ("Fixed", STOCK_ROLES))

    def test_keys_that_keep_the_admin_pair_are_left_alone(self):
        for key in ("contribution_sync_failed", "payment_plan_request", "audit_alert"):
            _put_key_row(key, "Role-Based", recipient_roles=STOCK_ROLES)
        _put_key_row("business_logic_alert", "Role-Based", recipient_roles=STOCK_ROLES)  # control: this one moves
        self._run()
        for key in ("contribution_sync_failed", "payment_plan_request", "audit_alert"):
            self.assertEqual(self._row(key).recipient_roles, STOCK_ROLES, key)
        self.assertEqual(self._row("business_logic_alert").recipient_roles, SM)

    def test_the_patch_is_idempotent_and_registered(self):
        _put_key_row("expulsion_report_submitted", "Role-Based", recipient_roles=STOCK_ROLES)
        self._run()
        self._run()
        self.assertEqual(self._row("expulsion_report_submitted").recipient_roles, VA)
        listing = (Path(frappe.get_app_path("verenigingen")) / "patches.txt").read_text()
        self.assertIn(PATCH, listing)

    def test_the_patch_mapping_agrees_with_the_registry(self):
        """The patch freezes its own mapping; it must still match what a fresh seed names."""
        from verenigingen.notification_registry import NOTIFICATION_KEYS

        for key, role in PATCHED.items():
            self.assertEqual(NOTIFICATION_KEYS[key].get("recipient_roles"), role, key)
