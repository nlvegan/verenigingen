"""
Debug donation system functionality
"""
import frappe
from frappe.utils import flt


def test_donation_creation():
    """Test donation creation with detailed error reporting"""
    print("=" * 60)
    print("DEBUGGING DONATION CREATION")
    print("=" * 60)

    try:
        # Import secure operations
        from verenigingen.utils.secure_operations import secure_document_operation

        print("✓ Secure operations imported successfully")

        # Test donor creation
        print("\n1. Testing donor creation...")

        # Clean up any existing test donor
        existing = frappe.db.get_value("Donor", {"donor_email": "debug@example.com"})
        if existing:
            frappe.delete_doc("Donor", existing, force=True)
            print("  - Cleaned up existing test donor")

        donor_doc = frappe.new_doc("Donor")
        donor_doc.update(
            {
                "donor_name": "Debug Test Donor",
                "donor_email": "debug@example.com",
                "donor_type": "Individual",
                "contact_person": "Debug Test Donor",
                "donor_category": "Regular Donor",
            }
        )

        donor_result = secure_document_operation(
            operation="insert",
            doc=donor_doc,
            justification="Debug test donor creation",
            required_permissions=["Donor:create"],
        )

        if donor_result.success:
            print(f"✓ Donor created: {donor_doc.name}")
        else:
            print(f"✗ Donor creation failed:")
            for error in donor_result.errors:
                print(f"    - {error}")
            return False

        # Test donation creation
        print("\n2. Testing donation creation...")

        settings = frappe.get_single("Verenigingen Settings")
        company = settings.donation_company or frappe.get_list("Company", limit=1)[0].name

        donation_doc = frappe.new_doc("Donation")
        donation_doc.update(
            {
                "company": company,
                "donor": donor_doc.name,
                "donation_date": frappe.utils.today(),
                "amount": 75.0,
                "donation_type": "General",
                "mode_of_payment": "Bank Transfer",
                "status": "One-time",
                "donation_purpose_type": "General",
                "donation_notes": "Debug test donation",
                "paid": 0,
            }
        )

        # Check required fields
        print(f"  - Company: {donation_doc.company}")
        print(f"  - Donor: {donation_doc.donor}")
        print(f"  - Amount: {donation_doc.amount}")
        print(f"  - Date: {donation_doc.donation_date}")

        donation_result = secure_document_operation(
            operation="insert",
            doc=donation_doc,
            justification="Debug test donation creation",
            required_permissions=["Donation:create"],
        )

        if donation_result.success:
            print(f"✓ Donation created: {donation_doc.name}")

            # Test submission
            print("\n3. Testing donation submission...")
            submit_result = secure_document_operation(
                operation="submit",
                doc=donation_doc,
                justification="Debug test donation submission",
                required_permissions=["Donation:submit"],
            )

            if submit_result.success:
                print(f"✓ Donation submitted: {donation_doc.name}")
                print(f"  - Status: {donation_doc.docstatus}")
                return True
            else:
                print(f"✗ Donation submission failed:")
                for error in submit_result.errors:
                    print(f"    - {error}")
                return False
        else:
            print(f"✗ Donation creation failed:")
            for error in donation_result.errors:
                print(f"    - {error}")

            # Try to see what permissions are available
            print("\n  Available permissions:")
            try:
                permissions = frappe.get_all(
                    "Has Role", filters={"parent": frappe.session.user}, fields=["role"]
                )
                for perm in permissions[:5]:  # Show first 5
                    print(f"    - Role: {perm.role}")
            except:
                print("    - Could not fetch permissions")

            return False

    except Exception as e:
        print(f"\n✗ Exception occurred: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def test_form_submission():
    """Test the actual form submission function"""
    print("\n" + "=" * 60)
    print("TESTING FORM SUBMISSION")
    print("=" * 60)

    try:
        from verenigingen.templates.pages.donate import submit_donation

        form_data = {
            "donor_name": "Form Test Donor",
            "donor_email": "formtest@example.com",
            "amount": "100.0",
            "donation_type": "General",
            "donation_status": "One-time",
            "payment_method": "Bank Transfer",
            "donation_purpose_type": "General",
            "donation_notes": "Form submission test",
        }

        print("Submitting donation form with data:")
        for key, value in form_data.items():
            print(f"  - {key}: {value}")

        result = submit_donation(**form_data)

        if result.get("success"):
            print(f"✓ Form submission successful:")
            print(f"  - Donation ID: {result.get('donation_id')}")
            print(f"  - Message: {result.get('message')}")
            return True
        else:
            print(f"✗ Form submission failed:")
            print(f"  - Message: {result.get('message')}")
            print(f"  - Debug error: {result.get('debug_error')}")
            return False

    except Exception as e:
        print(f"✗ Form submission exception: {str(e)}")
        import traceback

        traceback.print_exc()
        return False


def run_all_tests():
    """Run all debug tests"""
    print("Running donation system debug tests...")

    # Test 1: Direct donation creation
    test1_result = test_donation_creation()

    # Test 2: Form submission
    test2_result = test_form_submission()

    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Direct donation creation: {'PASS' if test1_result else 'FAIL'}")
    print(f"Form submission test: {'PASS' if test2_result else 'FAIL'}")

    if test1_result and test2_result:
        print("✓ All tests passed - donation system is working")
    else:
        print("✗ Some tests failed - issues need to be resolved")

    return test1_result and test2_result
