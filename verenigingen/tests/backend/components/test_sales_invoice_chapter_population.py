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
from verenigingen.services.chapter.chapter_utils import get_member_primary_chapter
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
        self.company = self._get_test_company()

    def _get_or_create_customer(self, customer_name, member=None):
        """Get existing Customer for member or create a new one."""
        if member:
            existing = frappe.db.get_value("Customer", {"member": member.name}, "name")
            if existing:
                return frappe.get_doc("Customer", existing)
        customer = frappe.get_doc(
            {
                "doctype": "Customer",
                "customer_name": customer_name,
                "customer_type": "Individual",
                "customer_group": "Individual",
                "territory": "Netherlands",
                **({"member": member.name} if member else {}),
            }
        )
        customer.insert()
        return customer

    def _make_invoice(self, customer_name, **overrides):
        """Build a Sales Invoice doc with all required ERPNext fields."""
        company = self.company
        currency = frappe.db.get_value("Company", company, "default_currency") or "EUR"
        debit_to = frappe.db.get_value("Company", company, "default_receivable_account")
        selling_price_list = (
            frappe.db.get_value("Selling Settings", None, "selling_price_list") or "Standard Selling"
        )
        # ERPNext's standard chart of accounts leaves account_type EMPTY on income
        # leaves; they carry root_type = "Income" instead (#442). Keying on
        # account_type resolved only when a sibling suite in the same shard had
        # already planted a hand-typed row.
        income_account = frappe.db.get_value(
            "Account", {"root_type": "Income", "company": company, "is_group": 0}, "name"
        )
        cost_center = frappe.db.get_value("Company", company, "cost_center")

        data = {
            "doctype": "Sales Invoice",
            "company": company,
            "currency": currency,
            "conversion_rate": 1.0,
            "selling_price_list": selling_price_list,
            "price_list_currency": currency,
            "plc_conversion_rate": 1.0,
            "debit_to": debit_to,
            "customer": customer_name,
            "posting_date": nowdate(),
            "due_date": nowdate(),
            "items": [
                {
                    "item_code": "_Test Item",
                    "qty": 1,
                    "rate": 100,
                    "income_account": income_account,
                    "cost_center": cost_center,
                }
            ],
        }
        data.update(overrides)
        return frappe.get_doc(data)

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
            "members",
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
            "members",
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
            "members",
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
            "members",
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
            "members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Get or create customer for member
        customer = self._get_or_create_customer(f"Test Customer {self.test_id}", member)

        # Create Sales Invoice
        invoice = self._make_invoice(customer.name)
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
            "members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter1.save()

        # Get or create customer for member
        customer = self._get_or_create_customer(f"Test Customer Override {self.test_id}", member)

        # Create Sales Invoice with manually set chapter
        invoice = self._make_invoice(customer.name, custom_member_chapter=chapter2.name)
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
        customer = self._get_or_create_customer(f"Non-Member Customer {self.test_id}")

        # Create Sales Invoice
        invoice = self._make_invoice(customer.name)
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
            "members",
            {
                "member": member.name,
                "enabled": 1,
                "status": "Active",
                "chapter_join_date": today(),
            },
        )
        chapter.save()

        # Get or create customer for member
        customer = self._get_or_create_customer(f"Test Customer Direct {self.test_id}", member)

        # Create Sales Invoice doc without inserting (no hooks)
        invoice = self._make_invoice(customer.name)

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
            "members",
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
