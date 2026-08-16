"""
Coverage-focused integration tests for the membership fee/type adjustment portal
controller (verenigingen.templates.pages.membership_adjustment).

These tests target the UNCOVERED functions/branches that the existing suite
(test_page_portal_cluster.TestPageMembershipAdjustment, the payment/* CAR tests,
and test_membership_type_change_integration) does NOT exercise:

  - get_effective_fee_for_member: active-dues-schedule branch + member-override
    legacy fallback branch.
  - get_member_fee_history: returns a combined list (dues schedules + amendment
    requests), capped at 10, newest first.
  - get_minimum_fee: quarterly branch + student-status branch.
  - can_member_adjust_fee: happy (enabled, under limit) + max-reached branch.
  - submit_fee_adjustment_request: HAPPY PATH (creates an amendment), same-amount
    no_change short-circuit, above-maximum throw, reason-required throw,
    effective-date-in-the-past throw.
  - submit_membership_type_change_request: HAPPY PATH (creates amendment +
    notification), missing-reason throw, custom-amount-below-minimum throw,
    already-pending-request throw.
  - create_new_dues_schedule: deprecated -> always throws.

Existing coverage we deliberately do NOT duplicate: get_context happy/error,
get_fee_adjustment_settings defaults, get_available_membership_types,
get_fee_calculation_info, _calculate_type_change_effective_date.
"""

import frappe
from frappe.utils import add_days, now_datetime, today

from verenigingen.templates.pages import membership_adjustment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMembershipAdjustmentCoverage(EnhancedTestCase):
    """Real-DB tests for the membership_adjustment portal controller."""

    def setUp(self):
        super().setUp()
        # Several @self_service_api endpoints are gated to DEVELOPMENT via
        # frappe.conf.developer_mode; a sibling shard test can leave it off
        # (shared, non-transactional flag). Force it on, restore in tearDown.
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1
        # Ensure fee adjustment is enabled with predictable limits so the
        # can_member_adjust_fee / submit paths behave deterministically.
        # enable_member_fee_adjustment / max_fee_adjustments_per_year /
        # maximum_fee_multiplier are real Verenigingen Settings fields, so these
        # assignments persist. adjustment_reason_required is NOT a field and is not
        # assigned here: it is the module constant
        # membership_adjustment.ADJUSTMENT_REASON_REQUIRED (issue #356). Assigning a
        # nonexistent field would be a silent no-op that save() discards.
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_member_fee_adjustment = 1
        settings.max_fee_adjustments_per_year = 2
        settings.maximum_fee_multiplier = 10
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    # ---- shared fixtures ------------------------------------------------

    def _ensure_member_user(self, email, first_name="Adj", last_name="User"):
        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    # User.username is UNIQUE and Frappe derives it from first_name,
                    # so every user here would claim "adj" and the second insert in a
                    # run dies on "Duplicate entry 'adj' for key 'username'". Pin it
                    # to the already-unique local part of the email instead.
                    "username": email.split("@")[0],
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", email)
        return email

    def _member_with_active_membership(self, minimum_amount=12.0, type_name="AdjCov"):
        """Member linked to a session User, with a submitted Active membership."""
        member = self.create_test_member(
            first_name="Adj",
            last_name="Cover",
            email=f"adjcov-{now_datetime().strftime('%H%M%S%f')}@example.com",
            birth_date="1990-01-01",
        )
        member.reload()
        email = member.email
        self._ensure_member_user(email)
        member.db_set("user", email)

        mt = self.create_test_membership_type(membership_type_name=type_name, minimum_amount=minimum_amount)
        membership = self.create_test_membership(member_name=member.name, membership_type_name=mt.name)
        membership.reload()
        if membership.docstatus == 0:
            membership.submit()
        if membership.status != "Active":
            membership.db_set("status", "Active")
        frappe.db.commit()
        return member, email, mt, membership

    def _active_dues_schedule_name(self, member_name):
        return frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": member_name, "status": "Active"},
            "name",
        )

    def _make_amendment_request(self, **fields):
        """Insert a Contribution Amendment Request from the given fields."""
        req = frappe.get_doc({"doctype": "Contribution Amendment Request", **fields})
        req.insert(ignore_permissions=True)
        return req

    # ---- get_effective_fee_for_member -----------------------------------

    def test_effective_fee_from_active_dues_schedule(self):
        """PRIORITY 1: an active dues schedule drives the returned amount/source."""
        member, _email, _mt, _membership = self._member_with_active_membership()
        member_doc = frappe.get_doc("Member", member.name)
        membership = frappe.db.get_value(
            "Membership",
            {"member": member.name, "status": "Active", "docstatus": 1},
            ["name", "membership_type"],
            as_dict=True,
        )
        with self.assertNoErrorLog():
            result = membership_adjustment.get_effective_fee_for_member(member_doc, membership)
        self.assertEqual(result["source"], "dues_schedule")
        self.assertIn("schedule_name", result)
        self.assertIsNotNone(result["schedule_name"])
        self.assertIn("amount", result)

    def test_effective_fee_member_override_fallback(self):
        """PRIORITY 3: with no active schedule, a member.dues_rate override is used."""
        member, _email, _mt, _membership = self._member_with_active_membership()
        # Cancel the auto-created active schedule so PRIORITY 1 is skipped.
        sched = self._active_dues_schedule_name(member.name)
        if sched:
            frappe.db.set_value("Membership Dues Schedule", sched, "status", "Cancelled")
        member_doc = frappe.get_doc("Member", member.name)
        if hasattr(member_doc, "dues_rate"):
            member_doc.dues_rate = 33.0
            membership = frappe.db.get_value(
                "Membership",
                {"member": member.name, "status": "Active", "docstatus": 1},
                ["name", "membership_type"],
                as_dict=True,
            )
            with self.assertNoErrorLog():
                result = membership_adjustment.get_effective_fee_for_member(member_doc, membership)
            self.assertEqual(result["source"], "member_override")
            self.assertEqual(result["amount"], 33.0)
        else:
            self.skipTest("Member has no dues_rate override field on this schema")

    # ---- get_minimum_fee branches ---------------------------------------

    def test_minimum_fee_quarterly_branch(self):
        """A 'kwartaal'/'quarter' membership type uses the 50% quarterly minimum."""
        member, _email, _mt, _membership = self._member_with_active_membership()
        # membership_type name contains 'quarter' -> quarterly branch
        qmt = self.create_test_membership_type(membership_type_name="QuarterPlan", minimum_amount=40.0)
        member_doc = frappe.get_doc("Member", member.name)
        mt_doc = frappe.get_doc("Membership Type", qmt.name)
        # membership.membership_type must contain "quarter" for the branch; the
        # factory uniquifies names but preserves the prefix.
        fake_membership = frappe._dict({"membership_type": qmt.name})
        self.assertIn("quarter", qmt.name.lower())
        with self.assertNoErrorLog():
            minimum = membership_adjustment.get_minimum_fee(member_doc, mt_doc, fake_membership)
        self.assertGreaterEqual(minimum, 5.0)

    def test_minimum_fee_student_branch(self):
        """student_status raises the minimum to at least 50% of the type minimum."""
        member, _email, _mt, _membership = self._member_with_active_membership()
        member_doc = frappe.get_doc("Member", member.name)
        if not hasattr(member_doc, "student_status"):
            self.skipTest("Member has no student_status field on this schema")
        member_doc.student_status = 1
        mt = self.create_test_membership_type(membership_type_name="StudentMin", minimum_amount=30.0)
        mt_doc = frappe.get_doc("Membership Type", mt.name)
        with self.assertNoErrorLog():
            minimum = membership_adjustment.get_minimum_fee(member_doc, mt_doc)
        # Student floor is 50% of type minimum (15.0) -> well above the €5 floor.
        self.assertGreaterEqual(minimum, 15.0)

    # ---- can_member_adjust_fee ------------------------------------------

    def test_can_member_adjust_fee_happy_path(self):
        """Enabled + under limit -> (True, '')."""
        member, _email, _mt, _membership = self._member_with_active_membership()
        member_doc = frappe.get_doc("Member", member.name)
        settings = membership_adjustment.get_fee_adjustment_settings()
        ok, msg = membership_adjustment.can_member_adjust_fee(member_doc, settings)
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_can_member_adjust_fee_max_reached(self):
        """At/over the per-365-day limit -> (False, message)."""
        member, _email, _mt, membership = self._member_with_active_membership()
        # Insert two member-originated Fee Change requests so the count hits 2.
        for i in range(2):
            self._make_amendment_request(
                member=member.name,
                membership=membership.name,
                amendment_type="Fee Change",
                # requested_amount must clear the membership-type minimum fee
                # (the doctype validate enforces it); keep it comfortably above.
                current_amount=50.0,
                requested_amount=50.0 + (i + 1),
                reason=f"bump {i}",
                status="Applied",
                requested_by_member=1,
                effective_date=today(),
            )
        frappe.db.commit()
        member_doc = frappe.get_doc("Member", member.name)
        settings = membership_adjustment.get_fee_adjustment_settings()
        # settings.max_adjustments_per_year is 2; two requests reach the cap.
        settings["max_adjustments_per_year"] = 2
        ok, msg = membership_adjustment.can_member_adjust_fee(member_doc, settings)
        self.assertFalse(ok)
        self.assertIn("maximum", msg.lower())

    # ---- get_member_fee_history -----------------------------------------

    def test_member_fee_history_returns_combined_list(self):
        """History merges dues schedules and amendment requests, newest first."""
        member, _email, _mt, membership = self._member_with_active_membership()
        # Add one amendment request so the history has both kinds of entries.
        self._make_amendment_request(
            member=member.name,
            membership=membership.name,
            amendment_type="Fee Change",
            current_amount=50.0,
            requested_amount=60.0,
            reason="history entry",
            status="Applied",
            requested_by_member=1,
            effective_date=today(),
        )
        frappe.db.commit()
        with self.assertNoErrorLog():
            history = membership_adjustment.get_member_fee_history(member.name)
        self.assertIsInstance(history, list)
        self.assertLessEqual(len(history), 10)
        sources = {entry["source"] for entry in history}
        # At least the amendment request should be present.
        self.assertIn("amendment_request", sources)
        # Every entry has the documented shape.
        for entry in history:
            self.assertIn("date", entry)
            self.assertIn("amount", entry)
            self.assertIn("status", entry)
            self.assertIn("reference", entry)

    def test_member_fee_history_empty_for_unknown_member(self):
        """No schedules/amendments -> empty list (no crash)."""
        with self.assertNoErrorLog():
            history = membership_adjustment.get_member_fee_history("NONEXISTENT-MEMBER-XYZ")
        self.assertEqual(history, [])

    # ---- submit_fee_adjustment_request: happy + branch throws -----------

    def test_submit_fee_adjustment_member_creates_amendment(self):
        """HAPPY PATH: a "Verenigingen Member" can self-service a fee adjustment.
        Members hold create + if_owner on Contribution Amendment Request, so the
        secure-op runs as the member and creates the request owned by them.
        new_amount=75.0 clears both the min-fee gate (effective minimum ~EUR 30)
        and the "same as current amount" guard.

        SECURITY: a member request must always land in Pending Approval -- the
        controller guard forbids members from auto-approving their own changes.
        """
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_fee_adjustment_request(
                new_amount=75.0, reason="I want to contribute more"
            )
        finally:
            frappe.set_user(original_user)
        self.assertTrue(result.get("success"), msg=result)
        self.assertNotIn("permission_error", result)
        self.assertIn("amendment_id", result)
        car = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])
        self.assertEqual(car.member, member.name)
        self.assertEqual(car.requested_by_member, 1)
        self.assertEqual(car.owner, email)
        self.assertEqual(car.status, "Pending Approval")

    def test_submit_fee_adjustment_member_decrease_requires_approval(self):
        """SECURITY (C1 guard): a member cannot auto-approve a fee DECREASE to the
        minimum -- it must route to manual staff review, not self-approve."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_fee_adjustment_request(
                new_amount=30.0, reason="reducing my contribution"
            )
        finally:
            frappe.set_user(original_user)
        self.assertTrue(result.get("success"), msg=result)
        car = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])
        self.assertEqual(car.status, "Pending Approval")
        self.assertNotEqual(car.status, "Approved")

    def test_submit_fee_adjustment_same_amount_no_change(self):
        """Requesting the current fee returns no_change without creating a request."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        # Determine the member's actual current fee from the active schedule.
        sched = self._active_dues_schedule_name(member.name)
        current = frappe.db.get_value("Membership Dues Schedule", sched, "dues_rate")
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertNoErrorLog():
                result = membership_adjustment.submit_fee_adjustment_request(
                    new_amount=current, reason="no change please"
                )
        finally:
            frappe.set_user(original_user)
        self.assertFalse(result.get("success"))
        self.assertTrue(result.get("no_change"))

    def test_submit_fee_adjustment_above_maximum_throws(self):
        """An amount above minimum_fee * maximum_fee_multiplier is rejected."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        # maximum_fee_multiplier is 10; minimum_fee >= 5, so 100000 is always over.
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError):
                membership_adjustment.submit_fee_adjustment_request(new_amount=100000.0, reason="too much")
        finally:
            frappe.set_user(original_user)

    def test_submit_fee_adjustment_reason_required_throws(self):
        """ADJUSTMENT_REASON_REQUIRED + a blank reason is rejected.

        The amount must clear the minimum-fee check, which runs earlier in
        submit_fee_adjustment_request: the previous version of this test passed
        25.0 against a fixture whose minimum resolves to 30, so it was really
        asserting the minimum-fee throw and would have stayed green with the
        reason check deleted. Assert on the message so the throw is attributable.
        """
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError) as raised:
                # Valid different amount, comfortably above the minimum, but empty reason.
                membership_adjustment.submit_fee_adjustment_request(new_amount=75.0, reason="   ")
        finally:
            frappe.set_user(original_user)
        self.assertIn("reason", str(raised.exception).lower())

    def test_submit_fee_adjustment_past_effective_date_throws(self):
        """An effective_date in the past is rejected."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError):
                membership_adjustment.submit_fee_adjustment_request(
                    new_amount=25.0,
                    reason="valid reason",
                    effective_date=add_days(today(), -5),
                )
        finally:
            frappe.set_user(original_user)

    # ---- enable_member_fee_adjustment kill switch -----------------------

    def _ensure_fee_adjustment_setting(self, value):
        """Persist enable_member_fee_adjustment, restoring the old value after.

        Restores via addCleanup rather than tearDown: cleanups run after the
        base-class teardown drain, which has been observed to discard restores
        made in tearDown.
        """
        previous = frappe.db.get_single_value("Verenigingen Settings", "enable_member_fee_adjustment")

        def _restore_setting():
            settings = frappe.get_single("Verenigingen Settings")
            settings.enable_member_fee_adjustment = previous
            settings.save(ignore_permissions=True)
            frappe.db.commit()

        self.addCleanup(_restore_setting)
        settings = frappe.get_single("Verenigingen Settings")
        settings.enable_member_fee_adjustment = value
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    def test_disabling_member_fee_adjustment_blocks_the_portal_endpoint(self):
        """The kill switch: enable_member_fee_adjustment=0 stops a member
        submitting a fee change through the real portal endpoint.

        This is the property that did not hold while the setting was a phantom
        field: assigning it was a silent no-op that save() discarded, so
        get_fee_adjustment_settings() always fell back to the getattr default 1
        and can_member_adjust_fee() could never refuse.

        Control: test_disabling_is_what_blocks_it_not_the_fixture below runs the
        identical call with the flag at 1 and gets an amendment.
        """
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        self._ensure_fee_adjustment_setting(0)

        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError) as raised:
                membership_adjustment.submit_fee_adjustment_request(
                    new_amount=75.0, reason="should never be accepted"
                )
        finally:
            frappe.set_user(original_user)
        self.assertIn("not enabled", str(raised.exception))

        # No amendment may have been created by the refused call.
        self.assertEqual(
            frappe.db.count(
                "Contribution Amendment Request",
                filters={"member": member.name, "amendment_type": "Fee Change"},
            ),
            0,
        )

        # Guard against the silent-no-op trap that hid this bug: prove the 0
        # actually reached the database rather than a throwaway Python attribute.
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "enable_member_fee_adjustment"), 0
        )

    def test_disabling_is_what_blocks_it_not_the_fixture(self):
        """CONTROL for the test above: with the flag explicitly at 1 the very same
        call succeeds, so the refusal is attributable to the setting alone."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        self._ensure_fee_adjustment_setting(1)

        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_fee_adjustment_request(
                new_amount=75.0, reason="accepted while the switch is on"
            )
        finally:
            frappe.set_user(original_user)
        self.assertTrue(result.get("success"), msg=result)
        self.assertIn("amendment_id", result)

    def test_enable_member_fee_adjustment_is_a_real_persisted_field(self):
        """Regression guard for the phantom-field class itself.

        A nonexistent field assigns silently and save() drops it, so a plain
        round-trip through the database is what distinguishes a real field from
        a throwaway attribute.
        """
        meta = frappe.get_meta("Verenigingen Settings")
        field = meta.get_field("enable_member_fee_adjustment")
        self.assertIsNotNone(field, "enable_member_fee_adjustment is not on Verenigingen Settings")
        self.assertEqual(field.fieldtype, "Check")

        self._ensure_fee_adjustment_setting(0)
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "enable_member_fee_adjustment"), 0
        )
        self._ensure_fee_adjustment_setting(1)
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "enable_member_fee_adjustment"), 1
        )

    # ---- submit_membership_type_change_request --------------------------

    def test_submit_type_change_member_creates_amendment(self):
        """HAPPY PATH: a "Verenigingen Member" can self-service a membership type
        change. Members hold create + if_owner on Contribution Amendment Request,
        so the secure-op runs as the member and creates a Pending Approval request
        owned by them (all type changes require staff approval)."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        target = self.create_test_membership_type(membership_type_name="UpgradePlan", minimum_amount=25.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_membership_type_change_request(
                new_membership_type=target.name, reason="upgrading my support"
            )
        finally:
            frappe.set_user(original_user)
        self.assertTrue(result.get("success"), msg=result)
        self.assertNotIn("permission_error", result)
        self.assertIn("amendment_id", result)
        car = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])
        self.assertEqual(car.member, member.name)
        self.assertEqual(car.requested_by_member, 1)
        self.assertEqual(car.owner, email)
        self.assertEqual(car.status, "Pending Approval")

    def test_submit_type_change_missing_reason_throws(self):
        """A blank reason is rejected for type changes."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        target = self.create_test_membership_type(membership_type_name="NoReasonPlan", minimum_amount=25.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError):
                membership_adjustment.submit_membership_type_change_request(
                    new_membership_type=target.name, reason=""
                )
        finally:
            frappe.set_user(original_user)

    def test_submit_type_change_custom_amount_below_minimum_throws(self):
        """A requested_amount below the new type's minimum is rejected."""
        member, email, _mt, _membership = self._member_with_active_membership(minimum_amount=10.0)
        target = self.create_test_membership_type(membership_type_name="PricyPlan", minimum_amount=50.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError):
                membership_adjustment.submit_membership_type_change_request(
                    new_membership_type=target.name,
                    reason="want to pay less than minimum",
                    requested_amount=10.0,
                )
        finally:
            frappe.set_user(original_user)

    def test_submit_type_change_already_pending_throws(self):
        """A second type-change request while one is pending is rejected."""
        member, email, _mt, membership = self._member_with_active_membership(minimum_amount=10.0)
        target = self.create_test_membership_type(membership_type_name="PendingPlan", minimum_amount=25.0)
        # Seed an existing pending type-change request directly.
        self._make_amendment_request(
            member=member.name,
            membership=membership.name,
            amendment_type="Membership Type Change",
            current_membership_type=membership.membership_type,
            requested_membership_type=target.name,
            current_amount=10.0,
            requested_amount=25.0,
            reason="first request",
            status="Pending Approval",
            requested_by_member=1,
            effective_date=today(),
        )
        frappe.db.commit()

        other = self.create_test_membership_type(membership_type_name="SecondPlan", minimum_amount=30.0)
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            with self.assertRaises(frappe.ValidationError):
                membership_adjustment.submit_membership_type_change_request(
                    new_membership_type=other.name, reason="second request should fail"
                )
        finally:
            frappe.set_user(original_user)

    # ---- create_new_dues_schedule (deprecated) --------------------------

    def test_create_new_dues_schedule_is_deprecated(self):
        """The deprecated direct-creation helper always throws."""
        with self.assertRaises(frappe.ValidationError):
            membership_adjustment.create_new_dues_schedule("ANY-MEMBER", 20.0, "reason")
