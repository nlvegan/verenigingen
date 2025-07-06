#!/usr/bin/env python3

import frappe

def direct_cleanup_eboekhouden():
    """
    Direct SQL cleanup of all e-Boekhouden imported data
    """
    
    # Get default company
    company = frappe.defaults.get_user_default("Company")
    if not company:
        company = frappe.get_all("Company", limit=1, pluck="name")[0]
    
    results = {}
    
    try:
        # Disable foreign key checks
        frappe.db.sql("SET FOREIGN_KEY_CHECKS = 0")
        
        # Get all e-Boekhouden journal entries
        journal_entries = frappe.db.sql("""
            SELECT name FROM `tabJournal Entry` 
            WHERE company = %s 
            AND (user_remark LIKE '%%E-Boekhouden REST Import%%' 
                 OR user_remark LIKE '%%Migrated from e-Boekhouden%%')
        """, company, as_dict=True)
        
        print(f"Found {len(journal_entries)} journal entries to delete")
        
        # Delete all linked records in batches
        batch_size = 100
        deleted_count = 0
        
        for i in range(0, len(journal_entries), batch_size):
            batch = journal_entries[i:i+batch_size]
            je_names = [je.name for je in batch]
            
            # Create placeholders for SQL IN clause
            placeholders = ','.join(['%s'] * len(je_names))
            
            # Delete all linked records for this batch
            frappe.db.sql(f"DELETE FROM `tabRepost Accounting Ledger Items` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabRepost Accounting Ledger` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabRepost Payment Ledger Items` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabRepost Payment Ledger` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabPayment Ledger Entry` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabGL Entry` WHERE voucher_no IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabJournal Entry Account` WHERE parent IN ({placeholders})", je_names)
            frappe.db.sql(f"DELETE FROM `tabJournal Entry` WHERE name IN ({placeholders})", je_names)
            
            deleted_count += len(batch)
            print(f"Deleted {deleted_count}/{len(journal_entries)} journal entries")
        
        results["journal_entries_deleted"] = deleted_count
        
        # Clean up orphaned GL Entries
        gl_deleted = frappe.db.sql("""
            DELETE FROM `tabGL Entry` 
            WHERE company = %s 
            AND (remarks LIKE '%%e-Boekhouden%%' 
                 OR remarks LIKE '%%eBoekhouden%%' 
                 OR remarks LIKE '%%E-Boekhouden REST Import%%')
        """, company)
        
        results["gl_entries_deleted"] = gl_deleted
        
        # Clean up other e-Boekhouden documents
        # Payment Entries
        payment_entries = frappe.db.sql("""
            SELECT name FROM `tabPayment Entry` 
            WHERE company = %s 
            AND (eboekhouden_mutation_nr IS NOT NULL 
                 OR reference_no REGEXP '^[0-9]+$'
                 OR remarks LIKE '%%Mutation Nr:%%')
        """, company, as_dict=True)
        
        if payment_entries:
            pe_names = [pe.name for pe in payment_entries]
            placeholders = ','.join(['%s'] * len(pe_names))
            frappe.db.sql(f"DELETE FROM `tabGL Entry` WHERE voucher_no IN ({placeholders}) AND voucher_type = 'Payment Entry'", pe_names)
            frappe.db.sql(f"DELETE FROM `tabPayment Entry` WHERE name IN ({placeholders})", pe_names)
            results["payment_entries_deleted"] = len(payment_entries)
        
        # Sales Invoices
        sales_invoices = frappe.db.sql("""
            SELECT name FROM `tabSales Invoice` 
            WHERE company = %s 
            AND (eboekhouden_invoice_number IS NOT NULL 
                 OR title LIKE '%%eBoekhouden%%'
                 OR remarks LIKE '%%e-Boekhouden%%')
        """, company, as_dict=True)
        
        if sales_invoices:
            si_names = [si.name for si in sales_invoices]
            placeholders = ','.join(['%s'] * len(si_names))
            frappe.db.sql(f"DELETE FROM `tabGL Entry` WHERE voucher_no IN ({placeholders}) AND voucher_type = 'Sales Invoice'", si_names)
            frappe.db.sql(f"DELETE FROM `tabSales Invoice Item` WHERE parent IN ({placeholders})", si_names)
            frappe.db.sql(f"DELETE FROM `tabSales Invoice` WHERE name IN ({placeholders})", si_names)
            results["sales_invoices_deleted"] = len(sales_invoices)
        
        # Purchase Invoices
        purchase_invoices = frappe.db.sql("""
            SELECT name FROM `tabPurchase Invoice` 
            WHERE company = %s 
            AND (eboekhouden_invoice_number IS NOT NULL 
                 OR title LIKE '%%eBoekhouden%%'
                 OR remarks LIKE '%%e-Boekhouden%%')
        """, company, as_dict=True)
        
        if purchase_invoices:
            pi_names = [pi.name for pi in purchase_invoices]
            placeholders = ','.join(['%s'] * len(pi_names))
            frappe.db.sql(f"DELETE FROM `tabGL Entry` WHERE voucher_no IN ({placeholders}) AND voucher_type = 'Purchase Invoice'", pi_names)
            frappe.db.sql(f"DELETE FROM `tabPurchase Invoice Item` WHERE parent IN ({placeholders})", pi_names)
            frappe.db.sql(f"DELETE FROM `tabPurchase Invoice` WHERE name IN ({placeholders})", pi_names)
            results["purchase_invoices_deleted"] = len(purchase_invoices)
        
        # Commit changes
        frappe.db.commit()
        
    except Exception as e:
        frappe.db.rollback()
        print(f"Error during cleanup: {str(e)}")
        results["error"] = str(e)
        
    finally:
        # Re-enable foreign key checks
        frappe.db.sql("SET FOREIGN_KEY_CHECKS = 1")
    
    return results

if __name__ == "__main__":
    frappe.init()
    frappe.connect()
    
    results = direct_cleanup_eboekhouden()
    print("\nCleanup Results:")
    for key, value in results.items():
        print(f"{key}: {value}")