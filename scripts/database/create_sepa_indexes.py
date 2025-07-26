#!/usr/bin/env python3
"""
Create Database Indexes for SEPA Operations

Creates optimized indexes for SEPA and billing-related operations
to support the performance improvements implemented in Week 1.
"""

import frappe


def create_sepa_indexes():
    """Create all SEPA-related database indexes"""
    
    indexes_to_create = [
        # SEPA invoice lookup optimization
        {
            "table": "tabSales Invoice",
            "name": "idx_sepa_invoice_lookup", 
            "columns": ["docstatus", "status", "outstanding_amount", "posting_date", "custom_membership_dues_schedule"],
            "description": "Optimizes SEPA invoice batch queries"
        },
        
        # Mandate lookup optimization
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_member_status",
            "columns": ["member", "status", "iban", "mandate_id"],
            "description": "Optimizes member mandate lookups"
        },
        
        # Batch processing optimization
        {
            "table": "tabDirect Debit Batch Invoice", 
            "name": "idx_direct_debit_batch_invoice",
            "columns": ["invoice", "parent"],
            "description": "Optimizes batch invoice conflict detection"
        },
        
        # Membership dues schedule optimization
        {
            "table": "tabMembership Dues Schedule",
            "name": "idx_membership_dues_schedule_member_freq",
            "columns": ["member", "status", "billing_frequency", "next_billing_period_start_date", "next_billing_period_end_date"],
            "description": "Optimizes billing frequency transition queries"
        },
        
        # Member mandate performance optimization
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_status_dates",
            "columns": ["status", "sign_date", "expiry_date", "creation"],
            "description": "Optimizes mandate validation and batch processing"
        },
        
        # Sales invoice payment method optimization
        {
            "table": "tabSales Invoice",
            "name": "idx_sales_invoice_payment_method",
            "columns": ["status", "outstanding_amount", "custom_membership_dues_schedule"],
            "description": "Optimizes unpaid invoice queries for SEPA batches"
        },
        
        # Direct debit batch status optimization
        {
            "table": "tabDirect Debit Batch",
            "name": "idx_direct_debit_batch_status",
            "columns": ["docstatus", "status", "batch_date"],
            "description": "Optimizes batch status and date queries"
        },
        
        # Billing frequency transition audit optimization
        {
            "table": "tabBilling Frequency Transition Audit",
            "name": "idx_billing_transition_audit_member",
            "columns": ["member", "transition_status", "processed_at"],
            "description": "Optimizes billing transition history queries"
        }
    ]
    
    created_indexes = []
    failed_indexes = []
    
    print(f"\n{'='*60}")
    print("CREATING SEPA DATABASE INDEXES")
    print(f"{'='*60}")
    print(f"Total indexes to create: {len(indexes_to_create)}")
    print(f"{'='*60}\n")
    
    for i, index_config in enumerate(indexes_to_create, 1):
        try:
            table = index_config["table"]
            name = index_config["name"]
            columns = index_config["columns"]
            description = index_config["description"]
            
            print(f"{i}. Creating index '{name}' on {table}")
            print(f"   Columns: {', '.join(columns)}")
            print(f"   Purpose: {description}")
            
            # Check if index already exists
            existing_indexes = frappe.db.sql(f"""
                SHOW INDEX FROM `{table}` 
                WHERE Key_name = '{name}'
            """)
            
            if existing_indexes:
                print(f"   ⚠️  Index '{name}' already exists, skipping...")
                continue
            
            # Create the index
            columns_sql = ", ".join([f"`{col}`" for col in columns])
            create_index_sql = f"""
                CREATE INDEX `{name}` 
                ON `{table}` ({columns_sql})
            """
            
            frappe.db.sql(create_index_sql)
            
            # Verify index was created
            verify_sql = f"""
                SHOW INDEX FROM `{table}` 
                WHERE Key_name = '{name}'
            """
            verification = frappe.db.sql(verify_sql)
            
            if verification:
                print(f"   ✅ Index '{name}' created successfully")
                created_indexes.append({
                    "name": name,
                    "table": table, 
                    "columns": len(columns),
                    "description": description
                })
            else:
                print(f"   ❌ Index '{name}' creation failed - not found after creation")
                failed_indexes.append(f"{name} on {table}")
                
        except Exception as e:
            error_msg = str(e)
            print(f"   ❌ Error creating index '{name}': {error_msg}")
            failed_indexes.append(f"{name} on {table}: {error_msg}")
            
            # Continue with other indexes even if one fails
            continue
        
        print()  # Add blank line between indexes
    
    # Summary
    print(f"{'='*60}")
    print("INDEX CREATION SUMMARY")
    print(f"{'='*60}")
    print(f"✅ Successfully created: {len(created_indexes)} indexes")
    print(f"❌ Failed to create: {len(failed_indexes)} indexes")
    print(f"📊 Total processing: {len(indexes_to_create)} indexes")
    
    if created_indexes:
        print(f"\n📈 CREATED INDEXES:")
        for idx in created_indexes:
            print(f"   • {idx['name']} ({idx['columns']} columns) - {idx['description']}")
    
    if failed_indexes:
        print(f"\n⚠️  FAILED INDEXES:")
        for fail in failed_indexes:
            print(f"   • {fail}")
    
    print(f"\n{'='*60}")
    print("INDEX CREATION COMPLETE")
    print(f"{'='*60}")
    
    # Commit changes
    frappe.db.commit()
    
    return {
        "success": len(failed_indexes) == 0,
        "created": len(created_indexes),
        "failed": len(failed_indexes),
        "total": len(indexes_to_create),
        "created_indexes": created_indexes,
        "failed_indexes": failed_indexes
    }


def analyze_sepa_query_performance():
    """Analyze query performance for SEPA operations"""
    
    print(f"\n{'='*60}")
    print("SEPA QUERY PERFORMANCE ANALYSIS")
    print(f"{'='*60}")
    
    performance_queries = [
        {
            "name": "SEPA Invoice Lookup",
            "sql": """
                EXPLAIN SELECT si.name, si.customer, si.outstanding_amount, si.custom_membership_dues_schedule
                FROM `tabSales Invoice` si 
                WHERE si.docstatus = 1 
                AND si.status IN ('Unpaid', 'Overdue')
                AND si.outstanding_amount > 0
                ORDER BY si.posting_date
                LIMIT 100
            """,
            "index": "idx_sepa_invoice_lookup"
        },
        
        {
            "name": "Member Mandate Lookup", 
            "sql": """
                EXPLAIN SELECT sm.name, sm.iban, sm.bic, sm.mandate_id
                FROM `tabSEPA Mandate` sm
                WHERE sm.member = 'TEST-MEMBER-001'
                AND sm.status = 'Active'
            """,
            "index": "idx_sepa_mandate_member_status"
        },
        
        {
            "name": "Billing Frequency Query",
            "sql": """
                EXPLAIN SELECT mds.name, mds.billing_frequency, mds.dues_rate
                FROM `tabMembership Dues Schedule` mds
                WHERE mds.member = 'TEST-MEMBER-001'
                AND mds.status = 'Active'
                AND mds.billing_frequency = 'Monthly'
            """,
            "index": "idx_membership_dues_schedule_member_freq"
        },
        
        {
            "name": "Batch Conflict Detection",
            "sql": """
                EXPLAIN SELECT ddi.invoice, ddb.name
                FROM `tabDirect Debit Batch Invoice` ddi
                JOIN `tabDirect Debit Batch` ddb ON ddi.parent = ddb.name
                WHERE ddi.invoice IN ('INV-001', 'INV-002', 'INV-003')
                AND ddb.docstatus != 2
            """,
            "index": "idx_direct_debit_batch_invoice"
        }
    ]
    
    for i, query_config in enumerate(performance_queries, 1):
        print(f"{i}. {query_config['name']}")
        print(f"   Expected Index: {query_config['index']}")
        
        try:
            # Run EXPLAIN query
            result = frappe.db.sql(query_config["sql"], as_dict=True)
            
            if result:
                # Analyze the first row of EXPLAIN output
                explain_row = result[0]
                
                # Check if our index is being used
                key_used = explain_row.get('key', explain_row.get('Key', 'None'))
                rows_examined = explain_row.get('rows', explain_row.get('Rows', 'Unknown'))
                query_type = explain_row.get('type', explain_row.get('Type', 'Unknown'))
                
                print(f"   📊 Rows examined: {rows_examined}")
                print(f"   🔑 Index used: {key_used}")
                print(f"   ⚡ Query type: {query_type}")
                
                # Performance assessment
                if key_used == query_config['index']:
                    print(f"   ✅ Using optimal index")
                elif key_used and key_used != 'NULL':
                    print(f"   ⚠️  Using different index: {key_used}")
                else:
                    print(f"   ❌ No index used - table scan")
                    
            else:
                print(f"   ⚠️  No EXPLAIN output available")
                
        except Exception as e:
            print(f"   ❌ Error analyzing query: {str(e)}")
        
        print()  # Blank line between queries
    
    print(f"{'='*60}")
    print("PERFORMANCE ANALYSIS COMPLETE")
    print(f"{'='*60}")


@frappe.whitelist()
def create_sepa_indexes_api():
    """API endpoint to create SEPA indexes"""
    try:
        result = create_sepa_indexes()
        return {
            "success": True,
            "message": f"Index creation completed. Created: {result['created']}, Failed: {result['failed']}",
            "details": result
        }
    except Exception as e:
        frappe.log_error(f"Error creating SEPA indexes: {str(e)}", "SEPA Index Creation")
        return {
            "success": False,
            "error": str(e),
            "message": "Index creation failed"
        }


@frappe.whitelist()
def analyze_sepa_performance_api():
    """API endpoint to analyze SEPA query performance"""
    try:
        analyze_sepa_query_performance()
        return {
            "success": True,
            "message": "Performance analysis completed - check console output"
        }
    except Exception as e:
        frappe.log_error(f"Error analyzing SEPA performance: {str(e)}", "SEPA Performance Analysis")
        return {
            "success": False,
            "error": str(e),
            "message": "Performance analysis failed"
        }


if __name__ == "__main__":
    print("SEPA Database Index Creation Tool")
    print("This script creates optimized indexes for SEPA operations")
    print()
    
    # Create indexes
    result = create_sepa_indexes()
    
    print()
    
    # Analyze performance
    analyze_sepa_query_performance()
    
    print(f"\n🎉 Setup complete! SEPA operations are now optimized.")