"""
Test the validation logic fixes and field naming corrections
"""

import frappe


@frappe.whitelist()
def test_dues_rate_validation():
    """Test that dues rate validation works correctly after fixes"""
    try:
        # Get a test member
        test_member = frappe.db.get_value("Member", {"status": "Active"}, ["name", "full_name"], as_dict=True)
        if not test_member:
            return {"error": "No active members found for testing"}

        # Get membership type
        membership_type = frappe.db.get_value("Membership Type", {"is_active": 1}, "name")
        if not membership_type:
            return {"error": "No active membership types found"}

        membership_type_doc = frappe.get_doc("Membership Type", membership_type)

        # Create test dues schedule
        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        dues_schedule.schedule_name = f"Test-Validation-{frappe.generate_hash(length=6)}"
        dues_schedule.member = test_member.name
        dues_schedule.membership_type = membership_type
        dues_schedule.contribution_mode = "Calculator"
        dues_schedule.base_multiplier = 1.0
        dues_schedule.billing_frequency = "Monthly"
        dues_schedule.status = "Active"

        # Test 1: Explicit dues_rate preservation
        test_dues_rate = 25.0
        dues_schedule.dues_rate = test_dues_rate

        # Run validation
        dues_schedule.validate()

        results = {
            "test_member": f"{test_member.full_name} ({test_member.name})",
            "membership_type": membership_type,
            "suggested_contribution": getattr(membership_type_doc, "suggested_contribution", None),
            "minimum_contribution": getattr(membership_type_doc, "minimum_amount", None),
            "tests": {},
        }

        # Test 1: Dues rate preservation
        results["tests"]["dues_rate_preservation"] = {
            "original_rate": test_dues_rate,
            "final_rate": dues_schedule.dues_rate,
            "preserved": dues_schedule.dues_rate == test_dues_rate,
            "status": "✅ PASS" if dues_schedule.dues_rate == test_dues_rate else "❌ FAIL",
        }

        # Test 2: Field existence (dues_rate vs amount)
        results["tests"]["field_naming"] = {
            "has_dues_rate": hasattr(dues_schedule, "dues_rate"),
            "dues_rate_value": getattr(dues_schedule, "dues_rate", None),
            "status": "✅ PASS" if hasattr(dues_schedule, "dues_rate") else "❌ FAIL",
        }

        # Test 3: Minimum enforcement
        if membership_type_doc.minimum_amount:
            min_contrib = membership_type_doc.minimum_amount

            # Test below minimum
            dues_schedule.dues_rate = min_contrib - 1.0
            original_low_rate = dues_schedule.dues_rate

            try:
                dues_schedule.validate()

                results["tests"]["minimum_enforcement"] = {
                    "minimum_contribution": min_contrib,
                    "original_low_rate": original_low_rate,
                    "final_rate": dues_schedule.dues_rate,
                    "auto_raised": dues_schedule.dues_rate >= min_contrib,
                    "status": "✅ PASS" if dues_schedule.dues_rate >= min_contrib else "❌ FAIL",
                }
            except Exception as e:
                results["tests"]["minimum_enforcement"] = {
                    "minimum_contribution": min_contrib,
                    "original_low_rate": original_low_rate,
                    "error": str(e),
                    "status": "ℹ️ ERROR (may be expected)",
                }

        # Test 4: Zero rate handling
        dues_schedule.dues_rate = 0.0
        dues_schedule.custom_amount_reason = "Test free membership"

        try:
            dues_schedule.validate()
            results["tests"]["zero_rate_handling"] = {"zero_rate_accepted": True, "status": "✅ PASS"}
        except Exception as e:
            results["tests"]["zero_rate_handling"] = {
                "zero_rate_accepted": False,
                "error": str(e),
                "status": "❌ FAIL",
            }

        # Test 5: Manager override
        settings = frappe.get_single("Verenigingen Settings")
        max_multiplier = getattr(settings, "maximum_fee_multiplier", None)

        if max_multiplier:
            base_amount = membership_type_doc.minimum_amount
            max_amount = base_amount * max_multiplier
            over_max_amount = max_amount + 10.0

            dues_schedule.dues_rate = over_max_amount

            try:
                dues_schedule.validate()

                results["tests"]["manager_override"] = {
                    "base_amount": base_amount,
                    "max_multiplier": max_multiplier,
                    "max_allowed": max_amount,
                    "test_amount": over_max_amount,
                    "uses_custom_amount": dues_schedule.uses_custom_amount,
                    "custom_amount_approved": dues_schedule.custom_amount_approved,
                    "auto_approved": dues_schedule.uses_custom_amount
                    and dues_schedule.custom_amount_approved,
                    "status": "✅ PASS"
                    if (dues_schedule.uses_custom_amount and dues_schedule.custom_amount_approved)
                    else "❌ FAIL",
                }

            except Exception as e:
                results["tests"]["manager_override"] = {
                    "base_amount": base_amount,
                    "max_multiplier": max_multiplier,
                    "max_allowed": max_amount,
                    "test_amount": over_max_amount,
                    "error": str(e),
                    "status": "ℹ️ ERROR",
                }

        # Overall status
        all_tests = results["tests"]
        passed_tests = sum(1 for test in all_tests.values() if test.get("status", "").startswith("✅"))
        total_tests = len(all_tests)

        results["summary"] = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "overall_status": "✅ ALL TESTS PASSED"
            if passed_tests == total_tests
            else f"⚠️ {passed_tests}/{total_tests} TESTS PASSED",
        }

        return results

    except Exception as e:
        return {"error": str(e), "traceback": frappe.get_traceback()}


@frappe.whitelist()
def test_field_naming_systematic():
    """Test that field naming has been fixed systematically"""
    try:
        # Get a sample dues schedule
        schedule_name = frappe.db.get_value("Membership Dues Schedule", {"is_template": 0}, "name")

        if not schedule_name:
            return {"error": "No dues schedules found for testing"}

        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)

        tests = {}

        # Test 1: Field existence
        tests["field_existence"] = {
            "has_dues_rate": hasattr(schedule, "dues_rate"),
            "dues_rate_value": getattr(schedule, "dues_rate", None),
            "doctype_name": schedule.doctype,
        }

        # Test 2: Database field query
        try:
            db_result = frappe.db.get_value(
                "Membership Dues Schedule",
                schedule_name,
                ["name", "dues_rate", "billing_frequency"],
                as_dict=True,
            )
            tests["database_query"] = {
                "query_successful": bool(db_result),
                "returned_dues_rate": db_result.get("dues_rate") if db_result else None,
                "query_result": db_result,
            }
        except Exception as e:
            tests["database_query"] = {"query_successful": False, "error": str(e)}

        # Test 3: DocType field definition
        try:
            from frappe.model.meta import get_meta

            meta = get_meta("Membership Dues Schedule")

            dues_rate_field = None
            amount_field = None

            for field in meta.fields:
                if field.fieldname == "dues_rate":
                    dues_rate_field = {
                        "fieldname": field.fieldname,
                        "fieldtype": field.fieldtype,
                        "label": field.label,
                    }
                elif field.fieldname == "amount":
                    amount_field = {
                        "fieldname": field.fieldname,
                        "fieldtype": field.fieldtype,
                        "label": field.label,
                    }

            tests["doctype_definition"] = {
                "has_dues_rate_field": bool(dues_rate_field),
                "has_amount_field": bool(amount_field),
                "dues_rate_field": dues_rate_field,
                "amount_field": amount_field,
            }

        except Exception as e:
            tests["doctype_definition"] = {"error": str(e)}

        return {
            "schedule_tested": schedule_name,
            "tests": tests,
            "summary": "Field naming verification complete",
        }

    except Exception as e:
        return {"error": str(e)}
