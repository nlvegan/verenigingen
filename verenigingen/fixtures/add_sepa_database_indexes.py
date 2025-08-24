#!/usr/bin/env python3
"""
Add database indexes for SEPA and membership dues optimization
Run via: bench --site dev.veganisme.net execute verenigingen.fixtures.add_sepa_database_indexes.create_sepa_indexes
"""

import frappe


def create_sepa_indexes():
    """Create database indexes for SEPA and membership dues queries"""

    indexes = [
        # Sales Invoice custom fields indexes
        {
            "table": "`tabSales Invoice`",
            "name": "idx_sepa_invoice_lookup",
            "columns": ["membership_dues_schedule_display", "docstatus", "status", "outstanding_amount"],
            "description": "Optimize SEPA invoice lookup queries",
        },
        {
            "table": "`tabSales Invoice`",
            "name": "idx_coverage_period_lookup",
            "columns": ["custom_coverage_start_date", "custom_coverage_end_date", "docstatus"],
            "description": "Optimize coverage period matching",
        },
        {
            "table": "`tabSales Invoice`",
            "name": "idx_dues_schedule_member",
            "columns": ["membership_dues_schedule_display", "custom_paying_for_member"],
            "description": "Optimize dues schedule and partner payment lookups",
        },
        # Membership Dues Schedule indexes
        {
            "table": "`tabMembership Dues Schedule`",
            "name": "idx_sepa_active_schedules",
            "columns": ["status", "auto_generate", "test_mode", "payment_method"],
            "description": "Optimize active SEPA schedule queries",
        },
        {
            "table": "`tabMembership Dues Schedule`",
            "name": "idx_schedule_coverage_dates",
            "columns": ["current_coverage_start", "current_coverage_end", "next_invoice_date"],
            "description": "Optimize coverage period and invoice date queries",
        },
        # SEPA Mandate indexes
        {
            "table": "`tabSEPA Mandate`",
            "name": "idx_active_mandate_lookup",
            "columns": ["member", "status"],
            "description": "Optimize active mandate lookups by member",
        },
        {
            "table": "`tabSEPA Mandate`",
            "name": "idx_mandate_iban_lookup",
            "columns": ["iban", "status", "mandate_id"],
            "description": "Optimize mandate lookups by IBAN",
        },
        # Direct Debit Batch indexes
        {
            "table": "`tabDirect Debit Batch Invoice`",
            "name": "idx_batch_invoice_exclusion",
            "columns": ["invoice", "parent"],
            "description": "Optimize batch invoice exclusion queries",
        },
        {
            "table": "`tabDirect Debit Batch`",
            "name": "idx_batch_status_date",
            "columns": ["docstatus", "batch_date", "status"],
            "description": "Optimize batch status and date queries",
        },
        # SEPA Mandate Usage indexes
        {
            "table": "`tabSEPA Mandate Usage`",
            "name": "idx_mandate_usage_lookup",
            "columns": ["parent", "reference_doctype", "reference_name"],
            "description": "Optimize mandate usage tracking",
        },
        {
            "table": "`tabSEPA Mandate Usage`",
            "name": "idx_mandate_sequence_history",
            "columns": ["parent", "usage_date", "sequence_type"],
            "description": "Optimize sequence type determination",
        },
    ]

    results = []

    for index_config in indexes:
        try:
            # Check if index already exists - using parameterized query for security
            # Note: Table name must be validated against known DocType tables
            table_name = index_config["table"]
            index_name = index_config["name"]

            # Validate table name against known DocTypes for security
            if not table_name.startswith("`tab") or not table_name.endswith("`"):
                raise ValueError(f"Invalid table name format: {table_name}")

            existing_indexes = frappe.db.sql(
                """
                SELECT COUNT(*) as count FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                AND TABLE_NAME = %s
                AND INDEX_NAME = %s
                """,
                (table_name.strip("`"), index_name),
            )

            if existing_indexes and existing_indexes[0][0] > 0:
                results.append(
                    {
                        "index": index_config["name"],
                        "status": "exists",
                        "table": index_config["table"],
                        "message": "Index already exists",
                    }
                )
                print(f"✅ {index_config['name']} - Already exists")
                continue

            # Create the index using safe parameterized approach
            # Validate input parameters for security
            table_name = index_config["table"]
            index_name = index_config["name"]
            columns = index_config["columns"]

            # Additional security validations
            if not table_name.startswith("`tab") or not table_name.endswith("`"):
                raise ValueError(f"Invalid table name format: {table_name}")

            if not index_name.replace("_", "").replace("idx", "").isalnum():
                raise ValueError(f"Invalid index name format: {index_name}")

            # Validate column names to prevent injection
            for col in columns:
                if not col.replace("_", "").isalnum():
                    raise ValueError(f"Invalid column name: {col}")

            columns_str = ", ".join(f"`{col}`" for col in columns)

            # Use string formatting only with validated inputs (no user input)
            create_sql = f"CREATE INDEX `{index_name}` ON {table_name} ({columns_str})"

            frappe.db.sql(create_sql)

            results.append(
                {
                    "index": index_config["name"],
                    "status": "created",
                    "table": index_config["table"],
                    "columns": index_config["columns"],
                    "description": index_config["description"],
                }
            )

            print(f"✅ {index_config['name']} - Created successfully")

        except Exception as e:
            results.append(
                {
                    "index": index_config["name"],
                    "status": "error",
                    "table": index_config["table"],
                    "error": str(e),
                }
            )
            print(f"❌ {index_config['name']} - Error: {str(e)}")

    # Commit all index creations
    frappe.db.commit()

    # Display summary
    created_count = len([r for r in results if r["status"] == "created"])
    existing_count = len([r for r in results if r["status"] == "exists"])
    error_count = len([r for r in results if r["status"] == "error"])

    print("\n🎯 Index Creation Summary:")
    print(f"✅ Created: {created_count}")
    print(f"ℹ️  Already existed: {existing_count}")
    print(f"❌ Errors: {error_count}")
    print(f"📊 Total indexes: {len(results)}")

    if created_count > 0:
        print("\n🚀 Database performance should be improved for SEPA operations!")

    return results


def verify_sepa_indexes():
    """Verify that SEPA indexes were created correctly"""

    expected_indexes = [
        "idx_sepa_invoice_lookup",
        "idx_coverage_period_lookup",
        "idx_dues_schedule_member",
        "idx_sepa_active_schedules",
        "idx_schedule_coverage_dates",
        "idx_active_mandate_lookup",
        "idx_mandate_iban_lookup",
        "idx_batch_invoice_exclusion",
        "idx_batch_status_date",
        "idx_mandate_usage_lookup",
        "idx_mandate_sequence_history",
    ]

    verification_results = []

    for index_name in expected_indexes:
        # Find which table this index should be on
        index_exists = False

        tables_to_check = [
            "`tabSales Invoice`",
            "`tabMembership Dues Schedule`",
            "`tabSEPA Mandate`",
            "`tabDirect Debit Batch Invoice`",
            "`tabDirect Debit Batch`",
            "`tabSEPA Mandate Usage`",
        ]

        for table in tables_to_check:
            try:
                # Use INFORMATION_SCHEMA for secure index checking
                # Validate table name format for security
                if not table.startswith("`tab") or not table.endswith("`"):
                    continue

                table_name_clean = table.strip("`")
                indexes = frappe.db.sql(
                    """
                    SELECT INDEX_NAME, TABLE_NAME
                    FROM INFORMATION_SCHEMA.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = %s
                    AND INDEX_NAME = %s
                    """,
                    (table_name_clean, index_name),
                    as_dict=True,
                )

                if indexes:
                    index_exists = True
                    verification_results.append(
                        {
                            "index": index_name,
                            "table": table,
                            "status": "found",
                            "columns": [idx["Column_name"] for idx in indexes],
                        }
                    )
                    print(f"✅ {index_name} - Found on {table}")
                    break

            except Exception:
                # Table might not exist, continue checking
                continue

        if not index_exists:
            verification_results.append({"index": index_name, "table": None, "status": "missing"})
            print(f"❌ {index_name} - Not found")

    found_count = len([r for r in verification_results if r["status"] == "found"])
    missing_count = len([r for r in verification_results if r["status"] == "missing"])

    print("\n📋 Index Verification Summary:")
    print(f"✅ Found: {found_count}/{len(expected_indexes)}")
    print(f"❌ Missing: {missing_count}/{len(expected_indexes)}")

    if missing_count == 0:
        print("🎉 All SEPA indexes are properly created!")
    else:
        print("⚠️  Some indexes are missing. Consider re-running create_sepa_indexes()")

    return verification_results


@frappe.whitelist()
def get_sepa_index_status():
    """API to check SEPA index status"""
    return verify_sepa_indexes()


if __name__ == "__main__":
    print("Creating SEPA database indexes...")
    results = create_sepa_indexes()

    print("\nVerifying indexes...")
    verify_sepa_indexes()
