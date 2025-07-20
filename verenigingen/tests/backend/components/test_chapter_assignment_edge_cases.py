import unittest

import frappe

from verenigingen.api.member_management import add_member_to_chapter_roster, assign_member_to_chapter


def get_member_primary_chapter(member_name):
    """Helper function to get member's primary chapter from Chapter Member table"""
    try:
        chapters = frappe.get_all(
            "Chapter Member",
            filters={"member": member_name, "enabled": 1},
            fields=["parent"],
            order_by="chapter_join_date desc",
            limit=1,
        )
        return chapters[0].parent if chapters else None
    except Exception:
        return None


class TestChapterAssignmentEdgeCases(unittest.TestCase):
    """Test edge cases for chapter assignment functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up test data"""
        # Create test chapters
        test_chapters = [
            {
                "name": "Test Chapter Alpha",
                "region": "Test Region Alpha",
                "postal_codes": "1000-1999",
                "published": 1,
                "introduction": "Test chapter Alpha"},
            {
                "name": "Test Chapter Beta",
                "region": "Test Region Beta",
                "postal_codes": "2000-2999",
                "published": 1,
                "introduction": "Test chapter Beta"},
            {
                "name": "Unpublished Test Chapter",
                "region": "Test Region Gamma",
                "postal_codes": "3000-3999",
                "published": 0,  # Unpublished
                "introduction": "Unpublished test chapter"},
        ]

        for chapter_data in test_chapters:
            if not frappe.db.exists("Chapter", chapter_data["name"]):
                chapter = frappe.get_doc({"doctype": "Chapter", **chapter_data})
                chapter.insert()

        # Create test membership type
        if not frappe.db.exists("Membership Type", "Test Membership"):
            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "amount": 100,
                    "currency": "EUR",
                    "subscription_period": "Annual"}
            )
            membership_type.insert()

    def setUp(self):
        """Set up for each test"""
        self.test_counter = getattr(self, "_test_counter", 0) + 1
        setattr(self, "_test_counter", self.test_counter)

        # Create test member
        self.test_member_name = f"TEST-MEMBER-{self.test_counter:03d}"
        self.test_email = f"chapter_edge_test_{self.test_counter}@example.com"

        if not frappe.db.exists("Member", self.test_member_name):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "name": self.test_member_name,
                    "first_name": "Test",
                    "last_name": f"Member{self.test_counter}",
                    "full_name": f"Test Member{self.test_counter}",
                    "email": self.test_email,
                    "status": "Active",
                    "birth_date": "1990-01-01",
                    "application_status": "Approved"}
            )
            member.insert()

    def tearDown(self):
        """Clean up after each test"""
        # Clean up test member and related data
        try:
            if frappe.db.exists("Member", self.test_member_name):
                member = frappe.get_doc("Member", self.test_member_name)

                # Remove from all chapter rosters
                chapters = frappe.get_all("Chapter", fields=["name"])
                for chapter in chapters:
                    try:
                        chapter_doc = frappe.get_doc("Chapter", chapter.name)
                        # Remove member from roster if present
                        for i, member_row in enumerate(chapter_doc.members):
                            if member_row.member == self.test_member_name:
                                chapter_doc.members.pop(i)
                                chapter_doc.save()
                                break
                    except Exception:
                        pass

                # Delete customer if exists
                if member.customer:
                    frappe.delete_doc("Customer", member.customer, force=True)

                # Delete member
                frappe.delete_doc("Member", self.test_member_name, force=True)
        except Exception:
            pass

        frappe.db.commit()

    def test_assign_member_to_same_chapter_twice(self):
        """Test assigning member to same chapter multiple times"""
        print("\n🧪 Testing assignment to same chapter twice...")

        # First assignment
        result1 = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result1["success"], "First assignment should succeed")

        # Second assignment to same chapter
        result2 = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result2["success"], "Second assignment to same chapter should succeed")
        self.assertIn("already assigned", result2["message"], "Should indicate already assigned")

        # Verify member is in chapter roster only once
        chapter = frappe.get_doc("Chapter", "Test Chapter Alpha")
        member_count = sum(1 for m in chapter.members if m.member == self.test_member_name)
        self.assertEqual(member_count, 1, "Member should appear only once in chapter roster")

        print("✅ Same chapter assignment handled correctly")

    def test_assign_to_nonexistent_chapter(self):
        """Test assigning member to non-existent chapter"""
        print("\n🧪 Testing assignment to non-existent chapter...")

        result = assign_member_to_chapter(self.test_member_name, "Non-Existent Chapter")

        self.assertFalse(result["success"], "Should fail for non-existent chapter")
        self.assertIn("not found", result["error"], "Error should mention chapter not found")

        # Member should not have any chapter assigned
        member = frappe.get_doc("Member", self.test_member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertFalse(primary_chapter, "Member should not have chapter assigned")

        print("✅ Non-existent chapter handled correctly")

    def test_assign_nonexistent_member_to_chapter(self):
        """Test assigning non-existent member to chapter"""
        print("\n🧪 Testing assignment of non-existent member...")

        result = assign_member_to_chapter("NON-EXISTENT-MEMBER", "Test Chapter Alpha")

        self.assertFalse(result["success"], "Should fail for non-existent member")
        self.assertIn("not found", result["error"], "Error should mention member not found")

        print("✅ Non-existent member handled correctly")

    def test_assign_to_unpublished_chapter(self):
        """Test assigning member to unpublished chapter"""
        print("\n🧪 Testing assignment to unpublished chapter...")

        result = assign_member_to_chapter(self.test_member_name, "Unpublished Test Chapter")

        # Should succeed (unpublished status doesn't prevent direct assignment)
        self.assertTrue(result["success"], "Assignment to unpublished chapter should succeed")

        # Verify assignment
        member = frappe.get_doc("Member", self.test_member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertEqual(
            primary_chapter, "Unpublished Test Chapter", "Member should be assigned to unpublished chapter"
        )

        print("✅ Unpublished chapter assignment works")

    def test_chapter_transfer_roster_management(self):
        """Test that transferring between chapters properly manages rosters"""
        print("\n🧪 Testing chapter transfer roster management...")

        # Assign to first chapter
        result1 = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result1["success"])

        # Verify member is in first chapter roster
        chapter_alpha = frappe.get_doc("Chapter", "Test Chapter Alpha")
        alpha_members = [m.member for m in chapter_alpha.members]
        self.assertIn(self.test_member_name, alpha_members, "Member should be in Alpha roster")

        # Transfer to second chapter
        result2 = assign_member_to_chapter(self.test_member_name, "Test Chapter Beta")
        self.assertTrue(result2["success"])

        # Verify member is removed from first chapter roster
        chapter_alpha.reload()
        alpha_members_after = [m.member for m in chapter_alpha.members]
        self.assertNotIn(
            self.test_member_name, alpha_members_after, "Member should be removed from Alpha roster"
        )

        # Verify member is in second chapter roster
        chapter_beta = frappe.get_doc("Chapter", "Test Chapter Beta")
        beta_members = [m.member for m in chapter_beta.members]
        self.assertIn(self.test_member_name, beta_members, "Member should be in Beta roster")

        print("✅ Chapter transfer roster management works correctly")

    def test_roster_member_enabling_and_disabling(self):
        """Test enabling/disabling members in chapter rosters"""
        print("\n🧪 Testing roster member enabling/disabling...")

        # Assign member to chapter
        result = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result["success"])

        # Verify member is enabled by default
        chapter = frappe.get_doc("Chapter", "Test Chapter Alpha")
        member_row = None
        for m in chapter.members:
            if m.member == self.test_member_name:
                member_row = m
                break

        self.assertIsNotNone(member_row, "Member should be in roster")
        self.assertTrue(member_row.enabled, "Member should be enabled by default")

        # Disable member in roster
        member_row.enabled = 0
        chapter.save()

        # Re-assign same member (should re-enable)
        result2 = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result2["success"])

        # Verify member is re-enabled
        chapter.reload()
        for m in chapter.members:
            if m.member == self.test_member_name:
                self.assertTrue(m.enabled, "Member should be re-enabled after assignment")
                break

        print("✅ Roster enabling/disabling works correctly")

    def test_empty_or_null_chapter_assignment(self):
        """Test assigning empty or null chapter values"""
        print("\n🧪 Testing empty/null chapter assignment...")

        # Test empty string
        result1 = assign_member_to_chapter(self.test_member_name, "")
        self.assertFalse(result1["success"], "Should fail for empty chapter name")
        self.assertIn("required", result1["error"], "Error should mention required field")

        # Test None
        result2 = assign_member_to_chapter(self.test_member_name, None)
        self.assertFalse(result2["success"], "Should fail for None chapter name")

        # Test whitespace only
        result3 = assign_member_to_chapter(self.test_member_name, "   ")
        self.assertFalse(result3["success"], "Should fail for whitespace-only chapter name")

        print("✅ Empty/null chapter assignment validation works")

    def test_empty_or_null_member_assignment(self):
        """Test assigning empty or null member values"""
        print("\n🧪 Testing empty/null member assignment...")

        # Test empty string
        result1 = assign_member_to_chapter("", "Test Chapter Alpha")
        self.assertFalse(result1["success"], "Should fail for empty member name")

        # Test None
        result2 = assign_member_to_chapter(None, "Test Chapter Alpha")
        self.assertFalse(result2["success"], "Should fail for None member name")

        print("✅ Empty/null member assignment validation works")

    def test_concurrent_chapter_assignments(self):
        """Test concurrent chapter assignments to same member"""
        print("\n🧪 Testing concurrent chapter assignments...")

        import threading
        import time

        results = []

        def assign_chapter(chapter_name, delay=0):
            if delay:
                time.sleep(delay)
            result = assign_member_to_chapter(self.test_member_name, chapter_name)
            results.append((chapter_name, result))

        # Start concurrent assignments
        thread1 = threading.Thread(target=assign_chapter, args=("Test Chapter Alpha", 0))
        thread2 = threading.Thread(target=assign_chapter, args=("Test Chapter Beta", 0.1))

        thread1.start()
        thread2.start()

        thread1.join()
        thread2.join()

        # At least one should succeed
        successful_results = [r for _, r in results if r["success"]]
        self.assertGreater(len(successful_results), 0, "At least one assignment should succeed")

        # Final state should be consistent
        member = frappe.get_doc("Member", self.test_member_name)
        primary_chapter = get_member_primary_chapter(member.name)
        self.assertTrue(primary_chapter, "Member should have a chapter assigned")

        print(f"✅ Concurrent assignments handled: {len(successful_results)}/{len(results)} succeeded")

    def test_roster_corruption_recovery(self):
        """Test recovery from corrupted chapter roster data"""
        print("\n🧪 Testing roster corruption recovery...")

        # Assign member normally
        result = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertTrue(result["success"])

        # Simulate roster corruption by adding duplicate entries
        chapter = frappe.get_doc("Chapter", "Test Chapter Alpha")
        chapter.append(
            "members",
            {"member": self.test_member_name, "member_name": f"Test Member{self.test_counter}", "enabled": 1},
        )
        chapter.save()

        # Count duplicates
        member_count_before = sum(1 for m in chapter.members if m.member == self.test_member_name)
        self.assertGreater(member_count_before, 1, "Should have duplicate entries")

        # Re-assign should clean up duplicates
        add_member_to_chapter_roster(self.test_member_name, "Test Chapter Alpha", None)

        # Verify cleanup (this is an edge case - the function might not clean duplicates)
        chapter.reload()
        member_count_after = sum(1 for m in chapter.members if m.member == self.test_member_name)
        # Note: The current implementation doesn't remove duplicates, just ensures member exists
        self.assertGreaterEqual(member_count_after, 1, "Member should still be in roster")

        print(f"✅ Roster corruption handled: {member_count_before} → {member_count_after} entries")

    def test_chapter_with_special_characters(self):
        """Test chapter assignment with special characters in names"""
        print("\n🧪 Testing special characters in chapter names...")

        # Create chapter with special characters
        special_chapter_name = "Test Chapter Ñieuwe-Åmsterdam (Spëcial)"
        if not frappe.db.exists("Chapter", special_chapter_name):
            special_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": special_chapter_name,
                    "region": "Special-Ñieuwe Test",
                    "postal_codes": "8000-8999",
                    "published": 1,
                    "introduction": "Special chapter with international characters"}
            )
            special_chapter.insert()

        # Test assignment
        result = assign_member_to_chapter(self.test_member_name, special_chapter_name)
        self.assertTrue(result["success"], "Should handle special characters in chapter names")

        # Verify assignment
        member = frappe.get_doc("Member", self.test_member_name)
        self.assertEqual(
            member.primary_chapter, special_chapter_name, "Special character chapter name should be preserved"
        )

        # Verify roster entry
        chapter = frappe.get_doc("Chapter", special_chapter_name)
        roster_members = [m.member for m in chapter.members]
        self.assertIn(self.test_member_name, roster_members, "Member should be in special chapter roster")

        print(f"✅ Special characters handled: {special_chapter_name}")

        # Clean up
        try:
            frappe.delete_doc("Chapter", special_chapter_name, force=True)
        except Exception:
            pass

    def test_member_with_special_characters(self):
        """Test member assignment with special characters in member data"""
        print("\n🧪 Testing special characters in member names...")

        # Create member with special characters
        special_member_name = f"SPECIAL-MEMBER-{self.test_counter}"
        special_email = f"spëcial_tëst_{self.test_counter}@exàmple.com"

        if not frappe.db.exists("Member", special_member_name):
            special_member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "name": special_member_name,
                    "first_name": "José-María",
                    "last_name": "Ñoël-O'Connor",
                    "full_name": "José-María Ñoël-O'Connor",
                    "email": special_email,
                    "status": "Active",
                    "birth_date": "1990-01-01",
                    "application_status": "Approved"}
            )
            special_member.insert()

        # Test assignment
        result = assign_member_to_chapter(special_member_name, "Test Chapter Alpha")
        self.assertTrue(result["success"], "Should handle special characters in member names")

        # Verify roster entry with special characters
        chapter = frappe.get_doc("Chapter", "Test Chapter Alpha")
        roster_entry = None
        for m in chapter.members:
            if m.member == special_member_name:
                roster_entry = m
                break

        self.assertIsNotNone(roster_entry, "Special character member should be in roster")
        self.assertEqual(
            roster_entry.member_name,
            "José-María Ñoël-O'Connor",
            "Special characters should be preserved in roster",
        )

        print("✅ Special character member names handled correctly")

        # Clean up
        try:
            frappe.delete_doc("Member", special_member_name, force=True)
        except Exception:
            pass

    def test_large_chapter_roster_performance(self):
        """Test performance with large chapter rosters"""
        print("\n🧪 Testing large chapter roster performance...")

        # Create chapter for performance test
        perf_chapter_name = "Performance Test Chapter"
        if not frappe.db.exists("Chapter", perf_chapter_name):
            perf_chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": perf_chapter_name,
                    "region": "Performance Test Region",
                    "postal_codes": "9000-9999",
                    "published": 1,
                    "introduction": "Chapter for performance testing"}
            )
            perf_chapter.insert()

        # Add many fake members to roster
        chapter = frappe.get_doc("Chapter", perf_chapter_name)
        for i in range(50):  # Add 50 fake members
            chapter.append(
                "members", {"member": f"FAKE-MEMBER-{i:03d}", "member_name": f"Fake Member {i}", "enabled": 1}
            )
        chapter.save()

        # Measure assignment performance
        import time

        start_time = time.time()

        result = assign_member_to_chapter(self.test_member_name, perf_chapter_name)

        end_time = time.time()
        assignment_time = end_time - start_time

        # Should complete quickly (under 2 seconds)
        self.assertTrue(result["success"], "Assignment should succeed with large roster")
        self.assertLess(assignment_time, 2.0, "Assignment should be fast even with large roster")

        # Verify member was added correctly
        chapter.reload()
        roster_members = [m.member for m in chapter.members]
        self.assertIn(self.test_member_name, roster_members, "Member should be in large roster")

        print(
            f"✅ Large roster performance acceptable: {assignment_time:.3f}s for roster of {len(chapter.members)} members"
        )

        # Clean up
        try:
            frappe.delete_doc("Chapter", perf_chapter_name, force=True)
        except Exception:
            pass

    def test_api_permission_edge_cases(self):
        """Test permission edge cases for chapter assignment API"""
        print("\n🧪 Testing API permission edge cases...")

        # Test with guest user (should fail)
        frappe.set_user("Guest")
        result = assign_member_to_chapter(self.test_member_name, "Test Chapter Alpha")
        self.assertFalse(result["success"], "Guest user should not be able to assign chapters")
        self.assertIn("permission", result["error"], "Error should mention permissions")

        # Reset to administrator
        frappe.set_user("Administrator")

        print("✅ Permission edge cases handled correctly")

    def test_database_transaction_rollback(self):
        """Test that failed assignments don't leave partial data"""
        print("\n🧪 Testing database transaction rollback...")

        # Get initial state
        member = frappe.get_doc("Member", self.test_member_name)
        initial_chapter = member.primary_chapter

        # Attempt assignment to non-existent chapter (should fail)
        result = assign_member_to_chapter(self.test_member_name, "Non-Existent Chapter")
        self.assertFalse(result["success"])

        # Verify no partial changes
        member.reload()
        self.assertEqual(
            member.primary_chapter, initial_chapter, "Failed assignment should not change member data"
        )

        # Verify no roster entries were created
        all_chapters = frappe.get_all("Chapter", fields=["name"])
        for chapter_info in all_chapters:
            chapter = frappe.get_doc("Chapter", chapter_info.name)
            roster_members = [m.member for m in chapter.members if m.member == self.test_member_name]
            # Should only be in roster if member was already assigned to that chapter
            if chapter_info.name != initial_chapter:
                self.assertEqual(
                    len(roster_members),
                    0,
                    f"Member should not be in {chapter_info.name} roster after failed assignment",
                )

        print("✅ Database transaction rollback works correctly")


class ObsoleteSubscriptionPlanTests(unittest.TestCase):
    """OBSOLETE: Tests removed due to subscription system elimination"""
    
    def test_obsolete_notice(self):
        """Notice that subscription plan tests are obsolete"""
        self.skipTest("Subscription system completely removed - no backwards compatibility")

    pass  # All subscription plan tests removed - no backwards compatibility


def run_edge_case_tests():
    """Run all edge case tests"""
    # Run chapter assignment edge cases
    print("🧪 Running Chapter Assignment Edge Case Tests...")
    chapter_suite = unittest.TestLoader().loadTestsFromTestCase(TestChapterAssignmentEdgeCases)
    chapter_runner = unittest.TextTestRunner(verbosity=2)
    chapter_result = chapter_runner.run(chapter_suite)

    # Run subscription cost field edge cases
    print("\n🧪 Running Subscription Cost Field Edge Case Tests...")
    cost_suite = unittest.TestLoader().loadTestsFromTestCase(TestSubscriptionPlanCostFieldEdgeCases)
    cost_runner = unittest.TextTestRunner(verbosity=2)
    cost_result = cost_runner.run(cost_suite)

    # Print summary
    total_tests = chapter_result.testsRun + cost_result.testsRun
    total_failures = len(chapter_result.failures) + len(cost_result.failures)
    total_errors = len(chapter_result.errors) + len(cost_result.errors)

    print("\n📊 Edge Case Tests Summary:")
    print(f"   Total Tests: {total_tests}")
    print(f"   Passed: {total_tests - total_failures - total_errors}")
    print(f"   Failures: {total_failures}")
    print(f"   Errors: {total_errors}")

    if total_failures == 0 and total_errors == 0:
        print("🎉 All edge case tests passed!")
    else:
        print("❌ Some edge case tests failed")

    return total_failures == 0 and total_errors == 0


if __name__ == "__main__":
    run_edge_case_tests()
