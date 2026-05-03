"""Clean legacy `upload_date` values overloaded by old MijnRood imports.

The pre-applies_on import path wrote document content dates into
`upload_date`. After this feature, `upload_date` reverts to "when this
record was created" and a separate `applies_on` field carries the
content date.

For rows where the discrepancy is still visible
(DATE(upload_date) != DATE(creation) AND applies_on IS NULL), copy the
old upload_date value into applies_on, set precision to Day, and reset
upload_date to DATE(creation). Idempotent.
"""

import frappe


def execute():
    affected = frappe.db.sql(
        """
        SELECT name, upload_date, DATE(creation) AS creation_date
        FROM `tabOrganization Document`
        WHERE applies_on IS NULL
          AND upload_date IS NOT NULL
          AND DATE(upload_date) != DATE(creation)
        """,
        as_dict=True,
    )

    if not affected:
        return

    for row in affected:
        frappe.db.set_value(
            "Organization Document",
            row["name"],
            {
                "applies_on": row["upload_date"],
                "applies_on_precision": "Day",
                "upload_date": row["creation_date"],
            },
            update_modified=False,
        )

    frappe.db.commit()
    print(f"clean_overloaded_upload_date: healed {len(affected)} Organization Document rows")
