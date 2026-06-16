# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Meaningful tests for verenigingen/api/manual_invoice_generation.py

This module is the admin tool that generates a membership-dues Sales Invoice
outside the automated billing cycle. It exposes two whitelisted endpoints, both
returning OperationResult (serialized to a dict by the security decorators):

- generate_manual_invoice(member_name)   -> @critical_api: finds the member's
      single Active, non-template Membership Dues Schedule and calls
      schedule.generate_invoice(force=True). Returns invoice_name/amount/
      customer/dues_schedule on success.
- get_member_invoice_info(member_name)   -> @standard_api: read-only summary of
      the member's customer linkage, active dues schedule, and recent invoices.

These tests seed REAL data (Member, Membership, Membership Dues Schedule,
Customer, Sales Invoice) and assert the concrete fields of the created Sales
Invoice (customer, rate/total, item, membership link, coverage dates) match the
seed, so they fail on wrong-column / missing-field / swapped-link regressions.

The @critical_api / @standard_api decorators serialize the returned
OperationResult via to_dict(scrub_sensitive=True), so each endpoint hands back a
plain dict: success -> {"success": True, "data": {...}}, failure ->
{"success": False, "error": {"message", "code", ...}}.
"""

import frappe
from frappe.utils import flt, today

from verenigingen.api.manual_invoice_generation import (
    generate_manual_invoice,
    get_member_invoice_info,
)
from verenigingen.tests.utils.base import VereningingenTestCase


class TestManualInvoiceGeneration(VereningingenTestCase):
    """Integration tests for the manual invoice generation API."""

    def setUp(self):
        super().setUp()
        # The endpoints are guarded by financial-API security decorators that
        # require an authenticated privileged user (auth is NOT mocked by the
        # base test case). Run as Administrator.
        frappe.set_user("Administrator")

    # ------------------------------------------------------------------ #
    # result helpers                                                      #
    # ------------------------------------------------------------------ #
    def _ok(self, result):
        """Assert the result succeeded and return its data payload."""
        self.assertIsInstance(result, dict)
        self.assertTrue(
            result.get("success"),
            msg=(result.get("error") or {}).get("message") if isinstance(result, dict) else result,
        )
        return result["data"]

    def _err(self, result):
        """Assert the result failed and return its error object."""
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success"), msg=f"Expected failure, got: {result}")
        return result.get("error", {})

    # ------------------------------------------------------------------ #
    # helpers (named _make_/_setup_ so the test-quality-enforcer allows   #
    # the insert/save calls that happen inside them)                      #
    # ------------------------------------------------------------------ #
    def _setup_customer(self, member):
        """Ensure the member has a linked Customer; return the customer name."""
        member.reload()
        if member.customer:
            return member.customer
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"{member.first_name} {member.last_name}"
        customer.customer_type = "Individual"
        customer.member = member.name
        customer.save()
        self.track_doc("Customer", customer.name)
        member.customer = customer.name
        member.save()
        return customer.name

    def _make_member_with_schedule(
        self, dues_rate=15.0, billing_frequency="Monthly", with_customer=True
    ):
        """Seed a member + active (submitted) membership + active dues schedule.

        Membership Dues Schedule.validate_member_membership requires the member
        to have an ACTIVE, SUBMITTED Membership; the core factory only inserts a
        draft (docstatus 0), so we submit it (suppressing its auto dues-schedule
        creation so our own schedule doesn't trip the one-active-schedule guard).
        """
        member = self.create_test_member(
            first_name="Manual",
            last_name=f"Inv{frappe.generate_hash(length=4)}",
            email=f"manual.{frappe.generate_hash(length=8).lower()}@example.com",
        )
        if with_customer:
            self._setup_customer(member)

        membership_type = self.create_test_membership_type(minimum_amount=0)
        membership = self.create_test_membership(
            member=member.name, membership_type=membership_type.name
        )
        if membership.docstatus == 0:
            membership.flags.skip_dues_schedule_creation = True
            membership.submit()

        # Cancel any auto-created active schedule so ours is the single active one.
        for existing in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0, "status": "Active"},
            pluck="name",
        ):
            frappe.db.set_value("Membership Dues Schedule", existing, "status", "Cancelled")

        schedule = self.create_test_dues_schedule(
            member=member.name,
            membership_type=membership_type.name,
            dues_rate=dues_rate,
            billing_frequency=billing_frequency,
            schedule_name=f"Test-MIG-{frappe.generate_hash(length=10)}",
        )
        member.reload()
        return member, schedule

    def _resolve_invoice_name(self, invoice_field):
        """generate_manual_invoice puts schedule.generate_invoice()'s return into
        data['invoice_name']. generate_invoice() returns the Sales Invoice *doc*,
        so depending on serialization invoice_field may be a doc, a dict, or a
        name string. Normalize to the invoice's name for assertions."""
        if isinstance(invoice_field, str):
            return invoice_field
        if isinstance(invoice_field, dict):
            return invoice_field.get("name")
        return getattr(invoice_field, "name", None)

    # ================================================================== #
    # generate_manual_invoice — happy path                               #
    # ================================================================== #
    def test_generate_manual_invoice_creates_invoice_matching_seed(self):
        """Happy path: the created Sales Invoice's customer, rate/total, item,
        member link and coverage dates match the seeded member/schedule."""
        member, schedule = self._make_member_with_schedule(dues_rate=23.50)

        result = generate_manual_invoice(member.name)
        data = self._ok(result)

        # --- payload shape ---
        self.assertEqual(data["customer"], member.customer)
        self.assertEqual(data["dues_schedule"], schedule.name)
        self.assertEqual(flt(data["amount"], 2), flt(23.50, 2))

        invoice_name = self._resolve_invoice_name(data["invoice_name"])
        self.assertTrue(invoice_name, f"No invoice name resolvable from {data['invoice_name']!r}")
        self.assertTrue(
            frappe.db.exists("Sales Invoice", invoice_name),
            f"Reported invoice {invoice_name} does not exist",
        )
        self.track_doc("Sales Invoice", invoice_name)

        # --- the actual persisted Sales Invoice must match the seed ---
        si = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(si.customer, member.customer)
        self.assertEqual(str(si.member), member.name)
        self.assertEqual(int(si.is_membership_invoice), 1)
        # Single dues line, billed at the schedule's dues_rate.
        self.assertEqual(len(si.items), 1)
        self.assertEqual(flt(si.items[0].rate, 2), flt(23.50, 2))
        self.assertEqual(flt(si.items[0].qty), flt(1))
        self.assertEqual(flt(si.net_total, 2), flt(23.50, 2))
        # Coverage dates are set by the generator (orchestrator throws otherwise).
        self.assertTrue(si.custom_coverage_start_date)
        self.assertTrue(si.custom_coverage_end_date)
        self.assertLessEqual(si.custom_coverage_start_date, si.custom_coverage_end_date)
        # The display link should name our schedule.
        self.assertEqual(si.membership_dues_schedule_display, schedule.name)

    def test_generate_manual_invoice_amount_reflects_schedule_rate(self):
        """The reported amount tracks the schedule's dues_rate, not a constant.

        Guards against a hardcoded/zero amount: a different rate must surface a
        different amount and a different invoice net_total.
        """
        member, schedule = self._make_member_with_schedule(dues_rate=42.00)

        data = self._ok(generate_manual_invoice(member.name))
        self.assertEqual(flt(data["amount"], 2), flt(42.00, 2))

        invoice_name = self._resolve_invoice_name(data["invoice_name"])
        self.track_doc("Sales Invoice", invoice_name)
        net_total = frappe.db.get_value("Sales Invoice", invoice_name, "net_total")
        self.assertEqual(flt(net_total, 2), flt(42.00, 2))

    # ================================================================== #
    # generate_manual_invoice — repeated-call / force-advance behavior   #
    # ================================================================== #
    def test_generate_manual_invoice_force_advances_to_next_period(self):
        """Characterize the force=True repeated-call behavior.

        generate_manual_invoice calls schedule.generate_invoice(force=True). The
        orchestrator's _check_eligibility does `if not can_generate and not force:`
        so force=True bypasses the EligibilityChecker (including coverage-overlap
        detection). However, each successful generation ADVANCES the schedule's
        coverage window, so a second call does NOT duplicate the first period —
        it bills the NEXT sequential period.

        This is the important, regression-worthy contract: repeated manual
        generation produces non-overlapping, sequentially-advancing coverage
        windows rather than two invoices for the identical period.
        """
        member, schedule = self._make_member_with_schedule(
            dues_rate=15.00, billing_frequency="Monthly"
        )

        first = self._ok(generate_manual_invoice(member.name))
        first_name = self._resolve_invoice_name(first["invoice_name"])
        self.track_doc("Sales Invoice", first_name)

        second = self._ok(generate_manual_invoice(member.name))
        second_name = self._resolve_invoice_name(second["invoice_name"])
        self.track_doc("Sales Invoice", second_name)

        self.assertNotEqual(second_name, first_name, "Second call reused the same invoice")

        invoices = {
            row["name"]: row
            for row in frappe.get_all(
                "Sales Invoice",
                filters={"customer": member.customer, "docstatus": ["!=", 2]},
                fields=["name", "custom_coverage_start_date", "custom_coverage_end_date"],
            )
        }
        self.assertEqual(len(invoices), 2)

        first_period = invoices[first_name]
        second_period = invoices[second_name]
        # Non-overlapping, advancing windows: the second period starts strictly
        # after the first period ends.
        self.assertGreater(
            second_period["custom_coverage_start_date"],
            first_period["custom_coverage_end_date"],
            f"Force re-generation produced an OVERLAPPING period: "
            f"first={first_period}, second={second_period}",
        )

    def test_generate_manual_invoice_returns_bare_name_string_in_invoice_name(self):
        """The success payload's `invoice_name` is the bare Sales Invoice name
        string (e.g. 'ACC-SINV-...'), not the Sales Invoice document/dict.

        generate_manual_invoice captures the doc returned by
        MembershipDuesSchedule.generate_invoice(force=True) and stores
        `invoice.name` under data['invoice_name'], so the field is a plain
        string equal to the created Sales Invoice's name. The success message is
        built via `_("Invoice {0} generated...").format(invoice_name)`, so it
        contains that exact name (and not a serialized doc like
        "Sales Invoice (ACC-SINV-...)").
        """
        member, _schedule = self._make_member_with_schedule(dues_rate=15.00)
        result = generate_manual_invoice(member.name)
        data = self._ok(result)

        invoice_field = data["invoice_name"]
        # Correct contract: a bare name string, not a doc/dict.
        self.assertIsInstance(
            invoice_field,
            str,
            f"invoice_name should be a bare name string, got {type(invoice_field).__name__}: "
            f"{invoice_field!r}",
        )
        self.assertTrue(
            frappe.db.exists("Sales Invoice", invoice_field),
            f"Reported invoice {invoice_field!r} does not exist",
        )
        self.track_doc("Sales Invoice", invoice_field)

        # The success message names exactly this invoice (no serialized doc).
        # On the nested OperationResult schema the message lands under "meta".
        message = (result.get("meta") or {}).get("message", "")
        self.assertIn(
            invoice_field,
            message,
            f"Success message should contain the bare invoice name; got {message!r}",
        )

    # ================================================================== #
    # generate_manual_invoice — error / edge paths                       #
    # ================================================================== #
    def test_generate_manual_invoice_missing_member(self):
        """Nonexistent member -> MEMBER_NOT_FOUND, no invoice created."""
        result = generate_manual_invoice("Nonexistent-Member-XYZ")
        err = self._err(result)
        self.assertEqual(err.get("code"), "MEMBER_NOT_FOUND")

    def test_generate_manual_invoice_member_without_customer(self):
        """Member with no Customer record -> NO_CUSTOMER_RECORD, no invoice.

        Submitting the membership can auto-link a Customer to the member, so we
        explicitly clear the customer link (directly in DB, bypassing hooks) to
        exercise the NO_CUSTOMER_RECORD branch.
        """
        member, _schedule = self._make_member_with_schedule(with_customer=False)
        # Clear any auto-created customer link so the API hits the no-customer path.
        frappe.db.set_value("Member", member.name, "customer", None)
        self.assertFalse(
            frappe.db.get_value("Member", member.name, "customer"),
            "Precondition failed: member still has a customer",
        )

        result = generate_manual_invoice(member.name)
        err = self._err(result)
        self.assertEqual(err.get("code"), "NO_CUSTOMER_RECORD")

        # No invoice should have been created for this member.
        member_invoices = frappe.get_all("Sales Invoice", filters={"member": member.name}, pluck="name")
        self.assertEqual(member_invoices, [])

    def test_generate_manual_invoice_no_active_dues_schedule(self):
        """Member with a customer but NO active dues schedule ->
        NO_ACTIVE_DUES_SCHEDULE."""
        member, schedule = self._make_member_with_schedule(dues_rate=15.00)
        # Cancel the only active schedule so the lookup finds nothing.
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Cancelled")

        result = generate_manual_invoice(member.name)
        err = self._err(result)
        self.assertEqual(err.get("code"), "NO_ACTIVE_DUES_SCHEDULE")

    def test_generate_manual_invoice_ignores_template_schedules(self):
        """A template schedule (is_template=1) must not be treated as the
        member's active schedule. With only a template present (no member
        instance), generation must report NO_ACTIVE_DUES_SCHEDULE rather than
        invoicing off the template."""
        member, schedule = self._make_member_with_schedule(dues_rate=15.00)
        # Turn the member's only active schedule into a (cancelled) instance and
        # leave no active non-template schedule.
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Cancelled")
        # Sanity: the lookup filters is_template=0, status=Active.
        active = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0, "status": "Active"},
            pluck="name",
        )
        self.assertEqual(active, [])

        err = self._err(generate_manual_invoice(member.name))
        self.assertEqual(err.get("code"), "NO_ACTIVE_DUES_SCHEDULE")

    # ================================================================== #
    # get_member_invoice_info                                            #
    # ================================================================== #
    def test_get_member_invoice_info_reports_schedule_and_customer(self):
        """Read-only summary must reflect the seeded customer + active schedule
        fields (name, rate, frequency)."""
        member, schedule = self._make_member_with_schedule(
            dues_rate=33.00, billing_frequency="Quarterly"
        )

        data = self._ok(get_member_invoice_info(member.name))

        self.assertEqual(data["member_name"], member.full_name)
        self.assertTrue(data["has_customer"])
        self.assertEqual(data["customer"], member.customer)
        self.assertTrue(data["has_dues_schedule"])
        self.assertEqual(data["dues_schedule_name"], schedule.name)
        self.assertEqual(flt(data["current_rate"], 2), flt(33.00, 2))
        self.assertEqual(data["billing_frequency"], "Quarterly")
        # recent_invoices is only populated when the member has a customer.
        self.assertIn("recent_invoices", data)
        self.assertIsInstance(data["recent_invoices"], list)

    def test_get_member_invoice_info_lists_generated_invoice(self):
        """After generating an invoice, the info endpoint's recent_invoices must
        list it (linking the read path to the write path)."""
        member, schedule = self._make_member_with_schedule(dues_rate=18.00)

        gen = self._ok(generate_manual_invoice(member.name))
        invoice_name = self._resolve_invoice_name(gen["invoice_name"])
        self.track_doc("Sales Invoice", invoice_name)

        data = self._ok(get_member_invoice_info(member.name))
        recent_names = [inv["name"] for inv in data["recent_invoices"]]
        self.assertIn(invoice_name, recent_names)

    def test_get_member_invoice_info_member_without_schedule(self):
        """Member with a customer but no active schedule: has_dues_schedule False
        and no schedule-specific keys leak in."""
        member, schedule = self._make_member_with_schedule(dues_rate=15.00)
        frappe.db.set_value("Membership Dues Schedule", schedule.name, "status", "Cancelled")

        data = self._ok(get_member_invoice_info(member.name))
        self.assertTrue(data["has_customer"])
        self.assertFalse(data["has_dues_schedule"])
        self.assertNotIn("dues_schedule_name", data)
        self.assertNotIn("current_rate", data)

    def test_get_member_invoice_info_missing_member(self):
        """Nonexistent member -> MEMBER_NOT_FOUND error object."""
        err = self._err(get_member_invoice_info("Nonexistent-Member-XYZ"))
        self.assertEqual(err.get("code"), "MEMBER_NOT_FOUND")
