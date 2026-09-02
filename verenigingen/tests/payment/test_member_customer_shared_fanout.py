"""Two Members sharing one Customer, and the join `dd_batch_api` resolves it through (#662).

`dd_batch_api.get_eligible_invoices` used to join:

    LEFT JOIN `tabMember` mem ON mem.customer = si.customer

`Member.customer` is a plain Link with no unique constraint -- measured on
test_site_2: `SHOW INDEX FROM tabMember WHERE Column_name='customer'` returns two
indexes, both `Non_unique = 1`, and `member.json` declares no `unique`. So two
Members sharing one Customer, each holding an Active membership-purpose mandate,
produced TWO rows for ONE invoice -- different `member_id`, `mandate_reference`
and `iban`.

## Two wrong fixes tried and rejected before this one (both measured, not assumed)

1. **"The row-level guard from #709 already covers it."** #709 added
   `refuse_invoices_with_more_than_one_row(eligible_invoices, "name", ...)` to
   bound the SEPA Mandate fan-out (two Active mandates on ONE member); it groups
   the query's OUTPUT by `si.name`, so it does refuse an UNFILTERED call's
   Member.customer fan-out as a side effect. It does NOT catch a
   `member_type`-filtered call: that filter compiles to
   `mem.selected_membership_type = %s`, a per-Member predicate applied INSIDE
   the SQL before the row guard ever runs. Measured on test_site_2: two Members
   sharing a Customer, each with their own `selected_membership_type`, and two
   separate `member_type`-filtered calls (an entirely ordinary "show me
   Individual members due" / "show me Student members due" workflow) each
   returned the SAME invoice attributed to a DIFFERENT member and mandate -- an
   actual double debit across two batches, since
   `DirectDebitBatch.validate_no_duplicate_invoices` (#606) only checks
   duplicates WITHIN one batch.

2. **"Bound the join through `si.member`."** `Sales Invoice.member` looks like
   the invoice's own member, but it is a `fetch_from: customer.member` custom
   field with `fetch_if_empty: 0` (`verenigingen/fixtures/custom_field.json`),
   so Frappe overwrites it from `Customer.member` -- a single Link -- on EVERY
   save, regardless of what a billing service explicitly set. Measured on
   test_site_2: a dues invoice created with `member=B` exactly as
   `invoice_generator.py` does was stored with `member=A` once `Customer.member`
   named A, and the query then offered it under A's mandate and IBAN -- a
   SILENT WRONG-ACCOUNT DEBIT of B's dues from A's bank account, which is worse
   than the original bug (that one at least got refused and logged).

## The actual fix

Bind through the invoice's OWN dues schedule, on its PRIMARY KEY -- the same
resolution the other two collection queries already use
(`dd_batch_optimizer.get_eligible_invoices_for_batching`, #616;
`sepa_mandate_service.get_sepa_invoices_with_mandates`):

    JOIN `tabMembership Dues Schedule` mds
        ON mds.name = si.membership_dues_schedule_display
    JOIN `tabMember` mem ON mem.name = mds.member

`mds.member` is `reqd` for any non-template schedule and is not subject to
`fetch_from`, so it is the only thing that actually knows which Member an
invoice was raised for. This does not merely bound the fan-out -- it removes
`Member.customer` from this query's member-resolution entirely, so the join is
no longer one-to-many regardless of how many Members share a Customer, and
`refuse_invoices_with_more_than_one_row` goes back to being what it is for the
other two producers: the backstop for two Active membership-purpose mandates on
one (now uniquely-resolved) member, not for the Customer join.

An invoice with no resolvable dues schedule is now excluded outright (JOIN, not
LEFT JOIN) rather than falling through to an ambiguous Member.customer match --
matching what `dd_batch_optimizer` already does, and measured on veg11 (a
production copy) to exclude none of this query's reachable population
(431/431 reachable invoices have a resolvable schedule).
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.payment.test_sepa_batch_ui import SepaBatchUITestBase
from verenigingen.verenigingen_payments.api.dd_batch_api import get_eligible_invoices

ROW_REFUSAL_TITLE = "DD Batch eligible invoices: duplicated invoice row"

# Deliberately different from whatever IBAN the base chain's own mandate generates:
# two Active mandates on the SAME account would still be two debits, but a reader
# could talk themselves into "harmless, it's one account". Different accounts
# remove that escape.
SECOND_IBAN = "NL39RABO0300065264"


class SharedCustomerFixture(SepaBatchUITestBase):
    """A batchable member -> mandate -> invoice chain, plus a SECOND Member on the
    SAME Customer -- with `Customer.member` deliberately pointed at that SECOND
    Member, not at the invoice's own one.

    That inversion is the load-bearing part of the fixture: `Customer.member` is
    what `Sales Invoice.member` silently copies (see the module docstring's
    rejected fix #2), so pointing it at the WRONG member is what would have hidden
    that regression. Built from
    `SepaBatchUITestBase._build_member_with_invoice` rather than duplicating it:
    that helper already owns "a member and invoice the endpoint will actually
    offer" (payment method, IBAN, a submitted invoice, dues schedule), and a
    second copy would drift from it the way #495/#394 describe.

    Two Members sharing one Customer is not an exotic or invalid state to reach:
    `customer_handling_service.py` tells an operator who reports "I already have a
    customer for this person" to link to the existing Customer manually rather
    than rejecting the idea, so nothing in the app's own validation stops a second
    Member from doing exactly that.
    """

    def _build_shared_customer_chain(self, first_name, second_mandate=False, point_customer_at_sharer=True):
        # A distinctive `grand_total`, scoped back in `_rows_for` via
        # `amount_min`/`amount_max`: the query is `ORDER BY ... LIMIT 500`, and on
        # a shared, dirty test site this invoice is not guaranteed to land in the
        # first 500 rows sorted by due date. `amount_min`/`amount_max` filter
        # `si.outstanding_amount` -- identical for both rows of a fan-out pair, so
        # this narrows the competing row count without discriminating between a
        # pair the way `member_type` does.
        # A process-global monotonic counter, not a hash: `get_next_sequence` on the
        # factory resets per instance (a fresh `SEPATestDataFactory` is created
        # inside `_build_member_with_invoice` for every chain), and a hash-derived
        # amount collided often enough in practice (~1 in 10 across a handful of
        # chains in one run, birthday-paradox on a 1000-bucket range) to make this
        # test flaky through no fault of the production code.
        from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

        # `round(..., 2)` is load-bearing, not tidiness: the bracket is an exact
        # equality against the stored `outstanding_amount`, and `25.0 + n / 100` is
        # not always representable in binary float. 32 of every 1000 sequence values
        # (n = 201, 226, 251, ... every 25th) land just BELOW the cent the invoice
        # actually stores, so `si.outstanding_amount <= amount_max` excludes the very
        # row under test and the assertion sees 0 rows. n=301 did exactly that in CI.
        # The value is deterministic per shard composition, so a re-run reproduces it.
        grand_total = round(25.0 + next(EnhancedTestDataFactory._global_unique_seq) / 100, 2)
        chain = self._build_member_with_invoice(first_name=first_name, grand_total=grand_total)
        chain["grand_total"] = grand_total
        second_member = self.factory.create_test_member(first_name=f"{first_name}Sib")
        # The factory's own `after_insert` already gave `second_member` its OWN
        # Customer, with THAT Customer's `member` pointed back at it
        # (`Customer.member` is unique -- confirmed via `SHOW INDEX FROM
        # tabCustomer`). Clear that backlink before repointing `second_member`
        # at the SHARED customer, or the repoint below collides on the unique
        # index.
        own_customer = second_member.customer
        # `db_set`, not a field assignment + save: this reaches the state under
        # test (two Members pointing at one Customer row) directly, matching how
        # `_build_member_with_invoice` itself backfills `Member.customer` when the
        # factory did not set one.
        second_member.db_set("customer", chain["customer"])
        if point_customer_at_sharer:
            if own_customer and own_customer != chain["customer"]:
                frappe.db.set_value("Customer", own_customer, "member", None)
            # THE TRAP -- and it only springs on an invoice created AFTER this
            # repoint. `fetch_from` runs on save, so `chain["invoice"]` (already
            # submitted by `_build_member_with_invoice` above) keeps the
            # correct `si.member` it was given before the repoint -- a fixture
            # that tested attribution on THAT invoice would pass even under the
            # rejected `si.member`/`Customer.member` bound, because the trap
            # was armed but never triggered. `fetch_trapped_invoice` below is
            # created AFTER the repoint for exactly this reason: measured on
            # test_site_2, its `si.member` is stored as `second_member`, not as
            # the Member whose dues schedule actually generated it.
            frappe.db.set_value("Customer", chain["customer"], "member", second_member.name)
        chain["second_member"] = second_member
        chain["second_mandate"] = None
        if second_mandate:
            chain["second_mandate"] = self.factory.create_test_sepa_mandate(
                member=second_member.name,
                iban=SECOND_IBAN,
                status="Active",
                used_for_memberships=1,
            )
        if point_customer_at_sharer:
            from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestDataFactory

            trapped_total = round(25.0 + next(EnhancedTestDataFactory._global_unique_seq) / 100, 2)
            chain["fetch_trapped_invoice"] = self.factory.create_test_sales_invoice(
                customer=chain["customer"],
                member=chain["member"].name,
                membership=chain["membership"].name,
                membership_dues_schedule_display=chain["schedule"].name,
                grand_total=trapped_total,
                submit=True,
            )
            chain["fetch_trapped_grand_total"] = trapped_total
            # Self-check: if this ever stops being overwritten (a Frappe
            # version change, or the custom field losing `fetch_from`), the
            # test below would pass for the wrong reason -- it would no longer
            # be exercising the trap at all.
            assert (
                frappe.db.get_value("Sales Invoice", chain["fetch_trapped_invoice"].name, "member")
                == second_member.name
            ), "fixture precondition: si.member must have been overwritten by fetch_from for this test to mean anything"
        return chain

    def _set_membership_type(self, member_name, membership_type):
        """`Member.selected_membership_type` is not populated by the ordinary
        factory chain (verified: stays NULL after `create_test_membership`), but
        it is what `filters["member_type"]` matches against, so a test of that
        filter has to set it directly."""
        frappe.db.set_value("Member", member_name, "selected_membership_type", membership_type)
        return membership_type

    def _rows_for(self, chain, invoice=None, grand_total=None, **extra_filters):
        """Rows for `invoice` (default: `chain["invoice"]`), scoped by `grand_total`
        (default: `chain["grand_total"]`).

        Pass `invoice=chain["fetch_trapped_invoice"], grand_total=chain["fetch_trapped_grand_total"]`
        to query the invoice created AFTER the Customer.member repoint -- see
        `_build_shared_customer_chain`.

        `_build_member_with_invoice` leaves the invoice at its payment-terms due
        date (the "SEPA Direct Debit" template's credit_days, +14 -- not the
        factory's own +30 default), so a `due_date` filter of plain `today()`
        would exclude it before the join under test ever runs. 400 days out, as
        the sibling mandate-fan-out test in test_collection_run_not_lost_silently.py
        already uses for the same reason. `amount_min`/`amount_max` bracket the
        invoice's own distinctive `grand_total` to keep it out of the LIMIT 500
        cutoff on a shared test site.
        """
        invoice = invoice or chain["invoice"]
        grand_total = chain["grand_total"] if grand_total is None else grand_total
        filters = {
            "due_date": add_days(today(), 400),
            "amount_min": grand_total,
            "amount_max": grand_total,
            **extra_filters,
        }
        result = get_eligible_invoices(filters=filters)
        return [row for row in result["invoices"] if row["name"] == invoice.name]


class TestTwoMembersOnOneCustomerIsReachable(SharedCustomerFixture):
    def test_the_shared_customer_state_is_reachable(self):
        """The control for this module: two Members really do share one Customer,
        with `Customer.member` naming the SHARER, not the invoice's own member."""
        chain = self._build_shared_customer_chain("SharedReach", second_mandate=True)
        sharing = frappe.get_all("Member", filters={"customer": chain["customer"]}, pluck="name")
        self.assertEqual(
            sorted(sharing),
            sorted([chain["member"].name, chain["second_member"].name]),
            "the fixture no longer produces two Members on one Customer; this module measures nothing",
        )
        self.assertEqual(
            frappe.db.get_value("Customer", chain["customer"], "member"),
            chain["second_member"].name,
            "fixture precondition: Customer.member must name the SHARER, not the invoice's own member",
        )


class TestAttributionIsBoundByTheInvoicesOwnDuesSchedule(SharedCustomerFixture):
    """The invoice's own dues schedule pins the join to the Member it was raised
    for -- NOT to whichever Member the shared Customer's backlink happens to name.
    """

    def test_one_members_mandate_is_offered_once(self):
        """CONTROL: a shared Customer with only ONE member holding a mandate is
        ordinary, not ambiguous, and must still be offered, correctly attributed."""
        chain = self._build_shared_customer_chain("SharedOneOk")
        rows = self._rows_for(chain)
        self.assertEqual(len(rows), 1, f"one invoice produced {len(rows)} rows: {rows}")
        self.assertEqual(rows[0]["member_id"], chain["member"].name)

    def test_the_invoice_is_attributed_to_its_own_member_not_the_customers_backlink(self):
        """The regression rejected fix #2 in the module docstring would have
        reintroduced: `Customer.member` names `second_member`, but the invoice was
        raised through `chain["member"]`'s own dues schedule, and both Members
        hold their own Active membership mandate. The row that comes back must
        name the invoice's OWN member and mandate -- never the Customer's
        backlink target.

        Asserted on `fetch_trapped_invoice`, NOT `chain["invoice"]`: the latter
        is created and submitted BEFORE the Customer.member repoint, so its
        `si.member` (a `fetch_from` field, see the module docstring) was already
        correctly stamped and never gets a chance to be overwritten --
        `si.member` `IS` `chain["member"].name` for that invoice regardless of
        which bound the query uses, so it cannot tell the correct fix from the
        rejected `si.member` one apart. `fetch_trapped_invoice` is created
        AFTER the repoint specifically so the trap is live; its own fixture
        assertion confirms `si.member` really was overwritten to
        `second_member`.
        """
        healthy = self._build_shared_customer_chain("SharedTwoOk", second_mandate=False)
        chain = self._build_shared_customer_chain("SharedTwoDup", second_mandate=True)

        healthy_rows = self._rows_for(healthy)
        rows = self._rows_for(
            chain, invoice=chain["fetch_trapped_invoice"], grand_total=chain["fetch_trapped_grand_total"]
        )

        self.assertEqual(
            len(healthy_rows),
            1,
            f"the unambiguous member's invoice produced {len(healthy_rows)} rows: {healthy_rows}",
        )
        self.assertEqual(
            len(rows),
            1,
            f"a tagged invoice must be offered exactly once even when its Customer is "
            f"shared and both Members hold mandates: {rows}",
        )
        self.assertEqual(
            rows[0]["member_id"],
            chain["member"].name,
            "the invoice was attributed to Customer.member's target (si.member, silently "
            "overwritten by fetch_from), not its own dues-schedule member",
        )
        self.assertEqual(
            rows[0]["mandate_reference"],
            chain["mandate"].mandate_id,
            "the invoice was offered under the sharer's mandate, not its own member's",
        )

    def test_a_member_type_filter_does_not_offer_the_invoice_under_the_sharer(self):
        """The double-debit shape rejected fix #1 left open: two ordinary,
        separately-filtered operator calls (one per membership type) must not
        both return the same invoice under different members/mandates.

        Asserted on `fetch_trapped_invoice` -- see the attribution test above
        for why `chain["invoice"]` cannot exercise the `si.member` trap.
        """
        chain = self._build_shared_customer_chain("SharedTypeFilter", second_mandate=True)
        own_type = frappe.db.get_value("Membership Dues Schedule", chain["schedule"].name, "membership_type")
        self._set_membership_type(chain["member"].name, own_type)
        # The sharer needs a membership_type of their OWN to filter on -- a
        # second Membership (auto-creates its own distinct Membership Type),
        # deliberately NOT wired to a dues schedule or invoice of its own: this
        # test is about `mem.selected_membership_type`, not about giving the
        # sharer a second collectible invoice.
        sharer_type = self.factory.create_test_membership(member=chain["second_member"].name).membership_type
        self._set_membership_type(chain["second_member"].name, sharer_type)
        self.assertNotEqual(own_type, sharer_type, "fixture precondition: the two types must differ")

        kwargs = dict(invoice=chain["fetch_trapped_invoice"], grand_total=chain["fetch_trapped_grand_total"])

        under_sharers_type = self._rows_for(chain, member_type=sharer_type, **kwargs)
        self.assertEqual(
            under_sharers_type,
            [],
            "filtering by the SHARING member's type must not offer an invoice that "
            "belongs to the other member sharing the same Customer",
        )

        under_own_type = self._rows_for(chain, member_type=own_type, **kwargs)
        self.assertEqual(len(under_own_type), 1, f"expected exactly one row: {under_own_type}")
        self.assertEqual(under_own_type[0]["member_id"], chain["member"].name)
        self.assertEqual(under_own_type[0]["mandate_reference"], chain["mandate"].mandate_id)


class TestTwoActiveMandatesOnTheResolvedMemberAreStillRefused(SharedCustomerFixture):
    """The join bound removes `Member.customer` as a source of ambiguity, but
    `refuse_invoices_with_more_than_one_row` (#709) remains the guard for the
    OTHER fan-out class: two Active `used_for_memberships` mandates on the ONE
    member the dues schedule resolves to. Built on the shared-Customer fixture
    to prove the two classes do not interact -- resolving the Customer ambiguity
    must not accidentally also suppress a genuine mandate ambiguity on the
    correctly-resolved member.
    """

    def test_two_active_mandates_on_the_invoices_own_member_are_refused(self):
        chain = self._build_shared_customer_chain("SharedMandateAmbig", second_mandate=False)
        # A second Active membership-purpose mandate for chain["member"] itself
        # (not the sharer) -- the Draft-then-activate route
        # `test_collection_run_not_lost_silently.AmbiguousMandateFixture` also
        # uses, since `SEPAMandate.validate_single_active_mandate_per_purpose`
        # rejects a second ordinary insert.
        second_mandate = self.factory.create_test_sepa_mandate(
            member=chain["member"].name, iban=SECOND_IBAN, status="Draft", used_for_memberships=1
        )
        frappe.db.set_value(
            "SEPA Mandate", second_mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
        )

        rows = self._rows_for(chain)
        self.assertEqual(
            rows,
            [],
            f"two Active mandates on the invoice's own member must still be refused: {rows}",
        )

    def test_the_refusal_names_both_mandates(self):
        chain = self._build_shared_customer_chain("SharedMandateLogged", second_mandate=False)
        second_mandate = self.factory.create_test_sepa_mandate(
            member=chain["member"].name, iban=SECOND_IBAN, status="Draft", used_for_memberships=1
        )
        frappe.db.set_value(
            "SEPA Mandate", second_mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
        )
        before = frappe.utils.now()

        self._rows_for(chain)

        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", before], "method": ROW_REFUSAL_TITLE},
            fields=["error"],
        )
        hits = [
            log
            for log in logs
            if chain["mandate"].mandate_id in (log.get("error") or "")
            and second_mandate.mandate_id in (log.get("error") or "")
        ]
        self.assertTrue(
            hits,
            "the refused invoice was dropped with no Error Log naming both colliding mandates",
        )


class TestAnInvoiceWithNoResolvableDuesScheduleIsExcluded(SharedCustomerFixture):
    """The join is now `JOIN`, not `LEFT JOIN`, on `Membership Dues Schedule`.

    Matching `dd_batch_optimizer`'s existing behaviour (#616): an invoice this
    endpoint cannot trace to a dues schedule is excluded outright rather than
    falling back to the ambiguous `Member.customer` match the old query used.
    Measured on veg11 (a production copy): none of this query's reachable
    population is affected (431/431 have a resolvable schedule) -- this proves
    the exclusion behaves correctly for the case veg11 does not exercise, not
    that the case is common.
    """

    def test_an_invoice_with_a_blanked_dues_schedule_link_is_not_offered(self):
        chain = self._build_shared_customer_chain("SharedNoSchedule")
        frappe.db.set_value("Sales Invoice", chain["invoice"].name, "membership_dues_schedule_display", None)

        rows = self._rows_for(chain)
        self.assertEqual(
            rows,
            [],
            f"an invoice with no resolvable dues schedule must be excluded, not offered "
            f"through an unbounded Customer match: {rows}",
        )
