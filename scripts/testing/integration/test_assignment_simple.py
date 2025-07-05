import frappe


def test_assignment_history():
    """Simple test of assignment history manager"""
    print("Starting assignment history test...")

    try:
        # Import our new manager
        from verenigingen.utils.assignment_history_manager import AssignmentHistoryManager

        # Get a volunteer for testing
        volunteers = frappe.get_all("Volunteer", limit=1)
        if not volunteers:
            print("❌ No volunteers found for testing")
            return False

        volunteer_id = volunteers[0].name
        volunteer_doc = frappe.get_doc("Volunteer", volunteer_id)
        print(f"✅ Testing with volunteer: {volunteer_doc.volunteer_name} ({volunteer_id})")

        # Test adding assignment history
        print("Testing add_assignment_history...")
        success = AssignmentHistoryManager.add_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Test Assignment",
            reference_doctype="Test",
            reference_name="TEST001",
            role="Test Role",
            start_date="2025-01-01",
        )

        if success:
            print("✅ Successfully added assignment history")
        else:
            print("❌ Failed to add assignment history")
            return False

        # Check if it was added
        volunteer_doc.reload()
        found_assignment = False
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == "TEST001" and assignment.status == "Active":
                found_assignment = True
                print(f"✅ Found active assignment: {assignment.assignment_type} - {assignment.role}")
                break

        if not found_assignment:
            print("❌ Assignment not found in volunteer history")
            return False

        # Test completing assignment
        print("Testing complete_assignment_history...")
        success = AssignmentHistoryManager.complete_assignment_history(
            volunteer_id=volunteer_id,
            assignment_type="Test Assignment",
            reference_doctype="Test",
            reference_name="TEST001",
            role="Test Role",
            start_date="2025-01-01",
            end_date="2025-01-02",
        )

        if success:
            print("✅ Successfully completed assignment history")
        else:
            print("❌ Failed to complete assignment history")
            return False

        # Check if it was completed
        volunteer_doc.reload()
        found_completed = False
        for assignment in volunteer_doc.assignment_history or []:
            if assignment.reference_name == "TEST001" and assignment.status == "Completed":
                found_completed = True
                print(f"✅ Found completed assignment with end date: {assignment.end_date}")
                break

        if not found_completed:
            print("❌ Completed assignment not found")
            return False

        print("✅ Assignment history manager test completed successfully!")
        return True

    except Exception as e:
        print(f"❌ Error during test: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


# Run the test
test_assignment_history()
