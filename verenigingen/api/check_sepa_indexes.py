"""
Check SEPA Database Indexes Validation Script
"""

import frappe


@frappe.whitelist()
def check_sepa_indexes():
    """Check if SEPA database indexes were created"""

    indexes_to_check = [
        {
            "table": "tabSales Invoice",
            "name": "idx_sepa_invoice_lookup",
            "expected_columns": [
                "docstatus",
                "status",
                "outstanding_amount",
                "posting_date",
                "custom_membership_dues_schedule",
            ],
        },
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_member_status",
            "expected_columns": ["member", "status", "iban", "mandate_id"],
        },
        {
            "table": "tabDirect Debit Batch Invoice",
            "name": "idx_direct_debit_batch_invoice",
            "expected_columns": ["invoice", "parent"],
        },
        {
            "table": "tabMembership Dues Schedule",
            "name": "idx_membership_dues_schedule_member_freq",
            "expected_columns": [
                "member",
                "status",
                "billing_frequency",
                "next_billing_period_start_date",
                "next_billing_period_end_date",
            ],
        },
        {
            "table": "tabSEPA Mandate",
            "name": "idx_sepa_mandate_status_dates",
            "expected_columns": ["status", "sign_date", "expiry_date", "creation"],
        },
        {
            "table": "tabSales Invoice",
            "name": "idx_sales_invoice_payment_method",
            "expected_columns": ["status", "outstanding_amount", "custom_membership_dues_schedule"],
        },
        {
            "table": "tabDirect Debit Batch",
            "name": "idx_direct_debit_batch_status",
            "expected_columns": ["docstatus", "status", "batch_date"],
        },
    ]

    results = {"found": [], "missing": [], "incomplete": []}

    for index_info in indexes_to_check:
        table = index_info["table"]
        index_name = index_info["name"]
        expected_columns = index_info["expected_columns"]

        try:
            # Get index information
            index_data = frappe.db.sql(
                f"""
                SHOW INDEX FROM `{table}`
                WHERE Key_name = %s
            """,
                (index_name,),
                as_dict=True,
            )

            if not index_data:
                results["missing"].append(
                    {"table": table, "index": index_name, "expected_columns": expected_columns}
                )
            else:
                # Check if all expected columns are in the index
                indexed_columns = [row.Column_name for row in index_data]

                if len(indexed_columns) != len(expected_columns):
                    results["incomplete"].append(
                        {
                            "table": table,
                            "index": index_name,
                            "expected": expected_columns,
                            "actual": indexed_columns,
                        }
                    )
                else:
                    results["found"].append({"table": table, "index": index_name, "columns": indexed_columns})

        except Exception as e:
            results["missing"].append({"table": table, "index": index_name, "error": str(e)})

    return {
        "success": len(results["missing"]) == 0 and len(results["incomplete"]) == 0,
        "found_count": len(results["found"]),
        "missing_count": len(results["missing"]),
        "incomplete_count": len(results["incomplete"]),
        "total_expected": len(indexes_to_check),
        "found": results["found"],
        "missing": results["missing"],
        "incomplete": results["incomplete"],
    }
