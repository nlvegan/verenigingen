"""One member's ambiguous mandate must not cost everyone else a month of collections (#627).

Two halves, and they fail together.

**The producer.** Both automated collection queries resolve the member's mandate by
JOIN:

    LEFT JOIN `tabSEPA Mandate` sm
        ON sm.member = mem.name AND sm.status = 'Active' AND sm.used_for_memberships = 1

#597/#604 added the purpose filter, which bounds a member holding a MEMBERSHIP mandate
and a DONATION mandate. It does not bound two Active mandates that share the membership
purpose, so such a member yields one row PER mandate for ONE invoice -- identical
`invoice`, different `mandate_reference` and (in general) different `iban`. #616/PR #670
bounded the *Membership* join in `dd_batch_optimizer`; the mandate join is the sibling it
did not touch, and it is in BOTH producers:

- `dd_batch_optimizer.get_eligible_invoices_for_batching`   (the DAILY path)
- `sepa_mandate_service.get_sepa_invoices_with_mandates`    (the MONTHLY path)

**The consequence.** Since #606, `DirectDebitBatch.validate_no_duplicate_invoices` throws
on a batch listing one invoice twice, so the duplicate no longer becomes a double debit --
it becomes a failed batch. `create_optimal_batches` wraps the whole group loop in
`except Exception`, so ONE such member takes down the run for EVERY other member in it.

**And the failure is silent.** `create_optimal_batches` returns
`{"success": False, "batches_created": 0}`; `dd_batch_scheduler` reads only
`result["success"] and result["batches_created"] > 0` and reports the false branch as
*"No batches created - no eligible invoices"* through `frappe.logger().info`, which writes
to a rotating file with `propagate=False` -- nothing an operator or CI ever reads. The
outer `except` that would have called `send_system_error_notification` cannot fire,
because the optimizer already swallowed. And the retry is not tomorrow:
`is_batch_creation_day()` defaults `batch_creation_days` to `"1"`, so the next attempt is
the 1st of next month.

## How the money consequence is measured here

The healthy members are the measurement. A test that only counts rows for the ambiguous
member cannot tell "the fan-out is gone" from "nothing was collected at all", which is the
failure being fixed. So every test below builds an ambiguous member ALONGSIDE healthy ones
and asserts what happens to the healthy ones' money.

Where a batch is actually built, the invariant is the one PR #687 established for this
pipeline:

    debited      = sum(amount over the batch's child rows)   # one SEPA transaction per row
    reconcilable = sum(outstanding of the invoices those rows name)

`batch_processing_service.mark_batch_invoices_as_paid` iterates the surviving child rows
and creates one Payment Entry per row from that row's Sales Invoice, so `debited >
reconcilable` is money collected that nothing can settle. That function is NOT driven
here, for the reason `test_dd_batch_pipeline_coverage` already documents (it needs a
submitted batch and commits real Payment Entries across a shared shard), so
reconcilability is measured as "every euro debited is named by a row that loop will
visit".

## Building the ambiguous state

Two Active mandates sharing `used_for_memberships` cannot be created by an ordinary
`insert()` -- `SEPAMandate.validate_single_active_mandate_per_purpose` throws -- but the
state is not exotic. `patches/v2_2/report_members_with_multiple_active_mandates` exists
precisely because rows predating that guard are NOT rewritten by it (which mandate a
member is charged on is a data decision), and MariaDB has no partial unique index, so the
invariant cannot be a column constraint at all. That patch then tells the operator, in as
many words, that until they cancel the superseded ones "direct debit batches will REFUSE
to select an IBAN for it (rather than guess)" -- a promise the two queries above did not
keep. The guard is additionally an unlocked read-then-throw, so two concurrent
activations both pass it.

The fixture reaches the state with `frappe.db.set_value` on `status`, which is what
`validate_single_active_mandate_per_purpose`'s own docstring names as the bypass and what
#606 measured. That is a shortcut to a state the app ships a migration report about, not
the only way in. `test_the_two_active_membership_mandate_state_is_reachable` is the
control: if it ever fails, everything below is asserting against a state the database no
longer holds and is measuring nothing.

Measured on veg11 (a copy of production data, read-only): 0 members hold two Active
mandates for any purpose, across 70 mandates, and none of its 29 Direct Debit Batches
carries a duplicated invoice -- so the shape does not exist there today. veg11 is a test
instance; that bounds veg11 and nothing else.
"""

from unittest.mock import patch

import frappe
from frappe.utils import flt

from verenigingen.tests.utils.force_delete import force_delete
from verenigingen.tests.payment.test_batch_one_row_per_invoice import (
    TwoActiveMembershipsFixture,
)
from verenigingen.tests.payment.test_dd_batch_scheduler_orchestration import (
    _SchedulerOrchestrationBase,
)
from verenigingen.verenigingen_payments.api import dd_batch_scheduler as sched
from verenigingen.verenigingen_payments.api.dd_batch_optimizer import (
    get_eligible_invoices_for_batching,
)
from verenigingen.verenigingen_payments.utils import sepa_mandate_service
from verenigingen.verenigingen_payments.utils.collection_rows import (
    DISCRIMINATING_FIELDS,
    refuse_invoices_with_more_than_one_row,
)
from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

NOTIF_MODULE = "verenigingen.verenigingen_payments.api.sepa_batch_notifications"

# `frappe.log_error(title=...)` lands in `Error Log.method`, so these are what a
# test filters on to tell the two refusals apart.
MANDATE_REFUSAL_TITLE = "DD Batch Optimizer: ambiguous membership mandate"
MONTHLY_MANDATE_REFUSAL_TITLE = "Monthly SEPA collection: ambiguous membership mandate"
ROW_REFUSAL_TITLE = "DD Batch Optimizer: duplicated invoice row"

# A second IBAN, deliberately different from the factory's. Two Active membership
# mandates on the SAME account would still be two debits, but a reader could talk
# themselves into "the duplicate is harmless, it is the same account". Different
# accounts remove that escape: whichever row a de-duplication kept would debit an
# account nobody chose.
SECOND_IBAN = "NL39RABO0300065264"


class ReleasesWhatTheBatcherCommitted:
    """Delete the batches a test drove the real batcher into creating.

    Necessary because `dd_batch_optimizer.create_dd_batch_document` calls
    `frappe.db.commit()`. That commit does not just persist the batch: it makes the
    ENTIRE fixture chain built earlier in the test permanent, so `EnhancedTestCase`'s
    per-test rollback no longer removes any of it and the captured-insert drain has to
    delete every row instead. Measured: the sibling module that uses the same fixture
    but never drives a committing path leaks 0 records; these tests leaked 5-7.

    The drain then fails on the chain's own parties, because the committed batch still
    references them:

        Member::Assoc-Member-... This document can not be deleted right now as it's
                                 being modified by another user.
        Customer::... You can disable this Address instead of deleting it.

    The captured-insert drain walks REVERSE CREATION ORDER, with none of the
    `DRAIN_PRIORITY_BY_DOCTYPE` tiering the tracked drain has -- and the Direct Debit
    Batch, its child rows and the SEPA Mandate Usage records are created LAST, by
    production code, inside the test body. So they are exactly the rows that must go
    first and the ones the drain is least able to order.

    Scoped by creation time rather than by the names a test happened to collect: the
    batcher runs site-wide, so one call can create several batches and usage records
    for invoices this test never built, and those are equally in the way.

    `frappe.db.commit()` here is load-bearing, not laziness: the rows being removed are
    already committed, so an uncommitted delete is undone by the drain's own
    `frappe.db.rollback()` a moment later (see `_drain_captured_inserts`).
    """

    def setUp(self):
        super().setUp()
        # Before any fixture exists, so nothing the batcher creates during this test
        # can fall outside the window.
        self._batcher_window_start = frappe.utils.now()

    def tearDown(self):
        try:
            self._release_committed_batches()
        finally:
            super().tearDown()

    def _release_committed_batches(self):
        batches = frappe.get_all(
            "Direct Debit Batch",
            filters={"creation": [">=", self._batcher_window_start]},
            pluck="name",
        )
        if not batches:
            return

        # Usage records first: they reference both the mandate and the invoice, so
        # they outlive and block the chain the drain has to remove afterwards.
        for usage in frappe.get_all(
            "SEPA Mandate Usage", filters={"batch_reference": ["in", batches]}, pluck="name"
        ):
            force_delete("SEPA Mandate Usage", usage)

        for batch in batches:
            # Deleting the parent removes its `Direct Debit Batch Invoice` children,
            # which are what point at the Member, Membership and Sales Invoice.
            force_delete("Direct Debit Batch", batch)

        self._release_chain_in_dependency_order()
        frappe.db.commit()

    def _release_chain_in_dependency_order(self):
        """Sales Invoice, then Address -- the order the captured-insert drain lacks.

        Once the batcher's commit has made the fixture chain permanent, the drain has
        to delete a Customer whose Address is still referenced by a Sales Invoice's
        `customer_address`, and Frappe answers "You can disable this Address instead of
        deleting it". That is the exact failure #328 records for the TRACKED drain,
        which was fixed by giving Sales Invoice a higher `DRAIN_PRIORITY_BY_DOCTYPE`
        tier than Customer and Address. The captured-insert drain has no such tiering
        -- it walks plain reverse creation order -- so the ordering has to come from
        here.

        Measured: the leaked Customers are not permanently stuck. A LATER test's drain
        removes them, which is precisely the shape the ratchet exists to stop -- the
        record is in the database for the rest of the shard, and whatever collides with
        it will not name this test.
        """
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"creation": [">=", self._batcher_window_start]},
            fields=["name", "docstatus"],
        )
        for invoice in invoices:
            if invoice.docstatus == 1:
                try:
                    frappe.get_doc("Sales Invoice", invoice.name).cancel()
                except Exception:
                    pass
            force_delete("Sales Invoice", invoice.name)

        for address in frappe.get_all(
            "Address", filters={"creation": [">=", self._batcher_window_start]}, pluck="name"
        ):
            force_delete("Address", address)

class AmbiguousMandateFixture(ReleasesWhatTheBatcherCommitted, TwoActiveMembershipsFixture):
    """#616's batchable member -> mandate -> invoice chain, plus a SECOND Active
    mandate that also carries `used_for_memberships`.

    The chain builder is inherited rather than copied. #616's suite already owns
    "a member the daily optimizer will actually batch" -- the payment method, the
    IBAN, the submitted membership, and the assertion that the dues schedule names
    it -- and a second copy would drift from it exactly the way #495/#394 describe.
    Its `second_membership` flag stays available and unused here; this module varies
    the MANDATE, which is the join #616 did not bound.
    """

    def _build_ambiguous_chain(self, first_name, second_mandate=False):
        chain = self._build_chain(first_name)
        chain["second_mandate"] = None
        if second_mandate:
            chain["second_mandate"] = self._add_second_membership_mandate(chain)
        return chain

    def _add_second_membership_mandate(self, chain):
        """A second Active mandate for the SAME purpose, on a DIFFERENT account.

        Created as Draft through the ordinary document path (so every other field
        is what the app would write) and then activated with `frappe.db.set_value`,
        which bypasses `validate` -- the route `SEPAMandate.
        validate_single_active_mandate_per_purpose` names in its own docstring, and
        the one #606 measured.
        """
        mandate = self.factory.create_test_sepa_mandate(
            member=chain["member"].name,
            iban=SECOND_IBAN,
            status="Draft",
            used_for_memberships=1,
        )
        frappe.db.set_value(
            "SEPA Mandate", mandate.name, {"status": "Active", "is_active": 1}, update_modified=False
        )
        mandate.reload()
        return mandate

    def _optimizer_rows_for(self, chain):
        """Call the production function, not a copy of its SQL."""
        rows = get_eligible_invoices_for_batching()
        return [r for r in rows if r.get("invoice") == chain["invoice"].name]

    def _monthly_rows_for(self, chain):
        rows = SEPAMandateService().get_sepa_invoices_with_mandates(
            frappe.utils.today(), lookback_days=3650
        )
        return [r for r in rows if r.get("name") == chain["invoice"].name]


class TestTheTwoActiveMembershipMandateStateIsReachable(AmbiguousMandateFixture):
    def test_the_two_active_membership_mandate_state_is_reachable(self):
        """The control for this module: two Active membership mandates coexist."""
        chain = self._build_ambiguous_chain("AmbigReach", second_mandate=True)
        active = frappe.get_all(
            "SEPA Mandate",
            filters={"member": chain["member"].name, "status": "Active", "used_for_memberships": 1},
            pluck="name",
        )
        self.assertEqual(
            sorted(active),
            sorted([chain["mandate"].name, chain["second_mandate"].name]),
            "the database no longer holds two Active membership mandates; this module "
            "measures nothing",
        )
        # And they name DIFFERENT accounts, so no de-duplication can claim the pick
        # is harmless.
        self.assertNotEqual(
            frappe.db.get_value("SEPA Mandate", chain["mandate"].name, "iban"),
            frappe.db.get_value("SEPA Mandate", chain["second_mandate"].name, "iban"),
        )


class TestOneRowPerInvoiceUnderAmbiguousMandates(AmbiguousMandateFixture):
    def test_one_active_mandate_yields_one_optimizer_row(self):
        """CONTROL: the ordinary single-mandate member is unaffected."""
        chain = self._build_ambiguous_chain("AmbigOptControl")
        mine = self._optimizer_rows_for(chain)
        self.assertEqual(len(mine), 1, f"one invoice produced {len(mine)} batch rows: {mine}")
        self.assertEqual(mine[0]["mandate_reference"], chain["mandate"].mandate_id)

    def test_two_membership_mandates_do_not_duplicate_the_daily_row(self):
        """The DAILY path: one invoice, one row -- or none, never two.

        Each row here becomes a `Direct Debit Batch Invoice` child row, i.e. one
        SEPA transaction. Two rows for one invoice are two debits for one debt.

        Both daily rows carry the SAME `iban` -- this query takes it from `mem`, not
        from the mandate -- and differ in `mandate_reference`, which is what the
        collection is authorised under and what decides FRST/RCUR and the SEPA
        Mandate Usage record. (The monthly twin below selects `sm.iban`, so there the
        two rows name two different accounts outright.)

        The healthy sibling is what makes a green result meaningful: refusing the
        ambiguous member must not be reachable by refusing everyone.
        """
        healthy = self._build_ambiguous_chain("AmbigOptHealthy")
        ambiguous = self._build_ambiguous_chain("AmbigOptDup", second_mandate=True)

        rows = get_eligible_invoices_for_batching()
        mine = [r for r in rows if r.get("invoice") == ambiguous["invoice"].name]
        theirs = [r for r in rows if r.get("invoice") == healthy["invoice"].name]

        self.assertEqual(
            len(theirs), 1, f"the unambiguous member's invoice produced {len(theirs)} rows: {theirs}"
        )
        # ZERO, not "at most one". Two rows are two debits for one debt; ONE row is a
        # debit under whichever of two mandates the database happened to return.
        # `report_members_with_multiple_active_mandates` already tells operators that
        # a batch will "REFUSE to select an IBAN ... rather than guess" for exactly
        # this member, so an arbitrary pick here would be both a wrong collection and
        # a broken promise. Asserting <= 1 would let a de-duplication that keeps an
        # arbitrary row pass.
        self.assertEqual(
            len(mine),
            0,
            f"one invoice produced {len(mine)} batch rows -- each becomes a debit "
            f"under a different mandate: {mine}",
        )

    def test_one_active_mandate_yields_one_monthly_row(self):
        """CONTROL for the monthly path: one row, and the RIGHT one.

        Counting rows alone would pass on a query that returns one row naming
        somebody else's mandate. `sm.iban` here is the field the SEPA XML debits.
        """
        chain = self._build_ambiguous_chain("AmbigMonControl")
        mine = self._monthly_rows_for(chain)
        self.assertEqual(len(mine), 1, f"one invoice produced {len(mine)} monthly rows: {mine}")
        self.assertEqual(mine[0]["mandate_reference"], chain["mandate"].mandate_id)
        self.assertEqual(mine[0]["iban"], chain["mandate"].iban)

    def test_two_membership_mandates_do_not_duplicate_the_monthly_row(self):
        """The MONTHLY path (`sepa_processor.create_monthly_dues_collection_batch`).

        `sepa_batch_processor.add_invoices_to_batch_optimized` feeds this query's
        output to `process_batch_invoices_optimized` as a LIST, so a duplicate
        survives all the way to the child rows (#606).
        """
        healthy = self._build_ambiguous_chain("AmbigMonHealthy")
        ambiguous = self._build_ambiguous_chain("AmbigMonDup", second_mandate=True)

        rows = SEPAMandateService().get_sepa_invoices_with_mandates(
            frappe.utils.today(), lookback_days=3650
        )
        mine = [r for r in rows if r.get("name") == ambiguous["invoice"].name]
        theirs = [r for r in rows if r.get("name") == healthy["invoice"].name]

        self.assertEqual(
            len(theirs), 1, f"the unambiguous member's invoice produced {len(theirs)} rows: {theirs}"
        )
        # ZERO for the same reason as the daily path, and here the rows carry `sm.iban`
        # directly, so the two candidates differ in the very field the SEPA XML debits.
        self.assertEqual(
            len(mine),
            0,
            f"one invoice produced {len(mine)} monthly collection rows, on IBANs "
            f"{[r.get('iban') for r in mine]}: {mine}",
        )

    def test_the_refusal_names_the_member_and_the_mandates(self):
        """A dropped collection that says nothing is the defect, not the fix.

        Refusing to guess an IBAN is only defensible if an operator can find out
        that it happened and which mandates to cancel.
        """
        ambiguous = self._build_ambiguous_chain("AmbigLogged", second_mandate=True)
        before = frappe.utils.now()

        get_eligible_invoices_for_batching()

        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", before], "method": ROW_REFUSAL_TITLE},
            fields=["method", "error"],
        )
        hits = [
            log
            for log in logs
            if ambiguous["member"].name in (log.get("error") or "")
            and ambiguous["second_mandate"].mandate_id in (log.get("error") or "")
        ]
        # Scoped to the row guard's own title: that is the only refusal on the daily
        # path (the mandate counter is monthly-only -- see
        # `members_with_ambiguous_mandate`), and an unscoped search would also be
        # satisfied by an Error Log some other suite wrote. The message must name the
        # member AND both mandates, because "cancel all but one" is unactionable
        # without knowing which ones collided.
        self.assertTrue(
            hits,
            "the ambiguous member's invoice was dropped from the collection with no "
            "Error Log naming the member and the mandates to cancel",
        )


class TestEachGuardIsPinnedWhereOnlyItCanAct(AmbiguousMandateFixture):
    """Two guards cover this invariant, and they mask each other.

    `mandate_candidates.members_with_ambiguous_mandate` asks about the MANDATES;
    `collection_rows.refuse_invoices_with_more_than_one_row` asks whether the query
    fanned out. On the ordinary two-mandate member both fire, so removing either one
    leaves every test above green and neither is actually tested. These two are the
    cases where exactly one of them can act.
    """

    def test_only_the_counter_sees_a_pair_the_query_filters_apart(self):
        """A second mandate with a blank IBAN: no fan-out, still ambiguous.

        The monthly query's WHERE carries `sm.iban IS NOT NULL AND sm.iban != ''`,
        so a blank-IBAN sibling is dropped INSIDE the query and it returns exactly
        one row -- nothing for the row-level guard to see.

        The pair is still ambiguous where the money is decided.
        `batch_performance_optimizer.get_members_with_mandates_bulk`, which is what
        actually resolves the IBAN written to the monthly child row, filters neither
        `iban` nor `mandate_id` and assigns in a last-wins loop with no `ORDER BY`.
        So the account debited would be whichever row MariaDB returned last.

        This is why the counter is deliberately LOOSER than the collection queries,
        and it is the whole reason both guards exist.
        """
        healthy = self._build_ambiguous_chain("AmbigOneUsable")
        chain = self._build_ambiguous_chain("AmbigBlankIban", second_mandate=True)
        frappe.db.set_value(
            "SEPA Mandate", chain["second_mandate"].name, "iban", "", update_modified=False
        )

        # CONTROL: exactly one of this member's Active membership mandates now
        # satisfies the query's own mandate predicates, so the query CANNOT have
        # returned two rows -- the row-level guard has nothing to refuse and a green
        # result below is the counter's doing.
        self.assertEqual(
            len(
                frappe.get_all(
                    "SEPA Mandate",
                    filters={
                        "member": chain["member"].name,
                        "status": "Active",
                        "used_for_memberships": 1,
                        "iban": ["!=", ""],
                        "mandate_id": ["is", "set"],
                    },
                )
            ),
            1,
            "the fixture no longer isolates the counter: the query would fan out too",
        )

        rows = SEPAMandateService().get_sepa_invoices_with_mandates(
            frappe.utils.today(), lookback_days=3650
        )
        names = {row.get("name") for row in rows}
        self.assertIn(healthy["invoice"].name, names, "the unambiguous member must still be collected")
        self.assertNotIn(
            chain["invoice"].name,
            names,
            "a member with two Active membership mandates was collected on whichever "
            "IBAN the mandate resolver happened to see last",
        )

    def test_the_monthly_producer_still_refuses_with_only_the_row_guard(self):
        """The row guard's WIRING into the monthly producer, not just the helper.

        The monthly path carries BOTH guards, so on the ordinary two-mandate member
        deleting this call site changes nothing any other test can see -- measured:
        the mutation survived the whole module. Disabling the mandate counter at its
        seam runs the producer in the arrangement that will exist the day a join fans
        out for a reason the mandates do not explain, which is the only reason the row
        guard is on this path at all.

        (The daily producer has only the row guard, so it needs no such test: every
        daily refusal above already exercises this call site.)
        """
        healthy = self._build_ambiguous_chain("AmbigRowOnlyMonOk")
        ambiguous = self._build_ambiguous_chain("AmbigRowOnlyMon", second_mandate=True)
        before = frappe.utils.now()

        with patch.object(sepa_mandate_service, "members_with_ambiguous_mandate", return_value=set()):
            rows = SEPAMandateService().get_sepa_invoices_with_mandates(
                frappe.utils.today(), lookback_days=3650
            )

        # SELF-CHECK, or this test goes quietly vacuous. `patch.object` only
        # intercepts while the call site is a module-level `from ... import`; rewrite
        # it as a qualified `mandate_candidates.members_with_ambiguous_mandate(...)`
        # and the patch stops biting, the counter refuses instead, and the assertions
        # below still pass while testing nothing.
        self.assertEqual(
            frappe.get_all(
                "Error Log",
                filters={"creation": [">=", before], "method": MONTHLY_MANDATE_REFUSAL_TITLE},
            ),
            [],
            "the mandate counter still ran, so this test is not measuring the row guard",
        )

        names = [row.get("name") for row in rows]
        self.assertEqual(names.count(healthy["invoice"].name), 1)
        self.assertEqual(
            names.count(ambiguous["invoice"].name),
            0,
            "with the mandate counter off, the monthly fan-out reached the batch unchecked",
        )

    def test_the_operator_facing_query_refuses_the_duplicate_too(self):
        """The THIRD copy of the same join, in `dd_batch_api.get_eligible_invoices`.

        #662 examined this query and cleared the mandate join as "bounded by #604's
        purpose filter" -- the belief #627 disproves. So this instance was filed
        nowhere, and the class was two-of-three closed.

        Unlike the two scheduled producers this one is operator-facing: its rows are
        rendered as a selectable list, so an unrefused duplicate offers the same
        invoice twice and `validate_no_duplicate_invoices` (#606) then rejects the
        batch the operator just built.
        """
        from verenigingen.verenigingen_payments.api.dd_batch_api import get_eligible_invoices

        healthy = self._build_ambiguous_chain("AmbigApiOk")
        ambiguous = self._build_ambiguous_chain("AmbigApiDup", second_mandate=True)

        result = get_eligible_invoices({"due_date": frappe.utils.add_days(frappe.utils.today(), 400)})
        names = [row.get("name") for row in result["invoices"]]

        self.assertEqual(
            names.count(healthy["invoice"].name),
            1,
            "the unambiguous member's invoice must still be offered exactly once",
        )
        self.assertEqual(
            names.count(ambiguous["invoice"].name),
            0,
            "the same invoice was offered twice, and selecting both builds a batch "
            "#606 will reject",
        )

    def test_the_refusal_names_every_field_that_decides_the_debit(self):
        """`DISCRIMINATING_FIELDS` must keep covering `dd_batch_api`'s own set.

        The two were derived independently at opposite ends of the pipeline -- #613
        refuses a de-duplication when duplicate rows disagree on those fields; this
        refuses the production of such rows and names them in the log. They are not
        imported across the api/utils layer boundary, so nothing but this stops them
        drifting apart and a refusal quietly ceasing to say what collided.
        """
        from verenigingen.verenigingen_payments.api.dd_batch_api import DEBIT_DECIDING_FIELDS

        self.assertEqual(
            tuple(DISCRIMINATING_FIELDS[-len(DEBIT_DECIDING_FIELDS) :]),
            tuple(DEBIT_DECIDING_FIELDS),
        )

    def test_only_the_row_guard_sees_a_duplicate_the_mandates_do_not_explain(self):
        """The row-level guard's own contract, on rows the producers cannot make today.

        Every join in both collection queries is now bounded, so there is no live
        input that fans out without the mandates being ambiguous -- which is exactly
        why this is a direct test of the helper rather than of a pipeline. Its job is
        the NEXT unbounded join: #616 was one, #662 is an open one, and the
        alternative to catching it here is `validate_no_duplicate_invoices` throwing
        and taking the whole collection run down (#606/#627).
        """
        before = frappe.utils.now()
        keep = {"invoice": "SINV-KEEP", "member": "M1", "mandate_reference": "MND-1", "amount": 25.0}
        dup_a = {"invoice": "SINV-DUP", "member": "M2", "mandate_reference": "MND-2", "amount": 30.0}
        dup_b = {"invoice": "SINV-DUP", "member": "M2", "mandate_reference": "MND-3", "amount": 30.0}

        kept = refuse_invoices_with_more_than_one_row(
            [keep, dup_a, dup_b], "invoice", ROW_REFUSAL_TITLE
        )

        # The duplicated invoice is dropped ENTIRELY -- not de-duplicated to one row.
        # Keeping either would debit under a mandate nobody chose.
        self.assertEqual(kept, [keep])

        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", before], "method": ROW_REFUSAL_TITLE},
            fields=["error"],
        )
        hits = [log for log in logs if "SINV-DUP" in (log.get("error") or "")]
        self.assertTrue(hits, "the refused invoice was dropped with no Error Log")
        # Both candidates named, or an operator cannot tell what collided.
        self.assertIn("MND-2", hits[0]["error"])
        self.assertIn("MND-3", hits[0]["error"])
        self.assertNotIn("SINV-KEEP", hits[0]["error"])

    def test_an_unduplicated_row_set_is_returned_untouched(self):
        """CONTROL: the guard must not be reachable by refusing everything."""
        before = frappe.utils.now()
        rows = [
            {"invoice": "SINV-A", "member": "M1", "mandate_reference": "MND-1", "amount": 25.0},
            {"invoice": "SINV-B", "member": "M2", "mandate_reference": "MND-2", "amount": 30.0},
        ]
        self.assertEqual(refuse_invoices_with_more_than_one_row(rows, "invoice", ROW_REFUSAL_TITLE), rows)
        self.assertEqual(
            frappe.get_all(
                "Error Log", filters={"creation": [">=", before], "method": ROW_REFUSAL_TITLE}
            ),
            [],
            "a clean row set raised a refusal nobody needed to read",
        )


class TestOneAmbiguousMemberDoesNotStopTheCollection(AmbiguousMandateFixture):
    """The money consequence, end to end through the real daily pipeline."""

    def test_the_other_members_are_still_collected(self):
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import create_optimal_batches

        healthy = [self._build_ambiguous_chain(f"AmbigRun{i}") for i in range(3)]
        self._build_ambiguous_chain("AmbigRunBad", second_mandate=True)

        result = create_optimal_batches(config={"min_invoices_per_batch": 1})
        for name in result.get("batch_names") or []:
            self._track_test_document("Direct Debit Batch", name)

        self.assertTrue(
            result.get("success"),
            f"one member's ambiguous mandate failed the whole collection run: {result}",
        )

        batched = self._batched_invoice_names(result.get("batch_names") or [])
        for chain in healthy:
            self.assertIn(
                chain["invoice"].name,
                batched,
                "an unambiguous member's dues invoice was not collected because a "
                "DIFFERENT member holds two mandates",
            )

    def test_every_euro_debited_is_named_by_a_row_that_can_be_reconciled(self):
        """debited == reconcilable, over THIS test's invoices.

        The left side is what the SEPA XML debits (one transaction per child row);
        the right side is what `mark_batch_invoices_as_paid` can settle (one Payment
        Entry per row, built from that row's Sales Invoice, for that invoice's own
        outstanding). A duplicated invoice row makes the left side bigger than the
        right, which is money collected that nothing can settle.

        Scoped to this test's own invoices deliberately. `create_optimal_batches`
        batches everything eligible on the site, and on a shared test site that can
        include another suite's partially-paid invoice, whose `outstanding_amount` is
        legitimately below the `grand_total` the child row carries -- a spurious
        inequality that has nothing to do with this fix. The ambiguous member's
        invoice IS in the scoped set, so a fan-out that reached the batch still shows
        up as debited > reconcilable.
        """
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import create_optimal_batches

        mine = [self._build_ambiguous_chain(f"AmbigInv{i}") for i in range(3)]
        mine.append(self._build_ambiguous_chain("AmbigInvBad", second_mandate=True))
        my_invoices = {chain["invoice"].name for chain in mine}

        result = create_optimal_batches(config={"min_invoices_per_batch": 1})
        batch_names = result.get("batch_names") or []
        for name in batch_names:
            self._track_test_document("Direct Debit Batch", name)
        self.assertTrue(batch_names, f"no batch was created at all: {result}")

        rows = [
            row
            for row in frappe.get_all(
                "Direct Debit Batch Invoice",
                filters={"parent": ["in", batch_names]},
                fields=["invoice", "amount"],
            )
            if row["invoice"] in my_invoices
        ]
        # Without this the test could pass on an empty row set, which is what a
        # regression that stops collecting altogether looks like.
        self.assertEqual(
            {row["invoice"] for row in rows},
            my_invoices - {mine[-1]["invoice"].name},
            "the three unambiguous invoices, and only those, must be in the batch",
        )

        debited = sum(flt(row["amount"]) for row in rows)
        reconcilable = sum(
            flt(outstanding)
            for outstanding in frappe.get_all(
                "Sales Invoice",
                filters={"name": ["in", sorted({row["invoice"] for row in rows})]},
                pluck="outstanding_amount",
            )
        )
        self.assertEqual(
            debited,
            reconcilable,
            "the batch debits more than the invoices it names can settle: "
            f"{debited} debited vs {reconcilable} reconcilable",
        )

    @staticmethod
    def _batched_invoice_names(batch_names):
        if not batch_names:
            return set()
        return set(
            frappe.get_all(
                "Direct Debit Batch Invoice",
                filters={"parent": ["in", batch_names]},
                pluck="invoice",
            )
        )


class TestABatchCreationFailureIsNotSilent(ReleasesWhatTheBatcherCommitted, _SchedulerOrchestrationBase):
    """The scheduler must not report a failed run as "nothing to collect".

    `create_optimal_batches` can fail for reasons this PR does not remove -- any
    throw inside the group loop lands in its `except Exception`. What must not
    survive is reporting that as the benign no-op, through a channel nobody reads.

    `create_optimal_batches` is replaced here by its own documented failure
    contract rather than by a fault injected into the pipeline: the subject under
    test is the scheduler's READING of that contract. The end-to-end route into it
    is covered by `TestOneAmbiguousMemberDoesNotStopTheCollection` above.
    """

    FAILURE = {
        "success": False,
        "error": "This batch lists the same invoice more than once",
        "batches_created": 0,
        "batch_names": [],
        "batches_planned": 3,
    }

    def _run_with_optimizer_result(self, result):
        self._enable_auto_creation()
        with patch.object(sched, "is_batch_creation_day", return_value=True), patch.object(
            sched, "should_skip_batch_creation", return_value=False
        ), patch.object(
            sched, "get_scheduler_config", return_value={"min_invoices_per_batch": 1}
        ), patch.object(
            sched, "create_optimal_batches", return_value=result
        ), patch(
            f"{NOTIF_MODULE}.send_system_error_notification"
        ) as notify, patch(
            f"{NOTIF_MODULE}.send_daily_batch_summary"
        ):
            sched._daily_batch_optimization_impl()
        return notify

    def test_a_failed_run_notifies_the_financial_admins(self):
        notify = self._run_with_optimizer_result(dict(self.FAILURE))
        self.assertTrue(
            notify.called,
            "batch creation failed and nobody was told; by default the next attempt "
            "is the 1st of next month",
        )
        detail = notify.call_args[0][0]
        self.assertIn("same invoice more than once", detail)
        # The "N of M planned" clause is built from keys `create_optimal_batches`
        # only started returning in this change; without them the message renders
        # "0 of an unknown number of" and the operator cannot tell a total failure
        # from a partial one.
        self.assertIn("0 of 3", detail)

    def test_a_failed_run_leaves_an_error_log(self):
        before = frappe.utils.now()
        self._run_with_optimizer_result(dict(self.FAILURE))
        logs = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", before]},
            fields=["method", "error"],
        )
        self.assertTrue(
            [log for log in logs if "same invoice more than once" in (log.get("error") or "")],
            "a failed collection run left no Error Log carrying the reason",
        )

    def test_an_empty_run_is_still_reported_as_empty(self):
        """CONTROL: "no eligible invoices" must not start crying wolf.

        Without this, the fix above could be "notify on every run", which an
        operator would learn to ignore within a month.
        """
        notify = self._run_with_optimizer_result(
            {
                "success": True,
                "message": "No eligible invoices found for batching",
                "batches_created": 0,
                "total_invoices": 0,
            }
        )
        self.assertFalse(
            notify.called, "an ordinary empty run raised a critical system alarm"
        )


class TestTheFailureReportSaysWhatWasActuallyLost(ReleasesWhatTheBatcherCommitted, _SchedulerOrchestrationBase):
    """A report that names the wrong loss sends an operator to the wrong repair.

    Three cases, not two, and the two-way version got the most likely one exactly
    backwards. `batch_groups` is assigned at STEP 3 of `create_optimal_batches`, and
    steps 1-3 now include two refusal helpers that each run a query and write Error
    Logs -- so a throw there leaves `batch_groups == []`, `created == []`, and
    `created < planned` is `0 < 0`, i.e. False. The else-branch then announced "Every
    planned batch was created" about a run that never reached batch creation.

    The Error Log and the notification are two records of ONE event, so they share
    one sentence. They did not: the log branched while the notification asserted a
    loss unconditionally, and the notification is the one that gets emailed.
    """

    def test_a_failure_before_batch_creation_does_not_claim_batches_were_created(self):
        from verenigingen.verenigingen_payments.api import dd_batch_optimizer as opt

        before = frappe.utils.now()
        with patch.object(
            opt, "get_eligible_invoices_for_batching", side_effect=frappe.ValidationError("planted step-1")
        ):
            result = opt.create_optimal_batches(config={"min_invoices_per_batch": 1})

        self.assertEqual((result["batches_created"], result["batches_planned"]), (0, 0))
        logged = [
            log["error"]
            for log in frappe.get_all(
                "Error Log",
                filters={"creation": [">=", before], "method": "DD Batch Optimization Error"},
                fields=["error"],
            )
            if "planted step-1" in (log.get("error") or "")
        ]
        self.assertTrue(logged, "the pre-batch failure left no Error Log")
        self.assertIn("failed before batch creation", logged[0])
        self.assertNotIn("Every planned batch was created", logged[0])

    def test_the_notification_and_the_error_log_agree_about_the_loss(self):
        """They are two records of one event; contradicting each other is the defect."""
        outcomes = {
            "nothing planned": ({"batches_created": 0, "batches_planned": 0}, "failed before batch creation"),
            "partial": ({"batches_created": 1, "batches_planned": 3}, "were NOT collected"),
            "after creation": ({"batches_created": 3, "batches_planned": 3}, "after batch creation"),
        }
        for label, (counts, expected) in outcomes.items():
            with self.subTest(outcome=label):
                result = dict(counts)
                result.update({"success": False, "error": "planted", "batch_names": []})
                with patch(f"{NOTIF_MODULE}.send_system_error_notification") as notify:
                    sched.report_failed_batch_creation(result, frappe.utils.today())
                self.assertIn(expected, notify.call_args[0][0])


class TestAPartiallyFailedRunStillHandlesTheBatchesItCommitted(ReleasesWhatTheBatcherCommitted, _SchedulerOrchestrationBase):
    """The gate `create_optimal_batches` results are read through.

    It was `if result["success"] and result["batches_created"] > 0`, so a run that
    failed after committing two batches skipped the block entirely: nobody read
    their `validation_status`, which is what flips a non-compliant batch to
    "Validation Failed" and notifies. Those batches are already in the database and
    their invoices are already excluded from the next run's eligibility SQL, so
    skipping them does not undo them -- it just leaves them unchecked.

    This is the one line in the change whose contract the rest of the module cannot
    see: every other test here uses `batches_created: 0`, for which both forms of
    the condition behave identically.
    """

    def test_a_partial_failure_validates_the_committed_batch_and_still_raises_the_alarm(self):
        from verenigingen.verenigingen_payments.api import dd_batch_optimizer as opt

        self._make_eligible_member_invoice("PartialGate", amount=30.0)
        created = opt.create_optimal_batches(config={"min_invoices_per_batch": 1})
        batch_names = created.get("batch_names") or []
        self.assertTrue(batch_names, f"fixture precondition: a real batch: {created}")
        for name in batch_names:
            self._track_test_document("Direct Debit Batch", name)

        # What `create_optimal_batches` now returns when group 2 of 3 throws: the
        # first group is committed, the rest were never built.
        partial = {
            "success": False,
            "error": "planted failure in a later group",
            "batches_created": 1,
            "batch_names": batch_names[:1],
            "batches_planned": 3,
        }

        settings = self._enable_auto_creation()
        # NOT `db_set(None)` as an arrange step: measured, that Single field reads
        # back as `datetime(1, 1, 1, 0, 0)`, so `assertIsNotNone` on it can never
        # fail and the assertion below would be vacuous. Compare against a timestamp
        # taken before the run instead.
        before_run = frappe.utils.now_datetime()

        with patch.object(sched, "is_batch_creation_day", return_value=True), patch.object(
            sched, "should_skip_batch_creation", return_value=False
        ), patch.object(
            sched, "get_scheduler_config", return_value={"min_invoices_per_batch": 1}
        ), patch.object(
            sched, "create_optimal_batches", return_value=partial
        ), patch(
            f"{NOTIF_MODULE}.handle_automated_batch_validation", return_value={"action": "processed"}
        ) as handle_validation, patch(
            f"{NOTIF_MODULE}.send_daily_batch_summary"
        ) as send_summary, patch(
            f"{NOTIF_MODULE}.send_system_error_notification"
        ) as notify:
            sched._daily_batch_optimization_impl()

        self.assertTrue(
            handle_validation.called,
            "a batch was created and committed, and its validation status was never read",
        )
        self.assertEqual(handle_validation.call_args[0][0].name, batch_names[0])
        self.assertTrue(send_summary.called)
        # The failure must ALSO be reported: handling the survivors is not the same
        # as saying the run failed.
        self.assertTrue(notify.called, "a partially failed run raised no alarm")
        self.assertIn("1 of 3", notify.call_args[0][0])
        self.assertIn(batch_names[0], notify.call_args[0][0])
        last_run = frappe.db.get_value(
            "Verenigingen Payments Settings",
            "Verenigingen Payments Settings",
            "last_batch_creation_run",
        )
        self.assertIsNotNone(last_run, "no last-run timestamp at all")
        self.assertGreaterEqual(
            last_run,
            before_run,
            "the run created batches but did not record a NEW last-run timestamp",
        )


class TestTheMonthlyRunAlsoReportsItsFailure(ReleasesWhatTheBatcherCommitted, _SchedulerOrchestrationBase):
    """#627 §3: the monthly producer has the same shape and #621 did not cover it.

    `sepa_processor._create_monthly_dues_collection_batch_impl` reaches
    `error_handler.execute_with_retry` -> `frappe.log_error(...)` -> `return None`,
    and its scheduler entry discards the return. By the time that branch runs the
    retries are exhausted, so it is the run's terminal state: no dues collected, and
    nothing reaches an operator in time to run the batch by hand.
    """

    def test_a_failed_monthly_run_notifies_the_financial_admins(self):
        from verenigingen.verenigingen_payments.doctype.direct_debit_batch import sepa_processor

        class _AlwaysCreationDay:
            def get_batch_timing_config(self):
                return {
                    "auto_creation_enabled": True,
                    "is_creation_day": True,
                    "creation_days": [frappe.utils.getdate().day],
                    "next_processing_date": frappe.utils.add_days(frappe.utils.today(), 7),
                    "auto_submit_enabled": False,
                }

        class _Exploding:
            def create_dues_collection_batch(self, collection_date=None, verify_invoicing=True):
                raise frappe.ValidationError("planted monthly batch failure")

        before = frappe.utils.now()
        # The timing config is a branch selector, flipped the way this module's
        # sibling tests flip `is_batch_creation_day`. The failure itself is injected
        # at the processor seam so the REAL `SEPAErrorHandler` runs its retries and
        # produces the real terminal result dict the reporting reads.
        with patch.object(
            sepa_processor, "get_sepa_config_manager", return_value=_AlwaysCreationDay()
        ), patch.object(
            sepa_processor, "get_sepa_batch_processor", return_value=_Exploding()
        ), patch(
            f"{NOTIF_MODULE}.send_system_error_notification"
        ) as notify:
            self.assertIsNone(sepa_processor._create_monthly_dues_collection_batch_impl())

        self.assertTrue(
            notify.called,
            "the monthly dues collection failed outright and nobody was told",
        )
        logs = frappe.get_all(
            "Error Log", filters={"creation": [">=", before]}, fields=["error"]
        )
        self.assertTrue(
            [log for log in logs if "NO membership dues were collected" in (log.get("error") or "")],
            "the monthly failure left no Error Log saying nothing was collected",
        )


class TestAPartialRunReportsWhatItAlreadyCommitted(ReleasesWhatTheBatcherCommitted, _SchedulerOrchestrationBase):
    """`create_dd_batch_document` commits, so a later group's failure cannot
    un-create the batches already inserted.

    Reporting `batches_created: 0` while N batches exist is not a cosmetic
    inaccuracy: those N are the ones whose `validation_status` the scheduler is
    supposed to act on, and the invoices in them are now excluded from the next
    run's eligibility SQL. An operator told "0 created" re-runs by hand and finds
    the money already claimed by batches nobody validated.
    """

    def test_the_batches_already_created_are_named_in_the_failure(self):
        from verenigingen.verenigingen_payments.api import dd_batch_optimizer as opt

        for i in range(4):
            self._make_eligible_member_invoice(f"PartialRun{i}", amount=30.0)

        real = opt.create_dd_batch_document
        calls = {"n": 0}

        def fail_after_the_first(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:
                raise frappe.ValidationError("planted failure in a later group")
            return real(*args, **kwargs)

        # Fault injection at a seam, not a mock of the logic under test: the
        # subject is what `create_optimal_batches` REPORTS once a group has
        # thrown, and only the first group's real, committed batch makes that
        # question answerable.
        with patch.object(opt, "create_dd_batch_document", side_effect=fail_after_the_first):
            result = opt.create_optimal_batches(config={"min_invoices_per_batch": 1, "max_invoices_per_batch": 1})

        for name in result.get("batch_names") or []:
            self._track_test_document("Direct Debit Batch", name)

        self.assertFalse(result["success"])
        self.assertGreater(calls["n"], 1, "the fixture did not reach a second group")
        self.assertEqual(
            result["batches_created"],
            1,
            f"a batch was inserted and committed but the caller was told 0: {result}",
        )
        self.assertEqual(len(result.get("batch_names") or []), 1, result)
