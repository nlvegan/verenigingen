#!/usr/bin/env python3
"""
Remove Period Closing Vouchers
"""

import frappe

@frappe.whitelist()
def check_period_closing_vouchers():
    """Check existing period closing vouchers"""
    try:
        vouchers = frappe.get_all(
            "Period Closing Voucher",
            fields=["name", "posting_date", "fiscal_year", "company", "docstatus"],
            order_by="posting_date desc"
        )
        
        return {
            "total_vouchers": len(vouchers),
            "vouchers": vouchers
        }
    except Exception as e:
        return {"error": str(e)}

@frappe.whitelist()
def remove_period_closing_vouchers():
    """Remove all period closing vouchers"""
    try:
        # Get all period closing vouchers
        vouchers = frappe.get_all("Period Closing Voucher", pluck="name")
        
        removed_count = 0
        errors = []
        
        for voucher_name in vouchers:
            try:
                # Cancel if submitted
                voucher = frappe.get_doc("Period Closing Voucher", voucher_name)
                if voucher.docstatus == 1:
                    voucher.cancel()
                    print(f"Cancelled voucher: {voucher_name}")
                
                # Delete the voucher
                frappe.delete_doc("Period Closing Voucher", voucher_name, force=True)
                removed_count += 1
                print(f"Deleted voucher: {voucher_name}")
                
            except Exception as e:
                errors.append({"voucher": voucher_name, "error": str(e)})
                print(f"Error removing {voucher_name}: {str(e)}")
        
        # Commit the changes
        frappe.db.commit()
        
        return {
            "success": True,
            "removed_count": removed_count,
            "total_vouchers": len(vouchers),
            "errors": errors
        }
        
    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    print("Checking period closing vouchers...")
    result = check_period_closing_vouchers()
    print(f"Found {result.get('total_vouchers', 0)} period closing vouchers")
    
    if result.get('vouchers'):
        for voucher in result['vouchers']:
            print(f"  - {voucher['name']} ({voucher['posting_date']}) - Status: {voucher['docstatus']}")
    
    if result.get('total_vouchers', 0) > 0:
        print("\nRemoving period closing vouchers...")
        removal_result = remove_period_closing_vouchers()
        
        if removal_result.get('success'):
            print(f"Successfully removed {removal_result['removed_count']} vouchers")
            if removal_result.get('errors'):
                print("Errors encountered:")
                for error in removal_result['errors']:
                    print(f"  - {error['voucher']}: {error['error']}")
        else:
            print(f"Failed to remove vouchers: {removal_result.get('error')}")
    else:
        print("No period closing vouchers found to remove")