#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests for verenigingen_payments/api/dd_batch_api.py

Covers the whitelisted Direct Debit Batch management endpoints and their helper
functions with REAL DocTypes (Direct Debit Batch / Direct Debit Batch Invoice /
SEPA Mandate / Member / Sales Invoice) built via the SEPA test factory.

Tests run as Administrator, which the SEPA authorization layer grants full
permissions to (see authorization.py get_user_permissions), and which satisfies
can_manage_dd_batches()/can_create_dd_batches() because Administrator holds
System Manager.
"""

from datetime import datetime, timedelta

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.api.dd_batch_api import (
    apply_conflict_resolutions,
    calculate_eligibility_score,
    can_create_dd_batches,
    can_manage_dd_batches,
    escalate_conflicts,
    get_batch_conflicts,
    get_batch_details_with_security,
    get_batch_list_with_security,
    get_eligible_invoices,
)


class TestDDBatchAPI(EnhancedTestCase):
    """Integration tests for the Direct Debit Batch API endpoints."""

    def setUp(self):
        super().setUp()
        self.sepa_factory = SEPATestDataFactory(seed=self.factory.seed, use_faker=self.factory.use_faker)
        self._batch = None

    # ------------------------------------------------------------------ helpers

    def _make_member_with_mandate(self, first_name="DDTest"):
        """Create a member + linked customer + active SEPA mandate + membership."""
        member = self.sepa_factory.create_test_member(first_name=first_name)
        customer = self.sepa_factory.create_test_customer(customer_name=f"Customer {member.full_name}")
        member.db_set("customer", customer.name)
        membership = self.sepa_factory.create_test_membership(member=member.name)
        mandate = self.sepa_factory.create_test_sepa_mandate(member=member.name)
        for dt, name in (
            ("Member", member.name),
            ("Customer", customer.name),
            ("Membership", membership.name),
            ("SEPA Mandate", mandate.name),
        ):
            self._track_test_document(dt, name)
        return member, customer, membership, mandate

    def _make_batch(self, entry_status="Pending", with_invoice=True, amount=25.0):
        """Build and insert a Direct Debit Batch with one invoice row."""
        member, customer, membership, mandate = self._make_member_with_mandate()
        invoice = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name,
            member=member.name,
            status="Unpaid",
            grand_total=amount,
            submit=True,
        )
        self._track_test_document("Sales Invoice", invoice.name)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.collection_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        batch.batch_description = "DD API Test Batch"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "FRST"  # SEPA sequence
        batch.currency = "EUR"

        if with_invoice:
            batch.append(
                "invoices",
                {
                    "invoice": invoice.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": amount,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": entry_status,
                    "sequence_type": "FRST",
                },
            )

        batch.insert()
        self._track_test_document("Direct Debit Batch", batch.name)
        self._batch = batch
        return batch, member, mandate, invoice

    # ------------------------------------------------ can_manage / can_create

    def test_can_manage_dd_batches_administrator(self):
        self.assertTrue(can_manage_dd_batches())

    def test_can_create_dd_batches_administrator(self):
        self.assertTrue(can_create_dd_batches())

    # ----------------------------------------------- get_batch_list_with_security

    def test_get_batch_list_returns_inserted_batch(self):
        batch, *_ = self._make_batch()
        result = get_batch_list_with_security()
        self.assertTrue(result["success"])
        names = [b["name"] for b in result["batches"]]
        self.assertIn(batch.name, names)
        row = next(b for b in result["batches"] if b["name"] == batch.name)
        # One pending entry expected
        self.assertEqual(row["pending_count"], 1)
        self.assertEqual(row["processed_count"], 0)
        self.assertEqual(row["failed_count"], 0)
        self.assertEqual(result["total_batches"], len(result["batches"]))

    def test_get_batch_list_status_filter_excludes(self):
        batch, *_ = self._make_batch()
        # Filter on a status the batch does not have -> batch absent
        result = get_batch_list_with_security({"status": "Processed"})
        self.assertTrue(result["success"])
        self.assertNotIn(batch.name, [b["name"] for b in result["batches"]])

    def test_get_batch_list_date_range_filter(self):
        batch, *_ = self._make_batch()
        result = get_batch_list_with_security({"from_date": today(), "to_date": today()})
        self.assertTrue(result["success"])
        self.assertIn(batch.name, [b["name"] for b in result["batches"]])

    def test_get_batch_list_to_date_only_filter(self):
        batch, *_ = self._make_batch()
        result = get_batch_list_with_security({"to_date": today()})
        self.assertTrue(result["success"])
        self.assertIn(batch.name, [b["name"] for b in result["batches"]])

    # --------------------------------------------- get_batch_details_with_security

    def test_get_batch_details_happy_path(self):
        batch, member, mandate, invoice = self._make_batch()
        result = get_batch_details_with_security(batch.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["batch"]["name"], batch.name)
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["summary"]["total_entries"], 1)
        self.assertEqual(result["summary"]["pending_entries"], 1)
        self.assertEqual(result["summary"]["pending_amount"], 25.0)
        self.assertEqual(result["summary"]["total_amount"], 25.0)

    def test_get_batch_details_missing_batch_returns_failure(self):
        # @handle_api_error converts the raised ValidationError into a failed
        # OperationResult, which the security decorator serialises to a dict.
        result = get_batch_details_with_security("NON-EXISTENT-BATCH-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"]["message"])

    def test_get_batch_details_requires_batch_id(self):
        result = get_batch_details_with_security(None)
        self.assertFalse(result["success"])

    # ----------------------------------------------------- get_batch_conflicts

    def test_get_batch_conflicts_no_failures(self):
        batch, *_ = self._make_batch(entry_status="Pending")
        result = get_batch_conflicts(batch.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["batch_id"], batch.name)
        self.assertEqual(result["total_conflicts"], 0)
        self.assertEqual(result["conflicts"], [])

    def test_get_batch_conflicts_missing_batch_returns_failure(self):
        result = get_batch_conflicts("NON-EXISTENT-BATCH-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"]["message"])

    def test_get_batch_conflicts_failed_entry_generic_resolution(self):
        """A failed entry with a generic error message yields a manual_review option.

        This exercises the 'else' branch of the resolution suggestion logic
        without hitting the IBAN branch (see test_get_batch_conflicts_iban_branch).
        """
        batch, *_ = self._make_batch(entry_status="Pending")
        # Set the child row to Failed with a generic message directly in the DB so
        # we don't trigger batch revalidation.
        entry_name = batch.invoices[0].name
        frappe.db.set_value(
            "Direct Debit Batch Invoice",
            entry_name,
            {"status": "Failed", "result_message": "Bank rejected: insufficient funds"},
        )
        result = get_batch_conflicts(batch.name)
        self.assertTrue(result["success"])
        self.assertEqual(result["total_conflicts"], 1)
        conflict = result["conflicts"][0]
        self.assertEqual(conflict["type"], "processing_error")
        actions = [o["action"] for o in conflict["resolution_options"]]
        self.assertIn("manual_review", actions)

    def test_get_batch_conflicts_mandate_branch(self):
        """A failed entry mentioning 'mandate' yields update_mandate/exclude options."""
        batch, *_ = self._make_batch(entry_status="Pending")
        entry_name = batch.invoices[0].name
        frappe.db.set_value(
            "Direct Debit Batch Invoice",
            entry_name,
            {"status": "Failed", "result_message": "SEPA mandate revoked"},
        )
        result = get_batch_conflicts(batch.name)
        conflict = result["conflicts"][0]
        actions = [o["action"] for o in conflict["resolution_options"]]
        self.assertIn("update_mandate", actions)
        self.assertIn("exclude_entry", actions)

    def test_get_batch_conflicts_iban_branch(self):
        """A failed entry whose message mentions 'iban' (but not 'mandate') gets
        the IBAN-specific update_iban resolution option.

        Regression: the branch previously read a non-existent entry.error_message
        field, so it was always empty and IBAN errors fell through to the generic
        manual_review option. The branch now reads result_message.
        """
        batch, *_ = self._make_batch(entry_status="Pending")
        entry_name = batch.invoices[0].name
        frappe.db.set_value(
            "Direct Debit Batch Invoice",
            entry_name,
            {"status": "Failed", "result_message": "Invalid iban for account"},
        )
        result = get_batch_conflicts(batch.name)
        conflict = result["conflicts"][0]
        actions = [o["action"] for o in conflict["resolution_options"]]
        self.assertIn("update_iban", actions)
        self.assertNotIn("manual_review", actions)

    def test_get_batch_conflicts_duplicate_mandate(self):
        """Two entries sharing a mandate_reference produce a duplicate_mandate conflict."""
        member, customer, membership, mandate = self._make_member_with_mandate()
        inv1 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        inv2 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        self._track_test_document("Sales Invoice", inv1.name)
        self._track_test_document("Sales Invoice", inv2.name)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Dup mandate batch"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "FRST"  # SEPA sequence
        batch.currency = "EUR"
        for inv in (inv1, inv2):
            batch.append(
                "invoices",
                {
                    "invoice": inv.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": 25.0,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    "sequence_type": "FRST",
                },
            )
        batch.insert()
        self._track_test_document("Direct Debit Batch", batch.name)

        result = get_batch_conflicts(batch.name)
        dup = [c for c in result["conflicts"] if c["type"] == "duplicate_mandate"]
        self.assertEqual(len(dup), 1)
        self.assertEqual(dup[0]["mandate_reference"], mandate.mandate_id)
        self.assertEqual(dup[0]["count"], 2)
        actions = [o["action"] for o in dup[0]["resolution_options"]]
        # exclude_duplicates is no longer offered: apply_conflict_resolutions has
        # no branch for it, so selecting it was a silent no-op (#615).
        self.assertEqual(actions, ["consolidate_entries"])

    # ------------------------------------------------------ get_eligible_invoices

    def test_get_eligible_invoices_finds_mandated_invoice(self):
        """A valid unpaid + due + active-mandate member's invoice is returned as
        eligible.

        Regression: get_eligible_invoices previously joined Member with
        `ON si.customer = mem.name` (Customer name vs Member ID), so the join
        never matched and EVERY invoice was filtered out by `sm.mandate_id IS NOT
        NULL`. The join is now `ON mem.customer = si.customer`.
        """
        from frappe.utils import add_days

        member, customer, membership, mandate = self._make_member_with_mandate()
        invoice = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name,
            member=member.name,
            status="Unpaid",
            grand_total=75.0,
            due_date=add_days(today(), -5),
            submit=True,
        )
        self._track_test_document("Sales Invoice", invoice.name)

        result = get_eligible_invoices()
        self.assertTrue(result["success"])
        match = [i for i in result["invoices"] if i["name"] == invoice.name]
        self.assertEqual(
            len(match),
            1,
            "Member join should make the mandated invoice eligible",
        )
        self.assertEqual(match[0]["mandate_reference"], mandate.mandate_id)

    def test_get_eligible_invoices_returns_dict_structure(self):
        """The response envelope is well-formed."""
        result = get_eligible_invoices({"amount_min": 1000})
        self.assertTrue(result["success"])
        self.assertIn("invoices", result)
        self.assertIn("total_invoices", result)
        self.assertEqual(result["filters_applied"], {"amount_min": 1000})
        self.assertEqual(result["total_invoices"], len(result["invoices"]))

    # --------------------------------------------------- apply_conflict_resolutions

    def test_apply_conflict_resolutions_exclude_entry_removes_row(self):
        """exclude_entry removes one entry from the batch entirely so it will not
        be debited, leaving the rest intact.

        Regression: it previously set status='Excluded' (an undeclared Select
        value that SEPA generation ignores anyway), and the change was then
        reverted by a save() on a stale in-memory batch. The entry is now deleted
        and the reload before save() keeps the deletion.
        """
        member, customer, membership, mandate = self._make_member_with_mandate()
        inv1 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        inv2 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        self._track_test_document("Sales Invoice", inv1.name)
        self._track_test_document("Sales Invoice", inv2.name)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Exclude batch"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "FRST"  # SEPA sequence
        batch.currency = "EUR"
        for inv in (inv1, inv2):
            batch.append(
                "invoices",
                {
                    "invoice": inv.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": 25.0,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    "sequence_type": "FRST",
                },
            )
        batch.insert()
        self._track_test_document("Direct Debit Batch", batch.name)
        excluded_name = batch.invoices[0].name
        kept_name = batch.invoices[1].name

        resolutions = [{"action": "exclude_entry", "entry_id": excluded_name}]
        result = apply_conflict_resolutions(batch.name, resolutions)
        self.assertTrue(result["success"])  # endpoint returns success wrapper
        res0 = result["resolution_results"][0]
        self.assertTrue(res0["success"])
        self.assertIn("excluded", res0["message"].lower())

        # The excluded entry is gone; the other entry remains.
        self.assertFalse(
            frappe.db.exists("Direct Debit Batch Invoice", excluded_name),
            "exclude_entry should delete the child row",
        )
        batch.reload()
        remaining = [e.name for e in batch.invoices]
        self.assertNotIn(excluded_name, remaining)
        self.assertIn(kept_name, remaining)

    def test_apply_conflict_resolutions_consolidate_entries_keeps_invoices_apart(self):
        """consolidate_entries must NOT merge two distinct invoices into one debit.

        This test used to assert the opposite -- "a single row with the summed
        55.0" -- and that assertion is why the behaviour looked deliberate. It was
        written for a real regression (a stale in-memory batch.save() reverting the
        child-row edits) and was right about that; the reload it guards is now
        exercised by the de-duplication case in
        tests/sepa/test_dd_batch_conflict_resolution.py, which asserts the removal
        survives the parent save.

        Merging distinct invoices debits their sum through the surviving row while
        `mark_batch_invoices_as_paid` only ever visits the rows that remain, so the
        deleted row's invoice is collected and never reconciled (#626).
        """
        member, customer, membership, mandate = self._make_member_with_mandate()
        inv1 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        inv2 = self.sepa_factory.create_test_sales_invoice(
            customer=customer.name, member=member.name, status="Unpaid", submit=True
        )
        self._track_test_document("Sales Invoice", inv1.name)
        self._track_test_document("Sales Invoice", inv2.name)

        batch = frappe.new_doc("Direct Debit Batch")
        batch.batch_date = today()
        batch.batch_description = "Consolidate batch"
        batch.batch_type = "CORE"  # SEPA scheme
        batch.sequence_type = "FRST"  # SEPA sequence
        batch.currency = "EUR"
        for inv, amt in ((inv1, 25.0), (inv2, 30.0)):
            batch.append(
                "invoices",
                {
                    "invoice": inv.name,
                    "membership": membership.name,
                    "member": member.name,
                    "member_name": member.full_name,
                    "amount": amt,
                    "currency": "EUR",
                    "iban": mandate.iban,
                    "mandate_reference": mandate.mandate_id,
                    "status": "Pending",
                    "sequence_type": "FRST",
                },
            )
        batch.insert()
        self._track_test_document("Direct Debit Batch", batch.name)

        resolutions = [{"action": "consolidate_entries", "mandate_reference": mandate.mandate_id}]
        result = apply_conflict_resolutions(batch.name, resolutions)
        # Nothing was applied, so the envelope reports no change (#615).
        self.assertFalse(result["success"])
        self.assertFalse(result["batch_updated"])
        res0 = result["resolution_results"][0]
        # The resolution refuses, and says why.
        self.assertFalse(res0["success"], res0.get("message"))
        self.assertIn("Nothing to consolidate", res0["message"])

        # Both debts remain, as separate debits that each name their own invoice.
        remaining = frappe.get_all(
            "Direct Debit Batch Invoice",
            filters={"parent": batch.name, "mandate_reference": mandate.mandate_id},
            fields=["name", "invoice", "amount"],
        )
        self.assertEqual(sorted(r["amount"] for r in remaining), [25.0, 30.0])
        self.assertEqual({r["invoice"] for r in remaining}, {inv1.name, inv2.name})

    def test_apply_conflict_resolutions_requires_inputs(self):
        result = apply_conflict_resolutions(None, None)
        self.assertFalse(result["success"])

    # ----------------------------------------------------------- escalate_conflicts

    def test_escalate_conflicts_happy_path(self):
        batch, *_ = self._make_batch()
        conflicts = [{"member_name": "Jane Doe", "error": "Mandate revoked", "type": "processing_error"}]
        result = escalate_conflicts(batch.name, conflicts)
        self.assertTrue(result["success"])
        self.assertEqual(result["batch_id"], batch.name)
        self.assertEqual(result["escalated_conflicts"], 1)
        self.assertIsInstance(result["notifications_sent"], int)
        # A comment should have been added to the batch.
        comments = frappe.get_all(
            "Comment",
            filters={
                "reference_doctype": "Direct Debit Batch",
                "reference_name": batch.name,
                "comment_type": "Comment",
            },
            fields=["content"],
        )
        self.assertTrue(any("escalated" in (c["content"] or "").lower() for c in comments))

    def test_escalate_conflicts_requires_inputs(self):
        result = escalate_conflicts(None, None)
        self.assertFalse(result["success"])

    # ----------------------------------------------------- calculate_eligibility_score

    def test_calculate_eligibility_score_high(self):
        from frappe.utils import add_days

        score = calculate_eligibility_score(
            frappe._dict(
                {
                    "due_date": add_days(today(), -40),
                    "outstanding_amount": 200,
                    "mandate_status": "Active",
                }
            )
        )
        # >30 days (50) + >100 amount (30) + active mandate (40) = 120
        self.assertEqual(score, 120)

    def test_calculate_eligibility_score_low(self):
        score = calculate_eligibility_score(
            frappe._dict(
                {
                    "due_date": today(),
                    "outstanding_amount": 5,
                    "mandate_status": "Inactive",
                }
            )
        )
        # due today (>=0 -> 20) + amount 5 (>0 -> 10) + no active mandate (0) = 30
        self.assertEqual(score, 30)
