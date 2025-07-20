#!/usr/bin/env python3
"""
Workspace Reorganization Script

Reorganizes the Verenigingen workspace with proper logical categorization.
"""

import frappe


def reorganize_workspace():
    """Reorganize workspace links into logical categories"""
    
    print("🔄 Reorganizing Verenigingen workspace...")
    
    # Clear existing links
    frappe.db.sql("DELETE FROM `tabWorkspace Link` WHERE parent = 'Verenigingen'")
    print("   ✅ Cleared existing workspace links")
    
    # Define the properly organized structure
    organized_links = [
        # === MEMBERS/MEMBERSHIPS SECTION ===
        ("Card Break", "Members & Memberships", None, None, 0, 6),
        ("Link", "Member", "DocType", "Member", 1, 0),
        ("Link", "Membership", "DocType", "Membership", 1, 0),
        ("Link", "Membership Type", "DocType", "Membership Type", 0, 0),
        ("Link", "Membership Dues Schedule", "DocType", "Membership Dues Schedule", 0, 0),
        ("Link", "Contribution Amendment Request", "DocType", "Contribution Amendment Request", 0, 0),
        ("Link", "Membership Termination Request", "DocType", "Membership Termination Request", 0, 0),
        
        # === APPLICATIONS & ONBOARDING ===
        ("Card Break", "Applications & Onboarding", None, None, 0, 3),
        ("Link", "Public Application Form", "Page", "/membership_application", 0, 0),
        ("Link", "Membership Application Workflow Demo", "Page", "/workflow_demo", 0, 0),
        ("Link", "Member Portal", "Page", "/member_portal", 0, 0),
        
        # === DONATIONS & ANBI ===
        ("Card Break", "Donations & ANBI", None, None, 0, 4),
        ("Link", "Donor", "DocType", "Donor", 0, 0),
        ("Link", "Donation", "DocType", "Donation", 0, 0),
        ("Link", "Donation Type", "DocType", "Donation Type", 0, 0),
        ("Link", "ANBI Donation Summary", "Report", "ANBI Donation Summary", 0, 0),
        
        # === VOLUNTEERS ===
        ("Card Break", "Volunteers", None, None, 0, 4),
        ("Link", "Volunteer", "DocType", "Volunteer", 1, 0),
        ("Link", "Volunteer Activity", "DocType", "Volunteer Activity", 0, 0),
        ("Link", "Volunteer Dashboard", "Page", "/volunteer/dashboard", 0, 0),
        ("Link", "Chapter Dashboard", "Page", "/chapter-dashboard", 0, 0),
        
        # === VOLUNTEER EXPENSES ===
        ("Card Break", "Volunteer Expenses", None, None, 0, 3),
        ("Link", "Volunteer Expense", "DocType", "Volunteer Expense", 0, 0),
        ("Link", "Expense Category", "DocType", "Expense Category", 0, 0),
        ("Link", "Expense Claims (ERPNext)", "DocType", "Expense Claim", 0, 0),
        
        # === CHAPTERS & TEAMS ===
        ("Card Break", "Chapters & Teams", None, None, 0, 4),
        ("Link", "Chapter", "DocType", "Chapter", 1, 0),
        ("Link", "Chapter Role", "DocType", "Chapter Role", 0, 0),
        ("Link", "Region", "DocType", "Region", 0, 0),
        ("Link", "Team", "DocType", "Team", 0, 0),
        
        # === PAYMENT PROCESSING ===
        ("Card Break", "Payment Processing", None, None, 0, 4),
        ("Link", "SEPA Mandate", "DocType", "SEPA Mandate", 0, 0),
        ("Link", "Direct Debit Batch", "DocType", "Direct Debit Batch", 0, 0),
        ("Link", "SEPA Payment Retry", "DocType", "SEPA Payment Retry", 0, 0),
        ("Link", "Fee Adjustment Portal", "Page", "/membership_fee_adjustment", 0, 0),
        
        # === BANKING ===
        ("Card Break", "Banking", None, None, 0, 6),
        ("Link", "Bank Account", "DocType", "Bank Account", 0, 0),
        ("Link", "Bank Transaction", "DocType", "Bank Transaction", 0, 0),
        ("Link", "Bank Reconciliation Tool", "DocType", "Bank Reconciliation Tool", 0, 0),
        ("Link", "Bank Statement Import", "DocType", "Bank Statement Import", 0, 0),
        ("Link", "Bank Guarantee", "DocType", "Bank Guarantee", 0, 0),
        ("Link", "MT940 Import", "DocType", "MT940 Import", 0, 0),
        
        # === ACCOUNTING ===
        ("Card Break", "Accounting", None, None, 0, 7),
        ("Link", "Sales Invoice", "DocType", "Sales Invoice", 0, 0),
        ("Link", "Purchase Invoice", "DocType", "Purchase Invoice", 0, 0),
        ("Link", "Payment Entry", "DocType", "Payment Entry", 0, 0),
        ("Link", "Payment Request", "DocType", "Payment Request", 0, 0),
        ("Link", "Payment Order", "DocType", "Payment Order", 0, 0),
        ("Link", "Journal Entry", "DocType", "Journal Entry", 0, 0),
        ("Link", "Account", "DocType", "Account", 0, 0),
        
        # === REPORTS ===
        ("Card Break", "Reports", None, None, 0, 7),
        ("Link", "Expiring Memberships", "Report", "Expiring Memberships", 0, 0),
        ("Link", "New Members", "Report", "New Members", 0, 0),
        ("Link", "Members Without Chapter", "Report", "Members Without Chapter", 0, 0),
        ("Link", "Overdue Member Payments", "Report", "Overdue Member Payments", 0, 0),
        ("Link", "Termination Compliance Report", "Report", "Termination Compliance Report", 0, 0),
        ("Link", "Chapter Expense Report", "Report", "Chapter Expense Report", 0, 0),
        ("Link", "Users by Team", "Report", "Users by Team", 0, 0),
        
        # === SETTINGS & ADMIN ===
        ("Card Break", "Settings & Administration", None, None, 0, 4),
        ("Link", "Verenigingen Settings", "DocType", "Verenigingen Settings", 0, 0),
        ("Link", "Brand Settings", "DocType", "Brand Settings", 0, 0),
        ("Link", "Brand Management", "Page", "/brand_management", 0, 0),
        ("Link", "Accounting Dimension", "DocType", "Accounting Dimension", 0, 0),
    ]
    
    # Insert the organized links
    for idx, (type_, label, link_type, link_to, onboard, link_count) in enumerate(organized_links, 1):
        name = frappe.generate_hash("", 10)
        frappe.db.sql("""
            INSERT INTO `tabWorkspace Link` (
                name, parent, parenttype, parentfield, idx, type, label, 
                link_type, link_to, hidden, is_query_report, onboard, link_count
            ) VALUES (
                %s, 'Verenigingen', 'Workspace', 'links', %s, %s, %s, %s, %s, 0, %s, %s, %s
            )
        """, (name, idx, type_, label, link_type, link_to, 
              1 if link_type == "Report" else 0, onboard, link_count))
    
    # Update workspace modified timestamp
    frappe.db.sql("UPDATE tabWorkspace SET modified = NOW() WHERE name = 'Verenigingen'")
    
    frappe.db.commit()
    
    print(f"   ✅ Created {len(organized_links)} organized workspace links")
    print("   ✅ Workspace reorganization completed successfully")
    
    return {
        "success": True,
        "links_created": len(organized_links),
        "message": "Workspace successfully reorganized with logical categorization"
    }


@frappe.whitelist()
def run_workspace_reorganization():
    """API endpoint for workspace reorganization"""
    return reorganize_workspace()


if __name__ == "__main__":
    frappe.init(site="dev.veganisme.net")
    frappe.connect()
    
    try:
        result = reorganize_workspace()
        print("\n🎉 Workspace reorganization completed!")
        print(f"📊 Result: {result}")
    except Exception as e:
        print(f"❌ Error during reorganization: {str(e)}")
        frappe.db.rollback()
        raise
    finally:
        frappe.destroy()