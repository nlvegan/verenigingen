#!/usr/bin/env python3

import frappe

@frappe.whitelist()
def test_invoice_auto_submit():
    """Test the auto-submission logic for draft invoice ACC-SINV-2025-20223"""
    
    invoice_name = "ACC-SINV-2025-20223"
    
    try:
        invoice = frappe.get_doc("Sales Invoice", invoice_name)
        print(f"Invoice: {invoice.name}")
        print(f"Customer: {invoice.customer}")
        print(f"Current docstatus: {invoice.docstatus}")
        print(f"Current status: {invoice.status}")
        print(f"Amount: €{invoice.grand_total}")
        
        # Check if it's a draft and submit it
        if invoice.docstatus == 0:
            print("\nSubmitting draft invoice...")
            invoice.submit()
            print(f"New docstatus: {invoice.docstatus}")
            print(f"New status: {invoice.status}")
            return {"success": True, "message": f"Invoice {invoice.name} submitted successfully"}
        else:
            print(f"\nInvoice is already submitted (docstatus: {invoice.docstatus})")
            return {"success": True, "message": f"Invoice {invoice.name} was already submitted"}
            
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return {"success": False, "error": str(e)}

@frappe.whitelist()
def test_member_payment_history():
    """Test payment history loading for member Assoc-Member-2025-07-0020"""
    
    member_id = "Assoc-Member-2025-07-0020"
    
    try:
        member = frappe.get_doc("Member", member_id)
        print(f"Member: {member.name}")
        print(f"Customer: {member.customer}")
        
        # Clear existing payment history
        member.payment_history = []
        
        # Load payment history using the updated method
        member.load_payment_history()
        
        print(f"\nPayment history entries: {len(member.payment_history)}")
        
        for entry in member.payment_history:
            print(f"\n--- Entry ---")
            print(f"Invoice: {entry.invoice}")
            print(f"Type: {entry.transaction_type}")
            print(f"Payment Status: {entry.payment_status}")
            print(f"Amount: €{entry.amount}")
            print(f"Outstanding: €{entry.outstanding_amount}")
            print(f"Date: {entry.posting_date}")
            
        return {"success": True, "entries": len(member.payment_history)}
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        return {"success": False, "error": str(e)}