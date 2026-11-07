"""Shared fixture for tests that need a member whose Membership Type frequency
differs from the frequency of the live Membership Dues Schedule that bills them
(#1909, #1934)."""

import frappe
from frappe.utils import add_days, today


class ScheduleFrequencyFixtureMixin:
    """Mix into a VereningingenTestCase."""

    def _create_schedule_test_member(self, first_name="SchedFreq"):
        """An Active member with a customer, unique name and email."""
        member = self.create_test_member(
            first_name=first_name,
            last_name=f"Member{frappe.generate_hash(length=4)}",
            email=f"{first_name.lower()}.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
            auto_create_customer=True,
        )
        member.reload()
        return member

    def _submit_membership_via_template(
        self, member, type_period, template_frequency, start_date=None, skip_schedule=False
    ):
        """Submit a Membership for `member` under a new Membership Type whose billing_period is
        `type_period`, after saving the Type's auto-created template with `template_frequency`.
        Submitting creates the member's schedule from that template (not when `skip_schedule`).
        `start_date` defaults to 120 days ago."""
        membership_type = self.create_test_membership_type(billing_period=type_period)
        template = frappe.db.get_value(
            "Membership Dues Schedule", {"is_template": 1, "membership_type": membership_type.name}
        )
        template_doc = frappe.get_doc("Membership Dues Schedule", template)
        template_doc.billing_frequency = template_frequency
        template_doc.save()
        membership = self.create_test_membership(member=member.name, membership_type=membership_type.name)
        membership.start_date = start_date or add_days(today(), -120)
        membership.flags.skip_dues_schedule_creation = skip_schedule
        membership.submit()
        return membership

    def _member_billed_by_template(self, type_period, template_frequency, start_date=None):
        """Member with an Active schedule built from a template saved with
        `template_frequency`, under a Membership Type whose billing_period is
        `type_period`. Goes through the normal path: the Type's auto-created template is
        saved, then submitting a Membership creates the member's schedule from it.
        `start_date` defaults to 120 days ago."""
        member = self._create_schedule_test_member()
        membership = self._submit_membership_via_template(
            member, type_period, template_frequency, start_date
        )
        membership_type = frappe.get_doc("Membership Type", membership.membership_type)
        schedule = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member.name, "status": "Active", "is_template": 0},
            ["name", "billing_frequency"],
            as_dict=True,
        )
        return member, membership_type, schedule
