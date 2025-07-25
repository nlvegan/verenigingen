import frappe


@frappe.whitelist()
def check_dues_schedule_fields():
    """Check what fields exist in Membership Dues Schedule table"""

    try:
        # Get field list from database
        result = frappe.db.sql("DESCRIBE `tabMembership Dues Schedule`", as_dict=True)

        field_names = [field["Field"] for field in result]

        # Check if membership field exists
        has_membership_field = "membership" in field_names

        # Look for similar fields
        membership_related_fields = [f for f in field_names if "member" in f.lower()]

        return {
            "total_fields": len(field_names),
            "has_membership_field": has_membership_field,
            "membership_related_fields": membership_related_fields,
            "all_fields": field_names[:20],  # First 20 fields
            "schema": result[:10] if result else [],  # First 10 field definitions
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def check_schedule_doctype_meta():
    """Check DocType meta information for Membership Dues Schedule"""

    try:
        meta = frappe.get_meta("Membership Dues Schedule")

        # Get all field names
        field_names = [field.fieldname for field in meta.fields]

        # Look for membership-related fields
        membership_fields = []
        for field in meta.fields:
            if "member" in field.fieldname.lower():
                membership_fields.append(
                    {
                        "fieldname": field.fieldname,
                        "fieldtype": field.fieldtype,
                        "label": field.label,
                        "options": getattr(field, "options", None),
                        "read_only": getattr(field, "read_only", 0),
                    }
                )

        return {
            "doctype": "Membership Dues Schedule",
            "total_fields": len(field_names),
            "has_membership_field": "membership" in field_names,
            "membership_related_fields": membership_fields,
            "first_10_fields": field_names[:10],
        }

    except Exception as e:
        return {"error": str(e)}


@frappe.whitelist()
def identify_invalid_member_schedules():
    """Identify schedules with non-existent member references"""

    # Get all active non-template schedules
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "is_template": 0},
        fields=["name", "member", "schedule_name", "membership_type", "dues_rate", "creation"],
    )

    invalid_schedules = []
    for schedule in schedules:
        if schedule.member:
            # Check if member exists
            member_exists = frappe.db.exists("Member", schedule.member)
            if not member_exists:
                invalid_schedules.append(schedule)

    return {
        "total_schedules": len(schedules),
        "invalid_schedules": len(invalid_schedules),
        "details": invalid_schedules[:20],  # Limit to first 20 for display
    }


@frappe.whitelist()
def cleanup_invalid_member_schedules(dry_run=True):
    """
    Clean up schedules with invalid member references using direct SQL

    Args:
        dry_run (bool): If True, only report what would be done without making changes
    """

    # First identify all invalid schedules (not just first 20)
    schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "is_template": 0},
        fields=["name", "member", "schedule_name", "membership_type", "dues_rate"],
    )

    invalid_schedules = []
    for schedule in schedules:
        if schedule.member:
            # Check if member exists
            member_exists = frappe.db.exists("Member", schedule.member)
            if not member_exists:
                invalid_schedules.append(schedule)

    if not invalid_schedules:
        return {"success": True, "message": "No invalid schedules found to clean up", "processed": 0}

    cleanup_actions = []

    try:
        if not dry_run:
            frappe.db.begin()

        for schedule_data in invalid_schedules:
            schedule_name = schedule_data["name"]
            member_name = schedule_data["member"]

            action = {
                "schedule": schedule_name,
                "member": member_name,
                "action": "would_cancel" if dry_run else "cancelled",
                "reason": f"Member {member_name} does not exist",
            }

            if not dry_run:
                # Cancel the schedule using direct SQL to avoid validation issues
                frappe.db.sql(
                    """
                    UPDATE `tabMembership Dues Schedule`
                    SET status = 'Cancelled', modified = NOW(), modified_by = %s
                    WHERE name = %s
                """,
                    (frappe.session.user, schedule_name),
                )

            cleanup_actions.append(action)

        if not dry_run:
            frappe.db.commit()

        return {
            "success": True,
            "message": f'{"Would cancel" if dry_run else "Cancelled"} {len(cleanup_actions)} invalid schedules',
            "processed": len(cleanup_actions),
            "actions": cleanup_actions,
            "dry_run": dry_run,
        }

    except Exception as e:
        if not dry_run:
            frappe.db.rollback()

        return {
            "success": False,
            "message": f"Error during cleanup: {str(e)}",
            "processed": 0,
            "actions": cleanup_actions,
        }


@frappe.whitelist()
def check_zero_rate_schedules():
    """Check why the zero-rate schedules are appropriate"""

    zero_schedules = frappe.get_all(
        "Membership Dues Schedule",
        filters={"status": "Active", "is_template": 0, "dues_rate": 0},
        fields=["name", "member", "membership_type", "dues_rate"],
    )

    results = []
    for schedule in zero_schedules:
        membership_type_data = frappe.db.get_value(
            "Membership Type", schedule.membership_type, ["minimum_amount"], as_dict=True
        )

        results.append(
            {
                "schedule": schedule.name,
                "member": schedule.member,
                "membership_type": schedule.membership_type,
                "schedule_rate": schedule.dues_rate,
                "type_minimum": membership_type_data.minimum_amount if membership_type_data else "Unknown",
                "appropriate": membership_type_data.minimum_amount == 0 if membership_type_data else False,
            }
        )

    return {"total_zero_schedules": len(zero_schedules), "details": results}


@frappe.whitelist()
def test_better_approach():
    """Demonstrate the better testing approach suggested by the user"""

    results = []

    try:
        # Step 1: Create member
        test_id = frappe.generate_hash(length=6)
        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "BetterTest",
                "last_name": f"User{test_id}",
                "email": f"better.test.{test_id}@example.com",
                "birth_date": "1990-01-01",
                "address_line1": "123 Test Street",
                "postal_code": "1234AB",
                "city": "Test City",
            }
        )
        member.insert()
        results.append(f"✅ Created member: {member.name}")

        # Step 2: Create membership type
        # Get an existing template
        template = (
            frappe.db.get_value("Membership Dues Schedule", {"is_template": 1}, "name")
            or "Monthly Membership Template"
        )

        membership_type = frappe.get_doc(
            {
                "doctype": "Membership Type",
                "membership_type_name": f"Better Test Type {test_id}",
                "minimum_amount": 30.0,
                "is_active": 1,
                "dues_schedule_template": template,
            }
        )
        membership_type.insert()
        results.append(f"✅ Created membership type: {membership_type.name}")

        # Step 3: Create membership (this should auto-create a schedule)
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": membership_type.name,
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        )
        membership.insert()
        membership.submit()
        results.append(f"✅ Created membership: {membership.name}")

        # Step 4: Check if auto-schedule was created
        auto_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            fields=["name", "billing_frequency", "dues_rate"],
        )

        if auto_schedules:
            results.append(f"✅ Found {len(auto_schedules)} auto-created schedule(s)")
            for sched in auto_schedules:
                results.append(f"   - {sched.name}: {sched.billing_frequency}, €{sched.dues_rate}")
        else:
            results.append("❓ No auto-schedules found")

        # Step 5: Cancel the auto-created schedule
        for schedule_info in auto_schedules:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
            schedule.status = "Cancelled"
            schedule.save()
            results.append(f"✅ Cancelled auto-schedule: {schedule.name}")

        # Step 6: Since no auto-schedule was created, let's test your approach directly
        # Create first controlled test schedule
        try:
            schedule1 = frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": f"Test-Monthly-{test_id}",
                    "member": member.name,
                    "membership_type": membership_type.name,
                    "dues_rate": 30.0,
                    "billing_frequency": "Monthly",
                    "status": "Active",
                    "auto_generate": 1,
                    "next_invoice_date": frappe.utils.today(),
                }
            )
            schedule1.insert()
            results.append(f"✅ Created first test schedule: {schedule1.name} (Monthly)")

            # Step 7: Try to create second schedule with different frequency
            schedule2 = frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": f"Test-Annual-{test_id}",
                    "member": member.name,  # Same member!
                    "membership_type": membership_type.name,
                    "dues_rate": 200.0,
                    "billing_frequency": "Annual",  # Different frequency!
                    "status": "Active",
                    "auto_generate": 1,
                    "next_invoice_date": frappe.utils.today(),
                }
            )

            try:
                schedule2.insert()
                results.append(f"✅ SUCCESS: Created second schedule: {schedule2.name} (Annual)")
                results.append("🎉 Your approach works! We can now test billing frequency conflicts!")

                # Test the validation method
                if hasattr(schedule2, "validate_billing_frequency_consistency"):
                    validation_result = schedule2.validate_billing_frequency_consistency()
                    results.append(f"📋 Billing frequency validation: {validation_result}")

                # Clean up test data
                schedule2.delete()
                schedule1.delete()

            except Exception as e:
                results.append(f"❌ Still blocked by business rule: {str(e)}")
                schedule1.delete()

        except Exception as e:
            results.append(f"❌ Couldn't create first schedule: {str(e)}")

        # Clean up membership and related data
        membership.cancel()
        membership.delete()
        membership_type.delete()
        member.delete()

    except Exception as e:
        results.append(f"❌ Error in test: {str(e)}")

    return {
        "test_approach": "User suggested: Create → Cancel auto-schedule → Create controlled schedules",
        "results": results,
    }


@frappe.whitelist()
def validate_clear_auto_schedules_approach():
    """Validate the approach of clearing auto-schedules for controlled testing"""

    results = []
    cleanup_items = []

    try:
        # Step 1: Create a simple member using existing membership type
        test_id = frappe.generate_hash(length=6)
        existing_type = frappe.db.get_value("Membership Type", {"is_active": 1}, "name")

        if not existing_type:
            results.append("❌ No active membership types found for testing")
            return {"results": results}

        member = frappe.get_doc(
            {
                "doctype": "Member",
                "first_name": "EdgeTest",
                "last_name": f"User{test_id}",
                "email": f"edge.test.{test_id}@example.com",
                "birth_date": "1990-01-01",
                "address_line1": "123 Test Street",
                "postal_code": "1234AB",
                "city": "Test City",
            }
        )
        member.insert()
        cleanup_items.append(("Member", member.name))
        results.append(f"✅ Created member: {member.name}")

        # Step 1.5: Create an active membership for this member
        membership = frappe.get_doc(
            {
                "doctype": "Membership",
                "member": member.name,
                "membership_type": existing_type,
                "status": "Active",
                "start_date": frappe.utils.today(),
            }
        )
        membership.insert()
        membership.submit()
        cleanup_items.append(("Membership", membership.name))
        results.append(f"✅ Created membership: {membership.name}")

        # Step 2: Check current schedules for this member (might be auto-created)
        initial_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member.name, "status": "Active"},
            fields=["name", "billing_frequency", "dues_rate", "membership_type"],
        )

        results.append(f"📋 Initial schedules: {len(initial_schedules)}")
        for sched in initial_schedules:
            results.append(f"   - {sched.name}: {sched.billing_frequency}, €{sched.dues_rate}")

        # Step 3: Clear auto-schedules (the key part of the approach)
        cleared_count = 0
        for schedule_info in initial_schedules:
            schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
            schedule.status = "Cancelled"
            schedule.save()
            cleanup_items.append(("Membership Dues Schedule", schedule.name))
            cleared_count += 1

        results.append(f"✅ Cleared {cleared_count} auto-schedules")

        # Step 4: Now try to create controlled test schedules
        test_schedules_created = []

        # Create first test schedule
        schedule1 = frappe.get_doc(
            {
                "doctype": "Membership Dues Schedule",
                "schedule_name": f"EdgeTest-Monthly-{test_id}",
                "member": member.name,
                "membership_type": existing_type,
                "dues_rate": 25.0,
                "billing_frequency": "Monthly",
                "status": "Active",
                "auto_generate": 1,
                "next_invoice_date": frappe.utils.today(),
                "is_template": 0,
            }
        )

        try:
            schedule1.insert()
            cleanup_items.append(("Membership Dues Schedule", schedule1.name))
            test_schedules_created.append(schedule1.name)
            results.append(f"✅ Created first test schedule: {schedule1.name} (Monthly)")

            # Create second test schedule with different frequency
            schedule2 = frappe.get_doc(
                {
                    "doctype": "Membership Dues Schedule",
                    "schedule_name": f"EdgeTest-Quarterly-{test_id}",
                    "member": member.name,  # Same member!
                    "membership_type": existing_type,
                    "dues_rate": 75.0,
                    "billing_frequency": "Quarterly",  # Different frequency!
                    "status": "Active",
                    "auto_generate": 1,
                    "next_invoice_date": frappe.utils.today(),
                    "is_template": 0,
                }
            )

            try:
                schedule2.insert()
                cleanup_items.append(("Membership Dues Schedule", schedule2.name))
                test_schedules_created.append(schedule2.name)
                results.append(f"✅ SUCCESS: Created second test schedule: {schedule2.name} (Quarterly)")
                results.append("🎉 APPROACH VALIDATED: Can create multiple controlled test schedules!")

                # Test if we can run validation methods now
                if hasattr(schedule2, "validate_billing_frequency_consistency"):
                    try:
                        validation_result = schedule2.validate_billing_frequency_consistency()
                        results.append(f"📋 Billing frequency validation test: {validation_result}")
                    except Exception as val_error:
                        results.append(f"⚠️ Validation method error: {str(val_error)}")

            except Exception as e:
                results.append(f"❌ Second schedule creation failed: {str(e)}")
                results.append("This means the business rule still blocks multiple schedules")

        except Exception as e:
            results.append(f"❌ First schedule creation failed: {str(e)}")

        results.append(f"📊 Total test schedules created: {len(test_schedules_created)}")

    except Exception as e:
        results.append(f"❌ Test setup error: {str(e)}")

    finally:
        # Clean up all test data in reverse order
        cleanup_results = []
        for doctype, name in reversed(cleanup_items):
            try:
                doc = frappe.get_doc(doctype, name)
                if doctype == "Membership Dues Schedule" and doc.status != "Cancelled":
                    doc.status = "Cancelled"
                    doc.save()
                doc.delete()
                cleanup_results.append(f"✅ Cleaned up {doctype}: {name}")
            except Exception as cleanup_error:
                cleanup_results.append(f"⚠️ Cleanup error for {doctype} {name}: {str(cleanup_error)}")

        results.extend(cleanup_results)

    return {"approach_validated": len([r for r in results if "SUCCESS" in r]) > 0, "results": results}


@frappe.whitelist()
def test_new_edge_case_methods():
    """Test that the new edge case testing methods are available and working"""

    try:
        # Import the test class to check if methods exist
        from verenigingen.tests.utils.base import VereningingenTestCase

        # Check if our new methods exist
        methods_to_check = [
            "clear_member_auto_schedules",
            "create_controlled_dues_schedule",
            "setup_edge_case_testing",
        ]

        results = []

        for method_name in methods_to_check:
            if hasattr(VereningingenTestCase, method_name):
                method = getattr(VereningingenTestCase, method_name)
                results.append(f"✅ {method_name}: Available")

                # Check if it has docstring
                if method.__doc__:
                    results.append(f"   📚 Has documentation: {len(method.__doc__)} chars")
                else:
                    results.append(f"   ⚠️ Missing documentation")
            else:
                results.append(f"❌ {method_name}: Not found")

        # Test the demo file exists and compiles
        try:
            import verenigingen.tests.test_edge_case_testing_demo

            results.append("✅ Demo test file: Available and imports correctly")
        except ImportError as e:
            results.append(f"❌ Demo test file: Import error - {str(e)}")

        # Check documentation exists
        import os

        doc_path = "/home/frappe/frappe-bench/apps/verenigingen/docs/testing/edge-case-testing-guide.md"
        if os.path.exists(doc_path):
            with open(doc_path, "r") as f:
                doc_content = f.read()
            results.append(f"✅ Documentation: Available ({len(doc_content)} chars)")
        else:
            results.append("❌ Documentation: Missing")

        return {
            "edge_case_methods_ready": all(
                "✅" in r for r in results if any(method in r for method in methods_to_check)
            ),
            "summary": f"Added {len(methods_to_check)} new edge case testing methods to VereningingenTestCase",
            "results": results,
            "usage_example": {
                "pattern": "self.clear_member_auto_schedules(member.name) → self.create_controlled_dues_schedule(...) → test validation",
                "documentation": "See docs/testing/edge-case-testing-guide.md",
                "demo": "vereinigen.tests.test_edge_case_testing_demo",
            },
        }

    except Exception as e:
        return {
            "edge_case_methods_ready": False,
            "error": str(e),
            "results": [f"❌ Error testing new methods: {str(e)}"],
        }
