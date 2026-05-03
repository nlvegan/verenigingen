"""Tests for Organization Document applies_on / precision normalization."""

from datetime import date

import frappe

from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory
from verenigingen.tests.utils.base import VereningingenTestCase


class TestOrganizationDocumentAppliesOn(VereningingenTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(cleanup_on_exit=False)
        cls.chapter = cls.factory.create_test_chapter()

    @classmethod
    def tearDownClass(cls):
        cls.factory.cleanup()
        super().tearDownClass()

    def _make_doc(self, **overrides):
        """Create a minimal Organization Document for a Chapter as Administrator."""
        defaults = dict(
            doctype="Organization Document",
            organization_type="Chapter",
            chapter=self.chapter.name,
            document_name="Test doc",
            document_type="Other",
            document_file="/private/files/dummy.pdf",
        )
        defaults.update(overrides)
        doc = frappe.get_doc(defaults)
        doc.flags.ignore_permissions = True  # System Manager equivalent for setup
        doc.insert()
        self.addCleanup(lambda: frappe.delete_doc(
            "Organization Document", doc.name, ignore_permissions=True, force=True))
        return doc

    def test_precision_month_snaps_day_to_one(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Month")
        self.assertEqual(doc.applies_on, date(2024, 5, 1))
        self.assertEqual(doc.applies_on_precision, "Month")

    def test_precision_year_snaps_month_and_day_to_one(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Year")
        self.assertEqual(doc.applies_on, date(2024, 1, 1))
        self.assertEqual(doc.applies_on_precision, "Year")

    def test_precision_day_leaves_date_alone(self):
        doc = self._make_doc(applies_on=date(2024, 5, 17), applies_on_precision="Day")
        self.assertEqual(doc.applies_on, date(2024, 5, 17))
        self.assertEqual(doc.applies_on_precision, "Day")

    def test_no_applies_on_no_op(self):
        doc = self._make_doc(applies_on=None, applies_on_precision="Month")
        self.assertIsNone(doc.applies_on)

    def test_default_precision_is_day(self):
        doc = self._make_doc()
        self.assertEqual(doc.applies_on_precision, "Day")
