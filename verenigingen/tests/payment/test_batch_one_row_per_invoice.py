"""One Direct Debit row per invoice, not one per Active membership (#616).

`dd_batch_optimizer.get_eligible_invoices_for_batching` -- the query behind
`dd_batch_scheduler.daily_batch_optimization`, which runs DAILY
(`hooks/scheduler.py`) -- joined `tabMembership` on nothing but
`m.member = mem.name AND m.status = 'Active'`.

Multiple Active memberships per member are explicitly permitted: the duplicate
check in `Membership.validate_existing_memberships` is bypassed by
`frappe.flags.allow_multiple_memberships`, set by a whitelisted server action
(`membership.allow_multiple_memberships`) that exists precisely so a second
Active membership can be created. So the join was one-to-many, and one Sales
Invoice produced one row PER Active membership -- identical `invoice`, `iban`
and `mandate_reference`, i.e. the same debit twice. This is the second live
route to the double debit #584/#604/#606 are about, independent of mandates.

The fixtures here need no `frappe.db.set_value` bypass for the state under
test: both memberships are submitted and Active through an ordinary
`submit()`, and `test_the_two_active_membership_state_is_reachable` is the
control that proves it. (Payment settings and other *surrounding* fields are
still written directly, as in the pre-existing helpers this builds on -- the
claim is about the two-membership state, not about every field.) If that
control ever fails, the duplicate-row test below is asserting against a state
the app has stopped permitting and is measuring nothing.

Half of this module guards the fix from the other direction. Reaching the
membership through the invoice's schedule can just as easily stop collecting
money, and a per-member drop is invisible -- it looks exactly like "that member
had nothing due". The renewal case in particular was measured to drop every
invoice of a renewed member in the first draft of this fix, which would have
been far worse than the bug being fixed.
"""

import frappe
from frappe.utils import add_days, add_years, today

from verenigingen.tests.payment.test_sepa_batch_ui import SepaBatchUITestBase
from verenigingen.verenigingen_payments.api.dd_batch_optimizer import (
    get_eligible_invoices_for_batching,
)

MEMBERSHIP_IBAN = "NL91ABNA0417164300"


class TwoActiveMembershipsFixture(SepaBatchUITestBase):
    """A batchable member -> mandate -> invoice chain, optionally with a second
    Active membership."""

    def _build_chain(self, first_name, second_membership=False):
        chain = self._build_member_with_invoice(first_name=first_name)

        # The dues schedule is what ties an invoice to ONE membership, and the
        # whole fix rests on it being populated. Assert rather than set it: the
        # link comes from the production path
        # (`TemplateCreationService.create_from_template`, reached through
        # `Membership.on_submit`), and on veg11 -- a copy of production data --
        # 595 of 595 non-template schedules carry it. A fixture that wrote the
        # link itself would keep passing if that path ever stopped writing it.
        self.assertEqual(
            frappe.db.get_value("Membership Dues Schedule", chain["schedule"].name, "membership"),
            chain["membership"].name,
            "fixture precondition: the dues schedule must name the membership it was created for",
        )

        # The optimizer only looks at members it can actually direct-debit.
        frappe.db.set_value(
            "Member",
            chain["member"].name,
            {"payment_method": "SEPA Direct Debit", "iban": MEMBERSHIP_IBAN},
        )

        # Submit the chain's membership so the duplicate guard (which filters
        # `docstatus: 1`) can see it, and so the second membership below is
        # created against the state the guard is written for.
        chain["membership"].reload()
        if chain["membership"].docstatus == 0:
            chain["membership"].submit()

        chain["second_membership"] = None
        if second_membership:
            chain["second_membership"] = self._add_second_active_membership(chain)

        return chain

    def _add_second_active_membership(self, chain):
        """A second Active membership, created the way the app permits it.

        `validate_existing_memberships` throws on overlapping periods
        unconditionally, so the second membership starts after the first one's
        renewal date -- an ordinary renewal whose predecessor's status was never
        flipped to Expired. The remaining "already has an active membership"
        throw is what `frappe.flags.allow_multiple_memberships` (set by the
        whitelisted `membership.allow_multiple_memberships`) exists to lift.
        """
        first = chain["membership"]
        start = add_days(first.renewal_date or add_years(today(), 1), 1)
        second = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": chain["member"].name,
                "membership_type": first.membership_type,
                "status": "Active",
                "start_date": start,
                "renewal_date": add_years(start, 1),
            }
        )
        original_flag = frappe.flags.get("allow_multiple_memberships")
        frappe.flags.allow_multiple_memberships = True
        try:
            second.insert()
            second.submit()
        finally:
            frappe.flags.allow_multiple_memberships = original_flag
        return second

    def _optimizer_rows_for_chain(self, chain):
        # Call the production function, not a copy of its SQL: a test that
        # embeds the query stays green when the real one loses the bound.
        rows = get_eligible_invoices_for_batching()
        return [r for r in rows if r.get("invoice") == chain["invoice"].name]


class TestTheTwoActiveMembershipStateIsReachable(TwoActiveMembershipsFixture):
    def test_the_two_active_membership_state_is_reachable(self):
        """The control for this module: two submitted Active memberships coexist."""
        chain = self._build_chain("TwoMemReach", second_membership=True)
        active = frappe.get_all(
            "Membership",
            filters={"member": chain["member"].name, "status": "Active", "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(
            sorted(active),
            sorted([chain["membership"].name, chain["second_membership"].name]),
            "the app no longer permits two Active memberships; this module measures nothing",
        )


class TestOneBatchRowPerInvoice(TwoActiveMembershipsFixture):
    def test_one_active_membership_yields_one_row(self):
        """CONTROL: the ordinary single-membership member is unaffected."""
        chain = self._build_chain("OneMemControl")
        mine = self._optimizer_rows_for_chain(chain)
        self.assertEqual(len(mine), 1, f"one invoice produced {len(mine)} batch rows: {mine}")
        self.assertEqual(mine[0]["membership"], chain["membership"].name)

    def test_two_active_memberships_still_yield_one_row(self):
        """One invoice is one debit, however many memberships the member holds.

        Each row here becomes a `Direct Debit Batch Invoice` child row carrying
        the same `iban` and `mandate_reference`, i.e. the same amount collected
        twice. Since #606 the batch is rejected instead, so the live consequence
        is that ONE member with two memberships fails the whole collection run.
        """
        chain = self._build_chain("TwoMemDup", second_membership=True)
        mine = self._optimizer_rows_for_chain(chain)
        self.assertEqual(
            len(mine),
            1,
            f"one invoice produced {len(mine)} batch rows -- each becomes a debit: {mine}",
        )

    def test_an_invoice_without_a_dues_schedule_is_not_batched(self):
        """Reaching Membership through the dues schedule narrows what is collected.

        The batcher's job is membership dues, and the dues schedule is what says
        an invoice is dues. Before #616 any unpaid invoice on a member's customer
        qualified -- merchandise, an event ticket -- and was direct-debited under
        whichever Active membership the join happened to pick. The other automated
        collection path (`sepa_mandate_service.get_sepa_invoices_with_mandates`)
        already INNER JOINs the schedule, so this converges rather than diverges.

        This is the deliberate narrowing in the change and it is a product
        decision, not a measurement: on veg11 the batcher's `payment_method =
        'SEPA Direct Debit'` predicate matches 0 members, so that dataset cannot
        say whether such invoices are ever collected in practice. With the
        predicate lifted, the old and new queries return the same 431 invoices.

        The second invoice below is the discriminator -- the first is built
        identically except for the schedule link and must still be batched, so a
        green result cannot come from a broken fixture.
        """
        chain = self._build_chain("NoSchedule")
        unlinked = self.factory.create_test_sales_invoice(
            customer=chain["customer"],
            member=chain["member"].name,
            grand_total=31.0,
            submit=True,
        )

        rows = get_eligible_invoices_for_batching()
        names = {r.get("invoice") for r in rows}
        self.assertIn(chain["invoice"].name, names, "the dues invoice must still be batched")
        self.assertNotIn(
            unlinked.name,
            names,
            "an invoice with no dues schedule was direct-debited under a membership "
            "it was never raised for",
        )

    def test_a_renewed_members_invoices_are_still_batched(self):
        """The regression this fix nearly shipped.

        `Membership.create_or_update_dues_schedule` takes the "existing schedule"
        branch on a renewal and updates only `membership_type` -- it never
        re-points `mds.membership`. `process_membership_statuses` then marks the
        previous membership Expired. So after an ordinary renewal the schedule
        names an EXPIRED membership while the member holds a live Active one.

        A first draft of #616 required the invoice's own membership to be Active,
        and this shape was measured to drop the invoice entirely -- every renewed
        member silently uncollectible, with nothing but a `frappe.logger().info`
        that CI never uploads and no operator reads. That is worse than the
        double debit being fixed. The schedule's own status is the billing
        authority, and it stays Active across a renewal.
        """
        chain = self._build_chain("RenewedMember", second_membership=True)
        # The renewal shape: the schedule still names the FIRST membership, and
        # that membership has since expired.
        frappe.db.set_value("Membership", chain["membership"].name, "status", "Expired")

        mine = self._optimizer_rows_for_chain(chain)
        self.assertEqual(
            len(mine),
            1,
            f"a renewed member's dues invoice produced {len(mine)} batch rows: {mine}",
        )
        self.assertEqual(mine[0]["membership"], chain["membership"].name)

    def test_a_schedule_without_a_membership_link_is_rejected_not_thrown_on(self):
        """`Direct Debit Batch Invoice.membership` is a required Link.

        `Membership Dues Schedule.membership` is not required, and the whitelisted
        `create_schedule_from_template(member, template_name)` creates a schedule
        without one. Letting such a row through would throw on the reqd field and
        take the whole collection run down for one bad record -- the "right
        failure, wrong outcome" #616 is about. It is rejected with an Error Log
        instead, and the sibling invoice below proves the rejection is about the
        missing link and not about the fixture.
        """
        chain = self._build_chain("NoMembershipLink")
        other = self._build_chain("NoMembershipLinkControl")
        frappe.db.set_value(
            "Membership Dues Schedule", chain["schedule"].name, "membership", None,
            update_modified=False,
        )

        rows = get_eligible_invoices_for_batching()
        names = {r.get("invoice") for r in rows}
        self.assertIn(other["invoice"].name, names, "the intact chain must still be batched")
        self.assertNotIn(
            chain["invoice"].name,
            names,
            "a batch row with no membership would throw on a required Link and fail the run",
        )

    def test_two_members_sharing_one_customer_still_yield_one_row(self):
        """`Member.customer` is a plain Link with no unique constraint.

        So `si.customer = mem.customer` is one-to-many on its own -- the same
        class as the Membership join this issue is about, through a different
        column. `mds.member = mem.name` is what bounds it: the schedule is one
        row, so it pins the Member to one.
        """
        chain = self._build_chain("SharedCustomer")
        squatter = self.factory.create_test_member(first_name="SharedCustomerTwin")
        # The twin must clear every OTHER filter in the query, or it is dropped
        # for an unrelated reason and the test measures nothing: it needs its own
        # Active membership mandate as well as the payment settings.
        self.factory.create_test_sepa_mandate(member=squatter.name)
        # `Member.customer` has no uniqueness guard, so this needs a direct write
        # rather than a save() -- the point of the test is that the DATABASE
        # permits the shape, whatever the document layer does.
        frappe.db.set_value(
            "Member",
            squatter.name,
            {
                "customer": chain["customer"],
                "payment_method": "SEPA Direct Debit",
                "iban": MEMBERSHIP_IBAN,
            },
        )

        mine = self._optimizer_rows_for_chain(chain)
        self.assertEqual(
            len(mine),
            1,
            f"two Members on one Customer produced {len(mine)} batch rows: {mine}",
        )
        self.assertEqual(mine[0]["member"], chain["member"].name)

    def test_an_invoice_billed_to_another_members_customer_is_not_batched(self):
        """`member` and `membership` on one batch row must describe one person.

        The old join gave that structurally (`m.member = mem.name`); reaching the
        membership through the invoice's schedule does not, because the invoice's
        customer and the schedule's member can differ -- a third party paying
        another member's dues. Such a row would carry one member's IBAN and
        another's membership, so it is excluded instead.

        A deliberate narrowing, and not one veg11 can speak to: 0 Sales Invoices
        there carry `custom_paying_for_member`, and the batcher reaches 0 members
        on that dataset at all. Third-party payment in the daily optimizer needs
        its own design.
        """
        payer = self._build_chain("MismatchPayer")
        other = self._build_chain("MismatchOther")
        cross = self.factory.create_test_sales_invoice(
            customer=payer["customer"],
            member=payer["member"].name,
            membership_dues_schedule_display=other["schedule"].name,
            grand_total=32.0,
            submit=True,
        )

        rows = get_eligible_invoices_for_batching()
        names = {r.get("invoice") for r in rows}
        self.assertIn(payer["invoice"].name, names, "the payer's own dues invoice must still be batched")
        self.assertNotIn(
            cross.name,
            names,
            "a batch row named one member's IBAN and another member's membership",
        )

    def test_the_row_names_the_invoices_own_membership(self):
        """Not just ONE row -- the RIGHT one.

        `Direct Debit Batch Invoice.membership` is a required Link to Membership,
        so an arbitrary tiebreak (the shape #604 removed from the mandate join)
        would satisfy the row count above while still labelling the debit with a
        membership the invoice was never raised for. The invoice's own dues
        schedule is the only thing that knows which membership it belongs to.

        Against the pre-fix code the count assertion fires first, so this is not
        independent of the row-count test above. What it guards is the OTHER
        family of fixes -- a `GROUP BY` or a `LIMIT 1` that returns one row and
        the wrong one.
        """
        chain = self._build_chain("TwoMemOwn", second_membership=True)
        mine = self._optimizer_rows_for_chain(chain)
        self.assertEqual(len(mine), 1, f"one invoice produced {len(mine)} batch rows: {mine}")
        self.assertEqual(
            mine[0]["membership"],
            chain["membership"].name,
            "the batch row named a membership this invoice was not raised for",
        )
