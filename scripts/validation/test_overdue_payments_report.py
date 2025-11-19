#!/usr/bin/env python3
"""
Test script for Overdue Member Payments report fix
"""

import frappe
from frappe.utils import today


def test_overdue_payments_report():
    """Test the Overdue Member Payments report"""
    
    try:
        print("🔍 Testing Overdue Member Payments report...")
        
        # Import the report module
        from verenigingen.verenigingen.report.overdue_member_payments.overdue_member_payments import execute
        
        # Test with sample filters
        filters = {
            "from_date": "2025-04-20",
            "to_date": "2025-07-20"
        }
        
        print(f"   📅 Testing with filters: {filters}")
        
        # Execute the report
        result = execute(filters)
        
        # Validate result structure
        if isinstance(result, tuple) and len(result) >= 2:
            columns, data = result[:2]
            print(f"   ✅ Report executed successfully")
            print(f"   📊 Columns: {len(columns)}")
            print(f"   📋 Data rows: {len(data) if data else 0}")
            
            # Test without filters
            print("   🔄 Testing report without filters...")
            result_no_filters = execute()
            if isinstance(result_no_filters, tuple):
                print("   ✅ Report works without filters")
            else:
                print("   ❌ Report failed without filters")
                
            return True
        else:
            print("   ❌ Report returned unexpected result structure")
            return False
            
    except Exception as e:
        print(f"   ❌ Report test failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main test function"""
    try:
        frappe.init(site="dev.veganisme.net")
        frappe.connect()
        
        success = test_overdue_payments_report()
        
        if success:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print("\n❌ Tests failed!")
            return 1
            
    except Exception as e:
        print(f"❌ Test script failed: {str(e)}")
        return 1
    finally:
        if frappe.db:
            frappe.destroy()


if __name__ == "__main__":
    import sys
    sys.exit(main())