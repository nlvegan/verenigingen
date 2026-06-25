# -*- coding: utf-8 -*-
"""
Integration tests for the dues-schedule template services:
  - verenigingen/services/billing/template_creation_service.py
  - verenigingen/services/billing/template_configuration_service.py

template_creation_service.TemplateCreationService:
  - create_default_template (standard config + back-link to membership type)
  - create_from_template (explicit template, membership-type, auto-detect;
    not-a-template throw, no-template-assigned throw, duplicate-schedule throw,
    dues-rate priority: user-selected > CSV > template; below-min user rate throw)

template_configuration_service:
  - load_template_for_membership_type (required throw vs optional None)
  - TemplateConfigurationService.get_template_values (no membership_type defaults,
    no template defaults, value retrieval, membership-type-minimum enforcement,
    below-minimum effective amount throw, skip_validation bypass)

Real DocTypes throughout; no business logic mocked. Fixtures are uniquely named,
tracked, and force-deleted in tearDown (create_from_template commits via
db.set_value on the member).
"""

import frappe
from frappe.utils import today

from verenigingen.services.billing.template_configuration_service import (
    TemplateConfigurationService,
    get_template_configuration_service,
    load_template_for_membership_type,
)
from verenigingen.services.billing.template_creation_service import (
    TemplateCreationService,
    get_template_creation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestTemplateServices(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.create_svc = TemplateCreationService()
        self.config_svc = TemplateConfigurationService()
        self._committed_docs = []

    def tearDown(self):
        order = {
            "Membership Dues Schedule": 0,
            "Membership": 1,
            "Member": 2,
            "Membership Type": 3,
        }
        for doctype, name in sorted(self._committed_docs, key=lambda dn: order.get(dn[0], 9)):
            if frappe.db.exists(doctype, name):
                try:
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
                except Exception:
                    pass
        frappe.db.commit()
        super().tearDown()

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------
    def _make_membership_type(self, minimum_amount=12.0, with_template=True, suggested=None):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"TSVC-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Template service test type"
        mt.is_active = 1
        mt.contribution_mode = "Fixed Amount"
        mt.minimum_amount = minimum_amount
        mt.role_profile = role_profile
        mt.save()
        self._committed_docs.append(("Membership Type", mt.name))

        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": mt.name},
            "name",
        )
        if template:
            self._committed_docs.append(("Membership Dues Schedule", template))
            tdoc = frappe.get_doc("Membership Dues Schedule", template)
            tdoc.suggested_amount = suggested if suggested is not None else minimum_amount
            tdoc.dues_rate = minimum_amount
            tdoc.minimum_amount = minimum_amount
            tdoc.billing_frequency = "Monthly"
            tdoc.invoice_days_before = 15
            tdoc.currency = "EUR"
            tdoc.save(ignore_permissions=True)
        if not with_template:
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", None)
            mt.reload()
        frappe.db.commit()
        mt.reload()
        return mt

    def _make_member_with_membership(self, mt, dues_rate=None, csv_fee=None, csv_reason=None):
        member = frappe.new_doc("Member")
        member.first_name = "Template"
        member.last_name = f"M{frappe.generate_hash(length=6)}"
        member.email = f"tsvc.{frappe.generate_hash(length=8)}@example.com"
        member.member_since = today()
        member.birth_date = "1990-01-01"
        if dues_rate is not None:
            member.dues_rate = dues_rate
        if csv_fee is not None:
            member.csv_import_custom_fee = csv_fee
        if csv_reason is not None:
            member.csv_import_custom_fee_reason = csv_reason
        member.save()
        frappe.db.commit()
        self._committed_docs.append(("Member", member.name))

        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = mt.name
        membership.start_date = today()
        membership.status = "Active"
        membership.flags.skip_dues_schedule_creation = True
        membership.insert(ignore_permissions=True)
        self._committed_docs.append(("Membership", membership.name))
        membership.flags.skip_dues_schedule_creation = True
        membership.submit()
        # Cancel any auto-created schedule so create_from_template won't hit the
        # "already has a schedule" guard unintentionally.
        for nm in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", nm))
            frappe.db.set_value("Membership Dues Schedule", nm, "status", "Cancelled")
            frappe.delete_doc("Membership Dues Schedule", nm, force=True, ignore_permissions=True)
        frappe.db.commit()
        return member, membership

    def _track_schedule(self, member_name):
        for nm in frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "is_template": 0},
            pluck="name",
        ):
            self._committed_docs.append(("Membership Dues Schedule", nm))

    # ==================================================================
    # create_default_template
    # ==================================================================
    def test_create_default_template_config_and_backlink(self):
        # A membership type WITHOUT a template (suppress the auto one).
        mt = self._make_membership_type(minimum_amount=5.0, with_template=False)
        template = self.create_svc.create_default_template(mt.name)
        self._committed_docs.append(("Membership Dues Schedule", template.name))
        self.assertEqual(template.is_template, 1)
        self.assertEqual(template.billing_frequency, "Annual")
        self.assertEqual(template.contribution_mode, "Income-Based")
        self.assertEqual(template.suggested_amount, 15.0)
        self.assertEqual(template.invoice_days_before, 30)
        # Back-linked to the membership type.
        self.assertEqual(
            frappe.db.get_value("Membership Type", mt.name, "dues_schedule_template"),
            template.name,
        )

    # ==================================================================
    # create_from_template — selection paths
    # ==================================================================
    def test_create_from_explicit_template(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, membership = self._make_member_with_membership(mt)
        name = self.create_svc.create_from_template(
            member_name=member.name,
            template_name=mt.dues_schedule_template,
            membership_name=membership.name,
        )
        self._track_schedule(member.name)
        sched = frappe.get_doc("Membership Dues Schedule", name)
        self.assertEqual(sched.member, member.name)
        self.assertEqual(sched.is_template, 0)
        self.assertEqual(sched.template_reference, mt.dues_schedule_template)
        self.assertEqual(sched.membership, membership.name)
        # Template dues_rate (10.0) used as fallback (no user/CSV rate).
        self.assertEqual(sched.dues_rate, 10.0)
        # Member back-link updated.
        self.assertEqual(frappe.db.get_value("Member", member.name, "current_dues_schedule"), name)

    def test_create_from_membership_type(self):
        mt = self._make_membership_type(minimum_amount=14.0)
        member, _ = self._make_member_with_membership(mt)
        name = self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self._track_schedule(member.name)
        sched = frappe.get_doc("Membership Dues Schedule", name)
        self.assertEqual(sched.dues_rate, 14.0)

    def test_create_from_template_auto_detect(self):
        mt = self._make_membership_type(minimum_amount=11.0)
        member, _ = self._make_member_with_membership(mt)
        # No template_name and no membership_type -> auto-detect from membership.
        name = self.create_svc.create_from_template(member_name=member.name)
        self._track_schedule(member.name)
        sched = frappe.get_doc("Membership Dues Schedule", name)
        self.assertEqual(sched.membership_type, mt.name)
        self.assertEqual(sched.dues_rate, 11.0)

    # ==================================================================
    # create_from_template — dues-rate priority
    # ==================================================================
    def test_user_selected_rate_takes_priority(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, _ = self._make_member_with_membership(mt, dues_rate=33.0)
        name = self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self._track_schedule(member.name)
        sched = frappe.get_doc("Membership Dues Schedule", name)
        self.assertEqual(sched.dues_rate, 33.0)

    def test_user_rate_below_template_minimum_throws(self):
        mt = self._make_membership_type(minimum_amount=20.0)
        member, _ = self._make_member_with_membership(mt, dues_rate=5.0)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self.assertIn("less than the minimum", str(cm.exception))

    def test_csv_custom_amount_used_when_no_user_rate(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, _ = self._make_member_with_membership(mt, csv_fee=18.5, csv_reason="legacy import")
        name = self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self._track_schedule(member.name)
        sched = frappe.get_doc("Membership Dues Schedule", name)
        self.assertEqual(sched.dues_rate, 18.5)

    # ==================================================================
    # create_from_template — rejection paths
    # ==================================================================
    def test_not_a_template_throws(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, _ = self._make_member_with_membership(mt)
        # Create a real NON-template schedule and pass it as template_name.
        non_template = self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self._track_schedule(member.name)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.create_svc.create_from_template(member_name=member.name, template_name=non_template)
        self.assertIn("is not a template", str(cm.exception))

    def test_membership_type_without_template_throws(self):
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        member, _ = self._make_member_with_membership(mt)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self.assertIn("no dues schedule template", str(cm.exception))

    def test_duplicate_schedule_throws(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member, _ = self._make_member_with_membership(mt)
        self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self._track_schedule(member.name)
        # Second creation -> existing schedule guard.
        with self.assertRaises(frappe.ValidationError) as cm:
            self.create_svc.create_from_template(member_name=member.name, membership_type=mt.name)
        self.assertIn("already has a dues schedule", str(cm.exception))

    def test_auto_detect_no_active_membership_throws(self):
        member = self.create_test_member()  # no membership
        with self.assertRaises(frappe.ValidationError) as cm:
            self.create_svc.create_from_template(member_name=member.name)
        self.assertIn("no active membership", str(cm.exception))

    # ==================================================================
    # load_template_for_membership_type
    # ==================================================================
    def test_load_template_required_throws_when_missing(self):
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        with self.assertRaises(frappe.ValidationError) as cm:
            load_template_for_membership_type(mt.name, required=True)
        self.assertIn("no dues schedule template", str(cm.exception))

    def test_load_template_optional_returns_none_when_missing(self):
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        self.assertIsNone(load_template_for_membership_type(mt.name, required=False))

    def test_load_template_returns_template_doc(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        template = load_template_for_membership_type(mt.name, required=True)
        self.assertEqual(template.name, mt.dues_schedule_template)
        self.assertEqual(template.is_template, 1)

    # ==================================================================
    # get_template_values
    # ==================================================================
    def test_get_template_values_no_membership_type_returns_defaults(self):
        doc = frappe.new_doc("Membership Dues Schedule")
        values = self.config_svc.get_template_values(doc, membership_type=None)
        self.assertEqual(values["minimum_amount"], 0)
        self.assertEqual(values["billing_frequency"], "Annual")
        self.assertEqual(values["invoice_days_before"], 30)

    def test_get_template_values_no_template_returns_defaults(self):
        mt = self._make_membership_type(minimum_amount=10.0, with_template=False)
        doc = frappe.new_doc("Membership Dues Schedule")
        values = self.config_svc.get_template_values(doc, membership_type=mt.name)
        # No template assigned -> default values returned.
        self.assertEqual(values["billing_frequency"], "Annual")

    def test_get_template_values_reads_template(self):
        mt = self._make_membership_type(minimum_amount=16.0)
        doc = frappe.new_doc("Membership Dues Schedule")
        values = self.config_svc.get_template_values(doc, membership_type=mt.name)
        self.assertEqual(values["minimum_amount"], 16.0)
        self.assertEqual(values["suggested_amount"], 16.0)
        self.assertEqual(values["billing_frequency"], "Monthly")
        self.assertEqual(values["invoice_days_before"], 15)

    def test_get_template_values_enforces_membership_type_minimum(self):
        # Template minimum below membership-type minimum -> bumped up to the type's.
        mt = self._make_membership_type(minimum_amount=10.0)
        # Lower the TEMPLATE minimum below the membership type's minimum, but keep
        # the effective amount (dues_rate/suggested) >= type minimum so no throw.
        template_name = mt.dues_schedule_template
        frappe.db.set_value("Membership Dues Schedule", template_name, "minimum_amount", 3.0)
        frappe.db.commit()
        doc = frappe.new_doc("Membership Dues Schedule")
        values = self.config_svc.get_template_values(doc, membership_type=mt.name)
        self.assertEqual(values["minimum_amount"], 10.0)

    def test_get_template_values_below_minimum_effective_amount_throws(self):
        mt = self._make_membership_type(minimum_amount=20.0)
        # Force template dues_rate + suggested below the membership-type minimum.
        template_name = mt.dues_schedule_template
        frappe.db.set_value(
            "Membership Dues Schedule",
            template_name,
            {"dues_rate": 5.0, "suggested_amount": 5.0, "minimum_amount": 5.0},
        )
        frappe.db.commit()
        doc = frappe.new_doc("Membership Dues Schedule")
        with self.assertRaises(frappe.ValidationError) as cm:
            self.config_svc.get_template_values(doc, membership_type=mt.name)
        self.assertIn("cannot be less than", str(cm.exception))

    def test_get_template_values_skip_validation_bypasses_throw(self):
        mt = self._make_membership_type(minimum_amount=20.0)
        template_name = mt.dues_schedule_template
        frappe.db.set_value(
            "Membership Dues Schedule",
            template_name,
            {"dues_rate": 5.0, "suggested_amount": 5.0, "minimum_amount": 5.0},
        )
        frappe.db.commit()
        doc = frappe.new_doc("Membership Dues Schedule")
        # skip_validation=True -> no throw despite below-minimum amount.
        values = self.config_svc.get_template_values(doc, membership_type=mt.name, skip_validation=True)
        self.assertEqual(values["suggested_amount"], 5.0)

    # ==================================================================
    # singleton accessors
    # ==================================================================
    def test_singleton_accessors(self):
        self.assertIsInstance(get_template_creation_service(), TemplateCreationService)
        self.assertIsInstance(get_template_configuration_service(), TemplateConfigurationService)
