"""#3055: a Rolled Back Direct Debit Batch must stop holding its invoices out of new batches.

Every state here is produced through the REAL flow: a batch is submitted, driven through
`mark_batch_invoices_as_paid` and then `initiate_sepa_batch_rollback` (which, after #3021,
leaves the batch `Rolled Back` and its rows `Pending`). Nothing sets `batch.status` by hand.
The CONTROL is a second batch that went through the same collection but was NOT rolled
back: its invoices must stay locked, or a predicate that simply ignores batches
would pass.
"""

import frappe
from frappe.utils import add_days, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestRolledBackBatchUnlocksInvoices3055(EnhancedTestCase):
    OPS_TABLES = (
        "tabSEPA_Compensation_Transaction",
        "tabSEPA_Rollback_Audit",
        "tabSEPA_Rollback_Operation",
    )

    def setUp(self):
        super().setUp()
        from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
        from verenigingen.tests.support.sepa_test_company import get_eur_test_company

        get_eur_test_company()
        self.expectErrorLog("Fiscal Year Auto-Creation Error")
        self._factory3055 = SEPATestDataFactory(seed=5155, use_faker=True)
        self._op_ids3055 = []
        self._batches3055 = []
        self.rolled3055, self.live3055 = self._rolled_back_and_live_batches3055()

    def tearDown(self):
        for op_id in self._op_ids3055:
            for table in self.OPS_TABLES:
                frappe.db.sql(f"DELETE FROM `{table}` WHERE operation_id = %s", (op_id,))
        for name in reversed(self._batches3055):
            try:
                frappe.delete_doc("Direct Debit Batch", name, force=True, ignore_permissions=True)
            except Exception:
                pass
        frappe.db.commit()
        super().tearDown()

    def _collected_batch3055(self):
        from verenigingen.verenigingen_payments.services.batch_processing_service import (
            batch_processing_service,
        )

        batch = self._factory3055.create_test_direct_debit_batch(
            batch_date=add_days(today(), 5), invoice_count=1
        )
        self._batches3055.append(batch.name)
        batch.sepa_file_generated = 1
        batch.save()
        batch.submit()
        self.assertEqual(batch_processing_service.mark_batch_invoices_as_paid(batch), 1)
        return batch

    def _rolled_back_and_live_batches3055(self):
        from verenigingen.verenigingen_payments.utils.sepa_rollback_manager import (
            initiate_sepa_batch_rollback,
        )

        rolled = self._collected_batch3055()
        res = initiate_sepa_batch_rollback(rolled.name, "technical_error", "full_batch", None)
        self._op_ids3055.append(res.get("operation_id"))
        self.assertTrue(res["success"], res)
        live = self._collected_batch3055()
        # The control batch is still "live": mark-paid leaves it Submitted/Processed, not rolled back.
        self.assertNotEqual(frappe.db.get_value("Direct Debit Batch", live.name, "status"), "Rolled Back")
        return rolled, live

    def _invoice3055(self, batch):
        return batch.invoices[0].invoice

    def test_fixture_is_the_real_rolled_back_state(self):
        """Premise: the real flow leaves the batch Rolled Back, row Pending, invoice Unpaid."""
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", self.rolled3055.name, "status"), "Rolled Back")
        self.assertEqual(frappe.db.get_value("Direct Debit Batch", self.rolled3055.name, "docstatus"), 1)
        row = frappe.get_all(
            "Direct Debit Batch Invoice", filters={"parent": self.rolled3055.name}, fields=["status"]
        )
        self.assertEqual([r.status for r in row], ["Pending"])
        self.assertEqual(
            frappe.db.get_value("Sales Invoice", self._invoice3055(self.rolled3055), "status"), "Unpaid"
        )

    def test_open_batch_invoice_names_no_longer_holds_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.api.sepa_batch_ui import get_open_batch_invoice_names

        locked = get_open_batch_invoice_names()
        self.assertNotIn(self._invoice3055(self.rolled3055), locked)

    def test_open_batch_invoice_names_still_holds_a_live_batchs_invoice(self):
        from verenigingen.verenigingen_payments.api.sepa_batch_ui import get_open_batch_invoice_names

        self.assertIn(self._invoice3055(self.live3055), get_open_batch_invoice_names())

    def test_payment_retry_open_batch_guard(self):
        from verenigingen.verenigingen_payments.utils.payment_retry import _invoice_in_open_batch

        self.assertFalse(_invoice_in_open_batch(self._invoice3055(self.rolled3055)))
        self.assertTrue(_invoice_in_open_batch(self._invoice3055(self.live3055)))

    def test_conflict_detector_cross_batch_check(self):
        from verenigingen.verenigingen_payments.utils.sepa_conflict_detector import SEPAConflictDetector

        detector = SEPAConflictDetector()
        rolled = detector._detect_cross_batch_conflicts([{"invoice": self._invoice3055(self.rolled3055)}])
        live = detector._detect_cross_batch_conflicts([{"invoice": self._invoice3055(self.live3055)}])
        self.assertEqual(rolled, [])
        self.assertEqual([c.conflict_type for c in live], ["cross_batch_conflict"])

    def test_race_manager_batch_conflict_check(self):
        from verenigingen.verenigingen_payments.utils.sepa_race_condition_manager import (
            SEPABatchRaceConditionManager,
        )

        manager = SEPABatchRaceConditionManager()
        rolled = manager._detect_batch_conflicts([self._invoice3055(self.rolled3055)], {})
        live = manager._detect_batch_conflicts([self._invoice3055(self.live3055)], {})
        self.assertEqual(rolled["conflicts"], [])
        self.assertEqual(len(live["conflicts"]), 1)

    def _make_eligible3055(self, batch):
        """PROBE SHORTCUT (declared): the factory batch's invoice has no dues schedule, which
        `get_eligible_invoices` joins on, so one is created and linked by db.set_value. The batch
        itself still reached its state through the real mark-paid / rollback flow."""
        row = batch.invoices[0]
        schedule = self._factory3055.create_test_membership_dues_schedule(
            member=row.member, payment_terms_template="SEPA Direct Debit"
        )
        frappe.db.set_value(
            "Sales Invoice",
            row.invoice,
            {
                "membership_dues_schedule_display": schedule.name,
                "member": row.member,
                "due_date": add_days(today(), -1),
            },
            update_modified=False,
        )
        return row.invoice

    def test_eligible_invoices_endpoint_offers_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.api.dd_batch_api import get_eligible_invoices

        rolled = self._make_eligible3055(self.rolled3055)
        live = self._make_eligible3055(self.live3055)
        # The live batch's invoice is Paid and its row Successful after mark-paid, which this
        # endpoint's row filter (Pending/Processing) already ignores. PROBE SHORTCUT (declared): put
        # the control back to an uncollected row on a live batch, so the batch lock is the only thing
        # that can hide it.
        frappe.db.set_value("Sales Invoice", live, {"outstanding_amount": 25, "status": "Unpaid"})
        frappe.db.set_value("Direct Debit Batch Invoice", {"parent": self.live3055.name}, "status", "Pending")
        offered = {i["name"] for i in get_eligible_invoices({}).get("invoices", [])}
        self.assertIn(rolled, offered)
        self.assertNotIn(live, offered)

    def _create_params3055(self, batch):
        row = batch.invoices[0]
        return {
            "batch_date": str(add_days(today(), 7)),
            "batch_type": "CORE",
            "invoice_list": [
                {
                    "invoice": row.invoice,
                    "amount": float(frappe.db.get_value("Sales Invoice", row.invoice, "outstanding_amount")),
                    "iban": row.iban.replace(" ", ""),
                    "member_name": row.member_name,
                    "mandate_reference": row.mandate_reference,
                    "currency": "EUR",
                }
            ],
        }

    def _assert_create_path3055(self, create):
        refused = create(**self._create_params3055(self.live3055))
        self.assertFalse(refused.get("success"), refused)
        self.assertIn("already in batch", str(refused), refused)
        created = create(**self._create_params3055(self.rolled3055))
        self.assertTrue(created.get("success"), created)
        self._batches3055.append(created["batch_name"])

    def test_create_sepa_batch_validated_accepts_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.api.sepa_batch_ui import create_sepa_batch_validated

        self._make_payable3055()
        self._assert_create_path3055(create_sepa_batch_validated)

    def test_create_sepa_batch_validated_secure_accepts_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.api.sepa_batch_ui_secure import (
            create_sepa_batch_validated_secure,
        )

        self._make_payable3055()
        self._assert_create_path3055(create_sepa_batch_validated_secure)

    def _make_payable3055(self):
        """PROBE SHORTCUT (declared): the live control's invoice is Paid after mark-paid, which the
        create path would refuse for being Paid before it ever reaches the batch lock. Reset it to
        Unpaid with its row Pending so only the lock can refuse it."""
        # The create path also resolves the member from the invoice's dues schedule (declared above).
        self._make_eligible3055(self.rolled3055)
        live = self._make_eligible3055(self.live3055)
        frappe.db.set_value("Sales Invoice", live, {"outstanding_amount": 25, "status": "Unpaid"})
        frappe.db.set_value("Direct Debit Batch Invoice", {"parent": self.live3055.name}, "status", "Pending")

    def test_optimizer_offers_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.api.dd_batch_optimizer import (
            get_eligible_invoices_for_batching,
        )

        self._make_payable3055()
        # PROBE SHORTCUT (declared): the optimizer also wants the member's own payment method and IBAN.
        for batch in (self.rolled3055, self.live3055):
            row = batch.invoices[0]
            frappe.db.set_value(
                "Member", row.member, {"payment_method": "SEPA Direct Debit", "iban": row.iban.replace(" ", "")}
            )
        offered = {r["invoice"] for r in get_eligible_invoices_for_batching()}
        self.assertIn(self.rolled3055.invoices[0].invoice, offered)
        self.assertNotIn(self.live3055.invoices[0].invoice, offered)

    def test_mandate_service_offers_the_rolled_back_invoice(self):
        from verenigingen.verenigingen_payments.utils.sepa_mandate_service import SEPAMandateService

        self._make_payable3055()
        rows = SEPAMandateService().get_sepa_invoices_with_mandates(str(add_days(today(), 7)))
        offered = {r["name"] for r in rows}
        self.assertIn(self.rolled3055.invoices[0].invoice, offered)
        self.assertNotIn(self.live3055.invoices[0].invoice, offered)
