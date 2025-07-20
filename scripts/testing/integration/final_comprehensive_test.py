import frappe


@frappe.whitelist()
def run_final_comprehensive_chapter_assignment_test():
    """Final comprehensive test for chapter assignment functionality"""

    results = {"test_name": "Final Comprehensive Chapter Assignment Test", "tests": [], "summary": {}}

    try:
        from verenigingen.verenigingen.doctype.chapter.chapter import assign_member_to_chapter_with_cleanup

        # Test 1: Error Handling Tests
        print("=== Test 1: Error Handling ===")

        # Test invalid parameters
        test1_results = []

        try:
            result = assign_member_to_chapter_with_cleanup(None, "Zeist")
            test1_results.append({"test": "Null member", "passed": False, "result": result})
        except Exception as e:
            test1_results.append({"test": "Null member", "passed": True, "error": str(e)})

        try:
            result = assign_member_to_chapter_with_cleanup("Assoc-Member-2025-06-0001", "NonExistent")
            test1_results.append(
                {"test": "Invalid chapter", "passed": not result.get("success"), "result": result}
            )
        except Exception as e:
            test1_results.append({"test": "Invalid chapter", "passed": True, "error": str(e)})

        results["tests"].append(
            {
                "test_group": "Error Handling",
                "tests": test1_results,
                "passed": all(t["passed"] for t in test1_results)}
        )

        # Test 2: Successful Assignment
        print("=== Test 2: Successful Assignment ===")

        # Find a member and assign them to a different chapter
        member_to_test = "Assoc-Member-2025-06-0001"  # This member exists

        # Get their current state
        current_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member_to_test, "enabled": 1}, fields=["parent", "name"]
        )

        # Try to assign to Zeist
        result = assign_member_to_chapter_with_cleanup(
            member=member_to_test, chapter="Zeist", note="Comprehensive test assignment"
        )

        # Check final state
        final_memberships = frappe.get_all(
            "Chapter Member", filters={"member": member_to_test, "enabled": 1}, fields=["parent", "name"]
        )

        assignment_success = result.get("success", False)
        in_target_chapter = any(m.parent == "Zeist" for m in final_memberships)
        only_one_chapter = len(final_memberships) == 1

        test2_results = [
            {"test": "Assignment succeeded", "passed": assignment_success, "details": result.get("message")},
            {
                "test": "Member in target chapter",
                "passed": in_target_chapter,
                "details": f"Chapters: {[m.parent for m in final_memberships]}"},
            {
                "test": "Member in exactly one chapter",
                "passed": only_one_chapter,
                "details": f"Chapter count: {len(final_memberships)}"},
        ]

        results["tests"].append(
            {
                "test_group": "Successful Assignment",
                "tests": test2_results,
                "passed": all(t["passed"] for t in test2_results),
                "initial_state": [m.parent for m in current_memberships],
                "final_state": [m.parent for m in final_memberships],
                "assignment_result": result}
        )

        # Test 3: Same Chapter Assignment
        print("=== Test 3: Same Chapter Assignment ===")

        # Assign to same chapter again
        result2 = assign_member_to_chapter_with_cleanup(
            member=member_to_test, chapter="Zeist", note="Same chapter test"
        )

        final_memberships2 = frappe.get_all(
            "Chapter Member", filters={"member": member_to_test, "enabled": 1}, fields=["parent", "name"]
        )

        test3_results = [
            {
                "test": "Same chapter assignment handled",
                "passed": result2.get("success", False),
                "details": result2.get("message")},
            {
                "test": "Still in one chapter",
                "passed": len(final_memberships2) == 1,
                "details": f"Chapters: {[m.parent for m in final_memberships2]}"},
        ]

        results["tests"].append(
            {
                "test_group": "Same Chapter Assignment",
                "tests": test3_results,
                "passed": all(t["passed"] for t in test3_results),
                "assignment_result": result2}
        )

        # Calculate summary
        total_test_groups = len(results["tests"])
        passed_test_groups = sum(1 for t in results["tests"] if t["passed"])

        all_individual_tests = []
        for group in results["tests"]:
            all_individual_tests.extend(group["tests"])

        total_individual_tests = len(all_individual_tests)
        passed_individual_tests = sum(1 for t in all_individual_tests if t["passed"])

        results["summary"] = {
            "total_test_groups": total_test_groups,
            "passed_test_groups": passed_test_groups,
            "total_individual_tests": total_individual_tests,
            "passed_individual_tests": passed_individual_tests,
            "overall_success": passed_test_groups == total_test_groups,
            "success_rate": f"{(passed_individual_tests/total_individual_tests*100):.1f}%"
            if total_individual_tests > 0
            else "0%"}

        results["success"] = results["summary"]["overall_success"]
        results[
            "message"
        ] = f"Comprehensive test completed: {passed_test_groups}/{total_test_groups} test groups passed"

        return results

    except Exception as e:
        import traceback

        results["success"] = False
        results["message"] = f"Test failed with error: {str(e)}"
        results["error_details"] = traceback.format_exc()

        return results


if __name__ == "__main__":
    result = run_final_comprehensive_chapter_assignment_test()
    print(f"Final test result: {result}")
