# Copyright (c) 2025, Veganisme.org and contributors
# For license information, please see license.txt

"""
Real-DB integration tests for the services/member/financial cluster:

- FeeChangeRecordingService   (record dedup filters + real entry creation)
- FeeOverrideHookService      (skip-processing guards + pending-change flow)
- MemberFeeCalculationService (override precedence, template, none, display)
- MemberItemService           (membership item get-or-create, item group)
- MemberFeeValidationService  (amount/reason/permission validation)

These services mutate the real fee_change_history child table and read real
Member/Membership/Item rows, so assertions check persisted DB state and exact
exception messages, not mocks.
"""

import frappe
from frappe.utils import flt

from verenigingen.services.member.financial.fee_change_recording_service import (
    DEDUP_WINDOW_SECONDS,
    get_fee_change_recording_service,
)
from verenigingen.services.member.financial.fee_override_hook_service import (
    get_fee_override_hook_service,
)
from verenigingen.services.member.financial.member_fee_calculation_service import (
    get_member_fee_calculation_service,
)
from verenigingen.services.member.financial.member_fee_validation_service import (
    get_member_fee_validation_service,
)
from verenigingen.services.member.financial.member_item_service import (
    get_member_item_service,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFeeChangeRecordingServiceRealDB(EnhancedTestCase):
    """record() dedup filters + real fee_change_history persistence."""

    def setUp(self):
        super().setUp()
        self.service = get_fee_change_recording_service()
        self.member = self.create_test_member(first_name="Rec", last_name="Fee")

    def _history_rows(self):
        self.member.reload()
        return self.member.fee_change_history or []

    def test_record_creates_entry(self):
        """A genuine change creates a fee_change_history row with old/new amounts."""
        result = self.service.record(
            member=self.member.name,
            old_amount=10.0,
            new_amount=25.0,
            change_type="Fee Adjustment",
            reason="Annual increase",
        )
        self.assertEqual(result.status, "created")
        rows = self._history_rows()
        match = [r for r in rows if flt(r.new_dues_rate) == 25.0 and flt(r.old_dues_rate) == 10.0]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].reason, "Annual increase")

    def test_record_skips_no_actual_change(self):
        """old == new is rejected as no actual change (Filter 1)."""
        result = self.service.record(member=self.member.name, old_amount=15.0, new_amount=15.0)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.message, "No actual change in amount")

    def test_record_skips_when_already_at_target(self):
        """If member.dues_rate already equals new_amount, change is skipped (Filter 2)."""
        # Persist the member already at the target rate via a privileged helper.
        self._set_member_rate(30.0)
        result = self.service.record(member=self.member.name, old_amount=10.0, new_amount=30.0)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.message, "Member already at target rate")

    def test_record_empty_reason_defaults_to_change_type(self):
        """An empty reason is backfilled (mandatory child field) from change_type."""
        result = self.service.record(
            member=self.member.name,
            old_amount=5.0,
            new_amount=8.0,
            change_type="New Schedule",
            reason="",
        )
        self.assertEqual(result.status, "created")
        rows = [r for r in self._history_rows() if flt(r.new_dues_rate) == 8.0]
        self.assertEqual(rows[0].reason, "New Schedule")

    def test_record_merges_context_returns_merged_status(self):
        """A second record() with the same amounts but new context reports 'merged'."""
        self.service.record(member=self.member.name, old_amount=10.0, new_amount=20.0)
        frappe.db.commit()
        result = self.service.record(
            member=self.member.name,
            old_amount=10.0,
            new_amount=20.0,
            amendment_request="AMEND-CTX-1",
        )
        self.assertEqual(result.status, "merged")

    def test_record_merge_persists_context(self):
        """A 'merged' result must persist the new context to the DB.

        Regression guard for a fixed bug: _merge_context_if_needed() mutated the
        in-memory child row only, and record() never persisted member_doc, so the
        merged amendment_request/dues_schedule context was silently dropped while
        status='merged' implied success. record() now flushes the child table via
        safe_child_table_update() after a successful merge.
        """
        self.service.record(member=self.member.name, old_amount=10.0, new_amount=20.0)
        frappe.db.commit()
        self.service.record(
            member=self.member.name,
            old_amount=10.0,
            new_amount=20.0,
            amendment_request="AMEND-CTX-1",
        )
        frappe.db.commit()
        persisted = frappe.get_all(
            "Member Fee Change History",
            filters={"parent": self.member.name, "amendment_request": "AMEND-CTX-1"},
            pluck="name",
        )
        self.assertEqual(len(persisted), 1, "merged amendment context must be persisted")

    def test_record_skips_duplicate_without_new_context(self):
        """An identical record() with no new context is skipped as a duplicate."""
        self.service.record(member=self.member.name, old_amount=10.0, new_amount=22.0)
        result = self.service.record(member=self.member.name, old_amount=10.0, new_amount=22.0)
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.message, "Duplicate entry within deduplication window")

    def test_dedup_window_constant(self):
        """The dedup window constant is 60 seconds (documented contract)."""
        self.assertEqual(DEDUP_WINDOW_SECONDS, 60)

    def _set_member_rate(self, rate):
        self.member.dues_rate = rate
        self.member.fee_override_reason = "test target rate"
        self.member.flags.ignore_validate_update_after_submit = True
        self.member._system_update = True
        self.member.save()
        self.member.reload()


class TestFeeOverrideHookServiceRealDB(EnhancedTestCase):
    """should_skip_processing guards and pending-change processing flow."""

    def setUp(self):
        super().setUp()
        self.service = get_fee_override_hook_service()
        self.member = self.create_test_member(first_name="Hook", last_name="Fee")

    def test_skip_processing_on_system_update_flag(self):
        """_system_update flag short-circuits processing."""
        self.member._system_update = True
        self.assertTrue(self.service.should_skip_processing(self.member))

    def test_skip_processing_on_csv_import_flag(self):
        """_csv_import flag short-circuits processing."""
        self.member._csv_import = True
        self.assertTrue(self.service.should_skip_processing(self.member))

    def test_skip_processing_on_bulk_flag(self):
        """frappe.flags.bulk_member_operations short-circuits processing."""
        original = getattr(frappe.flags, "bulk_member_operations", None)
        frappe.flags.bulk_member_operations = True
        try:
            self.assertTrue(self.service.should_skip_processing(self.member))
        finally:
            frappe.flags.bulk_member_operations = original

    def test_no_skip_for_clean_member(self):
        """A plain member (no flags) is not skipped."""
        # Ensure no leftover bulk flag from a sibling test.
        frappe.flags.bulk_member_operations = False
        self.assertFalse(self.service.should_skip_processing(self.member))

    def test_process_pending_returns_false_without_pending_attr(self):
        """No _pending_fee_change attribute -> process returns False (nothing to do)."""
        self.assertFalse(self.service.process_pending_fee_change(self.member))

    def test_handle_after_save_skips_when_flagged(self):
        """handle_after_save respects should_skip_processing and does no work."""
        self.member._system_update = True
        # Should not raise even though no _pending_fee_change exists.
        self.service.handle_after_save(self.member, method="on_update")


class TestMemberFeeCalculationServiceRealDB(EnhancedTestCase):
    """Fee calculation precedence against real members/memberships."""

    def setUp(self):
        super().setUp()
        self.service = get_member_fee_calculation_service()

    def test_custom_override_takes_precedence(self):
        """A member.dues_rate override is returned as source custom_override."""
        member = self.create_test_member(first_name="Override", last_name="Fee")
        member.dues_rate = 42.0
        member.fee_override_reason = "Board decision"
        member._system_update = True
        member.flags.ignore_validate_update_after_submit = True
        member.save()
        member.reload()

        result = self.service.get_current_membership_fee(member)
        self.assertEqual(result["source"], "custom_override")
        self.assertEqual(flt(result["amount"]), 42.0)
        self.assertEqual(result["reason"], "Board decision")

    def test_no_membership_returns_none_source(self):
        """A member with no override and no active membership returns source none."""
        member = self.create_test_member(first_name="NoFee", last_name="Member")
        member.dues_rate = 0
        member.save()
        member.reload()

        result = self.service.get_current_membership_fee(member)
        self.assertEqual(result["source"], "none")
        self.assertEqual(flt(result["amount"]), 0.0)

    def test_display_fee_current_when_no_amendment(self):
        """Display fee reports status 'Current' with no pending amendments."""
        member = self.create_test_member(first_name="Disp", last_name="Fee")
        member.dues_rate = 0
        member.save()
        member.reload()

        result = self.service.get_display_membership_fee(member)
        self.assertEqual(result["status"], "Current")
        self.assertIn("display_amount", result)
        self.assertEqual(flt(result["current_amount"]), flt(result["display_amount"]))


class TestMemberItemServiceRealDB(EnhancedTestCase):
    """Membership item creation / retrieval."""

    def setUp(self):
        super().setUp()
        self.service = get_member_item_service()
        self.member = self.create_test_member(first_name="Item", last_name="Svc")

    def test_get_or_create_membership_item(self):
        """The standardized MEMBERSHIP-FEE item is created/returned as a service item.

        Wrapped in production_validation() so ERPNext populates Item defaults
        (notably stock_uom from Stock Settings); EnhancedTestCase.setUp sets
        frappe.flags.in_import=True which otherwise skips that default population.
        """
        with self.production_validation():
            item = self.service.get_or_create_membership_item(self.member)
        self.assertIsNotNone(item)
        self.assertEqual(item.item_code, "MEMBERSHIP-FEE")
        self.assertEqual(item.is_sales_item, 1)
        self.assertEqual(item.maintain_stock, 0)

    def test_get_or_create_is_idempotent(self):
        """A second call returns the same singleton item (no duplicate)."""
        with self.production_validation():
            first = self.service.get_or_create_membership_item(self.member)
            second = self.service.get_or_create_membership_item(self.member)
        self.assertEqual(first.name, second.name)

    def test_default_item_group_resolves(self):
        """_get_default_item_group returns an Item Group that actually exists."""
        group = self.service._get_default_item_group()
        self.assertTrue(frappe.db.exists("Item Group", group))


class TestMemberFeeValidationServiceRealDB(EnhancedTestCase):
    """Fee override validation behaviour."""

    def setUp(self):
        super().setUp()
        self.service = get_member_fee_validation_service()
        self.member = self.create_test_member(first_name="Valid", last_name="Fee")

    def test_validate_amount_rejects_negative(self):
        """A negative override amount raises a ValidationError with the documented message."""
        with self.assertRaises(frappe.ValidationError) as ctx:
            self.service.validate_fee_override_amount(-5.0)
        self.assertIn("greater than 0", str(ctx.exception))

    def test_validate_amount_accepts_positive(self):
        """A positive amount passes validation (no exception)."""
        self.service.validate_fee_override_amount(25.0)  # must not raise

    def test_validate_amount_ignores_zero_falsy(self):
        """Zero is falsy and skips the > 0 check (no exception)."""
        self.service.validate_fee_override_amount(0)  # must not raise

    def test_validate_reason_skipped_in_test_env(self):
        """In test env (frappe.flags.in_test), missing reason does not throw."""
        self.member.dues_rate = 30.0
        # in_test is set during the test run, so validation is bypassed.
        self.service.validate_fee_override_reason(self.member)  # must not raise

    def test_validate_reason_no_override_returns_early(self):
        """With no dues_rate set, reason validation returns immediately."""
        self.member.dues_rate = 0
        self.service.validate_fee_override_reason(self.member)  # must not raise

    def test_validate_permissions_skips_system_update(self):
        """A system update bypasses permission validation entirely."""
        self.member.dues_rate = 30.0
        self.member._system_update = True
        # Member is not new (already inserted), but system flag short-circuits.
        self.service.validate_fee_override_permissions(self.member)  # must not raise

    def test_validate_permissions_skips_when_unchanged(self):
        """When dues_rate matches the DB value, no permission check runs."""
        # Persist a rate, then re-validate with the SAME value.
        self.member.dues_rate = 20.0
        self.member.fee_override_reason = "set once"
        self.member._system_update = True
        self.member.flags.ignore_validate_update_after_submit = True
        self.member.save()
        self.member.reload()

        # Clear the system flag; value is unchanged vs DB so it returns early.
        self.member._system_update = False
        self.service.validate_fee_override_permissions(self.member)  # must not raise
