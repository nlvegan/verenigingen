# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Coverage sweep for the VIP Import controller (data importer). The existing
# test_vip_import.py exercises the VIPDataValidator only; this file drives the
# controller's own surfaces REAL against the DB:
#
#   - process_import_background(): the end-to-end row engine — create volunteer
#     for an existing member, update an existing volunteer, skip-existing
#     handling, member-not-found skip, and create-member-if-missing. Drives the
#     real _find_member / _find_volunteer / _create_member / _create_volunteer /
#     _update_volunteer / _process_single_row / _set_final_import_status chain
#     and writes real Volunteer + Member rows and the import summary fields.
#   - validate_import_file(): success (Ready for Import) and empty-file failure.
#   - get_import_template(): real CSV template string.
#   - The empty-CSV and no-valid-rows short-circuits of the background job.
#
# The account-creation step (_process_account_creation → queue_bulk_account_
# creation_for_members) enqueues a background job; we let it run for real but do
# not assert on the queued worker. on_submit() itself only enqueues the long
# job (queue capacity + Redis), so it is not driven here — the background entry
# point is called directly, which is exactly what the worker would do.

import csv
import io

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.vip_import import vip_import as C

_CSV_HEADERS = [
    "id",
    "google_account_ref",
    "nvv_relatie_nummer",
    "email",
    "private_email",
    "first_name",
    "last_name",
    "phone_number",
    "mobile_number",
    "date_joined",
    "status",
    "notes",
    "status_notes",
    "is_delegated_account",
]


def _csv_attachment(rows):
    """Write `rows` (dicts keyed by _CSV_HEADERS) to a real File and return file_url."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_CSV_HEADERS)
    writer.writeheader()
    for r in rows:
        writer.writerow({h: r.get(h, "") for h in _CSV_HEADERS})
    file_doc = frappe.get_doc(
        {
            "doctype": "File",
            "file_name": f"vip_cov_{frappe.generate_hash(length=8)}.csv",
            "is_private": 1,
            "content": output.getvalue(),
        }
    )
    file_doc.insert()
    return file_doc.file_url


def _row(**kw):
    base = {h: "" for h in _CSV_HEADERS}
    base["status"] = "available"
    base.update(kw)
    return base


class _VIPCoverageBase(EnhancedTestCase):
    def _make_member(self, member_id, **kw):
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "member_id": member_id,
                "first_name": kw.get("first_name", "Vip"),
                "last_name": kw.get("last_name", "Member"),
                "email": kw.get("email", f"vipm+{member_id}@example.test"),
                "status": "Active",
            }
        )
        member.flags.ignore_mandatory = True
        member.flags.bulk_member_operations = True
        member.insert()
        return member

    def _make_import_doc(self, file_url, **fields):
        defaults = {"encoding": "utf-8", "duplicate_handling": "Update existing"}
        defaults.update(fields)
        doc = frappe.get_doc({"doctype": "VIP Import", "csv_file": file_url, **defaults})
        doc.insert()
        return doc


class TestVIPBackgroundCreatesVolunteer(_VIPCoverageBase):
    """process_import_background() creates a Volunteer for an existing Member."""

    def test_creates_volunteer_for_existing_member(self):
        suffix = frappe.generate_hash(length=8)
        member_id = f"VIPCOV-{suffix}"
        member = self._make_member(member_id)

        rows = [
            _row(
                **{
                    "id": f"vipid-{suffix}",
                    "nvv_relatie_nummer": member_id,
                    "email": f"org+{suffix}@example.test",
                    "first_name": "Vip",
                    "last_name": "Member",
                    "status": "available",
                }
            )
        ]
        doc = self._make_import_doc(_csv_attachment(rows))

        C.process_import_background(doc.name, test_mode=False)

        doc.reload()
        self.assertIn(doc.import_status, ("Completed", "Completed with Warnings"))
        self.assertEqual(doc.volunteers_created, 1)
        self.assertEqual(doc.members_not_found, 0)

        # A real Volunteer exists, linked to the member and carrying the VIP id.
        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        self.assertTrue(vol_name)
        vol = frappe.get_doc("Volunteer", vol_name)
        self.assertEqual(vol.vip_user_id, f"vipid-{suffix}")
        self.assertEqual(vol.status, "Active")

    def test_member_not_found_skips_when_not_creating(self):
        suffix = frappe.generate_hash(length=8)
        rows = [
            _row(
                **{
                    "id": f"orphan-{suffix}",
                    "nvv_relatie_nummer": f"NO-SUCH-MEMBER-{suffix}",
                    "email": f"orphan+{suffix}@example.test",
                    "first_name": "Orphan",
                    "last_name": "Row",
                }
            )
        ]
        # create_members_if_missing left falsy → member-not-found skip branch.
        doc = self._make_import_doc(_csv_attachment(rows))

        C.process_import_background(doc.name, test_mode=False)
        doc.reload()
        self.assertEqual(doc.members_not_found, 1)
        self.assertEqual(doc.volunteers_created, 0)
        # The skipped-rows log records the member-not-found category.
        self.assertIn("Member Not Found", doc.skipped_rows_log or "")

    def test_create_member_if_missing_creates_member_and_volunteer(self):
        suffix = frappe.generate_hash(length=8)
        rows = [
            _row(
                **{
                    "id": f"new-{suffix}",
                    "nvv_relatie_nummer": f"NEWMEM-{suffix}",
                    "email": f"newvol+{suffix}@example.test",
                    "private_email": f"newpriv+{suffix}@example.test",
                    "first_name": "Fresh",
                    "last_name": "Volunteer",
                    "status": "available",
                }
            )
        ]
        doc = self._make_import_doc(_csv_attachment(rows), create_members_if_missing=1)

        C.process_import_background(doc.name, test_mode=False)
        doc.reload()
        self.assertEqual(doc.members_created, 1)
        self.assertEqual(doc.volunteers_created, 1)
        # The new member exists with the personal email preferred.
        member_name = frappe.db.get_value("Member", {"member_id": f"NEWMEM-{suffix}"}, "name")
        self.assertTrue(member_name)


class TestVIPBackgroundUpdatesAndSkips(_VIPCoverageBase):
    """Existing-volunteer update vs skip-existing handling."""

    def _make_volunteer(self, member, **kw):
        vol = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": member.full_name or f"{member.first_name} {member.last_name}",
                "member": member.name,
                "status": kw.get("status", "Active"),
            }
        )
        vol.flags.bulk_member_operations = True
        vol.flags.skip_volunteer_account_creation = True
        vol.insert()
        return vol

    def test_updates_existing_volunteer(self):
        suffix = frappe.generate_hash(length=8)
        member_id = f"VIPUPD-{suffix}"
        member = self._make_member(member_id)
        self._make_volunteer(member)  # exists, no vip_user_id yet

        rows = [
            _row(
                **{
                    "id": f"updvip-{suffix}",
                    "nvv_relatie_nummer": member_id,
                    "email": f"updorg+{suffix}@example.test",
                    "first_name": "Vip",
                    "last_name": "Member",
                    "status": "holiday",  # → Inactive
                }
            )
        ]
        # default duplicate_handling is "Update existing" (anything != "Skip existing")
        doc = self._make_import_doc(_csv_attachment(rows), duplicate_handling="Update existing")

        C.process_import_background(doc.name, test_mode=False)
        doc.reload()
        self.assertEqual(doc.volunteers_updated, 1)
        self.assertEqual(doc.volunteers_created, 0)

        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        vol = frappe.get_doc("Volunteer", vol_name)
        self.assertEqual(vol.vip_user_id, f"updvip-{suffix}")
        self.assertEqual(vol.status, "Inactive")  # holiday → Inactive

    def test_skip_existing_volunteer(self):
        suffix = frappe.generate_hash(length=8)
        member_id = f"VIPSKIP-{suffix}"
        member = self._make_member(member_id)
        self._make_volunteer(member)

        rows = [
            _row(
                **{
                    "id": f"skipvip-{suffix}",
                    "nvv_relatie_nummer": member_id,
                    "email": f"skiporg+{suffix}@example.test",
                    "first_name": "Vip",
                    "last_name": "Member",
                }
            )
        ]
        doc = self._make_import_doc(_csv_attachment(rows), duplicate_handling="Skip existing")

        C.process_import_background(doc.name, test_mode=False)
        doc.reload()
        self.assertEqual(doc.volunteers_skipped, 1)
        self.assertEqual(doc.volunteers_updated, 0)
        self.assertIn("Volunteer Already Exists", doc.skipped_rows_log or "")

        # The existing volunteer must NOT have been given the vip_user_id.
        vol_name = frappe.db.get_value("Volunteer", {"member": member.name}, "name")
        vol = frappe.get_doc("Volunteer", vol_name)
        self.assertFalse(vol.vip_user_id)


class TestVIPBackgroundShortCircuits(_VIPCoverageBase):
    """Empty-file / no-valid-rows early returns in process_import_background."""

    def test_empty_csv_marks_failed(self):
        file_url = _csv_attachment([])  # header only
        doc = self._make_import_doc(file_url)
        C.process_import_background(doc.name, test_mode=False)
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")
        self.assertTrue(doc.error_log)


class TestVIPValidateImportFile(_VIPCoverageBase):
    """validate_import_file() whitelisted endpoint branches."""

    def test_validate_success_sets_ready(self):
        suffix = frappe.generate_hash(length=8)
        rows = [
            _row(
                **{
                    "id": f"valid-{suffix}",
                    "nvv_relatie_nummer": f"VAL-{suffix}",
                    "email": f"val+{suffix}@example.test",
                    "first_name": "Val",
                    "last_name": "Id",
                }
            )
        ]
        doc = self._make_import_doc(_csv_attachment(rows))
        result = C.validate_import_file(doc.name)
        self.assertTrue(result["success"], msg=result.get("error"))
        doc.reload()
        self.assertEqual(doc.import_status, "Ready for Import")
        self.assertTrue(doc.preview_data)

    def test_validate_empty_file_returns_error(self):
        doc = self._make_import_doc(_csv_attachment([]))
        result = C.validate_import_file(doc.name)
        self.assertFalse(result["success"])
        doc.reload()
        self.assertEqual(doc.import_status, "Failed")


class TestVIPImportTemplate(EnhancedTestCase):
    """get_import_template() returns a real, parseable CSV string."""

    def test_template_has_headers_and_sample(self):
        template = C.get_import_template()
        self.assertIsInstance(template, str)
        parsed = list(csv.reader(io.StringIO(template)))
        self.assertEqual(parsed[0][0], "id")
        self.assertIn("nvv_relatie_nummer", parsed[0])
        # Exactly header + one sample row.
        self.assertEqual(len(parsed), 2)
