# -*- coding: utf-8 -*-
"""
Integration tests for
verenigingen/services/billing/dues_schedule_validation_service.py

Focus: the rejection / boundary paths that drive uncovered lines —
- validate_dues_rate_change (below-minimum throw, no-membership-type early-out)
- validate_dues_rate_configuration (Income-Based + Flexible auto-calc, template skip)
- validate_financial_constraints (absolute-min throw, max-limit throw vs admin warn,
  schedule.minimum_amount floor throw)
- validate_dues_rate (negative reject, exceeds-max reject, valid pass)
- validate_rate_boundaries (negative raise, new-schedule below-min raise,
  existing-schedule below-min warn-not-raise)
- validate_dates (future last-invoice auto-correct, next-before-last throw)
- validate_membership_type_consistency (mismatch reject, no-member pass)

These validators operate on a MembershipDuesSchedule document. To exercise the
service methods in isolation WITHOUT triggering the controller's full validate()
chain (which calls many of these same methods), tests build a real
`frappe.new_doc("Membership Dues Schedule")`, set the fields the method reads,
and call the service method directly. Real DocTypes / real Membership Type docs
are used throughout; no business logic is mocked.

ISOLATION: fixtures (Membership Type, template) are committed by the factory's
nature; each is uniquely named, tracked, and force-deleted in tearDown.
"""

import frappe

from verenigingen.services.billing.dues_schedule_validation_service import (
    DuesScheduleValidationService,
    get_dues_schedule_validation_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDuesScheduleValidationService(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.svc = DuesScheduleValidationService()
        self._committed_docs = []  # (doctype, name)

    def tearDown(self):
        order = {
            "Membership Dues Schedule": 0,
            "Membership Type": 1,
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
    def _make_membership_type(self, minimum_amount=12.0, with_template=True):
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": "Verenigingen Member"}
        ) or frappe.db.get_value("Role Profile", {}, "name")
        mt = frappe.new_doc("Membership Type")
        mt.membership_type_name = f"DSVS-Type-{frappe.generate_hash(length=8)}"
        mt.description = "Validation service test type"
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
            tdoc.suggested_amount = minimum_amount
            tdoc.dues_rate = minimum_amount
            tdoc.minimum_amount = minimum_amount
            tdoc.currency = "EUR"
            tdoc.save(ignore_permissions=True)
        if not with_template:
            frappe.db.set_value("Membership Type", mt.name, "dues_schedule_template", None)
            mt.reload()
        frappe.db.commit()
        return mt

    def _new_schedule(self, **fields):
        """Build an UNSAVED schedule doc carrying just the fields a validator reads."""
        doc = frappe.new_doc("Membership Dues Schedule")
        doc.is_template = 0
        for k, v in fields.items():
            setattr(doc, k, v)
        return doc

    def _as_user(self, user):
        """Switch session to a (non-admin) user — keeps set_user out of test bodies."""
        frappe.set_user(user or "Guest")

    def _as_admin(self):
        """Restore the Administrator session."""
        frappe.set_user("Administrator")

    # ==================================================================
    # validate_dues_rate_change
    # ==================================================================
    def test_rate_change_no_membership_type_returns_false(self):
        doc = self._new_schedule(membership_type=None, dues_rate=10.0)
        self.assertFalse(self.svc.validate_dues_rate_change(doc))

    def test_rate_change_below_minimum_throws(self):
        mt = self._make_membership_type(minimum_amount=25.0)
        doc = self._new_schedule(membership_type=mt.name, dues_rate=5.0)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.svc.validate_dues_rate_change(doc)
        self.assertIn("minimum contribution", str(cm.exception))
        self.assertIn("25", str(cm.exception))

    def test_rate_change_at_or_above_minimum_passes(self):
        mt = self._make_membership_type(minimum_amount=20.0)
        doc = self._new_schedule(membership_type=mt.name, dues_rate=20.0)
        self.assertTrue(self.svc.validate_dues_rate_change(doc))

    # ==================================================================
    # validate_dues_rate_configuration
    # ==================================================================
    def test_config_template_short_circuits(self):
        # is_template True -> returns without touching dues_rate
        doc = self._new_schedule(is_template=1, membership_type=None, dues_rate=None)
        self.assertIsNone(self.svc.validate_dues_rate_configuration(doc))
        self.assertIsNone(doc.dues_rate)

    def test_config_no_membership_type_short_circuits(self):
        doc = self._new_schedule(membership_type=None, dues_rate=None)
        self.svc.validate_dues_rate_configuration(doc)
        self.assertIsNone(doc.dues_rate)

    def test_config_income_based_computes_from_suggested_times_multiplier(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        # template suggested_amount == 10.0 (from fixture); multiplier 1.5 -> 15.0
        doc = self._new_schedule(
            membership_type=mt.name,
            dues_rate=None,
            contribution_mode="Income-Based",
            default_multiplier=1.5,
        )
        self.svc.validate_dues_rate_configuration(doc)
        self.assertEqual(doc.dues_rate, 15.0)

    def test_config_income_based_defaults_multiplier_to_one(self):
        mt = self._make_membership_type(minimum_amount=8.0)
        doc = self._new_schedule(
            membership_type=mt.name,
            dues_rate=None,
            contribution_mode="Income-Based",
            default_multiplier=None,
        )
        self.svc.validate_dues_rate_configuration(doc)
        # suggested_amount 8.0 * 1.0
        self.assertEqual(doc.dues_rate, 8.0)

    def test_config_flexible_falls_back_to_suggested_amount(self):
        mt = self._make_membership_type(minimum_amount=9.0)
        doc = self._new_schedule(
            membership_type=mt.name,
            dues_rate=None,
            contribution_mode="Flexible",
        )
        self.svc.validate_dues_rate_configuration(doc)
        self.assertEqual(doc.dues_rate, 9.0)

    def test_config_does_not_overwrite_explicit_rate(self):
        mt = self._make_membership_type(minimum_amount=9.0)
        doc = self._new_schedule(
            membership_type=mt.name,
            dues_rate=42.0,  # already set -> untouched
            contribution_mode="Income-Based",
            default_multiplier=2.0,
        )
        self.svc.validate_dues_rate_configuration(doc)
        self.assertEqual(doc.dues_rate, 42.0)

    # ==================================================================
    # validate_financial_constraints
    # ==================================================================
    def test_constraints_template_skips(self):
        doc = self._new_schedule(is_template=1, dues_rate=999999.0)
        # No raise even though absurdly high, because template path returns early.
        self.assertIsNone(self.svc.validate_financial_constraints(doc))

    def test_constraints_none_rate_skips(self):
        doc = self._new_schedule(dues_rate=None)
        self.assertIsNone(self.svc.validate_financial_constraints(doc))

    def test_constraints_below_absolute_minimum_throws(self):
        # 0.005 is > 0 but below the €0.01 absolute minimum.
        doc = self._new_schedule(membership_type=None, dues_rate=0.005, minimum_amount=0)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.svc.validate_financial_constraints(doc)
        self.assertIn("0.01", str(cm.exception))

    def test_constraints_exceeds_maximum_throws_for_regular_user(self):
        mt = self._make_membership_type(minimum_amount=1.0)
        member = self.create_test_member()
        doc = self._new_schedule(membership_type=mt.name, dues_rate=5000.0, minimum_amount=0)
        # Run as a regular (non-admin) member user so the max-limit branch THROWS.
        self._as_user(getattr(member, "user", None))
        try:
            with self.assertRaises(frappe.ValidationError) as cm:
                self.svc.validate_financial_constraints(doc)
            self.assertIn("maximum limit", str(cm.exception))
        finally:
            self._as_admin()

    def test_constraints_below_schedule_minimum_amount_throws(self):
        # dues_rate above absolute min and below max, but below the schedule's own
        # minimum_amount field -> dedicated throw branch.
        doc = self._new_schedule(membership_type=None, dues_rate=5.0, minimum_amount=20.0)
        with self.assertRaises(frappe.ValidationError) as cm:
            self.svc.validate_financial_constraints(doc)
        self.assertIn("cannot be less than minimum amount", str(cm.exception))

    def test_constraints_valid_rate_passes(self):
        mt = self._make_membership_type(minimum_amount=5.0)
        doc = self._new_schedule(membership_type=mt.name, dues_rate=25.0, minimum_amount=5.0)
        self.assertIsNone(self.svc.validate_financial_constraints(doc))

    # ==================================================================
    # validate_dues_rate (returns dict, never throws)
    # ==================================================================
    def test_dues_rate_negative_rejected(self):
        doc = self._new_schedule(dues_rate=-1.0)
        result = self.svc.validate_dues_rate(doc)
        self.assertFalse(result["valid"])
        self.assertIn("cannot be negative", result["reason"])

    def test_dues_rate_none_rejected(self):
        doc = self._new_schedule(dues_rate=None)
        result = self.svc.validate_dues_rate(doc)
        self.assertFalse(result["valid"])

    def test_dues_rate_exceeds_max_reasonable_rejected(self):
        doc = self._new_schedule(dues_rate=999999.0, last_generated_invoice=None)
        result = self.svc.validate_dues_rate(doc)
        self.assertFalse(result["valid"])
        self.assertIn("exceeds max", result["reason"])

    def test_dues_rate_zero_allowed_for_free_membership(self):
        doc = self._new_schedule(dues_rate=0, last_generated_invoice=None)
        result = self.svc.validate_dues_rate(doc)
        self.assertTrue(result["valid"])

    def test_dues_rate_normal_passes(self):
        doc = self._new_schedule(dues_rate=50.0, last_generated_invoice=None)
        result = self.svc.validate_dues_rate(doc)
        self.assertTrue(result["valid"])
        self.assertEqual(result["reason"], "Rate validation passed")

    # ==================================================================
    # validate_rate_boundaries
    # ==================================================================
    def test_boundaries_template_skips(self):
        doc = self._new_schedule(is_template=1, dues_rate=-5.0)
        self.assertIsNone(self.svc.validate_rate_boundaries(doc))

    def test_boundaries_negative_raises_invalid_dues_rate(self):
        from verenigingen.utils.exceptions import InvalidDuesRateError

        doc = self._new_schedule(membership_type=None, dues_rate=-3.0)
        with self.assertRaises(InvalidDuesRateError) as cm:
            self.svc.validate_rate_boundaries(doc)
        self.assertIn("cannot be negative", str(cm.exception))

    def test_boundaries_new_schedule_below_min_raises(self):
        from verenigingen.utils.exceptions import InvalidDuesRateError

        mt = self._make_membership_type(minimum_amount=30.0)
        doc = self._new_schedule(membership_type=mt.name, dues_rate=5.0)
        # New (unsaved) schedule: must comply -> raise.
        with self.assertRaises(InvalidDuesRateError) as cm:
            self.svc.validate_rate_boundaries(doc)
        self.assertIn("below minimum required", str(cm.exception))

    def test_boundaries_skip_minimum_validation_flag_bypasses(self):
        mt = self._make_membership_type(minimum_amount=30.0)
        doc = self._new_schedule(membership_type=mt.name, dues_rate=5.0)
        doc._skip_minimum_validation = True
        # Should NOT raise despite being below minimum.
        self.assertIsNone(self.svc.validate_rate_boundaries(doc))

    # ==================================================================
    # validate_membership_type_consistency
    # ==================================================================
    def test_consistency_no_member_passes(self):
        doc = self._new_schedule(member=None, membership_type=None)
        result = self.svc.validate_membership_type_consistency(doc)
        self.assertTrue(result["valid"])

    def test_consistency_mismatch_rejected(self):
        # Member with active membership of type A; schedule claims type B.
        mt_a = self._make_membership_type(minimum_amount=10.0)
        mt_b = self._make_membership_type(minimum_amount=10.0)
        member = self.create_test_member()
        self.create_test_membership(member_name=member.name, membership_type_name=mt_a.name)
        doc = self._new_schedule(member=member.name, membership_type=mt_b.name)
        result = self.svc.validate_membership_type_consistency(doc)
        self.assertFalse(result["valid"])
        self.assertIn("Type mismatch", result["reason"])

    def test_consistency_match_passes(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member = self.create_test_member()
        self.create_test_membership(member_name=member.name, membership_type_name=mt.name)
        doc = self._new_schedule(member=member.name, membership_type=mt.name)
        result = self.svc.validate_membership_type_consistency(doc)
        self.assertTrue(result["valid"])

    def test_consistency_no_active_membership_passes(self):
        mt = self._make_membership_type(minimum_amount=10.0)
        member = self.create_test_member()  # no membership
        doc = self._new_schedule(member=member.name, membership_type=mt.name)
        result = self.svc.validate_membership_type_consistency(doc)
        self.assertTrue(result["valid"])
        self.assertIn("No active membership", result["reason"])

    # ==================================================================
    # validate_dates
    # ==================================================================
    def test_dates_future_last_invoice_auto_corrected(self):
        from frappe.utils import add_days, getdate, today

        future = add_days(today(), 10)
        doc = self._new_schedule(
            last_invoice_date=future,
            next_invoice_date=add_days(today(), 40),
            last_invoice_coverage_end=None,
        )
        self.svc.validate_dates(doc)
        self.assertEqual(getdate(doc.last_invoice_date), getdate(today()))

    def test_dates_next_before_last_throws(self):
        from frappe.utils import add_days, today

        doc = self._new_schedule(
            last_invoice_date=today(),
            next_invoice_date=add_days(today(), -5),
            last_invoice_coverage_end=None,
        )
        with self.assertRaises(frappe.ValidationError) as cm:
            self.svc.validate_dates(doc)
        self.assertIn("cannot be before", str(cm.exception))

    # ==================================================================
    # singleton accessor
    # ==================================================================
    def test_singleton_accessor_returns_service(self):
        self.assertIsInstance(get_dues_schedule_validation_service(), DuesScheduleValidationService)
