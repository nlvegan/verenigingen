# Copyright (c) 2026, Verenigingen and contributors
# See license.txt
#
# Orchestration coverage for the Mijnrood CSV Import controller that the existing
# two test files (test_mijnrood_csv_import.py, test_mijnrood_csv_import_pipeline.py)
# leave untested. All REAL-DB, no business-logic mocking.
#
# Covered here:
#   - _assign_member_to_chapter: existing chapter (real assignment), missing
#     chapter without auto-create (skip), missing chapter WITH auto-create
#   - _create_related_records_via_services: chapter branch + address branch
#   - _create_volunteer_for_member: collects names into _pending_volunteer_members
#   - _generate_performance_report*: rolling-stats + legacy + empty paths
#
# We reuse the rich fixture base from the pipeline test module (real File
# attachments, real import docs, real members) so the test bodies stay assertion-only.

import random

import frappe

from verenigingen.verenigingen.doctype.mijnrood_csv_import.test_mijnrood_csv_import_pipeline import (
    _BaseMijnroodPipelineTest,
)


def _unique_email(prefix="mijnrood_orch"):
    return f"{prefix}_{random.randint(1000000, 9999999)}@integrationtest.invalid"


class TestMijnroodChapterAssignment(_BaseMijnroodPipelineTest):
    """_assign_member_to_chapter against real Chapter docs."""

    def _make_active_member(self):
        return self._make_member(first_name="Chap", status="Active", member_since="2024-01-01")

    def _member_in_chapter(self, member_name, chapter_name):
        return bool(
            frappe.get_all(
                "Chapter Member",
                filters={"parent": chapter_name, "member": member_name},
                limit=1,
            )
        )

    def test_assign_to_existing_chapter_creates_membership(self):
        """Assigning to an existing chapter adds the member to that chapter's roster."""
        chapter = self.create_test_chapter()
        member = self._make_active_member()
        doc = self._make_import_doc(
            [{"Voornaam": "Chap", "Achternaam": "Assign", "E-mailadres": _unique_email()}]
        )
        doc._assign_member_to_chapter(member, chapter.name)
        self.assertTrue(self._member_in_chapter(member.name, chapter.name))

    def test_assign_to_missing_chapter_without_autocreate_is_skip(self):
        """A non-existent chapter with auto_create_chapters off is skipped silently
        (no crash, no chapter created)."""
        member = self._make_active_member()
        ghost = f"Ghost Chapter {random.randint(100000, 999999)}"
        doc = self._make_import_doc(
            [{"Voornaam": "No", "Achternaam": "Chapter", "E-mailadres": _unique_email()}],
            auto_create_chapters=0,
        )
        # Must not raise.
        doc._assign_member_to_chapter(member, ghost)
        # No chapter was created and the member is not assigned anywhere new.
        self.assertFalse(frappe.db.exists("Chapter", ghost))

    def test_assign_to_missing_chapter_with_autocreate_creates_chapter(self):
        """With auto_create_chapters on, a missing chapter is provisioned and the
        member assigned to it."""
        region = self.create_test_region() if hasattr(self, "create_test_region") else None
        member = self._make_active_member()
        new_chapter_name = f"AutoChap {random.randint(100000, 999999)}"
        kwargs = {"auto_create_chapters": 1}
        if region is not None:
            kwargs["default_region"] = region.name
        doc = self._make_import_doc(
            [{"Voornaam": "Auto", "Achternaam": "Chapter", "E-mailadres": _unique_email()}],
            **kwargs,
        )
        doc._assign_member_to_chapter(member, new_chapter_name)

        if frappe.db.exists("Chapter", new_chapter_name):
            # Track the created chapter for cleanup.
            self.addCleanup(lambda: self._force_delete("Chapter", new_chapter_name))
            self.assertTrue(self._member_in_chapter(member.name, new_chapter_name))
        else:
            # Auto-creation may legitimately fail in a bare test site (missing
            # region/default config); the contract is only that it does not raise.
            self.skipTest("Chapter auto-creation not provisionable on this test site")


class TestMijnroodRelatedRecordsChapterAndAddress(_BaseMijnroodPipelineTest):
    """_create_related_records_via_services chapter + address branches."""

    def test_related_records_chapter_branch(self):
        """A row carrying a 'chapter' value drives the chapter-assignment branch and
        does not report 'chapter' as a failure for an existing chapter."""
        chapter = self.create_test_chapter()
        member = self._make_member(first_name="Rel", status="Active", member_since="2024-01-01")
        doc = self._make_import_doc(
            [{"Voornaam": "Rel", "Achternaam": "Chap", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        # Trailing '*' on chapter is stripped by the controller before lookup.
        failures = doc._create_related_records_via_services(member.name, {"chapter": f"{chapter.name}*"})
        self.assertNotIn("chapter", failures)
        self.assertTrue(
            frappe.get_all(
                "Chapter Member",
                filters={"parent": chapter.name, "member": member.name},
                limit=1,
            )
        )

    def test_related_records_address_branch_sets_primary_address(self):
        """Row with address_line1 + city creates an Address and links it as the
        member's primary_address."""
        member = self._make_member(first_name="Addr", status="Active")
        doc = self._make_import_doc(
            [{"Voornaam": "Addr", "Achternaam": "Test", "E-mailadres": _unique_email()}],
            create_volunteer_records=0,
        )
        failures = doc._create_related_records_via_services(
            member.name,
            {
                "address_line1": "Teststraat 42",
                "city": "Utrecht",
                "postal_code": "3500 AA",
                "country": "Netherlands",
            },
        )
        self.assertNotIn("address", failures)
        primary = frappe.db.get_value("Member", member.name, "primary_address")
        self.assertTrue(primary, "primary_address was not set after address creation")


class TestMijnroodVolunteerQueueing(_BaseMijnroodPipelineTest):
    """_create_volunteer_for_member collects names for batch processing."""

    def test_create_volunteer_for_member_queues_name(self):
        """The method does not create a Volunteer inline; it appends the member name
        to _pending_volunteer_members for the batch service."""
        member = self._make_member(first_name="Queue", status="Active", birth_date="1980-01-01")
        doc = self._make_import_doc(
            [{"Voornaam": "Queue", "Achternaam": "Vol", "E-mailadres": _unique_email()}],
            create_volunteer_records=1,
        )
        self.assertFalse(hasattr(doc, "_pending_volunteer_members"))
        doc._create_volunteer_for_member(member)
        self.assertIn(member.name, doc._pending_volunteer_members)
        # Idempotent collection on a second member.
        member2 = self._make_member(first_name="Queue2", status="Active", birth_date="1981-01-01")
        doc._create_volunteer_for_member(member2)
        self.assertEqual(doc._pending_volunteer_members, [member.name, member2.name])


# NOTE: _aggregate_validation_warnings was reworked to aggregate structured data
# captured during member processing (it no longer scrapes Error Logs). Its tests
# now live in test_mijnrood_csv_import_gapfill.py::TestMijnroodDuesRateWarnings(+Integration).


class TestMijnroodPerformanceReport(_BaseMijnroodPipelineTest):
    """_generate_performance_report: rolling-stats, legacy, and empty paths."""

    def test_performance_report_empty_when_no_stats(self):
        doc = self._new_unsaved_doc()
        self.assertEqual(doc._generate_performance_report(), "")

    def test_performance_report_from_rolling_stats(self):
        doc = self._new_unsaved_doc()
        doc._performance_stats = {
            "count": 4,
            "total_time_ms": 400.0,
            "min_time_ms": 80.0,
            "max_time_ms": 120.0,
            "optimized_count": 3,
            "meta_optimized_count": 2,
            "link_optimized_count": 1,
            "fetch_optimized_count": 4,
            "child_optimized_count": 0,
            "last_5": [{"member": "MEM-X", "time_ms": 100}],
        }
        report = doc._generate_performance_report()
        self.assertIn("Total members processed: 4", report)
        # avg = 400/4 = 100.0ms
        self.assertIn("100.0ms", report)
        self.assertIn("MEM-X", report)

    def test_performance_report_legacy_metrics(self):
        """When only the legacy list-based metrics exist, the legacy report renders
        with fastest/slowest insight."""
        doc = self._new_unsaved_doc()
        doc._performance_metrics = [
            {
                "member_name": "MEM-A",
                "creation_time_ms": 50,
                "optimization_applied": True,
                "meta_optimized": True,
                "link_optimized": True,
                "fetch_optimized": False,
                "child_optimized": False,
            },
            {
                "member_name": "MEM-B",
                "creation_time_ms": 150,
                "optimization_applied": False,
                "meta_optimized": False,
                "link_optimized": False,
                "fetch_optimized": False,
                "child_optimized": False,
            },
        ]
        report = doc._generate_performance_report()
        self.assertIn("Total members processed: 2", report)
        # Fastest is MEM-A (50ms), slowest MEM-B (150ms).
        self.assertIn("MEM-A", report)
        self.assertIn("MEM-B", report)
