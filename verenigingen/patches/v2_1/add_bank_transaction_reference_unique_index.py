import frappe


def execute():
    """
    Add unique index on Bank Transaction reference_number field.

    This ensures that Mollie payment processors cannot create duplicate
    Bank Transactions when processing the same payment via different APIs
    (DuesPaymentProcessor, BalanceTransactionProcessor, etc.).

    The unique index prevents race conditions and ensures idempotency across:
    - Mollie payment webhook processing
    - Balance transaction processing
    - Settlement transaction processing
    - Manual bank transaction imports

    Expected benefits:
    - Eliminates duplicate Bank Transaction creation
    - Prevents race conditions during concurrent processing
    - Ensures proper idempotency across payment APIs
    - Database-level constraint enforcement (more reliable than application logic)
    """

    try:
        table_name = "tabBank Transaction"
        index_name = "idx_reference_number_unique"

        # Check if table exists
        table_exists = frappe.db.sql(
            f"""
            SELECT COUNT(*) as count FROM information_schema.tables
            WHERE table_name = '{table_name}' AND table_schema = DATABASE()
        """,
            as_dict=True,
        )

        if not table_exists[0]["count"]:
            print(f"⚠ Table {table_name} doesn't exist - skipping unique index creation")
            return

        # Check if index already exists
        existing_indexes = frappe.db.sql(
            f"""
            SHOW INDEX FROM `{table_name}`
            WHERE Key_name = %s
        """,
            [index_name],
        )

        if existing_indexes:
            print(f"✓ Unique index {index_name} already exists on {table_name}")
            return

        # Check for existing duplicates before creating unique index
        duplicates = frappe.db.sql(
            f"""
            SELECT reference_number, COUNT(*) as count
            FROM `{table_name}`
            WHERE reference_number IS NOT NULL AND reference_number != ''
            GROUP BY reference_number
            HAVING count > 1
        """,
            as_dict=True,
        )

        if duplicates:
            print(f"\n⚠ WARNING: Found {len(duplicates)} duplicate reference_number values:")
            for dup in duplicates[:10]:  # Show first 10
                print(f"  - {dup.reference_number}: {dup.count} occurrences")

            if len(duplicates) > 10:
                print(f"  ... and {len(duplicates) - 10} more")

            print("\nCannot create unique index until duplicates are resolved.")
            print("Please review and merge/delete duplicate Bank Transactions manually.")

            # Log error for tracking
            frappe.log_error(
                message=f"Found {len(duplicates)} duplicate reference_number values in Bank Transaction. "
                "Unique index creation skipped.",
                title="Bank Transaction Unique Index Migration - Duplicates Found",
            )
            return

        # Create the unique index
        sql = f"ALTER TABLE `{table_name}` ADD UNIQUE INDEX `{index_name}` (`reference_number`)"

        print(f"Adding unique index {index_name} on {table_name}(reference_number)")
        print("Purpose: Prevent duplicate Bank Transactions across Mollie payment APIs")

        # sql_ddl(): CREATE/ALTER autocommits in MariaDB; frappe.db.sql() would
        # raise ImplicitCommitError mid-migration (silently caught below).
        frappe.db.sql_ddl(sql)

        print(f"✓ Successfully added unique index {index_name}")
        print("\nBenefits:")
        print("  - Eliminates duplicate Bank Transaction creation")
        print("  - Prevents race conditions during concurrent processing")
        print("  - Ensures idempotency across payment APIs")

    except Exception as e:
        error_msg = f"Failed to add unique index on Bank Transaction reference_number: {str(e)}"
        print(f"✗ {error_msg}")

        # Log error but don't fail migration
        frappe.log_error(message=error_msg, title="Bank Transaction Unique Index Migration Error")

        # Don't raise exception - allow migration to continue
        print("Migration will continue despite this error")
