"""
A member-initiated dues fee change must not alter an already-settled Sales Invoice.

WHY THIS EXISTS
---------------
Issue #355 is the donation-side defect: `update_recurring_donation` writes
`donation.db_set("amount", ...)` on a Donation that *is* the settled financial
record (a Journal Entry is booked against it), so a donor can rewrite history in
place.

The dues side is structurally immune, and this module pins the reason rather than
asserting it in prose. On the dues path the member-facing amount lives on the
Membership Dues Schedule (a forward-looking template) and the settled financial
record is a separate submitted Sales Invoice. A fee change moves the former and
must never touch the latter.

The realistic regression this guards: a future change to
`ContributionAmendmentApprovalService._update_existing_schedule` (or anything it
calls) deciding to "sync" outstanding invoices to the new rate. That would silently
restate booked revenue.

WHAT MAKES THIS TEST NON-VACUOUS
--------------------------------
Asserting only "the invoice did not change" would pass even if the fee change never
happened at all -- and today no code path even attempts the write, so the assertion
alone proves nothing. Every test here therefore carries a CONTROL assertion that the
fee change really did land on the dues schedule. If the control fails, the isolation
assertion is meaningless and the test says so.
"""

import frappe
from frappe.utils import flt, now_datetime

from verenigingen.templates.pages import membership_adjustment
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

OLD_RATE = 20.0
NEW_RATE = 75.0


class TestFeeChangeSettledInvoiceIsolation(EnhancedTestCase):
    """An applied fee change moves future dues only; booked invoices are frozen."""

    def setUp(self):
        super().setUp()
        # Both knobs below are process/DB-global and NOT transactional, so they must be
        # restored via addCleanup rather than tearDown: cleanups run AFTER the base
        # class's teardown drain, which has been observed to discard restores made
        # inside tearDown. Each restore commits for the same reason.

        # Several @self_service_api endpoints gate on frappe.conf.developer_mode,
        # which a sibling shard test can leave off.
        original_dev_mode = frappe.conf.get("developer_mode")
        self.addCleanup(self._restore_dev_mode, original_dev_mode)
        frappe.conf["developer_mode"] = 1

        # Only these two are real fields on Verenigingen Settings. The rest of the
        # knobs get_fee_adjustment_settings() reads (enable_member_fee_adjustment,
        # adjustment_reason_required, ...) do NOT exist on the doctype -- it resolves
        # them via getattr() defaults, so assigning them here would be a silent no-op.
        settings = frappe.get_single("Verenigingen Settings")
        original_settings = {
            "maximum_fee_multiplier": settings.maximum_fee_multiplier,
            "max_fee_adjustments_per_year": settings.max_fee_adjustments_per_year,
        }
        self.addCleanup(self._restore_settings, original_settings)
        settings.maximum_fee_multiplier = 10
        settings.max_fee_adjustments_per_year = 5
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    @staticmethod
    def _restore_dev_mode(original):
        if original is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = original

    @staticmethod
    def _restore_settings(original):
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in original.items():
            setattr(settings, field, value)
        settings.save(ignore_permissions=True)
        frappe.db.commit()

    # ---- fixtures -------------------------------------------------------

    def _member_with_active_membership(self):
        """Member linked to a session User, with a submitted Active membership."""
        member = self.create_test_member(
            first_name="Settled",
            last_name="Invoice",
            email=f"settled-{now_datetime().strftime('%H%M%S%f')}@example.com",
            birth_date="1990-01-01",
        )
        member.reload()
        email = member.email

        if not frappe.db.exists("User", email):
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Settled",
                    "last_name": "Invoice",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", email)
        member.db_set("user", email)

        membership_type = self.create_test_membership_type(
            membership_type_name="SettledInv", minimum_amount=10.0
        )
        membership = self.create_test_membership(
            member_name=member.name, membership_type_name=membership_type.name
        )
        membership.reload()
        if membership.docstatus == 0:
            membership.submit()
        if membership.status != "Active":
            membership.db_set("status", "Active")
        frappe.db.commit()
        return member, email, membership

    def _active_dues_schedule(self, member_name):
        name = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member_name, "status": "Active"}, "name"
        )
        self.assertIsNotNone(name, "fixture is broken: member has no active dues schedule")
        return frappe.get_doc("Membership Dues Schedule", name)

    def _settled_invoice_for(self, member):
        """A SUBMITTED Sales Invoice at OLD_RATE -- the booked financial record.

        The line rate comes from the helper's `grand_total` kwarg, NOT `rate`/`qty`
        (enhanced_test_factory.create_test_sales_invoice reads
        `kwargs.get("grand_total", 100.0)` for both rate and amount). Passing `rate=`
        is a silent no-op that leaves the invoice at the 100.0 default.
        """
        invoice = self.create_test_sales_invoice(
            customer=member.name, grand_total=OLD_RATE, item_code="Test Service"
        )
        invoice.reload()
        if invoice.docstatus == 0:
            invoice.submit()
        invoice.reload()
        self.assertEqual(invoice.docstatus, 1, "fixture is broken: invoice is not submitted")
        # Pin the fixture's amount so a helper change cannot silently move it back
        # to the 100.0 default and leave the isolation assertions comparing noise.
        self.assertEqual(
            flt(invoice.items[0].rate),
            OLD_RATE,
            "fixture is broken: the settled invoice is not at OLD_RATE",
        )
        return invoice

    def _apply_fee_change_as_member_then_staff(self, email, new_amount):
        """Drive the real portal endpoint as the member, then approve+apply as staff.

        Returns the applied Contribution Amendment Request.
        """
        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_fee_adjustment_request(
                new_amount=new_amount, reason="I want to contribute more"
            )
        finally:
            frappe.set_user(original_user)

        self.assertTrue(result.get("success"), msg=f"portal rejected the request: {result}")
        car = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])

        # A member request always lands in Pending Approval -- members may not
        # auto-approve their own fee changes. Staff approval is what applies it.
        self.assertEqual(car.status, "Pending Approval")
        car.status = "Approved"
        car.save(ignore_permissions=True)
        car.reload()

        apply_result = car.apply_amendment()
        self.assertEqual(apply_result.get("status"), "success", msg=apply_result)
        return car

    # ---- the invariant --------------------------------------------------

    def test_applied_fee_change_leaves_a_settled_invoice_untouched(self):
        """An applied fee change moves the dues schedule and freezes booked invoices."""
        member, email, _ = self._member_with_active_membership()

        schedule = self._active_dues_schedule(member.name)
        schedule.db_set("dues_rate", OLD_RATE)
        frappe.db.commit()

        invoice = self._settled_invoice_for(member)
        before = {
            "docstatus": invoice.docstatus,
            "grand_total": flt(invoice.grand_total),
            "item_rate": flt(invoice.items[0].rate),
            "modified": invoice.modified,
        }

        self._apply_fee_change_as_member_then_staff(email, NEW_RATE)

        # CONTROL: without this, every assertion below passes vacuously when the
        # fee change silently fails to apply.
        schedule.reload()
        self.assertEqual(
            flt(schedule.dues_rate),
            NEW_RATE,
            "CONTROL FAILED: the fee change never reached the dues schedule, so this "
            "test proves nothing about invoice isolation",
        )

        # THE INVARIANT: the booked record is frozen.
        invoice.reload()
        self.assertEqual(invoice.docstatus, before["docstatus"], "settled invoice was cancelled/amended")
        self.assertEqual(
            flt(invoice.grand_total),
            before["grand_total"],
            "a fee change restated the grand_total of a SUBMITTED invoice",
        )
        self.assertEqual(
            flt(invoice.items[0].rate),
            before["item_rate"],
            "a fee change rewrote the line rate of a SUBMITTED invoice",
        )
        self.assertEqual(
            invoice.modified,
            before["modified"],
            "a fee change wrote to a SUBMITTED invoice (modified timestamp moved)",
        )

    def test_member_alone_cannot_move_the_dues_rate(self):
        """The member's own request is inert until staff approve it.

        This is the property that makes the #355 shape absent on the dues path: the
        member-facing endpoint creates an approval-gated request, it does not write
        an amount anywhere.
        """
        member, email, _ = self._member_with_active_membership()

        schedule = self._active_dues_schedule(member.name)
        schedule.db_set("dues_rate", OLD_RATE)
        frappe.db.commit()

        original_user = frappe.session.user
        try:
            frappe.set_user(email)
            result = membership_adjustment.submit_fee_adjustment_request(
                new_amount=NEW_RATE, reason="I want to contribute more"
            )
        finally:
            frappe.set_user(original_user)

        # CONTROL: the request really was accepted -- otherwise "rate unchanged"
        # would just mean the endpoint threw.
        self.assertTrue(result.get("success"), msg=f"portal rejected the request: {result}")
        car = frappe.get_doc("Contribution Amendment Request", result["amendment_id"])

        # The distinctive assertion FIRST: no amount moved anywhere. Asserting the
        # request's status before this would mask it -- the status check fires on any
        # guard regression and the rate would never be looked at.
        schedule.reload()
        self.assertEqual(
            flt(schedule.dues_rate),
            OLD_RATE,
            "a member moved their own dues rate without staff approval",
        )

        # Supporting context for *why* nothing moved. The status alone is already
        # covered by tests/backend/portal/test_page_membership_adjustment_coverage.py;
        # it is kept here to document the mechanism, not as this test's point.
        self.assertEqual(car.status, "Pending Approval")
