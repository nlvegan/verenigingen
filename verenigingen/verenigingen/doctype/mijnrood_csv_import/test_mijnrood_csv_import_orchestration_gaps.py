# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# ORCHESTRATION-GAPS coverage for the Mijnrood CSV Import controller.
#
# Complements the five existing mijnrood test modules:
#   - test_mijnrood_csv_import.py
#   - test_mijnrood_csv_import_coverage.py
#   - test_mijnrood_csv_import_gapfill.py
#   - test_mijnrood_csv_import_orchestration.py
#   - test_mijnrood_csv_import_pipeline.py
#
# What those leave UNCOVERED and we exercise here (all REAL-DB, no business-logic
# mocks):
#   - _process_user_account_creation (def 541):
#       * empty processed_members -> "no members processed" short-circuit (549-551)
#       * happy path with REAL Active members: delegates to
#         queue_bulk_account_creation_for_members, the success guard at 577 passes,
#         the summary assembly at 584-610 runs, and (because the members are not
#         account-creatable here) it returns the "no accounts created or linked"
#         summary with NO tracker linked (584-610, 636-643).
#   - _process_bulk_volunteer_creation (def 651):
#       * no-eligible-members short-circuit (676-678)
#       * happy path with REAL Active members: delegates to the
#         BulkVolunteerCreationService, real Volunteer docs are created, and the
#         "N created" summary string is returned (660-717).
#   - retry_failed_account_creations (def 880): the FULL retry path beyond the
#     guard branches the pipeline suite already covers -- a real tracker whose
#     retry_queue references a real Failed ACR (with a real source_record member)
#     drives member extraction (929-934) and the re-queue call (947), which fails
#     validation and raises through the failed-queue / outer-except branches
#     (973-985).
#
# Test philosophy: nothing here patches frappe.db, the import controller, or the
# extracted services. We feed REAL members / trackers / ACRs and assert the REAL
# observable effect (returned summary strings, created Volunteer docs, the raised
# ValidationError).

import json
import random

import frappe

from verenigingen.verenigingen.doctype.mijnrood_csv_import.test_mijnrood_csv_import_pipeline import (
    _BaseMijnroodPipelineTest,
)


def _unique_email(prefix="mijnrood_orchgap"):
    return f"{prefix}_{random.randint(1000000, 9999999)}@integrationtest.invalid"


class TestMijnroodUserAccountCreationOrchestration(_BaseMijnroodPipelineTest):
    """_process_user_account_creation: empty short-circuit + real delegation."""

    def test_user_account_creation_empty_members_short_circuits(self):
        """An empty processed_members list returns the 'no members processed'
        marker without queuing anything (lines 549-551)."""
        doc = self._make_import_doc(
            [{"Voornaam": "Empty", "Achternaam": "Users", "E-mailadres": _unique_email()}],
            create_user_accounts=0,
        )
        summary = doc._process_user_account_creation([])
        self.assertEqual(summary, ". No user accounts created (no members processed)")
        # No tracker is linked when nothing is queued.
        self.assertFalse(doc.bulk_operation_tracker)

    def test_user_account_creation_no_creatable_members_returns_empty_summary(self):
        """A Suspended member is status-valid for the queue but cannot have an
        account created (a validation error inside the service), so zero requests
        are produced: the success guard passes and the summary-assembly branch
        yields the 'no accounts created or linked' summary with NO tracker linked
        (lines 584-610, 636-643). No batch runs (no requests created)."""
        member = self._make_member(first_name="UserSusp", status="Suspended")
        doc = self._make_import_doc(
            [{"Voornaam": "US", "Achternaam": "Real", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        summary = doc._process_user_account_creation([member.name])
        self.assertEqual(summary, ". No user accounts created or linked")
        self.assertNotIn("failed", summary)
        # No progress tracker was produced/linked for an empty queue result.
        self.assertFalse(doc.bulk_operation_tracker)

    def test_user_account_creation_filtered_members_returns_failure_summary(self):
        """A Banned member is filtered out by status before any request is created,
        so the service returns success=False ('No valid members found'). The
        method's failure guard (577-582) returns a 'User account creation failed'
        summary and links NO tracker."""
        member = self._make_member(first_name="UserBan", status="Banned")
        doc = self._make_import_doc(
            [{"Voornaam": "UB", "Achternaam": "Real", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        # The failure branch logs the queue failure as an Error Log (real path).
        self.expectErrorLog("Mijnrood Bulk Account Creation Error")
        summary = doc._process_user_account_creation([member.name])
        self.assertIn("User account creation failed", summary)
        self.assertIn("No valid members found", summary)
        self.assertFalse(doc.bulk_operation_tracker)


class TestMijnroodBulkVolunteerCreationOrchestration(_BaseMijnroodPipelineTest):
    """_process_bulk_volunteer_creation: no-eligible short-circuit + real creation."""

    def _track_volunteers_for(self, *member_names):
        for member_name in member_names:
            for v in frappe.get_all("Volunteer", filters={"member": member_name}, pluck="name"):
                if v not in self._created_volunteers:
                    self._created_volunteers.append(v)

    def test_bulk_volunteer_creation_no_eligible_members(self):
        """A processed_members list with no Active members (the fallback filter
        finds nobody) returns the 'no eligible members' marker (676-678)."""
        inactive = self._make_member(first_name="Inact", status="Suspended")
        doc = self._make_import_doc(
            [{"Voornaam": "NoVol", "Achternaam": "Eligible", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        summary = doc._process_bulk_volunteer_creation([inactive.name])
        self.assertEqual(summary, ". No volunteer records created (no eligible members)")
        # No Volunteer was created for the inactive member.
        self.assertFalse(frappe.db.exists("Volunteer", {"member": inactive.name}))

    def test_bulk_volunteer_creation_empty_list_no_eligible(self):
        """An empty processed_members list yields no eligible members (676-678)."""
        doc = self._make_import_doc(
            [{"Voornaam": "EmptyVol", "Achternaam": "List", "E-mailadres": _unique_email()}],
        )
        summary = doc._process_bulk_volunteer_creation([])
        self.assertEqual(summary, ". No volunteer records created (no eligible members)")

    def test_bulk_volunteer_creation_creates_real_volunteers(self):
        """Two REAL Active members drive the BulkVolunteerCreationService: real
        Volunteer docs are created and the summary reports the created count
        (660-717)."""
        member_a = self._make_member(first_name="VolA", status="Active", birth_date="1980-01-01")
        member_b = self._make_member(first_name="VolB", status="Active", birth_date="1981-02-02")
        doc = self._make_import_doc(
            [{"Voornaam": "BV", "Achternaam": "Real", "E-mailadres": _unique_email()}],
            create_volunteer_records=1,
        )
        summary = doc._process_bulk_volunteer_creation([member_a.name, member_b.name])
        self._track_volunteers_for(member_a.name, member_b.name)

        # The summary reflects a real creation result (not the no-eligible marker
        # and not the failure fallback).
        self.assertIn("Volunteers", summary)
        self.assertNotIn("No volunteer records created", summary)
        self.assertNotIn("Volunteer creation failed", summary)
        # Real Volunteer docs now exist for both active members.
        self.assertTrue(frappe.db.exists("Volunteer", {"member": member_a.name}))
        self.assertTrue(frappe.db.exists("Volunteer", {"member": member_b.name}))


class TestMijnroodRetryAccountCreationsFullPath(_BaseMijnroodPipelineTest):
    """retry_failed_account_creations: the full re-queue path past the guards."""

    def test_retry_with_real_failed_acr_requeues_and_raises_on_validation(self):
        """A real tracker whose retry_queue references a real Failed ACR (backed by
        a real source_record member) drives member extraction (929-934) and the
        re-queue call (947). The bare member is not account-creatable, so the
        re-queue returns success=False, hitting the failed-queue throw which the
        outer except re-raises as a ValidationError (973-985)."""
        tracker = self._make_tracker(total_records=1, successful_records=0, failed_records=1)
        # A real Failed ACR whose source_record is a real Member.
        acr = self._make_failed_acr(tracker.name, failure_reason="initial boom")
        frappe.db.set_value("Bulk Operation Tracker", tracker.name, "retry_queue", json.dumps([acr.name]))
        doc = self._make_import_doc(
            [{"Voornaam": "Retry", "Achternaam": "Full", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
            create_volunteer_records=0,
        )
        # The method calls frappe.log_error on the failure branch before re-raising.
        self.expectErrorLog("CSV Import Retry Error")
        with self.assertRaises(frappe.exceptions.ValidationError) as ctx:
            doc.retry_failed_account_creations()
        # The raised message is the wrapped failed-queue error, proving we reached
        # the re-queue call (not an earlier guard branch).
        self.assertIn("Error retrying failed account creations", str(ctx.exception))
        self.assertIn("Failed to queue retry", str(ctx.exception))
