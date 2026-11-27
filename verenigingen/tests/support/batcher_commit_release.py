"""Shared teardown for tests that drive the committing DD batcher path (#709, #716)."""

import frappe

from verenigingen.tests.utils.force_delete import force_delete


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
