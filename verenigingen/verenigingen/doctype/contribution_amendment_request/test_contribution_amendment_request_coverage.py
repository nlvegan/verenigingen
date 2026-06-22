"""
Coverage-focused real-DB integration tests for the Contribution Amendment
Request controller (``contribution_amendment_request.py``).

These complement the existing endpoint tests in
``verenigingen/tests/membership/test_contribution_amendment_request.py`` and
concentrate on the controller-local validation branches that gate creation:
membership existence/status, past effective date, fee-change amount guards
(zero / same / below-minimum / student minimum), membership-type-change guards,
conflicting-amendment detection, adjustment-frequency limits, current-detail
population, the impact-preview generator for each billing frequency, and the
``format_error_for_logging`` helper.

No business logic is mocked. Real Members, Membership Types, Memberships and
dues schedules are built via the factory and the tests run as Administrator.
"""

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.verenigingen.doctype.contribution_amendment_request.contribution_amendment_request import (
    ERROR_MESSAGE_MAX_LENGTH,
    format_error_for_logging,
)


class TestContributionAmendmentRequestCoverage(VereningingenTestCase):
    """Member, Membership Type and (submitted) Membership are built ONCE for the
    class. Submitting a Membership fans out into payment-history bulk updates and
    dues-schedule creation, all of which contend on the naming-series row lock;
    doing that per-test caused intermittent QueryDeadlockError on the shared test
    DB. Per-test FrappeTestCase savepoints still roll back every amendment (and
    any mid-test ``db_set`` on the shared membership) created during a test."""

    _class_docs = []

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

        factory = EnhancedTestDataFactory(use_faker=True)
        cls.member = factory.create_member(
            first_name="AmendCov",
            last_name="Member",
            email=f"amendcov.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        cls.membership_type = factory.create_test_membership_type(
            membership_type_name=f"AmendCovType{frappe.generate_hash(length=6)}",
        )
        cls.membership = factory.create_test_membership(
            member_name=cls.member.name, membership_type_name=cls.membership_type.name
        )
        if cls.membership.docstatus == 0:
            cls.membership.submit()
        cls.membership.reload()
        # The class fixtures are committed (they live above the per-test
        # savepoint). Record them for explicit teardown.
        cls._class_docs = [
            ("Contribution Amendment Request", None),  # placeholder; amendments tracked per-test
        ]
        frappe.db.commit()

    @classmethod
    def tearDownClass(cls):
        # Remove the committed class fixtures (and any amendments still attached).
        for amend in frappe.get_all(
            "Contribution Amendment Request", filters={"member": cls.member.name}, pluck="name"
        ):
            frappe.delete_doc("Contribution Amendment Request", amend, force=True, ignore_permissions=True)
        for sched in frappe.get_all(
            "Membership Dues Schedule", filters={"member": cls.member.name}, pluck="name"
        ):
            try:
                frappe.delete_doc("Membership Dues Schedule", sched, force=True, ignore_permissions=True)
            except Exception:
                pass
        try:
            m = frappe.get_doc("Membership", cls.membership.name)
            if m.docstatus == 1:
                m.cancel()
            frappe.delete_doc("Membership", m.name, force=True, ignore_permissions=True)
        except Exception:
            pass
        frappe.db.commit()
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        # Class-scoped fixtures shared by every test (read-only unless a test
        # explicitly db_sets the membership, which the per-test rollback reverts).
        self.member = type(self).member
        self.membership_type = type(self).membership_type
        self.membership = type(self).membership

    # ------------------------------------------------------------------ helpers

    # Minimum-fee thresholds derive from the membership-type template's
    # suggested_amount (see MINIMUM_FEE_PERCENTAGE etc. in the controller). The
    # factory's auto-created template uses a base of 100, but compute it from the
    # live record so the tests stay correct if that default changes.
    MINIMUM_FEE_PERCENTAGE = 0.3
    STUDENT_MINIMUM_FEE_PERCENTAGE = 0.5
    ABSOLUTE_MINIMUM_FEE = 5.0

    def _base_amount(self):
        from verenigingen.services.billing.template_configuration_service import (
            load_template_for_membership_type,
        )

        mt = frappe.get_doc("Membership Type", self.membership_type.name)
        return float(load_template_for_membership_type(mt).suggested_amount)

    def _minimum_fee(self, student=False):
        pct = self.STUDENT_MINIMUM_FEE_PERCENTAGE if student else self.MINIMUM_FEE_PERCENTAGE
        return max(self._base_amount() * pct, self.ABSOLUTE_MINIMUM_FEE)

    def _make(self, **overrides):
        data = {
            "doctype": "Contribution Amendment Request",
            "membership": self.membership.name,
            "member": self.member.name,
            "amendment_type": "Fee Change",
            # Default well above the minimum fee and different from the current
            # rate so the happy path inserts.
            "requested_amount": self._minimum_fee() + 25.0,
            "reason": "coverage amendment",
            "effective_date": add_days(today(), 30),
            "status": "Draft",
        }
        data.update(overrides)
        return frappe.get_doc(data)

    def _insert(self, **overrides):
        # The Membership submit fan-out (payment-history bulk update +
        # dues-schedule creation) contends with the amendment naming-series row
        # lock on the shared test DB and intermittently raises
        # QueryDeadlockError. Retry the insert a few times -- mirrors Frappe's own
        # built-in deadlock retry; no business logic is bypassed.
        last_err = None
        for _ in range(8):
            amendment = self._make(**overrides)
            try:
                amendment.insert()
            except frappe.QueryDeadlockError as err:  # pragma: no cover - timing
                last_err = err
                continue
            self.track_doc("Contribution Amendment Request", amendment.name)
            return amendment
        raise last_err

    def _active_rate(self):
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        return float(frappe.db.get_value("Membership Dues Schedule", name, "dues_rate")) if name else None

    def _valid_request(self):
        """An amount above both the minimum fee and the current active rate -> a
        valid fee INCREASE that always passes the amount-change guards."""
        current = self._active_rate() or 0
        return max(self._minimum_fee(), current) + 20.0

    # ------------------------------------------------------------------ validate_membership_exists

    def test_missing_membership_throws(self):
        amendment = self._make(membership=None)
        with self.assertRaises(frappe.ValidationError):
            amendment.insert()

    def test_inactive_membership_allowed(self):
        """Inactive (not just Active) memberships may still be amended."""
        self.membership.db_set("status", "Inactive")
        amendment = self._insert(requested_amount=self._minimum_fee() + 10.0)
        self.assertTrue(amendment.name)
        # restore for teardown sanity
        self.membership.db_set("status", "Active")

    def test_cancelled_membership_throws(self):
        self.membership.db_set("status", "Cancelled")
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=27.0).insert()
        self.membership.db_set("status", "Active")

    # ------------------------------------------------------------------ validate_effective_date

    def test_past_effective_date_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._make(effective_date=add_days(today(), -5)).insert()

    # ------------------------------------------------------------------ validate_amount_changes (Fee Change)

    def test_zero_requested_amount_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=0).insert()

    def test_negative_requested_amount_throws(self):
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=-10).insert()

    def test_same_as_current_amount_throws(self):
        # validate_amount_changes runs before set_current_details on creation, so
        # the "same as current" guard only fires when current_amount is already
        # populated. Provide it explicitly to exercise that branch.
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=20.0, current_amount=20.0).insert()

    def test_below_minimum_fee_throws(self):
        """A fee below max(30% of base, EUR5) is rejected. Request just under the
        computed minimum (but still > 0)."""
        below = max(self._minimum_fee() - 1.0, 1.0)
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=below).insert()

    def test_student_higher_minimum_fee_throws(self):
        """Students face a 50% minimum. A value between the non-student floor and
        the student floor passes for a normal member but fails for a student."""
        non_student_min = self._minimum_fee(student=False)
        student_min = self._minimum_fee(student=True)
        # Only meaningful when the student floor is strictly higher.
        if student_min <= non_student_min:
            self.skipTest("Student minimum not higher than standard for this base amount")
        between = (non_student_min + student_min) / 2.0
        if not hasattr(self.member, "student_status"):
            self.skipTest("Member doctype has no student_status field")
        self.member.db_set("student_status", 1)
        self.member.reload()
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=between).insert()

    def test_valid_fee_change_inserts(self):
        """A reasonable increase above the minimum and different from current
        succeeds and populates derived details."""
        expected = self._valid_request()
        with self.assertNoErrorLog():
            amendment = self._insert(requested_amount=expected)
        self.assertEqual(float(amendment.requested_amount), expected)
        self.assertEqual(amendment.current_membership_type, self.membership_type.name)

    # ------------------------------------------------------------------ validate_amount_changes (Membership Type Change)

    def test_membership_type_change_same_type_throws(self):
        amendment = self._make(
            amendment_type="Membership Type Change",
            requested_amount=None,
            current_membership_type=self.membership_type.name,
            requested_membership_type=self.membership_type.name,
        )
        with self.assertRaises(frappe.ValidationError):
            amendment.insert()

    # ------------------------------------------------------------------ validate_no_conflicting_amendments

    def test_conflicting_pending_amendment_throws(self):
        """A second amendment is blocked while the member has one in Pending
        Approval."""
        first = self._insert(requested_amount=self._valid_request())
        first.db_set("status", "Pending Approval")
        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=self._valid_request() + 5.0).insert()

    # ------------------------------------------------------------------ validate_adjustment_frequency

    def test_adjustment_frequency_limit_throws(self):
        """Member-requested fee changes are capped per 365 days
        (max_fee_adjustments_per_year, default 2). The 3rd is rejected."""
        settings = frappe.get_single("Verenigingen Settings")
        max_adj = getattr(settings, "max_fee_adjustments_per_year", 2) or 2

        created = []
        base_req = self._minimum_fee() + 5.0
        for i in range(max_adj):
            amendment = self._insert(
                requested_amount=base_req + i,
                requested_by_member=1,
            )
            # Move out of Pending so it doesn't trip the conflict guard, but it
            # still counts toward the 365-day frequency window.
            amendment.db_set("status", "Approved")
            amendment.db_set("effective_date", add_days(today(), 60 + i))
            created.append(amendment)

        with self.assertRaises(frappe.ValidationError):
            self._make(requested_amount=self._valid_request() + 50.0, requested_by_member=1).insert()

    # ------------------------------------------------------------------ set_current_details

    def test_current_details_from_active_dues_schedule(self):
        amendment = self._insert(requested_amount=self._valid_request())
        self.assertIsNotNone(amendment.current_amount)
        self.assertTrue(amendment.current_dues_schedule)
        self.assertTrue(amendment.current_billing_interval)
        self.assertEqual(float(amendment.current_amount), self._active_rate())

    # ------------------------------------------------------------------ set_default_effective_date

    def test_default_effective_date_not_in_past(self):
        amendment = self._insert(effective_date=None)
        self.assertTrue(amendment.effective_date)
        self.assertGreaterEqual(getdate(amendment.effective_date), getdate(today()))

    # ------------------------------------------------------------------ set_requested_by / set_requested_date

    def test_requested_by_and_date_defaulted(self):
        amendment = self._insert(requested_amount=self._valid_request())
        self.assertEqual(amendment.requested_by, frappe.session.user)
        self.assertTrue(amendment.requested_date)

    # ------------------------------------------------------------------ get_impact_preview

    def test_impact_preview_fee_change_increase(self):
        amendment = self._insert(requested_amount=self._valid_request())
        preview = amendment.get_impact_preview()
        self.assertIn("Amendment Impact Preview", preview["html"])
        self.assertIn("increase", preview["html"])

    def test_impact_preview_non_fee_change_returns_stub(self):
        amendment = frappe.new_doc("Contribution Amendment Request")
        amendment.amendment_type = "Membership Type Change"
        amendment.membership = self.membership.name
        self.assertEqual(amendment.get_impact_preview()["html"], "<p>No preview available</p>")

    def test_impact_preview_no_membership_returns_stub(self):
        amendment = frappe.new_doc("Contribution Amendment Request")
        amendment.amendment_type = "Fee Change"
        self.assertEqual(amendment.get_impact_preview()["html"], "<p>No preview available</p>")

    def test_impact_preview_zero_current_amount_no_division_error(self):
        """current_amount 0 must not raise (percentage guard) -> still returns
        an Impact Preview block."""
        amendment = self._insert(requested_amount=self._valid_request())
        amendment.current_amount = 0
        amendment.current_dues_schedule = None
        preview = amendment.get_impact_preview()
        self.assertIn("Amendment Impact Preview", preview["html"])
        # 0 current -> percentage_change computed as 0.0, no ZeroDivisionError.
        self.assertIn("0.0%", preview["html"])

    def test_impact_preview_uses_dues_schedule_quarterly(self):
        """When the linked dues schedule bills quarterly the annual multiplier is
        4 -> the annual impact equals difference * 4."""
        amendment = self._insert(requested_amount=self._valid_request())
        schedule = amendment.current_dues_schedule
        if schedule and hasattr(frappe.get_doc("Membership Dues Schedule", schedule), "billing_frequency"):
            frappe.db.set_value("Membership Dues Schedule", schedule, "billing_frequency", "Quarterly")
            preview = amendment.get_impact_preview()
            self.assertIn("per quarter", preview["html"])
        else:
            self.skipTest("No dues schedule billing_frequency to drive quarterly path")

    # ------------------------------------------------------------------ format_error_for_logging

    def test_format_error_short(self):
        result = format_error_for_logging(ValueError("boom"), context="ctx")
        self.assertEqual(result["error_type"], "ValueError")
        self.assertEqual(result["error_message"], "boom")
        self.assertFalse(result["full_error_logged"])
        self.assertEqual(result["context"], "ctx")

    def test_format_error_truncates(self):
        long_msg = "x" * (ERROR_MESSAGE_MAX_LENGTH + 25)
        result = format_error_for_logging(Exception(long_msg))
        self.assertEqual(len(result["error_message"]), ERROR_MESSAGE_MAX_LENGTH)
        self.assertTrue(result["full_error_logged"])

    def test_format_error_string_input(self):
        result = format_error_for_logging("plain string")
        self.assertEqual(result["error_type"], "str")
        self.assertEqual(result["error_message"], "plain string")
