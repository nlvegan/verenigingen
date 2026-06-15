"""
Add composite indexes for volunteer assignment UNION query optimization.

The AssignmentQueryBuilder uses UNION queries across three tables:
- Chapter Board Member (volunteer, is_active)
- Team Member (volunteer, status)
- Volunteer Activity (volunteer, status)

Existing single-column indexes exist but composite indexes provide
better performance for the specific WHERE clauses used.

Expected improvement: 2-3x faster query execution for volunteers
with many assignments, especially on larger datasets.
"""

import frappe


def execute():
    """Add composite indexes for volunteer assignment queries."""

    indexes_to_add = [
        # Composite index for Chapter Board Member UNION branch
        # Query: WHERE cbm.volunteer = %s AND cbm.is_active = 1
        {
            "table": "tabChapter Board Member",
            "index_name": "idx_volunteer_active_composite",
            "columns": ["volunteer", "is_active"],
            "description": "Composite for volunteer assignment UNION query",
        },
        # Composite index for Team Member UNION branch
        # Query: WHERE tm.volunteer = %s AND tm.status = 'Active'
        {
            "table": "tabTeam Member",
            "index_name": "idx_volunteer_status_composite",
            "columns": ["volunteer", "status"],
            "description": "Composite for volunteer assignment UNION query",
        },
        # Indexes for Volunteer Activity table (no existing indexes)
        # Query: WHERE va.volunteer = %s AND va.status = 'Active'
        {
            "table": "tabVolunteer Activity",
            "index_name": "idx_activity_volunteer",
            "columns": ["volunteer"],
            "description": "Volunteer relationship lookups for activities",
        },
        {
            "table": "tabVolunteer Activity",
            "index_name": "idx_activity_status",
            "columns": ["status"],
            "description": "Activity status filtering",
        },
        {
            "table": "tabVolunteer Activity",
            "index_name": "idx_activity_volunteer_status",
            "columns": ["volunteer", "status"],
            "description": "Composite for volunteer assignment UNION query",
        },
    ]

    print("Adding composite indexes for volunteer assignment queries...")

    indexes_added = []
    errors = []

    for idx_config in indexes_to_add:
        table = idx_config["table"]
        index_name = idx_config["index_name"]
        columns = idx_config["columns"]

        try:
            # Check if table exists
            table_exists = frappe.db.sql(
                """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = %s
                """,
                (table,),
            )

            if not table_exists or table_exists[0][0] == 0:
                print(f"  - Skipping {table} (table does not exist)")
                continue

            # Check if index already exists
            existing = frappe.db.sql(
                """
                SELECT COUNT(*) FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                AND table_name = %s AND index_name = %s
                """,
                (table, index_name),
            )

            if existing and existing[0][0] > 0:
                print(f"  - Index {index_name} already exists on {table}")
                continue

            # Create the index
            columns_sql = ", ".join(f"`{c}`" for c in columns)
            # sql_ddl(): ALTER autocommits in MariaDB; frappe.db.sql() would raise
            # ImplicitCommitError mid-migration (silently caught below).
            frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({columns_sql})")

            indexes_added.append(f"{index_name} on {table}")
            print(f"  + Added {index_name} on {table}({', '.join(columns)})")

        except Exception as e:
            errors.append(f"{index_name}: {str(e)}")
            print(f"  ! Failed to add {index_name}: {str(e)}")

    # Summary
    print(f"\nSummary: Added {len(indexes_added)} indexes, {len(errors)} errors")

    if errors:
        for err in errors:
            print(f"  Error: {err}")
