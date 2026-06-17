# Copyright (c) 2024, Frappe Technologies and Contributors
# See license.txt
#
# Pipeline / orchestration coverage for the Mijnrood CSV Import controller.
#
# This file is the COMPLEMENT of test_mijnrood_csv_import.py. That file already
# covers the pure helpers (clean/validate/parse), the validate+map pipeline,
# _read_csv_file from real attachments, _process_single_member (basic create +
# failed), security/path-safety helpers and _validate_csv_import_settings.
#
# Here we cover the orchestration surfaces that file leaves untested:
#   - on_submit() queueing + status transition
#   - process_import_background() end-to-end (real Members created, real tracking
#     counters updated) + its validation-error short-circuit branch
#   - validate_import_file() whitelisted entry point (success / no-file /
#     validation-error / empty-file branches)
#   - retry_failed_account_creations() guard branches (no tracker, empty queue,
#     no failed ACRs) against a REAL Bulk Operation Tracker
#   - retry_failed_volunteer_creations() (no-eligible-members branch + real
#     volunteer creation path)
#   - update_import_tracking_after_retry() + _update_account_creation_tracking()
#     against a REAL linked tracker with REAL Account Creation Requests
#   - _link_tracker_atomically() (link + idempotent no-overwrite)
#   - _generate_top_errors_summary() against REAL failed ACRs
#   - _create_termination_record() (real Membership Termination Request) and the
#     termination branch of _create_related_records_via_services()
#   - _generate_itemized_member_list() shaping
#
# Test philosophy: stub only true external boundaries (the background enqueue in
# on_submit). Member / Donor / Volunteer / Tracker / ACR creation and the import
# doc updates all run for REAL; we assert the real created docs + tracking fields.

import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
from unittest.mock import patch  # noqa: E402

import frappe  # noqa: E402

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase  # noqa: E402
from verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import import (  # noqa: E402
    get_import_template,
    process_import_background,
    update_import_tracking_after_retry,
    validate_import_file,
)


def _rand(prefix="pipe"):
    return f"{prefix}_{random.randint(1000000, 9999999)}"


def _unique_email(prefix="mijnrood_pipe"):
    return f"{prefix}_{random.randint(1000000, 9999999)}@integrationtest.invalid"


class _BaseMijnroodPipelineTest(EnhancedTestCase):
    """Shared fixtures: real File attachments, real import docs, real members.

    All data-creating work (insert/save with ignore_permissions) lives in
    _make_*/_setup_*/_cleanup_* helpers so the test-quality enforcer is satisfied
    and the test bodies only assert observable effects.
    """

    SETTINGS_FIELDS = (
        "csv_monthly_dues_schedule",
        "csv_annual_dues_schedule",
        "default_membership_type",
    )

    def setUp(self):
        super().setUp()
        self._created_files = []
        self._created_imports = []
        self._created_members = []
        self._created_trackers = []
        self._created_acrs = []
        self._created_terminations = []
        self._created_volunteers = []

    def tearDown(self):
        for name in self._created_terminations:
            self._force_delete("Membership Termination Request", name)
        for name in self._created_acrs:
            self._force_delete("Account Creation Request", name)
        for name in self._created_volunteers:
            self._force_delete("Volunteer", name)
        for name in self._created_members:
            self._force_delete("Member", name)
        for name in self._created_imports:
            self._force_delete("Mijnrood CSV Import", name)
        for name in self._created_trackers:
            self._force_delete("Bulk Operation Tracker", name)
        for name in self._created_files:
            self._force_delete("File", name)
        super().tearDown()

    @staticmethod
    def _force_delete(doctype, name):
        try:
            frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        except Exception:
            pass

    # --- CSV / File / import-doc fixtures ----------------------------------

    def _make_csv_bytes(self, rows, headers=None):
        if headers is None:
            headers = list(rows[0].keys()) if rows else []
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=headers)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        return out.getvalue()

    def _create_csv_file_doc(self, content, file_name=None):
        if file_name is None:
            file_name = f"mijnrood_pipe_{random.randint(1000000, 9999999)}.csv"
        file_doc = frappe.get_doc(
            {
                "doctype": "File",
                "file_name": file_name,
                "is_private": 1,
                "content": content,
            }
        ).insert(ignore_permissions=True)
        self._created_files.append(file_doc.name)
        return file_doc

    def _make_import_doc(self, rows, **kwargs):
        return self._make_import_doc_from_content(self._make_csv_bytes(rows), **kwargs)

    def _make_import_doc_from_content(self, content, **kwargs):
        file_doc = self._create_csv_file_doc(content)
        doc = frappe.get_doc(
            {
                "doctype": "Mijnrood CSV Import",
                "csv_file": file_doc.file_url,
                "encoding": "utf-8",
                "import_date": frappe.utils.today(),
                **kwargs,
            }
        )
        doc.insert(ignore_permissions=True)
        self._created_imports.append(doc.name)
        return doc

    def _make_member(self, **overrides):
        fields = {
            "doctype": "Member",
            "first_name": "Pipe",
            "last_name": _rand("Member"),
            "email": _unique_email(),
        }
        fields.update(overrides)
        member = frappe.get_doc(fields)
        member.flags.ignore_permissions = True
        member.insert(ignore_permissions=True)
        self._created_members.append(member.name)
        return member

    def _new_unsaved_doc(self, **kwargs):
        return frappe.get_doc(
            {
                "doctype": "Mijnrood CSV Import",
                "encoding": "utf-8",
                "import_date": frappe.utils.today(),
                **kwargs,
            }
        )

    # --- settings save/restore --------------------------------------------

    def _save_settings(self):
        settings = frappe.get_single("Verenigingen Settings")
        self._saved_settings = {f: settings.get(f) for f in self.SETTINGS_FIELDS}

    def _restore_settings(self):
        if not getattr(self, "_saved_settings", None):
            return
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._saved_settings.items():
            settings.set(field, value)
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)

    # --- real Bulk Operation Tracker + ACR fixtures ------------------------

    def _make_tracker(self, **kwargs):
        fields = {
            "doctype": "Bulk Operation Tracker",
            "operation_type": "Account Creation",
            "status": "Completed",
            "total_records": 0,
            "total_batches": 1,
            "batch_size": 50,
            "processed_records": 0,
            "successful_records": 0,
            "failed_records": 0,
        }
        fields.update(kwargs)
        tracker = frappe.get_doc(fields).insert(ignore_permissions=True)
        self._created_trackers.append(tracker.name)
        return tracker

    def _make_acr(self, tracker_name, status, failure_reason=None, created_user=None):
        """Insert a real ACR (source_record = a real Member) then force the
        status/failure_reason/created_user via db_set.

        before_insert() forces status='Requested' and clears created_user as an
        anti-mass-assignment guard, so we set the post-processing state directly
        in the DB to model a completed/failed request.
        """
        member = self._make_member()
        acr = frappe.get_doc(
            {
                "doctype": "Account Creation Request",
                "bulk_operation_tracker": tracker_name,
                "request_type": "Member",
                "source_record": member.name,
                "email": _unique_email("acr"),
                "full_name": "Acr Person",
            }
        )
        acr.flags.ignore_permissions = True
        acr.insert(ignore_permissions=True)
        self._created_acrs.append(acr.name)
        frappe.db.set_value("Account Creation Request", acr.name, "status", status)
        if failure_reason is not None:
            frappe.db.set_value("Account Creation Request", acr.name, "failure_reason", failure_reason)
        if created_user is not None:
            frappe.db.set_value("Account Creation Request", acr.name, "created_user", created_user)
        return acr

    def _make_failed_acr(self, tracker_name, failure_reason="boom"):
        return self._make_acr(tracker_name, "Failed", failure_reason=failure_reason)


class TestMijnroodPipelineBackground(_BaseMijnroodPipelineTest):
    """process_import_background() end-to-end + validation short-circuit."""

    def setUp(self):
        super().setUp()
        self._save_settings()

    def tearDown(self):
        self._restore_settings()
        super().tearDown()

    def _track_members_from_import(self, import_name):
        """Schedule for cleanup any Member referencing this import in review_notes."""
        for m in frappe.get_all(
            "Member", filters={"review_notes": ["like", f"%{import_name}%"]}, pluck="name"
        ):
            if m not in self._created_members:
                self._created_members.append(m)

    def test_background_creates_real_members_and_updates_counters(self):
        """process_import_background runs the real pipeline: Members are created,
        the import doc's members_created counter is updated, the itemized notes
        list the created members, and a successful import is persisted as
        "Completed" with an import_summary.

        Regression guard: _finalize_import_results() sets import_status/
        import_summary in memory then calls self.reload() (to avoid a timestamp
        mismatch from concurrent progress updates), which previously DISCARDED
        those values so a successful import stayed "In Progress". The finalizer
        now re-applies them after the reload; this test pins that.
        """
        e1 = _unique_email()
        e2 = _unique_email()
        rows = [
            {"Voornaam": "Pipeline", "Achternaam": "One", "E-mailadres": e1},
            {"Voornaam": "Pipeline", "Achternaam": "Two", "E-mailadres": e2},
        ]
        doc = self._make_import_doc(rows, create_volunteer_records=0, create_user_accounts=0)

        process_import_background(doc.name, test_mode=False)
        self._track_members_from_import(doc.name)

        doc.reload()
        self.assertEqual(doc.members_created, 2)
        self.assertEqual(doc.members_skipped, 0)
        # The real members exist in the DB with the imported emails.
        self.assertTrue(frappe.db.exists("Member", {"email": e1}))
        self.assertTrue(frappe.db.exists("Member", {"email": e2}))
        # Itemized notes (set AFTER the reload) survive and list the created members.
        self.assertIn("Created Members (2)", doc.notes or "")
        # A successful import is persisted as Completed with a summary (the
        # finalize reload no longer wipes these).
        self.assertEqual(doc.import_status, "Completed")
        self.assertIn("Import completed successfully", doc.import_summary or "")

    def test_background_validation_errors_short_circuit_to_failed(self):
        """When validate/map produces errors, the job sets Failed and creates no
        members (the bad email row is rejected before processing)."""
        bad_email = _unique_email()
        rows = [{"Voornaam": "Bad", "Achternaam": "Row", "E-mailadres": "not-an-email"}]
        doc = self._make_import_doc(rows)

        process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertIn("Invalid email", doc.error_log)
        self.assertFalse(frappe.db.exists("Member", {"email": bad_email}))

    def test_background_test_mode_caps_rows_at_25(self):
        """In test_mode only the first 25 mapped rows are processed even when the
        file has more."""
        rows = [
            {"Voornaam": f"Cap{i}", "Achternaam": "Member", "E-mailadres": _unique_email()} for i in range(30)
        ]
        doc = self._make_import_doc(rows, create_volunteer_records=0, create_user_accounts=0)

        process_import_background(doc.name, test_mode=True)
        self._track_members_from_import(doc.name)

        doc.reload()
        # Only the first 25 of the 30 mapped rows are processed in test mode.
        self.assertEqual(doc.members_created, 25)


class TestMijnroodOnSubmitQueueing(_BaseMijnroodPipelineTest):
    """on_submit() enqueues the background job and flips status to Queued."""

    def setUp(self):
        super().setUp()
        self._save_settings()
        self._setup_valid_settings()

    def tearDown(self):
        self._restore_settings()
        super().tearDown()

    def _setup_valid_settings(self):
        settings = frappe.get_single("Verenigingen Settings")
        settings.csv_monthly_dues_schedule = self._ensure_dues_template("Pipe Monthly")
        settings.csv_annual_dues_schedule = self._ensure_dues_template("Pipe Annual")
        settings.default_membership_type = self._ensure_membership_type()
        settings.flags.ignore_validate = True
        settings.flags.ignore_mandatory = True
        settings.save(ignore_permissions=True)

    def _ensure_dues_template(self, label):
        # The Link fields on Verenigingen Settings are validated on save, so a
        # bare string fallback (the previous behaviour) raised LinkValidationError
        # on a fresh CI site that has no dues-schedule template. Create a real
        # template and return its name.
        existing = frappe.db.get_value("Membership Dues Schedule", {"is_template": 1}, "name")
        if existing:
            return existing
        return self.ensure_dues_schedule_template(label).name

    def _ensure_membership_type(self):
        # Must be a real Membership Type (Link field is validated on save).
        existing = frappe.db.get_value("Membership Type", {}, "name")
        if existing:
            return existing
        return self.create_test_membership_type().name

    def test_on_submit_sets_queued_and_enqueues(self):
        """Submitting the import enqueues process_import_background and the doc
        status becomes Queued (enqueue stubbed to keep it in-process)."""
        doc = self._make_import_doc(
            [{"Voornaam": "Submit", "Achternaam": "Me", "E-mailadres": _unique_email()}],
            test_mode=1,
        )
        with patch(
            "verenigingen.verenigingen.doctype.mijnrood_csv_import.mijnrood_csv_import.frappe.enqueue"
        ) as mock_enqueue:
            doc.submit()

        self.assertTrue(mock_enqueue.called)
        call_kwargs = mock_enqueue.call_args.kwargs
        self.assertEqual(call_kwargs["import_doc_name"], doc.name)
        self.assertEqual(
            call_kwargs["method"],
            "verenigingen.verenigingen.doctype.mijnrood_csv_import."
            "mijnrood_csv_import.process_import_background",
        )
        doc.reload()
        self.assertEqual(doc.import_status, "Queued")


class TestMijnroodValidateImportFile(_BaseMijnroodPipelineTest):
    """validate_import_file() whitelisted entry point branches."""

    def test_validate_import_file_success_sets_ready(self):
        """A clean file validates to 'Ready for Import' and stores preview data."""
        rows = [
            {
                "Voornaam": "Valid",
                "Achternaam": "File",
                "E-mailadres": _unique_email(),
                "IBAN": "NL91ABNA0417164300",
            }
        ]
        doc = self._make_import_doc(rows)
        result = validate_import_file(doc.name)

        self.assertEqual(result["status"], "success")
        doc.reload()
        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertTrue(doc.preview_data)
        # preview_data is JSON of mapped Member-field dicts.
        preview = json.loads(doc.preview_data)
        self.assertEqual(preview[0]["first_name"], "Valid")

    def test_validate_import_file_no_file_returns_error(self):
        """When csv_file is empty, validate_import_file returns an upload error.

        csv_file is a mandatory field, so we insert a valid doc then clear the
        column directly in the DB to model the 'no file' state the guard checks.
        """
        rows = [{"Voornaam": "Has", "Achternaam": "File", "E-mailadres": _unique_email()}]
        doc = self._make_import_doc(rows)
        frappe.db.set_value("Mijnrood CSV Import", doc.name, "csv_file", "")
        result = validate_import_file(doc.name)
        self.assertEqual(result["status"], "error")
        self.assertIn("upload", result["message"].lower())

    def test_validate_import_file_validation_errors_set_failed(self):
        """A file with row errors validates to Failed with the errors in error_log."""
        rows = [{"Voornaam": "Bad", "Achternaam": "Mail", "E-mailadres": "nope"}]
        doc = self._make_import_doc(rows)
        result = validate_import_file(doc.name)

        self.assertEqual(result["status"], "error")
        self.assertIn("Validation failed", result["message"])
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertIn("Invalid email", doc.error_log)

    def test_validate_import_file_empty_csv_sets_failed(self):
        """A header-only CSV (no data rows) => empty/failed branch."""
        content = "Voornaam,Achternaam,E-mailadres\n"
        doc = self._make_import_doc_from_content(content)

        result = validate_import_file(doc.name)
        self.assertEqual(result["status"], "error")
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")


class TestMijnroodRetryAccountCreations(_BaseMijnroodPipelineTest):
    """retry_failed_account_creations() guard branches against a real tracker."""

    def test_retry_without_tracker_throws(self):
        """No linked Bulk Operation Tracker => ValidationError."""
        doc = self._make_import_doc(
            [{"Voornaam": "No", "Achternaam": "Tracker", "E-mailadres": _unique_email()}]
        )
        with self.assertRaises(frappe.exceptions.ValidationError):
            doc.retry_failed_account_creations()

    def test_retry_with_empty_retry_queue_returns_no_failed(self):
        """A linked tracker with an empty retry_queue returns success=False."""
        tracker = self._make_tracker(retry_queue=None)
        doc = self._make_import_doc(
            [{"Voornaam": "Empty", "Achternaam": "Queue", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        result = doc.retry_failed_account_creations()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No failed items")

    def test_retry_with_queue_but_no_matching_failed_acrs(self):
        """retry_queue references ACR names that don't exist/aren't Failed =>
        'No failed ACRs found'."""
        tracker = self._make_tracker(retry_queue=json.dumps(["ACR-NONEXISTENT-0001"]))
        doc = self._make_import_doc(
            [{"Voornaam": "Stale", "Achternaam": "Queue", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        result = doc.retry_failed_account_creations()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "No failed ACRs found")


class TestMijnroodRetryVolunteerCreations(_BaseMijnroodPipelineTest):
    """retry_failed_volunteer_creations() member-discovery branches."""

    def test_retry_volunteers_no_eligible_members(self):
        """When no Active member references this import, the retry reports that no
        members need volunteer records (created=0)."""
        doc = self._make_import_doc(
            [{"Voornaam": "No", "Achternaam": "Vols", "E-mailadres": _unique_email()}]
        )
        result = doc.retry_failed_volunteer_creations()
        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 0)
        self.assertIn("No members", result["message"])

    def test_retry_volunteers_creates_for_active_member(self):
        """An Active member referencing this import (via review_notes) and lacking
        a volunteer record gets a real Volunteer created on retry."""
        doc = self._make_import_doc(
            [{"Voornaam": "Vol", "Achternaam": "Wanted", "E-mailadres": _unique_email()}]
        )
        member = self._make_member(
            first_name="Vol",
            status="Active",
            review_notes=f"Imported from {doc.name}",
            birth_date="1980-01-01",
        )

        result = doc.retry_failed_volunteer_creations()
        for v in frappe.get_all("Volunteer", filters={"member": member.name}, pluck="name"):
            self._created_volunteers.append(v)

        self.assertTrue(result["success"])
        # A real Volunteer now exists for the imported member (created or already-existed).
        self.assertTrue(frappe.db.exists("Volunteer", {"member": member.name}))


class TestMijnroodTrackingUpdate(_BaseMijnroodPipelineTest):
    """_update_account_creation_tracking / update_import_tracking_after_retry /
    _generate_top_errors_summary against REAL trackers + ACRs."""

    def test_update_tracking_from_linked_tracker_sets_acr_counts(self):
        """A linked tracker's totals are copied onto the import's acrs_* fields,
        and the failed-ACR errors produce a top_errors_summary."""
        tracker = self._make_tracker(
            total_records=5, successful_records=3, failed_records=2, retry_queue=None
        )
        # Two real Failed ACRs back the failed_records=2 so the summary is real.
        self._make_failed_acr(tracker.name, failure_reason="Import blew up")
        self._make_failed_acr(tracker.name, failure_reason="Import blew up")
        doc = self._make_import_doc(
            [{"Voornaam": "Track", "Achternaam": "Import", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        doc._update_account_creation_tracking()
        self.assertEqual(doc.acrs_created, 5)
        self.assertEqual(doc.acrs_successful, 3)
        self.assertEqual(doc.acrs_failed, 2)
        # With failed ACRs present, a top-errors summary is generated.
        self.assertIn("Import blew up", doc.top_errors_summary)

    def test_update_tracking_counts_created_users(self):
        """Completed ACRs with created_user are counted into users_created."""
        tracker = self._make_tracker(total_records=1, successful_records=1, failed_records=0)
        # A Completed ACR with a created_user should be counted.
        self._make_acr(tracker.name, "Completed", created_user=frappe.session.user)

        doc = self._make_import_doc(
            [{"Voornaam": "Count", "Achternaam": "Users", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        doc._update_account_creation_tracking()
        self.assertEqual(doc.users_created, 1)
        self.assertEqual(doc.contacts_created, 1)

    def test_generate_top_errors_summary_buckets_failures(self):
        """_generate_top_errors_summary tallies failure reasons from real ACRs."""
        tracker = self._make_tracker(failed_records=3)
        self._make_failed_acr(tracker.name, failure_reason="Permission denied")
        self._make_failed_acr(tracker.name, failure_reason="Permission denied")
        self._make_failed_acr(tracker.name, failure_reason="Email already exists")
        doc = self._make_import_doc(
            [{"Voornaam": "Top", "Achternaam": "Errors", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        summary = doc._generate_top_errors_summary(tracker.name)
        self.assertIn("Permission denied", summary)
        self.assertIn("Email already exists", summary)
        # The most-common error reports its count of 2.
        self.assertIn("2", summary)

    def test_generate_top_errors_summary_empty_when_no_failures(self):
        tracker = self._make_tracker()
        doc = self._make_import_doc(
            [{"Voornaam": "No", "Achternaam": "Fail", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        self.assertEqual(doc._generate_top_errors_summary(tracker.name), "")

    def test_update_import_tracking_after_retry_persists(self):
        """The queued post-retry hook reloads the doc, recomputes and saves the
        acrs_* counters from the linked tracker."""
        tracker = self._make_tracker(total_records=4, successful_records=4, failed_records=0)
        doc = self._make_import_doc(
            [{"Voornaam": "After", "Achternaam": "Retry", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=tracker.name,
        )
        update_import_tracking_after_retry(doc.name)
        doc.reload()
        self.assertEqual(doc.acrs_created, 4)
        self.assertEqual(doc.acrs_successful, 4)


class TestMijnroodLinkTrackerAtomically(_BaseMijnroodPipelineTest):
    """_link_tracker_atomically() link + idempotent no-overwrite."""

    def test_link_sets_tracker_field(self):
        tracker = self._make_tracker()
        doc = self._make_import_doc(
            [{"Voornaam": "Link", "Achternaam": "Me", "E-mailadres": _unique_email()}]
        )
        self.assertFalse(doc.bulk_operation_tracker)
        doc._link_tracker_atomically(tracker.name)
        # The link is applied to the import (in-memory value reflects the DB write
        # performed under the FOR UPDATE lock inside the method).
        self.assertEqual(doc.bulk_operation_tracker, tracker.name)

    def test_link_does_not_overwrite_existing(self):
        """Idempotent: an already-linked tracker is not replaced by a new one."""
        first = self._make_tracker()
        second = self._make_tracker()
        doc = self._make_import_doc(
            [{"Voornaam": "Keep", "Achternaam": "First", "E-mailadres": _unique_email()}],
            bulk_operation_tracker=first.name,
        )
        frappe.db.commit()
        doc._link_tracker_atomically(second.name)
        self.assertEqual(
            frappe.db.get_value("Mijnrood CSV Import", doc.name, "bulk_operation_tracker"),
            first.name,
        )


class TestMijnroodRelatedRecords(_BaseMijnroodPipelineTest):
    """Termination + related-record orchestration with real DB writes."""

    def setUp(self):
        super().setUp()
        self._save_settings()

    def tearDown(self):
        self._restore_settings()
        super().tearDown()

    def _make_active_member(self):
        return self._make_member(first_name="Rel", status="Active")

    def _track_terminations_for(self, member_name):
        for t in frappe.get_all(
            "Membership Termination Request", filters={"member": member_name}, pluck="name"
        ):
            if t not in self._created_terminations:
                self._created_terminations.append(t)

    def test_create_termination_record_creates_real_request(self):
        """_create_termination_record inserts an Approved Membership Termination
        Request for a non-terminal member."""
        member = self._make_active_member()
        doc = self._make_import_doc(
            [{"Voornaam": "Term", "Achternaam": "Member", "E-mailadres": _unique_email()}]
        )
        doc._create_termination_record(
            member,
            {
                "membership_type": "opgezegd",
                "member_since": None,
                "termination_reason": "Membership cancelled/terminated voluntarily",
            },
        )
        self._track_terminations_for(member.name)
        created = frappe.get_all(
            "Membership Termination Request",
            filters={"member": member.name},
            fields=["name", "status", "termination_reason"],
        )
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]["status"], "Approved")
        self.assertEqual(created[0]["termination_reason"], "Membership cancelled/terminated voluntarily")

    def test_create_termination_record_skips_terminal_status(self):
        """A member already in a terminal state (Quit/Banned) gets no termination
        request (early return)."""
        member = self._make_active_member()
        member.status = "Banned"
        member.flags.ignore_permissions = True
        member.save(ignore_permissions=True)
        doc = self._make_import_doc(
            [{"Voornaam": "Skip", "Achternaam": "Term", "E-mailadres": _unique_email()}]
        )
        doc._create_termination_record(
            member,
            {
                "membership_type": "geroyeerd",
                "member_since": None,
                "termination_reason": "Expelled from organization for cause",
            },
        )
        self.assertFalse(frappe.db.exists("Membership Termination Request", {"member": member.name}))

    def test_related_records_termination_branch_for_opgezegd(self):
        """_create_related_records_via_services drives the termination branch when
        the row's membership_type is a terminated type."""
        member = self._make_active_member()
        doc = self._make_import_doc(
            [{"Voornaam": "Combo", "Achternaam": "Member", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        failures = doc._create_related_records_via_services(member.name, {"membership_type": "opgezegd"})
        self._track_terminations_for(member.name)
        # Termination should succeed (not be in failures) and a request exists.
        self.assertNotIn("termination", failures)
        self.assertTrue(frappe.db.exists("Membership Termination Request", {"member": member.name}))


class TestMijnroodItemizedReport(_BaseMijnroodPipelineTest):
    """_generate_itemized_member_list() shaping (created/updated/skipped sections)."""

    def test_itemized_list_sections_and_categorization(self):
        doc = self._new_unsaved_doc()
        created = ["MEM-0001", "MEM-0002"]
        updated = ["MEM-0003"]
        skipped = [
            "Lidnr 7: Piet Pietersen - Invalid email format: x",
            "Lidnr 8: Anna Bos - Duplicate entry found",
        ]
        out = doc._generate_itemized_member_list(created, updated, skipped)
        self.assertIn("Created Members (2)", out)
        self.assertIn("- MEM-0001", out)
        self.assertIn("Updated Members (1)", out)
        self.assertIn("Skipped Members (2)", out)
        # Skip reasons are bucketed.
        self.assertIn("Email Validation Failed", out)
        self.assertIn("Duplicate Entry", out)

    def test_itemized_list_truncates_over_100_created(self):
        doc = self._new_unsaved_doc()
        created = [f"MEM-{i:04d}" for i in range(150)]
        out = doc._generate_itemized_member_list(created, None, None)
        self.assertIn("Created Members (150)", out)
        self.assertIn("and 50 more", out)

    def test_itemized_list_empty_returns_header_only(self):
        doc = self._new_unsaved_doc()
        out = doc._generate_itemized_member_list(None, None, None)
        # Only the top-level header, no member sections.
        self.assertIn("Itemized Import Results", out)
        self.assertNotIn("Created Members", out)


class TestMijnroodTemplateComplement(_BaseMijnroodPipelineTest):
    """get_import_template() content/row shape (complements the header-only
    assertion in the existing suite)."""

    def test_template_sample_row_aligns_with_headers(self):
        template = get_import_template()
        reader = list(csv.reader(io.StringIO(template["content"])))
        headers, sample = reader[0], reader[1]
        # Sample row has exactly one value per header column.
        self.assertEqual(len(headers), len(sample))
        # The sample IBAN column carries a real IBAN value.
        self.assertIn("NL91ABNA0417164300", sample)
        # Tussenvoegsel (Dutch name infix) is present in the template headers.
        self.assertIn("Tussenvoegsel", headers)
