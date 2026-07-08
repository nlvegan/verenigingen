"""
Member Lifecycle Mock Elimination: Production Issues Fixed
=========================================================

Phase 5.1 Database Mock Elimination: Fixed production issues discovered by real testing.

PRODUCTION ISSUES DISCOVERED & FIXED:
1. Invalid Member Status "Application Pending" → Fixed to "Pending" (line 508 Member.json)
2. Missing Address Fields - Member has primary_address Link, not postal_code directly
3. Enhanced Test Factory API inconsistencies - Fixed method signatures

ELIMINATED INAPPROPRIATE MOCKS:
- @patch('member_id_manager.generate_member_id') - Real member ID generation
- Mock status validation - Real DocType validation
- Mock address logic - Real Address DocType relationships

This demonstrates the value of mock elimination: real database testing immediately
discovers production configuration issues that mocked tests completely miss.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestMemberLifecycleMockEliminationFixed(EnhancedTestCase):
    """Fixed member lifecycle tests with real database operations"""

    def setUp(self):
        """Set up real test data"""
        super().setUp()

        # Create real test chapter
        self.test_chapter = self.create_chapter(region="Noord-Holland")

    def test_real_member_status_validation_fixed(self):
        """Test real Member DocType status validation (FIXED: use valid status)"""

        # Production Issue Fixed: "Application Pending" → "Pending" (valid status)
        pending_member = self.create_test_member(
            first_name="Pending",
            last_name="Member",
            status="Pending",  # FIXED: Valid status from Member.json line 508
        )

        self.assertEqual(pending_member.status, "Pending")
        print(f"✅ Fixed production issue: Valid Member status used")

        # Test valid status transition
        pending_member.status = "Active"
        pending_member.save()
        self.assertEqual(pending_member.status, "Active")

        print(f"✅ Real status transition validation works: Pending → Active")

    def test_real_address_structure_fixed(self):
        """Test real Address DocType relationship (FIXED: use primary_address Link)"""

        # Production Issue Fixed: Direct postal_code → Address DocType relationship
        test_address = frappe.get_doc(
            {
                "doctype": "Address",
                # address_type/title set explicitly: DocType defaults aren't applied
                # under frappe.flags.in_import (EnhancedTestCase).
                "address_type": "Personal",
                "address_title": "Kalverstraat Test Address",
                "address_line1": "Kalverstraat 123",
                "city": "Amsterdam",
                "country": "Netherlands",
                "pincode": "1012AB",
            }
        )
        test_address.insert()

        # FIXED: Use primary_address Link field, not non-existent postal_code
        member = self.create_test_member(
            first_name="Address",
            last_name="Test",
            primary_address=test_address.name,  # FIXED: Real Member field
        )

        self.assertEqual(member.primary_address, test_address.name)
        print(f"✅ Fixed production issue: Real Address DocType relationship used")

        # Verify address data can be accessed through relationship
        address_doc = frappe.get_doc("Address", member.primary_address)
        self.assertEqual(address_doc.pincode, "1012AB")

        print(f"✅ Real Address relationship: {address_doc.address_line1}, {address_doc.city}")

    def test_real_member_id_generation_workflow(self):
        """Test real member ID generation without mocks.

        member_id=None is passed explicitly: the test factory pre-assigns its own
        member_id by default, which would mask the real production generation logic
        (MemberBeforeSaveService._handle_id_generation) entirely if left in place.
        """

        member = self.create_test_member(
            first_name="MemberID", last_name="Test", status="Active", member_id=None
        )

        self.assertTrue(member.member_id, "Active member should have a real member_id assigned")
        print(f"✅ Real member ID generation: {member.member_id}")

    def test_real_dutch_name_formatting(self):
        """Test real Dutch name formatting business logic"""

        # Test Dutch name with tussenvoegsel
        member = self.create_test_member(
            first_name="Jan", tussenvoegsel="van", last_name="Dijk", email="jan.van.dijk@test.example.com"
        )

        # Test real full_name generation -- unconditional: full_name must always be
        # auto-generated on save (dutch_name_service.update_member_full_name).
        self.assertTrue(member.full_name, "Member.full_name should be auto-generated on save")
        self.assertIn("Jan", member.full_name)
        self.assertIn("van", member.full_name)
        self.assertIn("Dijk", member.full_name)
        print(f"✅ Real Dutch name formatting: {member.full_name}")
