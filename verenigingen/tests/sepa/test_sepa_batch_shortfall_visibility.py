"""#774: the optimized SEPA batch path drops invoices silently.

`batch_performance_optimizer.process_batch_invoices_optimized` and
`sepa_batch_processor.add_invoices_to_batch_optimized` each compute a shortfall
between what was requested and what was actually collected/added, and hand it to
`frappe.logger()` -- a bare logger whose effective level is ERROR, so `.warning()`
and `.info()` never even reach the rotating file handler, let alone anywhere an
operator or CI would look (measured empirically: `frappe.logger().isEnabledFor
(logging.INFO)` and `.isEnabledFor(logging.WARNING)` are both False on this site).

These tests use `test_error_handling_during_performance_optimization`'s own
construction (`test_sepa_integration_performance.py`): appending an invoice name
that has no matching Sales Invoice row is enough to make
`process_batch_invoices_optimized` silently drop one -- `invoice_data` comes back
`None` from the bulk lookup and the loop does `continue` with **no log call at
all**, not even a dropped one. That single line proves the shortfall is a real,
already-exercised code path, not a hypothetical.
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.verenigingen_payments.services.sepa_batch_processor import SEPABatchProcessor
from verenigingen.verenigingen_payments.utils.batch_performance_optimizer import (
    get_batch_performance_optimizer,
)


class TestSEPABatchShortfallVisibility(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # SEPABatchProcessor() reads a company from the SEPA config at construction.
        get_eur_test_company()

    def setUp(self):
        super().setUp()
        self.sepa_factory = SEPATestDataFactory(seed=774, use_faker=True)
        self.optimizer = get_batch_performance_optimizer()
        self.optimizer.clear_cache()

    def test_missing_invoice_shortfall_reaches_error_log(self):
        """A requested invoice name with no matching Sales Invoice row is dropped
        by `process_batch_invoices_optimized` with NO log call of any kind today.
        An operator asking "why did I get 2 of 3?" has nothing to find."""
        scenario = self.sepa_factory.create_sepa_test_scenario(
            scenario_name="shortfall_missing_invoice", member_count=2
        )
        invoice_names = [inv.name for inv in scenario["invoices"]]
        requested = invoice_names + ["NONEXISTENT-INVOICE-774"]

        self.expectErrorLog(
            "SEPA Batch - Invoice Not Found",
            "SEPA Batch - Invoice Processing Shortfall (Optimizer)",
        )
        before = frappe.db.count("Error Log")
        processed = self.optimizer.process_batch_invoices_optimized(requested)

        # Premise, part 1: the shortfall really happens.
        self.assertEqual(
            len(processed),
            len(invoice_names),
            "fixture did not reproduce the shortfall -- the missing invoice was not dropped",
        )

        after = frappe.db.count("Error Log")
        self.assertGreater(
            after,
            before,
            "a requested invoice vanished from the batch and nothing recorded it -- "
            "not even an Error Log entry names the missing invoice",
        )

    def test_missing_member_mandate_shortfall_reaches_error_log(self):
        """A member whose mandate was revoked between selection and processing
        makes `member_data`/`mandate_data` come back None for their invoice. Today
        this is a `frappe.logger().warning()` call -- confirmed dropped on level."""
        scenario = self.sepa_factory.create_sepa_test_scenario(
            scenario_name="shortfall_missing_mandate", member_count=2
        )
        invoice_names = [inv.name for inv in scenario["invoices"]]

        # Revoke one member's mandate so the bulk mandate JOIN yields no row for them.
        victim_mandate = scenario["mandates"][0]
        frappe.db.set_value("SEPA Mandate", victim_mandate.name, "status", "Cancelled")

        self.expectErrorLog(
            "SEPA Batch - Invoice Skipped (Missing Member/Mandate Data)",
            "SEPA Batch - Invoice Processing Shortfall (Optimizer)",
        )
        before = frappe.db.count("Error Log")
        processed = self.optimizer.process_batch_invoices_optimized(invoice_names)

        self.assertEqual(
            len(processed),
            len(invoice_names) - 1,
            "fixture did not reproduce the shortfall -- the mandate-less invoice was not dropped",
        )

        after = frappe.db.count("Error Log")
        self.assertGreater(
            after,
            before,
            "an invoice was dropped for missing member/mandate data and nothing recorded it",
        )

    def test_batch_level_shortfall_recorded_on_batch_and_error_log(self):
        """`add_invoices_to_batch_optimized` computes `successful_count vs
        len(invoice_names)` and, before this fix, handed that ratio to
        `frappe.logger().info()` only -- dropped the same way. The batch document
        itself must carry a visible record of the shortfall (its own `batch_log`
        field), and the Error Log must carry one findable without knowing which
        batch to open."""
        scenario = self.sepa_factory.create_sepa_test_scenario(
            scenario_name="shortfall_batch_level", member_count=2
        )
        invoices = [{"name": inv.name} for inv in scenario["invoices"]]
        invoices.append({"name": "NONEXISTENT-INVOICE-774-BATCH"})

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "CORE"

        processor = SEPABatchProcessor()
        self.expectErrorLog(
            "SEPA Batch - Invoice Not Found",
            "SEPA Batch - Invoice Processing Shortfall (Optimizer)",
            "SEPA Batch - Invoice Shortfall",
        )
        before = frappe.db.count("Error Log", {"method": "SEPA Batch - Invoice Shortfall"})

        processor.add_invoices_to_batch_optimized(batch, invoices)

        # The shortfall really happened: one of the three requested invoices
        # never became a batch row.
        self.assertEqual(len(batch.invoices), len(invoices) - 1)

        self.assertIn(
            "requested 3 invoices, added 2",
            batch.batch_log or "",
            "the batch's own batch_log field has no record of the shortfall",
        )

        # Review round 2/3 (#774): the shortfall must be a structured, queryable
        # fact on the batch, not just a message someone has to go looking for.
        # A DISTINCT status ("Partially Collected"), not the existing
        # "Partially Failed" -- that string already means "the bank bounced a
        # payment post-submission" (process_batch_returns), asserted by
        # test_sepa_batch_processor_returns_coverage.py:131.
        self.assertEqual(
            batch.status,
            "Partially Collected",
            "a batch that collected fewer invoices than requested must be "
            "flagged Partially Collected, not left looking identical to a full success",
        )

        after = frappe.db.count("Error Log", {"method": "SEPA Batch - Invoice Shortfall"})
        self.assertGreater(
            after,
            before,
            "no Error Log entry under a stable, findable title records the batch-level shortfall",
        )

    def test_full_success_does_not_mark_batch_partially_collected(self):
        """Control for the status assertion above: a batch that collects every
        requested invoice must NOT be flagged Partially Collected."""
        scenario = self.sepa_factory.create_sepa_test_scenario(
            scenario_name="shortfall_control_full_success", member_count=2
        )
        invoices = [{"name": inv.name} for inv in scenario["invoices"]]

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_type = "CORE"
        batch.status = "Draft"

        processor = SEPABatchProcessor()
        processor.add_invoices_to_batch_optimized(batch, invoices)

        self.assertEqual(len(batch.invoices), len(invoices))
        self.assertEqual(
            batch.status,
            "Draft",
            "a fully successful batch must not be marked Partially Collected",
        )

    def test_many_missing_invoices_cap_detail_logs_but_keep_full_count(self):
        """#774 review round 2: 300 nonexistent invoice names must NOT produce
        300 permanent Error Log rows (tabError Log is MyISAM -- they survive
        rollback). Detail is capped; one aggregate entry must still carry the
        full count."""
        requested = [f"NONEXISTENT-INVOICE-774-CAP-{i}" for i in range(300)]

        self.expectErrorLog(
            "SEPA Batch - Invoice Not Found",
            "SEPA Batch - Invoice Processing Shortfall (Optimizer)",
        )
        before = frappe.db.count("Error Log", {"method": "SEPA Batch - Invoice Not Found"})

        processed = self.optimizer.process_batch_invoices_optimized(requested)

        self.assertEqual(processed, [])

        detail_rows = frappe.db.count("Error Log", {"method": "SEPA Batch - Invoice Not Found"}) - before
        self.assertLessEqual(
            detail_rows,
            10,
            f"expected at most 10 per-invoice detail rows, got {detail_rows} for 300 missing invoices",
        )

        aggregate = frappe.get_all(
            "Error Log",
            filters={"method": "SEPA Batch - Invoice Processing Shortfall (Optimizer)"},
            fields=["error"],
            order_by="creation desc",
            limit=1,
        )
        self.assertTrue(aggregate, "no aggregate shortfall entry was written")
        self.assertIn(
            "skipped 300 total",
            aggregate[0].error,
            "the aggregate entry must carry the FULL count, not just the capped detail count",
        )

    def test_partially_collected_status_survives_a_real_save(self):
        """#774 review round 3: setting `batch.status` to a brand-new Select
        option is not enough on its own -- Frappe's `_validate_selects()`
        (base_document.py) throws on `.save()`/`.insert()` if a value is not
        among the DocField's options AS CACHED ON THIS SITE, and a JSON edit
        alone does not refresh that cache. This is the exact trap the
        `_validate_links()`-vs-`validate()` ordering note (see the sibling
        test in test_dd_batch_pipeline_coverage.py) is about, one layer up:
        an in-memory assertion on an unsaved doc cannot prove the real
        `create_dues_collection_batch` path (which DOES call `batch.save()`
        right after `add_invoices_to_batch_optimized`) will not crash.
        `bench reload-doctype "Direct Debit Batch"` (or `migrate`) must run on
        a site before this status can ever be saved there -- documented as a
        deployment requirement, not assumed away here."""
        scenario = self.sepa_factory.create_sepa_test_scenario(
            scenario_name="shortfall_real_save", member_count=2
        )
        invoices = [{"name": inv.name} for inv in scenario["invoices"]]
        invoices.append({"name": "NONEXISTENT-INVOICE-774-REALSAVE"})

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Test #774 real-save shortfall"
        batch.batch_type = "CORE"
        batch.sequence_type = "RCUR"
        batch.currency = "EUR"

        processor = SEPABatchProcessor()
        self.expectErrorLog(
            "SEPA Batch - Invoice Not Found",
            "SEPA Batch - Invoice Processing Shortfall (Optimizer)",
            "SEPA Batch - Invoice Shortfall",
        )
        processor.add_invoices_to_batch_optimized(batch, invoices)
        self.assertEqual(batch.status, "Partially Collected")

        # Mirrors create_dues_collection_batch's own sequence exactly.
        batch.calculate_totals()
        batch.insert()  # Must NOT raise frappe.ValidationError from _validate_selects()
        self.addCleanup(lambda: frappe.delete_doc("Direct Debit Batch", batch.name, force=True))

        batch.reload()
        self.assertEqual(
            batch.status,
            "Partially Collected",
            "the status must round-trip through a real save, not just live in memory",
        )
