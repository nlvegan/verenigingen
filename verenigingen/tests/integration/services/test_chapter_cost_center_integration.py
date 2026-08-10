# Copyright (c) 2025, Verenigingen and contributors
# For license information, please see license.txt

"""
Integration tests for chapter cost center resolution in invoice generation.

Tests real database operations with EnhancedTestCase — no mocks.
Covers:
- InvoiceGenerator: chapter cost center flows through to invoice line items
- InvoiceGenerator: fallback to company default when no chapter cost center
- DuesPaymentProcessor._resolve_chapter_cost_center: chapter + company fallback
- DuesPaymentProcessor._create_simple_invoice: is_membership_invoice, member, cost_center
"""

from datetime import date

import frappe
from frappe.utils import today

from verenigingen.services.billing.invoice_generator import InvoiceGenerator
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.chapter_utils import get_member_primary_chapter


def _get_root_cost_center(company, company_abbr):
    """Find the root group cost center for a company (required as parent for new CCs)."""
    root = frappe.get_all(
        "Cost Center",
        filters={"company": company, "is_group": 1, "parent_cost_center": ["in", ["", None]]},
        fields=["name"],
        limit=1,
    )
    if root:
        return root[0].name
    # Fallback: company-named root
    return f"{company} - {company_abbr}"


class TestChapterCostCenterInvoiceGenerator(EnhancedTestCase):
    """Integration tests: chapter cost center resolution in canonical InvoiceGenerator."""

    def setUp(self):
        super().setUp()

        # Own the membership type instead of borrowing whichever one the database
        # happens to surface. The previous helper did
        # `frappe.get_all("Membership Type", limit=1)` with no order_by, so Frappe
        # falls back to the doctype's own sort — Membership Type declares
        # `sort_field: modified, sort_order: DESC` — and it returned whichever type
        # the PREVIOUS test in the process last touched, out of 289 on a warm site.
        # When that borrowed type produced no Active dues schedule, setUp raised
        # "No schedule was created with membership" and errored all five tests:
        # green in isolation, red only in the shard that ran the wrong neighbour
        # first (CI run 31333421464, shard 3/12). The factory creates a
        # uniquely-named type and aligns its auto-created template's rate, so the
        # membership below always yields a schedule.
        # See #248 (shard re-partition exposes latent contamination) and #263/#264
        # (shared membership-type fixtures).
        self.membership_type_name = self.create_test_membership_type(
            membership_type_name="CostCenterType", amount=25.0
        ).name

        # Create test member with customer (uid ensures uniqueness across runs)
        self.member = self.create_test_member(
            first_name="CostCenter", last_name=f"Test{self.uid}", birth_date="1985-05-15"
        )
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"CC Test Customer {self.uid}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        self.member.customer = self.customer_doc.name
        self.member.save()
        self.member.reload()

        # Create membership (auto-creates dues schedule)
        self.membership = self.create_test_membership(
            member_name=self.member.name, membership_type_name=self.membership_type_name
        )

        # Get the auto-created schedule
        schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "status": "Active"},
            limit=1,
        )
        if schedules:
            self.schedule = frappe.get_doc("Membership Dues Schedule", schedules[0].name)
        else:
            frappe.throw("No schedule was created with membership")

        self.member.reload()

        # Get company for cost center operations
        settings = frappe.get_single("Verenigingen Settings")
        self.company = settings.company
        self.company_abbr = frappe.db.get_value("Company", self.company, "abbr")

    def _create_chapter_with_cost_center(self):
        """Helper: create a chapter and a cost center, link them, add member."""
        chapter = self.create_chapter()
        chapter.reload()

        # Create a dedicated cost center for this chapter under the root group CC
        cc_name = f"{chapter.name} - {self.company_abbr}"
        if not frappe.db.exists("Cost Center", cc_name):
            parent_cc = _get_root_cost_center(self.company, self.company_abbr)

            cc = frappe.new_doc("Cost Center")
            cc.cost_center_name = chapter.name
            cc.company = self.company
            cc.parent_cost_center = parent_cc
            cc.insert(ignore_permissions=True)

        # Link cost center to chapter
        chapter.cost_center = cc_name
        chapter.save(ignore_permissions=True)

        # Add member to chapter via child table insert
        frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": self.member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            }
        ).insert(ignore_permissions=True)

        return chapter, cc_name

    def test_invoice_item_gets_chapter_cost_center(self):
        """Invoice line item should use chapter cost center when member has an active chapter."""
        chapter, cc_name = self._create_chapter_with_cost_center()

        # Verify the utility function sees the chapter
        primary_chapter = get_member_primary_chapter(self.member.name)
        self.assertEqual(primary_chapter, chapter.name)

        # Generate invoice
        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")
        self.assertIsNotNone(result.data)

        # Verify the item's cost center matches the chapter's cost center
        self.assertEqual(len(result.data.items), 1)
        self.assertEqual(result.data.items[0].cost_center, cc_name)

    def test_invoice_item_falls_back_to_company_default(self):
        """When member has no chapter, invoice should use company default cost center."""
        # No chapter created — member has no chapter membership
        primary_chapter = get_member_primary_chapter(self.member.name)
        self.assertIsNone(primary_chapter)

        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")

        # Should have a cost center (company default or Main), but NOT None
        item_cc = result.data.items[0].cost_center
        self.assertIsNotNone(item_cc, "Cost center should fall back to company default")

    def test_invoice_falls_back_when_chapter_has_no_cost_center(self):
        """Chapter without a cost center should fall back to company default."""
        chapter = self.create_chapter()
        chapter.reload()

        # Explicitly clear cost center (factory may have set one via after_insert hook)
        chapter.cost_center = None
        chapter.save()

        # Add member to chapter
        frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": self.member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            }
        ).insert()

        # Verify member IS in the chapter
        primary_chapter = get_member_primary_chapter(self.member.name)
        self.assertEqual(primary_chapter, chapter.name)

        # Generate invoice
        generator = InvoiceGenerator(self.schedule)
        result = generator.generate_invoice(
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 12, 31),
            member_doc=self.member,
        )

        self.assertTrue(result.success, f"Invoice generation failed: {result.error_message}")

        # Should still have a cost center (company fallback), not the chapter's (which is None)
        item_cc = result.data.items[0].cost_center
        self.assertIsNotNone(item_cc, "Should fall back to company default cost center")
        # Verify it's NOT the chapter's (which we cleared)
        chapter.reload()
        self.assertNotEqual(item_cc, chapter.cost_center)

    def test_get_chapter_cost_center_private_method(self):
        """Directly test _get_chapter_cost_center with real data."""
        chapter, cc_name = self._create_chapter_with_cost_center()

        generator = InvoiceGenerator(self.schedule)
        result = generator._get_chapter_cost_center(self.member.name)

        self.assertEqual(result, cc_name)

    def test_get_chapter_cost_center_returns_none_for_no_chapter(self):
        """_get_chapter_cost_center returns None when member has no chapter."""
        generator = InvoiceGenerator(self.schedule)
        result = generator._get_chapter_cost_center(self.member.name)

        self.assertIsNone(result)


class TestChapterCostCenterMolliePath(EnhancedTestCase):
    """Integration tests: cost center resolution in DuesPaymentProcessor (Mollie path)."""

    def setUp(self):
        super().setUp()

        # Create test member with customer (uid ensures uniqueness across runs)
        self.member = self.create_test_member(
            first_name="MolliCC", last_name=f"Test{self.uid}", birth_date="1985-05-15"
        )
        self.customer_doc = frappe.new_doc("Customer")
        self.customer_doc.customer_name = f"Mollie CC Customer {self.uid}"
        self.customer_doc.customer_type = "Individual"
        self.customer_doc.insert()

        self.member.customer = self.customer_doc.name
        self.member.save()
        self.member.reload()

        settings = frappe.get_single("Verenigingen Settings")
        self.company = settings.company
        self.company_abbr = frappe.db.get_value("Company", self.company, "abbr")

    def _create_chapter_with_cost_center(self):
        """Helper: create chapter with cost center, add member."""
        chapter = self.create_chapter()
        chapter.reload()

        cc_name = f"{chapter.name} - {self.company_abbr}"
        if not frappe.db.exists("Cost Center", cc_name):
            parent_cc = _get_root_cost_center(self.company, self.company_abbr)

            cc = frappe.new_doc("Cost Center")
            cc.cost_center_name = chapter.name
            cc.company = self.company
            cc.parent_cost_center = parent_cc
            cc.insert(ignore_permissions=True)

        chapter.cost_center = cc_name
        chapter.save(ignore_permissions=True)

        frappe.get_doc(
            {
                "doctype": "Chapter Member",
                "parent": chapter.name,
                "parenttype": "Chapter",
                "parentfield": "members",
                "member": self.member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            }
        ).insert(ignore_permissions=True)

        return chapter, cc_name

    def test_resolve_chapter_cost_center_returns_chapter_cc(self):
        """_resolve_chapter_cost_center returns chapter cost center when available."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        chapter, cc_name = self._create_chapter_with_cost_center()

        # Use __new__ to avoid __init__ side effects (MollieClient instantiation)
        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)
        result = processor._resolve_chapter_cost_center(self.member, self.company)

        self.assertEqual(result, cc_name)

    def test_resolve_chapter_cost_center_falls_back_to_company(self):
        """_resolve_chapter_cost_center returns company default when no chapter CC."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        # No chapter — member has no chapter membership
        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)
        result = processor._resolve_chapter_cost_center(self.member, self.company)

        # Should return company default cost center (not None, assuming company has one)
        company_cc = frappe.db.get_value("Company", self.company, "cost_center")
        if company_cc:
            self.assertEqual(result, company_cc)
        else:
            # Company has no default CC — None is acceptable
            self.assertIsNone(result)

    def test_resolve_chapter_cost_center_returns_none_when_nothing_configured(self):
        """Returns None when neither chapter nor company has cost center."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)

        # Use a fake company that has no cost center
        result = processor._resolve_chapter_cost_center(self.member, "NONEXISTENT-COMPANY")

        self.assertIsNone(result)

    def test_create_simple_invoice_sets_membership_fields(self):
        """_create_simple_invoice should set is_membership_invoice and member."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        settings = frappe.get_single("Verenigingen Settings")
        membership_type = settings.default_membership_type
        if not membership_type:
            self.skipTest("No default_membership_type configured in Verenigingen Settings")

        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)

        invoice_name = processor._create_simple_invoice(
            member_doc=self.member,
            membership_type=membership_type,
            coverage_start=date(2025, 1, 1),
            coverage_end=date(2025, 3, 31),
            amount=25.0,
            payment_date=date(2025, 1, 15),
        )

        self.assertIsNotNone(invoice_name, "Invoice creation should succeed")

        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.is_membership_invoice, 1)
        self.assertEqual(invoice.member, self.member.name)

    def test_create_simple_invoice_has_chapter_cost_center_on_item(self):
        """_create_simple_invoice should set chapter cost center on line items."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        chapter, cc_name = self._create_chapter_with_cost_center()

        settings = frappe.get_single("Verenigingen Settings")
        membership_type = settings.default_membership_type
        if not membership_type:
            self.skipTest("No default_membership_type configured in Verenigingen Settings")

        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)

        invoice_name = processor._create_simple_invoice(
            member_doc=self.member,
            membership_type=membership_type,
            coverage_start=date(2025, 4, 1),
            coverage_end=date(2025, 6, 30),
            amount=25.0,
            payment_date=date(2025, 4, 15),
        )

        self.assertIsNotNone(invoice_name, "Invoice creation should succeed")

        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(len(invoice.items), 1)
        self.assertEqual(invoice.items[0].cost_center, cc_name)

    def test_create_simple_invoice_succeeds_without_any_cost_center(self):
        """_create_simple_invoice should succeed even when no cost center is configured."""
        from verenigingen.verenigingen_payments.mollie.services.dues_payment_processor import (
            DuesPaymentProcessor,
        )

        # Member has no chapter → no chapter CC.  Company may or may not have a default.
        settings = frappe.get_single("Verenigingen Settings")
        membership_type = settings.default_membership_type
        if not membership_type:
            self.skipTest("No default_membership_type configured in Verenigingen Settings")

        processor = DuesPaymentProcessor.__new__(DuesPaymentProcessor)

        invoice_name = processor._create_simple_invoice(
            member_doc=self.member,
            membership_type=membership_type,
            coverage_start=date(2025, 7, 1),
            coverage_end=date(2025, 9, 30),
            amount=25.0,
            payment_date=date(2025, 7, 15),
        )

        self.assertIsNotNone(invoice_name, "Invoice creation should succeed without a cost center")
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        self.assertEqual(invoice.is_membership_invoice, 1)
        self.assertEqual(invoice.member, self.member.name)
