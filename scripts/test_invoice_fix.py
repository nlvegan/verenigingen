#!/usr/bin/env python3

import frappe

def test_invoice_visibility():
    """Test the invoice visibility fixes for member Assoc-Member-2025-07-0020"""
    
    member_id = "Assoc-Member-2025-07-0020"
    
    try:
        member = frappe.get_doc("Member", member_id)
        print(f"Testing invoice visibility for member: {member.name}")
        print(f"Customer: {member.customer}")
        
        if not member.customer:
            print("ERROR: Member has no linked customer")
            return False
            
        # Check raw invoice data from database
        print("\n=== Raw Invoice Query ===")
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"customer": member.customer},
            fields=["name", "docstatus", "status", "grand_total", "outstanding_amount", "posting_date"]
        )
        
        print(f"Found {len(invoices)} total invoices:")
        for inv in invoices:
            docstatus_name = ["Draft", "Submitted", "Cancelled"][inv.docstatus]
            print(f"  - {inv.name}: {docstatus_name} ({inv.docstatus}), Status: {inv.status}, Amount: €{inv.grand_total}")
        
        # Test with new filter logic (includes drafts)
        print("\n=== New Filter Logic (includes drafts) ===")
        invoices_new = frappe.get_all(
            "Sales Invoice", 
            filters={"customer": member.customer, "docstatus": ["in", [0, 1]]},
            fields=["name", "docstatus", "status", "grand_total", "outstanding_amount", "posting_date"]
        )
        
        print(f"Found {len(invoices_new)} invoices with new filter:")
        for inv in invoices_new:
            docstatus_name = ["Draft", "Submitted", "Cancelled"][inv.docstatus]
            print(f"  - {inv.name}: {docstatus_name} ({inv.docstatus}), Status: {inv.status}, Amount: €{inv.grand_total}")
        
        # Test payment history loading
        print("\n=== Testing Payment History Loading ===")
        member.load_payment_history()
        print(f"Payment history entries: {len(member.payment_history)}")
        
        for entry in member.payment_history:
            print(f"  - Invoice: {entry.invoice or 'None'}")
            print(f"    Type: {entry.transaction_type}")  
            print(f"    Status: {entry.payment_status}")
            print(f"    Amount: €{entry.amount}")
            print(f"    Outstanding: €{entry.outstanding_amount}")
            print()
            
        return True
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return False

if __name__ == "__main__":
    test_invoice_visibility()