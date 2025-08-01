import frappe


@frappe.whitelist()
def create_missing_indexes():
    """Create missing address matching indexes"""

    indexes_to_create = [
        ("idx_member_address_fingerprint", "tabMember", "address_fingerprint"),
        ("idx_member_normalized_address", "tabMember", "normalized_address_line, normalized_city"),
        ("idx_member_primary_address", "tabMember", "primary_address"),
    ]

    results = []

    for index_name, table_name, columns in indexes_to_create:
        try:
            # Check if index exists
            existing = frappe.db.sql(
                f"""
                SELECT INDEX_NAME
                FROM INFORMATION_SCHEMA.STATISTICS
                WHERE TABLE_SCHEMA = DATABASE()
                    AND TABLE_NAME = '{table_name}'
                    AND INDEX_NAME = '{index_name}'
            """
            )

            if not existing:
                # Create index
                sql = f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns})"
                frappe.db.sql(sql)
                results.append(f"Created index: {index_name}")
            else:
                results.append(f"Index already exists: {index_name}")

        except Exception as e:
            results.append(f"Error creating index {index_name}: {e}")

    return results
