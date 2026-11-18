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
            fields=["name", "period_start_date", "fiscal_year", "company", "docstatus"],
            order_by="period_start_date desc"
        )
        
        return {
            "total_vouchers": len(vouchers),
            "vouchers": vouchers
        }
    except Exception as e:
        return {"error": str(e)}

def remove_period_closing_vouchers():
    """Cancel all submitted period closing vouchers.

    A cancelled voucher is deliberately NOT deleted (#1413): cancelling posts the
    reversing GL rows and keeps the voucher as the audit trail, whereas a force
    delete strands its ledger rows and frees the name for reuse by the next voucher.
    """
    try:
        # Get all period closing vouchers
        vouchers = frappe.get_all("Period Closing Voucher", pluck="name")
        
        cancelled_count = 0
        errors = []
        
        for voucher_name in vouchers:
            try:
                voucher = frappe.get_doc("Period Closing Voucher", voucher_name)
                if voucher.docstatus == 1:
                    voucher.cancel()
                    cancelled_count += 1
                    print(f"Cancelled voucher: {voucher_name}")
                
            except Exception as e:
                errors.append({"voucher": voucher_name, "error": str(e)})
                print(f"Error removing {voucher_name}: {str(e)}")
        
        # Commit the changes
        frappe.db.commit()
        
        return {
            "success": True,
            "cancelled_count": cancelled_count,
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
            print(f"  - {voucher['name']} ({voucher['period_start_date']}) - Status: {voucher['docstatus']}")
    
    if result.get('total_vouchers', 0) > 0:
        print("\nRemoving period closing vouchers...")
        removal_result = remove_period_closing_vouchers()
        
        if removal_result.get('success'):
            print(f"Successfully cancelled {removal_result['cancelled_count']} vouchers")
            if removal_result.get('errors'):
                print("Errors encountered:")
                for error in removal_result['errors']:
                    print(f"  - {error['voucher']}: {error['error']}")
        else:
            print(f"Failed to remove vouchers: {removal_result.get('error')}")
    else:
        print("No period closing vouchers found to remove")