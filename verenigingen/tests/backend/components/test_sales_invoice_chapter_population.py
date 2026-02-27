"""
Test Sales Invoice Chapter Population

Tests the automatic population of the custom_member_chapter field on Sales Invoices
via the populate_member_chapter hook and get_member_primary_chapter function.

Key scenarios:
- Invoice creation with member who has active chapter
- Invoice creation with member who has no chapter
- Invoice creation with member who has multiple chapters
- Invoice creation without member (non-member invoice)
- Hook execution on before_validate event
"""

import frappe
from frappe.utils import today, nowdate
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.chapter_utils import get_member_primary_chapter
from verenigingen.services.billing.sales_invoice_hooks import populate_member_chapter


class TestSalesInvoiceChapterPopulation(EnhancedTestCase):
    """Test automatic chapter population on Sales Invoices"""

    @classmethod
    def setUpClass(cls):
        """Set up test data once for all tests"""
        super().setUpClass()
        cls.test_counter = 0

    def setUp(self):
        """Set up for each test"""
        super().setUp()
        TestSalesInvoiceChapterPopulation.test_counter += 1
        self.test_id = f"SINV{TestSalesInvoiceChapterPopulation.test_counter:03d}"

    def test_get_member_primary_chapter_with_active_chapter(self):
        """Test get_member_primary_chapter returns active chapter"""
        print("\n🧪 Testing get_member_primary_chapter with active chapter...")

        # Create member and chapter
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Member {self.test_id}",
            email=f"member{self.test_id.lower()}@example.com",
        )

        chapter = self.create_chapter()

        # Reload chapter to get child tables
        chapter.reload()

        # Add member to chapter
        chapter.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Test function
        result = get_member_primary_chapter(member.name)

        self.assertEqual(result, chapter.name, "Should return active chapter name")
        print(f"✅ get_member_primary_chapter correctly returned: {result}")

    def test_get_member_primary_chapter_with_no_chapter(self):
        """Test get_member_primary_chapter returns None when no chapter"""
        print("\n🧪 Testing get_member_primary_chapter with no chapter...")

        # Create member without chapter
        member = self.create_test_member(
            first_name="Test",
            last_name=f"NoChapter {self.test_id}",
            email=f"nochapter{self.test_id.lower()}@example.com",
        )

        # Test function
        result = get_member_primary_chapter(member.name)

        self.assertIsNone(result, "Should return None when member has no chapter")
        print("✅ get_member_primary_chapter correctly returned None")

    def test_get_member_primary_chapter_with_inactive_chapter(self):
        """Test get_member_primary_chapter ignores inactive chapter memberships"""
        print("\n🧪 Testing get_member_primary_chapter with inactive chapter...")

        # Create member and chapter
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Inactive {self.test_id}",
            email=f"inactive{self.test_id.lower()}@example.com",
        )

        chapter = self.create_chapter()

        # Add member to chapter with inactive status
        chapter.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 0,  # Disabled
                "status": "Inactive",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Test function
        result = get_member_primary_chapter(member.name)

        self.assertIsNone(result, "Should return None when chapter membership is inactive")
        print("✅ get_member_primary_chapter correctly ignored inactive membership")

    def test_get_member_primary_chapter_with_multiple_chapters(self):
        """Test get_member_primary_chapter returns most recent chapter"""
        print("\n🧪 Testing get_member_primary_chapter with multiple chapters...")

        # Create member
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Multi {self.test_id}",
            email=f"multi{self.test_id.lower()}@example.com",
        )

        # Create two chapters
        chapter1 = self.create_chapter()
        chapter2 = self.create_chapter()

        # Reload chapters to get child tables
        chapter1.reload()
        chapter2.reload()

        # Add member to first chapter (older)
        chapter1.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": "2020-01-01",
            },
        )
        chapter1.save()

        # Add member to second chapter (newer)
        chapter2.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": "2024-01-01",
            },
        )
        chapter2.save()

        # Test function - should return most recent chapter
        result = get_member_primary_chapter(member.name)

        self.assertEqual(result, chapter2.name, "Should return most recent chapter")
        print(f"✅ get_member_primary_chapter correctly returned most recent: {result}")

    def test_sales_invoice_chapter_population_via_hook(self):
        """Test Sales Invoice chapter auto-populated via hook"""
        print("\n🧪 Testing Sales Invoice chapter population via hook...")

        # Create member and chapter
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Invoice {self.test_id}",
            email=f"invoice{self.test_id.lower()}@example.com",
        )

        chapter = self.create_chapter()

        # Reload chapter to get child tables
        chapter.reload()

        # Add member to chapter
        chapter.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Create customer for member
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Test Customer {self.test_id}",
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
                "member": member.name,
            }
        )
        customer.insert()

        # Create Sales Invoice
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer.name,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "items": [
                    {
                        "item_code": "_Test Item",
                        "qty": 1,
                        "rate": 100,
                    }
                ],
            }
        )
        invoice.insert()

        # Verify chapter was populated
        self.assertEqual(
            invoice.custom_member_chapter,
            chapter.name,
            "Sales Invoice should have chapter auto-populated",
        )
        print(f"✅ Sales Invoice chapter auto-populated: {invoice.custom_member_chapter}")

    def test_sales_invoice_chapter_not_overwritten_if_set(self):
        """Test Sales Invoice chapter not overwritten if already set"""
        print("\n🧪 Testing Sales Invoice chapter not overwritten...")

        # Create member and two chapters
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Override {self.test_id}",
            email=f"override{self.test_id.lower()}@example.com",
        )

        chapter1 = self.create_chapter()
        chapter2 = self.create_chapter()

        # Add member to chapter1
        chapter1.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter1.save()

        # Create customer
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Test Customer Override {self.test_id}",
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
                "member": member.name,
            }
        )
        customer.insert()

        # Create Sales Invoice with manually set chapter
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer.name,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "custom_member_chapter": chapter2.name,  # Manually set to different chapter
                "items": [
                    {
                        "item_code": "_Test Item",
                        "qty": 1,
                        "rate": 100,
                    }
                ],
            }
        )
        invoice.insert()

        # Verify chapter was NOT overwritten
        self.assertEqual(
            invoice.custom_member_chapter,
            chapter2.name,
            "Sales Invoice should keep manually set chapter",
        )
        print(f"✅ Sales Invoice chapter not overwritten: {invoice.custom_member_chapter}")

    def test_sales_invoice_no_chapter_for_non_member(self):
        """Test Sales Invoice without member has no chapter"""
        print("\n🧪 Testing Sales Invoice for non-member has no chapter...")

        # Create customer without member
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Non-Member Customer {self.test_id}",
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
            }
        )
        customer.insert()

        # Create Sales Invoice
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer.name,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "items": [
                    {
                        "item_code": "_Test Item",
                        "qty": 1,
                        "rate": 100,
                    }
                ],
            }
        )
        invoice.insert()

        # Verify chapter is empty
        self.assertIsNone(
            invoice.custom_member_chapter,
            "Sales Invoice for non-member should have no chapter",
        )
        print("✅ Sales Invoice for non-member correctly has no chapter")

    def test_populate_member_chapter_function_directly(self):
        """Test populate_member_chapter function directly"""
        print("\n🧪 Testing populate_member_chapter function directly...")

        # Create member and chapter
        member = self.create_test_member(
            first_name="Test",
            last_name=f"Direct {self.test_id}",
            email=f"direct{self.test_id.lower()}@example.com",
        )

        chapter = self.create_chapter()

        # Reload chapter to get child tables
        chapter.reload()

        # Add member to chapter
        chapter.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Create customer
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": f"Test Customer Direct {self.test_id}",
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
                "member": member.name,
            }
        )
        customer.insert()

        # Create Sales Invoice without triggering hooks
        invoice = frappe.get_doc(
            {
                "doctype": "Sales Invoice",
                "customer": customer.name,
                "posting_date": nowdate(),
                "due_date": nowdate(),
                "items": [
                    {
                        "item_code": "_Test Item",
                        "qty": 1,
                        "rate": 100,
                    }
                ],
            }
        )

        # Call function directly
        populate_member_chapter(invoice)

        # Verify chapter was populated
        self.assertEqual(
            invoice.custom_member_chapter,
            chapter.name,
            "populate_member_chapter should set chapter field",
        )
        print(f"✅ populate_member_chapter correctly set: {invoice.custom_member_chapter}")

    def test_get_member_primary_chapter_with_inactive_parent_chapter(self):
        """Test get_member_primary_chapter ignores inactive parent chapters"""
        print("\n🧪 Testing get_member_primary_chapter with inactive parent chapter...")

        # Create member
        member = self.create_test_member(
            first_name="Test",
            last_name=f"InactiveParent {self.test_id}",
            email=f"inactiveparent{self.test_id.lower()}@example.com",
        )

        # Create inactive chapter
        chapter = self.create_chapter(status="Inactive")

        # Add member to chapter
        chapter.append(
            "chapter_members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Test function - should return None because parent chapter is inactive
        result = get_member_primary_chapter(member.name)

        self.assertIsNone(result, "Should return None when parent chapter is inactive")
        print("✅ get_member_primary_chapter correctly ignored inactive parent chapter")
