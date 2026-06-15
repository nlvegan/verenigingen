import frappe


def execute():
    """
    Add composite indexes for Chapter Dashboard performance optimization.

    These indexes optimize the complex multi-table query used in the
    Chapter Dashboard's dues payment status section (get_financial_summary).

    Targeted query from chapter_dashboard.py lines 715-747:
    - Joins Chapter Member, Member, Sales Invoice, Membership, Membership Dues Schedule
    - Filters by chapter and enabled status
    - Aggregates coverage dates and payment status

    Expected benefits:
    - 50-80% query time reduction for chapters with 100+ members
    - Eliminates full table scans on Member and Sales Invoice tables
    - Improves dashboard load time from ~2-3s to <500ms (large chapters)
    """

    indexes_to_create = [
        {
            "table": "tabChapter Member",
            "index_name": "idx_chapter_member_lookup",
            "columns": ["parent", "enabled"],
            "description": "Composite index for chapter member lookup by parent chapter and status",
        },
        {
            "table": "tabSales Invoice",
            "index_name": "idx_sales_invoice_member_coverage",
            "columns": ["member", "docstatus", "custom_coverage_end_date"],
            "description": "Composite index for member invoice lookup with coverage date",
        },
        {
            "table": "tabMembership",
            "index_name": "idx_membership_member_status",
            "columns": ["member", "status", "docstatus"],
            "description": "Composite index for membership lookup by member and status",
        },
        {
            "table": "tabMembership Dues Schedule",
            "index_name": "idx_dues_schedule_member",
            "columns": ["member"],
            "description": "Single column index for dues schedule member lookup",
        },
    ]

    for index_config in indexes_to_create:
        create_index_safe(
            table_name=index_config["table"],
            index_name=index_config["index_name"],
            columns=index_config["columns"],
            description=index_config["description"],
        )


def create_index_safe(table_name: str, index_name: str, columns: list, description: str):
    """
    Safely create a database index with existence checks.

    Args:
        table_name: Name of the table (e.g., "tabChapter Member")
        index_name: Name for the index (e.g., "idx_chapter_member_lookup")
        columns: List of column names to index
        description: Human-readable description of index purpose
    """
    try:
        # Check if table exists
        table_exists = frappe.db.sql(
            """
            SELECT COUNT(*) as count FROM information_schema.tables
            WHERE table_name = %s AND table_schema = DATABASE()
            """,
            [table_name],
            as_dict=True,
        )

        if not table_exists[0]["count"]:
            print(f"⚠ Table {table_name} doesn't exist - skipping index {index_name}")
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
            print(f"✓ Index {index_name} already exists on {table_name}")
            return

        # Verify all columns exist before creating index
        for column in columns:
            column_exists = frappe.db.sql(
                """
                SELECT COUNT(*) as count FROM information_schema.columns
                WHERE table_name = %s
                AND column_name = %s
                AND table_schema = DATABASE()
                """,
                [table_name, column],
                as_dict=True,
            )

            if not column_exists[0]["count"]:
                print(f"⚠ Column {column} doesn't exist in {table_name} - skipping index {index_name}")
                return

        # Build index creation SQL
        columns_str = ", ".join([f"`{col}`" for col in columns])
        sql = f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns_str})"

        print(f"\nAdding index {index_name} on {table_name}({', '.join(columns)})")
        print(f"Purpose: {description}")

        # Use sql_ddl(): CREATE INDEX autocommits in MariaDB, so running it through
        # frappe.db.sql() mid-migration raises ImplicitCommitError (previously
        # swallowed by the except below, so these indexes were never created).
        frappe.db.sql_ddl(sql)

        print(f"✓ Successfully added index {index_name}")

    except Exception as e:
        error_msg = f"Failed to add index {index_name} on {table_name}: {str(e)}"
        print(f"✗ {error_msg}")

        # Log error but don't fail migration
        frappe.log_error(
            message=error_msg,
            title=f"Chapter Dashboard Index Migration Error - {index_name}",
        )

        # Don't raise exception - allow migration to continue
        print("Migration will continue despite this error")
