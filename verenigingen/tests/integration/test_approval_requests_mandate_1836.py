# -*- coding: utf-8 -*-
"""
#1836: approving a SEPA Direct Debit applicant creates NO mandate; it asks the member to sign one.

Maintainer ruling (option 2): a mandate is the member's own authorisation, so approval never creates it.
The member is mailed (registered key ``member_sepa_mandate_signature_requested``), the payment dashboard
shows a mandate waiting to be signed, and until it is signed the first dues invoice is paid by transfer.
Signing goes through the existing self-service path, ``setup_sepa_direct_debit``.

Driven through the real flow: submit -> confirm -> ``approve_application`` as a least-privileged board
member (#1862); the reapplication case runs the real termination service first. Stand-ins, stated: the
member's portal User is linked with ``_link_member_to_user`` (the approval as a board member queues no
account), and the mail boundary is spied, not stubbed (the real service and template render still run).
"""

from unittest.mock import patch

import frappe

from verenigingen.api.member import sepa_api
from verenigingen.services.communication.email_service import EmailService
from verenigingen.services.payment.sepa_mandate_consent import get_mandate_consent_text, hash_consent_text
from verenigingen.services.payment.sepa_mandate_manager import member_needs_mandate_signature
from verenigingen.setup.notification_registry_setup import ensure_notification_registry_rows
from verenigingen.templates.pages import payment_dashboard
from verenigingen.tests.fixtures.portal_self_service_mixin import PortalSelfServiceTestMixin
from verenigingen.tests.integration.test_application_record_approval import (
    IBAN,
    OTHER_IBAN,
    ApprovalCase,
)
from verenigingen.tests.support.termination_request import execute_real_termination
from verenigingen.tests.utils.reminder_mail_state import (
    clear_email_cooldowns,
    ensure_outgoing_email_account,
)

KEY = "member_sepa_mandate_signature_requested"
TEMPLATE = "sepa_mandate_signature_request"


class TestApprovalRequestsMandate(PortalSelfServiceTestMixin, ApprovalCase):
    def setUp(self):
        super().setUp()
        ensure_outgoing_email_account(self)
        # Rows are seeded by install and migrate; run the same seeder so a site that predates the key has it.
        ensure_notification_registry_rows()
        self.board = self.create_test_board_member(self.chapter.name, permissions_level="Admin")
        self.mails = []

    # -- helpers -----------------------------------------------------------------------------------

    def _approve_spied(self, application, **kwargs):
        clear_email_cooldowns()
        real = EmailService._send_email_internal
        mails = self.mails

        def spy(service, *args, **kw):
            result = real(service, *args, **kw)
            mails.append((kw, result))
            return result

        kwargs.setdefault("membership_type", self.membership_type.name)
        kwargs.setdefault("chapter", self.chapter.name)
        # Mock justified: spy on the mail boundary; the real service (and template render) still runs
        with patch.object(EmailService, "_send_email_internal", spy):
            return self._approve_as(application, user=self.board.user, send_mail=True, **kwargs)

    def _signature_mails(self):
        """Requests that actually went out: a send the key's row skipped is spied too, but is not a mail."""
        return [
            kw
            for kw, result in self.mails
            if self.email in (kw.get("recipients") or [])
            and "direct debit authorisation" in (kw.get("subject") or "")
            and not (isinstance(result.data, dict) and result.data.get("skipped"))
        ]

    def _mandates(self, member, **filters):
        return frappe.get_all(
            "SEPA Mandate", {"member": member, **filters}, ["name", "status", "iban", "used_for_memberships"]
        )

    def _apply_for_sepa_and_approve(self, iban=IBAN, **kwargs):
        application = self._stage_and_confirm(
            iban=iban, bank_account_name="A. Applicant", payment_method="SEPA Direct Debit"
        )
        response = self._approve_spied(application, **kwargs)
        self.assertTrue(response["success"], response)
        return response["member"], response

    def _sign_as_member(self, member, iban):
        member_doc = frappe.get_doc("Member", member)
        # PROBE SHORTCUT, stated: the portal User is linked directly; the signing call is the real endpoint.
        user = self._link_member_to_user(member_doc)
        with self._as_user(user.name):
            return sepa_api.setup_sepa_direct_debit(
                iban=iban,
                account_holder_name="A. Applicant",
                consent=1,
                consent_text_hash=hash_consent_text(get_mandate_consent_text()),
            )

    def _dashboard_context(self, member):
        context = frappe._dict(member=member)
        payment_dashboard._add_bank_details_context(context)
        return context

    # -- the ruling --------------------------------------------------------------------------------

    def test_new_sepa_applicant_gets_no_mandate_and_a_signature_request(self):
        member, _ = self._apply_for_sepa_and_approve()

        self.assertEqual(self._mandates(member), [], "approval created a mandate without consent")
        self.assertEqual(frappe.db.get_value("Member", member, "payment_method"), "SEPA Direct Debit")
        self.assertEqual(len(self._signature_mails()), 1, "one signature request mailed to the member")
        self.assertTrue(member_needs_mandate_signature(member))

    def test_signature_request_is_sent_on_the_registered_key(self):
        """The mail must carry the registered key, so staff can toggle it in Verenigingen Email Configuration."""
        from verenigingen.services.communication.email_configuration_service import (
            get_email_configuration_service,
        )

        self.assertTrue(get_email_configuration_service().is_notification_enabled(KEY))
        self.assertTrue(frappe.db.exists("Email Template", TEMPLATE))
        member, _ = self._apply_for_sepa_and_approve()
        dashboard_mails = [m for m in self._signature_mails() if "/payment_dashboard" in (m.get("content") or "")]
        self.assertEqual(len(dashboard_mails), 1, "the mail links to the dashboard where the member signs")

    def test_disabled_key_sends_no_request_and_does_not_fail_approval(self):
        config = frappe.get_single("Verenigingen Email Configuration")
        row = next(r for r in config.notification_types if r.notification_key == KEY)
        row.enabled = 0
        config.save()
        member, response = self._apply_for_sepa_and_approve()

        self.assertEqual(self._signature_mails(), [])
        self.assertEqual(frappe.db.get_value("Member", member, "status"), "Active")
        self.assertEqual(self._mandates(member), [])

    def test_bank_transfer_applicant_is_not_asked_to_sign(self):
        """Control: the request keys on SEPA Direct Debit, not on every approval."""
        application = self._stage_and_confirm(payment_method="Bank Transfer")
        response = self._approve_spied(application)

        self.assertEqual(self._signature_mails(), [])
        self.assertFalse(member_needs_mandate_signature(response["member"]))

    def test_reapplication_with_changed_iban_the_issue_scenario(self):
        """Member with IBAN A and an Active mandate, voluntarily terminated; reapplies with IBAN B."""
        member = self.create_test_member(email=self.email, iban=IBAN)
        old = self.create_test_sepa_mandate(member=member.name, iban=IBAN)
        self.assertEqual(frappe.db.get_value("SEPA Mandate", old.name, "status"), "Active")
        execute_real_termination(self, member.name, frappe.utils.today())
        self.assertEqual(frappe.db.get_value("SEPA Mandate", old.name, "status"), "Cancelled")

        application = self._stage_and_confirm(
            iban=OTHER_IBAN, bank_account_name="A. Applicant", payment_method="SEPA Direct Debit"
        )
        self._approve_spied(application)

        rows = self._mandates(member.name)
        self.assertEqual([(r.name, r.status) for r in rows], [(old.name, "Cancelled")], "old mandate untouched, none new")
        self.assertEqual(rows[0].iban.replace(" ", ""), IBAN)
        self.assertEqual(frappe.db.get_value("Member", member.name, "iban").replace(" ", ""), OTHER_IBAN)
        self.assertEqual(len(self._signature_mails()), 1)
        self.assertTrue(self._dashboard_context(member.name).mandate_to_sign)

    # -- the dashboard ------------------------------------------------------------------------------

    def test_dashboard_shows_the_mandate_to_sign_until_signed(self):
        member, _ = self._apply_for_sepa_and_approve()
        context = self._dashboard_context(member)
        self.assertTrue(context.mandate_to_sign)
        self.assertIsNone(context.current_mandate)
        self.assertFalse(context.mandate_ambiguous)

        result = self._sign_as_member(member, IBAN)
        self.assertTrue(result.get("success"), result)

        context = self._dashboard_context(member)
        self.assertFalse(context.mandate_to_sign)
        self.assertIsNotNone(context.current_mandate)

    def test_signing_through_the_existing_path_yields_exactly_one_active_mandate(self):
        member, _ = self._apply_for_sepa_and_approve()

        result = self._sign_as_member(member, IBAN)
        self.assertTrue(result.get("success"), result)

        active = self._mandates(member, status="Active", used_for_memberships=1)
        self.assertEqual(len(active), 1, active)
        self.assertEqual(active[0].iban.replace(" ", ""), IBAN)
        again = self._sign_as_member(member, IBAN)  # signing twice must not manufacture a second Active one
        self.assertTrue(again.get("success"), again)
        self.assertEqual(len(self._mandates(member, status="Active", used_for_memberships=1)), 1)

    def test_signing_a_replacement_supersedes_the_old_mandate(self):
        """#607: whatever signing does, two Active same-purpose mandates must not result."""
        member, _ = self._apply_for_sepa_and_approve()
        self._sign_as_member(member, IBAN)
        self._sign_as_member(member, OTHER_IBAN)

        rows = self._mandates(member)
        self.assertEqual(sorted(r.status for r in rows), ["Active", "Cancelled"], rows)

    # -- the helper's other states ------------------------------------------------------------------

    def test_member_with_an_active_mandate_needs_no_signature(self):
        member = self.create_test_member(
            email=self.email, iban=IBAN, payment_method="SEPA Direct Debit", bank_account_name="A. Applicant"
        )
        self.assertTrue(member_needs_mandate_signature(member.name), "control: no mandate yet")
        self.create_test_sepa_mandate(member=member.name, iban=IBAN)
        self.assertFalse(member_needs_mandate_signature(member.name))

    def test_a_donation_only_mandate_does_not_cover_dues(self):
        """The mandate must be a MEMBERSHIP one: a member whose only Active mandate is donation-only still
        has to sign for dues (a helper counting any Active mandate would say 'no signature needed')."""
        member = self.create_test_member(
            email=self.email, iban=IBAN, payment_method="SEPA Direct Debit", bank_account_name="A. Applicant"
        )
        donation = self.create_test_sepa_mandate(
            member=member.name, iban=IBAN, used_for_memberships=0, used_for_donations=1
        )
        self.assertEqual(
            [(r.name, r.status) for r in self._mandates(member.name, status="Active")],
            [(donation.name, "Active")],
            "control: the donation mandate is Active",
        )

        self.assertTrue(member_needs_mandate_signature(member.name))
        self.assertTrue(self._dashboard_context(member.name).mandate_to_sign)

    def test_two_active_mandates_are_not_a_request_for_a_signature(self):
        """#607: a member with two Active same-purpose mandates is 'needs attention', not 'sign'. The state is
        legacy-only (a doctype guard refuses a second Active row), so the second row skips the guard with a raw
        write, stated."""
        member = self.create_test_member(
            email=self.email, iban=IBAN, payment_method="SEPA Direct Debit", bank_account_name="A. Applicant"
        )
        first = self.create_test_sepa_mandate(member=member.name, iban=IBAN)
        second = self.create_test_sepa_mandate(
            member=member.name, iban=OTHER_IBAN, used_for_memberships=0, used_for_donations=1
        )
        frappe.db.set_value("SEPA Mandate", second.name, {"used_for_memberships": 1})
        self.assertEqual(len(self._mandates(member.name, status="Active")), 2, f"control: {first.name}")

        self.assertFalse(member_needs_mandate_signature(member.name))
        context = self._dashboard_context(member.name)
        self.assertTrue(context.mandate_ambiguous)
        self.assertFalse(context.mandate_to_sign)

    # -- the pages render the state -----------------------------------------------------------------

    def _render_page(self, page, member_name):
        """get_context as the member, then the real template's page_content block. `current_schedule` is set on the dues page when
        approval left no Membership Dues Schedule (its notice sits inside `{% if current_schedule %}`)."""
        from verenigingen.templates.pages import my_dues_schedule

        module = {"payment_dashboard": payment_dashboard, "my_dues_schedule": my_dues_schedule}[page]
        user = self._link_member_to_user(frappe.get_doc("Member", member_name))
        with self._as_user(user.name):
            context = module.get_context(frappe._dict())
            if page == "my_dues_schedule" and not context.get("current_schedule"):
                context["current_schedule"] = frappe._dict(name="stand-in", billing_frequency="Monthly")
            path = frappe.get_app_path("verenigingen", "templates", "pages", f"{page}.html")
            with open(path) as handle:
                source = handle.read()
            # Only the page's own block: the portal base layout needs the website router's boot context.
            body = source.split("{% block page_content %}", 1)[1].split("{% block script %}")[0]
            return frappe.render_template(body[: body.rindex("{% endblock %}")], context)

    def test_pages_render_the_signature_state_until_signed(self):
        member, _ = self._apply_for_sepa_and_approve()
        for page in ("payment_dashboard", "my_dues_schedule"):
            self.assertIn('id="sepa-sign-notice"', self._render_page(page, member), page)

        self._sign_as_member(member, IBAN)

        for page in ("payment_dashboard", "my_dues_schedule"):
            self.assertNotIn('id="sepa-sign-notice"', self._render_page(page, member), f"{page} after signing")
