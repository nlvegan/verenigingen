"""
Create Database Indexes for SEPA Operations
"""

import frappe


@frappe.whitelist()
def create_sepa_indexes():
    """Create all SEPA-related database indexes"""

    indexes_to_create = [
        # SEPA invoice lookup optimization
        {
            "table": "tabSales Invoice",
            "name": "idx_sepa_invoice_lookup",
            "columns": [
                "docstatus",
                "status",
                "outstanding_amount",
                "posting_date",
                "custom_membership_dues_schedule",
            ],
            "description": "Optimizes SEPA invoice batch queries",
        },
        # Mandate lookup optimization
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_member_status",
            "columns": ["member", "status", "iban", "mandate_id"],
            "description": "Optimizes member mandate lookups",
        },
        # Batch processing optimization
        {
            "table": "tabDirect Debit Batch Invoice",
            "name": "idx_direct_debit_batch_invoice",
            "columns": ["invoice", "parent"],
            "description": "Optimizes batch invoice conflict detection",
        },
        # Membership dues schedule optimization
        {
            "table": "tabMembership Dues Schedule",
            "name": "idx_membership_dues_schedule_member_freq",
            "columns": [
                "member",
                "status",
                "billing_frequency",
                "next_billing_period_start_date",
                "next_billing_period_end_date",
            ],
            "description": "Optimizes billing frequency transition queries",
        },
        # Member mandate performance optimization
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_status_dates",
            "columns": ["status", "sign_date", "expiry_date", "creation"],
            "description": "Optimizes mandate validation and batch processing",
        },
        # Sales invoice payment method optimization
        {
            "table": "tabSales Invoice",
            "name": "idx_sales_invoice_payment_method",
            "columns": ["status", "outstanding_amount", "custom_membership_dues_schedule"],
            "description": "Optimizes unpaid invoice queries for SEPA batches",
        },
        # Direct debit batch status optimization
        {
            "table": "tabDirect Debit Batch",
            "name": "idx_direct_debit_batch_status",
            "columns": ["docstatus", "status", "batch_date"],
            "description": "Optimizes batch status and date queries",
        },
    ]

    created_indexes = []
    failed_indexes = []

    print(f"\n{'=' * 60}")
    print("CREATING SEPA DATABASE INDEXES")
    print(f"{'=' * 60}")
    print(f"Total indexes to create: {len(indexes_to_create)}")
    print(f"{'=' * 60}\n")

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
            existing_indexes = frappe.db.sql(
                f"""
                SHOW INDEX FROM `{table}`
                WHERE Key_name = '{name}'
            """
            )

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
                created_indexes.append(
                    {"name": name, "table": table, "columns": len(columns), "description": description}
                )
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
    print(f"{'=' * 60}")
    print("INDEX CREATION SUMMARY")
    print(f"{'=' * 60}")
    print(f"✅ Successfully created: {len(created_indexes)} indexes")
    print(f"❌ Failed to create: {len(failed_indexes)} indexes")
    print(f"📊 Total processing: {len(indexes_to_create)} indexes")

    if created_indexes:
        print("\n📈 CREATED INDEXES:")
        for idx in created_indexes:
            print(f"   • {idx['name']} ({idx['columns']} columns) - {idx['description']}")

    if failed_indexes:
        print("\n⚠️  FAILED INDEXES:")
        for fail in failed_indexes:
            print(f"   • {fail}")

    print(f"\n{'=' * 60}")
    print("INDEX CREATION COMPLETE")
    print(f"{'=' * 60}")

    # Commit changes
    frappe.db.commit()

    return {
        "success": len(failed_indexes) == 0,
        "created": len(created_indexes),
        "failed": len(failed_indexes),
        "total": len(indexes_to_create),
        "created_indexes": created_indexes,
        "failed_indexes": failed_indexes,
    }
