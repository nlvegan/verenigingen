import frappe

from verenigingen.utils.secure_service_account import background_service_context
from verenigingen.utils.security.api_security_framework import OperationType, development_only_api


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_expense_query_fix():
    """Test that the expense claim query works without 'title' field"""
    try:
        expense_claims = frappe.get_all(
            "Expense Claim",
            fields=[
                "name",
                "employee_name",
                "total_claimed_amount",
                "status",
                "posting_date",
                "creation",
                "approval_status",
                "company",
                "cost_center",
            ],
            limit=2,
        )

        return {
            "success": True,
            "message": f"Query successful! Found {len(expense_claims)} expense claims",
            "sample_data": expense_claims[0] if expense_claims else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_employee_creation_only():
    """Test just the employee creation functionality without expense submission"""
    try:
        print("🧪 Testing Employee Creation for Volunteers")
        print("=" * 50)

        # Test 1: Find a volunteer without employee record
        print("\n1. Finding volunteer without employee record...")

        volunteers_without_employees = frappe.db.sql(
            """
            SELECT name, volunteer_name, email, employee_id
            FROM `tabVolunteer`
            WHERE employee_id IS NULL OR employee_id = ''
            LIMIT 3
        """,
            as_dict=True,
        )

        if not volunteers_without_employees:
            print("   No volunteers without employee records found")

            # Check existing volunteers with employees
            volunteers_with_employees = frappe.db.sql(
                """
                SELECT name, volunteer_name, email, employee_id
                FROM `tabVolunteer`
                WHERE employee_id IS NOT NULL AND employee_id != ''
                LIMIT 3
            """,
                as_dict=True,
            )

            if volunteers_with_employees:
                print("   Existing volunteers with employee records:")
                for vol in volunteers_with_employees:
                    print(f"   - {vol.volunteer_name} ({vol.name}) -> {vol.employee_id}")

                return {
                    "success": True,
                    "message": "Employee creation already working - existing volunteers have employee records",
                    "volunteers_with_employees": len(volunteers_with_employees),
                }
            else:
                return {"success": False, "message": "No volunteers found to test"}

        print(f"   Found {len(volunteers_without_employees)} volunteers without employee records")

        # Test 2: Try creating employee records for these volunteers
        created_employees = []
        failed_creations = []

        for volunteer_data in volunteers_without_employees:
            volunteer_doc = frappe.get_doc("Volunteer", volunteer_data.name)
            print(f"\n2. Testing employee creation for: {volunteer_doc.volunteer_name}")

            try:
                employee_id = volunteer_doc.create_minimal_employee()
                if employee_id:
                    created_employees.append(
                        {
                            "volunteer": volunteer_doc.name,
                            "volunteer_name": volunteer_doc.volunteer_name,
                            "employee_id": employee_id,
                        }
                    )
                    print(f"   ✅ Created employee: {employee_id}")

                    # Verify employee record exists
                    employee_exists = frappe.db.exists("Employee", employee_id)
                    if employee_exists:
                        employee_doc = frappe.get_doc("Employee", employee_id)
                        print(f"   ✅ Employee record verified: {employee_doc.employee_name}")
                        print(f"   - Company: {employee_doc.company}")
                        print(f"   - Status: {employee_doc.status}")
                        print(f"   - Gender: {employee_doc.gender}")
                        print(f"   - Date of Birth: {employee_doc.date_of_birth}")
                    else:
                        print("   ⚠️ Employee ID returned but record not found in database")
                else:
                    failed_creations.append(
                        {
                            "volunteer": volunteer_doc.name,
                            "volunteer_name": volunteer_doc.volunteer_name,
                            "error": "Employee creation returned None",
                        }
                    )
                    print("   ❌ Employee creation returned None")

            except Exception as e:
                failed_creations.append(
                    {
                        "volunteer": volunteer_doc.name,
                        "volunteer_name": volunteer_doc.volunteer_name,
                        "error": str(e),
                    }
                )
                print(f"   ❌ Employee creation failed: {str(e)}")

        # Test 3: Summary
        print("\n3. Employee Creation Test Summary:")
        print(f"   - Volunteers tested: {len(volunteers_without_employees)}")
        print(f"   - Successful creations: {len(created_employees)}")
        print(f"   - Failed creations: {len(failed_creations)}")

        if created_employees:
            print("\n   ✅ Successfully created employees:")
            for emp in created_employees:
                print(f'   - {emp["volunteer_name"]} -> {emp["employee_id"]}')

        if failed_creations:
            print("\n   ❌ Failed employee creations:")
            for fail in failed_creations:
                print(f'   - {fail["volunteer_name"]}: {fail["error"]}')

        success = len(created_employees) > 0

        return {
            "success": success,
            "message": f"Employee creation test completed. {len(created_employees)} successful, {len(failed_creations)} failed.",
            "created_employees": created_employees,
            "failed_creations": failed_creations,
            "total_tested": len(volunteers_without_employees),
        }

    except Exception as e:
        print(f"\n❌ Employee creation test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "message": f"Test failed with error: {str(e)}"}
    finally:
        # Commit changes to see test results
        frappe.db.commit()


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_expense_integration():
    """Test ERPNext Expense Claim integration with HRMS"""
    try:
        print("🧪 Testing ERPNext Expense Claim Integration with HRMS")
        print("=" * 60)

        # Test 1: Verify HRMS is installed and Expense Claims are available
        print("\n1. Checking HRMS and Expense Claim availability...")

        # Check if HRMS is installed by checking if Expense Claim doctype exists
        try:
            hrms_installed = "hrms" in frappe.get_installed_apps()
        except Exception:
            hrms_installed = False
        print(f"   HRMS installed: {hrms_installed}")

        # Check if Expense Claim doctype exists
        expense_claim_exists = frappe.db.exists("DocType", "Expense Claim")
        print(f"   Expense Claim doctype exists: {expense_claim_exists}")

        # Check if Expense Claim Type exists
        expense_claim_type_exists = frappe.db.exists("DocType", "Expense Claim Type")
        print(f"   Expense Claim Type doctype exists: {expense_claim_type_exists}")

        if not all([expense_claim_exists, expense_claim_type_exists]):
            return {
                "success": False,
                "message": "ERPNext Expense Claims not available - HRMS may not be installed",
            }

        print("✅ HRMS integration requirements satisfied")

        # Test 2: Find or create test volunteer
        print("\n2. Finding or creating test volunteer...")

        # First check for any existing volunteer
        volunteers = frappe.get_all("Volunteer", fields=["name", "volunteer_name", "email"], limit=1)
        if volunteers:
            volunteer = volunteers[0]["name"]
            volunteer_name = volunteers[0]["volunteer_name"]
            print(f"   Using existing volunteer: {volunteer_name} ({volunteer})")
        else:
            # Find Foppe's member record to create volunteer
            member = frappe.db.get_value("Member", {"email": "foppe@veganisme.org"}, "name")
            if member:
                # Create volunteer record for Foppe
                member_doc = frappe.get_doc("Member", member)
                volunteer_doc = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": f"{member_doc.first_name} {member_doc.last_name}",
                        "email": member_doc.email,
                        "member": member,
                        "status": "Active",
                        "start_date": frappe.utils.today(),
                    }
                )

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                volunteer_result = secure_document_operation(
                    operation="insert",
                    doc=volunteer_doc,
                    justification=f"Create volunteer profile for member {member_doc.first_name} {member_doc.last_name} ({member}) for expense testing",
                    required_permissions=["Volunteer:create"],
                )

                if not volunteer_result.success:
                    frappe.logger().error(
                        f"Failed to create volunteer for member {member}: {'; '.join(volunteer_result.errors)}"
                    )
                    return {
                        "success": False,
                        "message": f"Volunteer creation failed: {volunteer_result.errors[0] if volunteer_result.errors else 'Unknown error'}",
                    }
                volunteer = volunteer_doc.name
                volunteer_name = volunteer_doc.volunteer_name
                print(f"   Created new volunteer: {volunteer_name} ({volunteer})")
            else:
                # Create a simple test volunteer without member link
                volunteer_doc = frappe.get_doc(
                    {
                        "doctype": "Volunteer",
                        "volunteer_name": "Test Volunteer",
                        "email": "test@example.com",
                        "status": "Active",
                        "start_date": frappe.utils.today(),
                    }
                )

                # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
                volunteer_result = secure_document_operation(
                    operation="insert",
                    doc=volunteer_doc,
                    justification="Create test volunteer profile for expense claim testing purposes",
                    required_permissions=["Volunteer:create"],
                )

                if not volunteer_result.success:
                    frappe.logger().error(
                        f"Failed to create test volunteer: {'; '.join(volunteer_result.errors)}"
                    )
                    return {
                        "success": False,
                        "message": f"Test volunteer creation failed: {volunteer_result.errors[0] if volunteer_result.errors else 'Unknown error'}",
                    }
                volunteer = volunteer_doc.name
                volunteer_name = volunteer_doc.volunteer_name
                print(f"   Created test volunteer: {volunteer_name} ({volunteer})")

        if not volunteer:
            return {"success": False, "message": "No volunteer found or could be created for testing"}

        print(f"   Using volunteer: {volunteer}")

        # Check if volunteer has an employee record
        volunteer_doc = frappe.get_doc("Volunteer", volunteer)
        print(f'   Employee ID: {volunteer_doc.employee_id or "None - will be created"}')

        # Set up expense claim types with accounts first
        print("\n   Setting up expense claim types with accounts...")
        test_category = setup_expense_claim_types()
        print(f"   Using expense type: {test_category}")

        # Test expense data
        expense_data = {
            "description": "Test ERPNext Integration - Office Supplies",
            "amount": 25.50,
            "expense_date": "2024-12-14",
            "organization_type": "National",
            "category": test_category,  # Use working expense type
            "notes": "Testing HRMS integration with ERPNext Expense Claims",
        }

        print(f'   Test expense: {expense_data["description"]} - €{expense_data["amount"]}')

        # Set up session context
        original_user = frappe.session.user
        frappe.session.user = volunteer_doc.email if volunteer_doc.email else "test@example.com"

        try:
            # Submit the expense
            result = submit_expense(expense_data)

            print("\n3. Expense submission result:")
            print(f'   Success: {result.get("success")}')
            print(f'   Message: {result.get("message")}')
            if result.get("expense_claim_name"):
                print(f'   ERPNext Expense Claim: {result.get("expense_claim_name")}')
            if result.get("expense_name"):
                print(f'   Volunteer Expense: {result.get("expense_name")}')
            if result.get("employee_created"):
                print(f'   Employee created: {result.get("employee_created")}')

            if result.get("success"):
                print("\n✅ Expense submission test PASSED")

                # Test 3: Verify records were created
                print("\n4. Verifying created records...")

                if result.get("expense_claim_name"):
                    expense_claim = frappe.get_doc("Expense Claim", result.get("expense_claim_name"))
                    print(f"   ERPNext Expense Claim status: {expense_claim.status}")
                    print(f"   Total claimed amount: {expense_claim.total_claimed_amount}")
                    print(f"   Employee: {expense_claim.employee}")

                if result.get("expense_name"):
                    volunteer_expense = frappe.get_doc("Volunteer Expense", result.get("expense_name"))
                    print(f"   Volunteer Expense status: {volunteer_expense.status}")
                    print(f"   Linked expense claim: {volunteer_expense.expense_claim_id}")

                print("\n✅ ERPNext Expense Claim integration test COMPLETED SUCCESSFULLY")
                return {
                    "success": True,
                    "message": "ERPNext integration test completed successfully",
                    "expense_claim_name": result.get("expense_claim_name"),
                    "expense_name": result.get("expense_name"),
                    "employee_created": result.get("employee_created"),
                }
            else:
                print("\n❌ Expense submission test FAILED")
                print(f'Error: {result.get("message")}')
                return {"success": False, "message": f'Expense submission failed: {result.get("message")}'}

        finally:
            frappe.session.user = original_user

    except Exception as e:
        print(f"\n❌ Test failed with error: {str(e)}")
        import traceback

        traceback.print_exc()
        return {"success": False, "message": f"Test failed with error: {str(e)}"}
    finally:
        # Commit changes to see test results
        frappe.db.commit()


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def test_expense_form_with_foppe():
    """Test expense form APIs with Foppe de Haan's account"""

    print("🚀 TESTING EXPENSE FORM WITH FOPPE DE HAAN")
    print("=" * 60)

    # Check if Foppe exists
    foppe_member = frappe.db.get_value(
        "Member", {"email": "foppe@veganisme.org"}, ["name", "first_name", "last_name"], as_dict=True
    )

    if not foppe_member:
        print("❌ Foppe de Haan not found in Member records")
        return {"success": False, "error": "Foppe de Haan not found"}

    print(f"✅ Found Foppe: {foppe_member.first_name} {foppe_member.last_name}")

    # Check if Foppe has a volunteer record
    foppe_volunteer = frappe.db.get_value(
        "Volunteer",
        {"member": foppe_member.name},
        ["name", "volunteer_name", "email"],
        as_dict=True,
    )

    if not foppe_volunteer:
        print("❌ No volunteer record found for Foppe")
        # Create volunteer record for Foppe
        try:
            volunteer_doc = frappe.get_doc(
                {
                    "doctype": "Volunteer",
                    "volunteer_name": f"{foppe_member.first_name} {foppe_member.last_name}",
                    "email": "foppe@veganisme.org",
                    "member": foppe_member.name,
                    "status": "Active",
                    "start_date": frappe.utils.today(),
                }
            )
            # Use secure service account for test data creation
            with background_service_context("Create test volunteer record for expense testing"):
                volunteer_doc.insert()
            foppe_volunteer = {
                "name": volunteer_doc.name,
                "volunteer_name": volunteer_doc.volunteer_name,
                "email": volunteer_doc.email,
            }
            print(f"✅ Created volunteer record for Foppe: {foppe_volunteer['name']}")
        except Exception as e:
            print(f"❌ Failed to create volunteer record: {e}")
            return {"success": False, "error": f"Failed to create volunteer: {e}"}
    else:
        print(f"✅ Found volunteer record: {foppe_volunteer.volunteer_name}")

    # Store original user
    original_user = frappe.session.user

    try:
        # Switch to Foppe's session
        frappe.session.user = "foppe@veganisme.org"
        print(f"🔄 Switched to user: {frappe.session.user}")

        # Test 1: Get volunteer expense context
        print("\n1. Testing get_volunteer_expense_context with Foppe")
        try:
            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.get_volunteer_expense_context"
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: API returns successful response")
                    print(f"   Volunteer: {response.get('volunteer')}")
                    print(f"   User chapters: {len(response.get('user_chapters', []))}")
                    print(f"   User teams: {len(response.get('user_teams', []))}")
                    print(f"   Expense categories: {len(response.get('expense_categories', []))}")
                    print(f"   Available categories: {response.get('expense_categories', [])}")
                    context_success = True
                    # Store available categories for test
                    available_categories = response.get("expense_categories", [])
                else:
                    print("❌ FAIL: API returns failure response")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    context_success = False
                    available_categories = []
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                context_success = False
                available_categories = []

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            context_success = False
            available_categories = []

        # Test 2: Submit multiple expenses with Foppe
        print("\n2. Testing submit_multiple_expenses with Foppe")
        try:
            # Use the first available category if any
            test_category = available_categories[0] if available_categories else "Travel"
            print(f"   Using category: {test_category}")

            test_expenses = [
                {
                    "description": "Test expense - Office supplies",
                    "amount": 25.50,
                    "expense_date": "2025-01-10",
                    "organization_type": "Team",
                    "category": test_category,
                    "chapter": None,
                    "team": "IT",  # Try with IT team
                    "notes": "Test expense submission via API",
                    "receipt_attachment": None,
                }
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=test_expenses,
            )

            if response and isinstance(response, dict):
                if response.get("success"):
                    print("✅ PASS: Expenses submitted successfully")
                    print(f"   Created count: {response.get('created_count', 0)}")
                    print(f"   Total amount: €{response.get('total_amount', 0)}")
                    submit_success = True
                else:
                    print("❌ FAIL: Failed to submit expenses")
                    print(f"   Error: {response.get('message', 'Unknown error')}")
                    print(f"   Full response: {response}")
                    submit_success = False
            else:
                print("❌ FAIL: Invalid response format")
                print(f"   Response: {response}")
                submit_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            submit_success = False

        # Test 3: Test validation with invalid data
        print("\n3. Testing form validation with invalid data")
        try:
            invalid_expenses = [
                {
                    "description": "",  # Empty description
                    "amount": 0,  # Zero amount
                    "expense_date": "",  # Empty date
                    "organization_type": "",
                    "category": "",
                    "chapter": None,
                    "team": None,
                    "notes": "",
                    "receipt_attachment": None,
                }
            ]

            response = frappe.call(
                "verenigingen.templates.pages.volunteer.expenses.submit_multiple_expenses",
                expenses=invalid_expenses,
            )

            if response and isinstance(response, dict):
                if not response.get("success"):
                    print("✅ PASS: Form validation correctly rejects invalid data")
                    print(f"   Error: {response.get('message', 'Validation error')}")
                    validation_success = True
                else:
                    print("❌ FAIL: Form validation should reject invalid data")
                    validation_success = False
            else:
                print("❌ FAIL: Invalid response format")
                validation_success = False

        except Exception as e:
            print(f"❌ FAIL: Exception occurred: {e}")
            validation_success = False

    finally:
        # Restore original user
        frappe.session.user = original_user
        print(f"🔄 Restored user: {frappe.session.user}")

    # Summary
    print("\n" + "=" * 50)
    print("📊 EXPENSE FORM TEST SUMMARY (FOPPE)")
    print("=" * 50)

    tests_passed = sum([context_success, submit_success, validation_success])
    total_tests = 3

    print(f"Tests Passed: {tests_passed}/{total_tests}")

    if tests_passed == total_tests:
        print("🎉 ALL TESTS PASSED! Expense form works with Foppe's account.")
        success = True
    else:
        print("⚠️  Some tests failed. Check the details above.")
        success = False

    print(f"Test completed at: {frappe.utils.now_datetime()}")

    return {
        "success": success,
        "tests_passed": tests_passed,
        "total_tests": total_tests,
        "foppe_member": foppe_member.name if foppe_member else None,
        "foppe_volunteer": foppe_volunteer["name"] if foppe_volunteer else None,
    }


def debug_volunteer_access():
    """Debug function to help administrators troubleshoot volunteer access issues"""
    # Security check: Only allow debug functions in development or for System Managers
    if not frappe.conf.get("developer_mode") and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Debug functions are only available in development mode or for System Managers"))

    if not frappe.has_permission("Volunteer", "read"):
        frappe.throw(_("Insufficient permissions to debug volunteer access"))

    user_email = frappe.session.user
    result = {"user_email": user_email, "timestamp": frappe.utils.now()}

    # Check Member record
    member = frappe.db.get_value(
        "Member", {"email": user_email}, ["name", "first_name", "last_name"], as_dict=True
    )
    result["member"] = member

    if member:
        # Check for linked Volunteer
        volunteer = frappe.db.get_value(
            "Volunteer",
            {"member": member.name},
            ["name", "volunteer_name", "status"],
            as_dict=True,
        )
        result["volunteer_via_member"] = volunteer

    # Check direct Volunteer record
    volunteer_direct = frappe.db.get_value(
        "Volunteer",
        {"email": user_email},
        ["name", "volunteer_name", "member", "status"],
        as_dict=True,
    )
    result["volunteer_direct"] = volunteer_direct

    return result


@frappe.whitelist()
@development_only_api(operation_type=OperationType.UTILITY)
def debug_request_info():
    """Debug function to check what's available in the request without file upload"""
    try:
        debug_info = {
            "method": frappe.request.method if hasattr(frappe, "request") else None,
            "content_type": frappe.request.content_type if hasattr(frappe, "request") else None,
            "form_dict_keys": list(frappe.form_dict.keys()) if hasattr(frappe, "form_dict") else [],
            "form_dict_content": dict(frappe.form_dict) if hasattr(frappe, "form_dict") else {},
            "request_files_keys": list(frappe.request.files.keys())
            if hasattr(frappe, "request") and hasattr(frappe.request, "files")
            else [],
            "request_exists": hasattr(frappe, "request"),
            "session_user": frappe.session.user,
            "local_uploaded_files": getattr(frappe.local, "uploaded_files", None),
        }
        return {"success": True, "debug_info": debug_info}
    except Exception as e:
        import traceback

        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}
