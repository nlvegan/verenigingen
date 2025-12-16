"""Cleanup of orphaned Dynamic Links and other orphaned records"""
import frappe


def cleanup():
    """Remove orphaned records that cause test fixture failures"""
    _cleanup_dynamic_links()
    _cleanup_mode_of_payment_accounts()


def _cleanup_dynamic_links():
    """Remove Dynamic Links pointing to non-existent test documents"""
    # DocTypes to check for orphaned links
    doctypes_to_check = [
        ("Donor", "tabDonor"),
        ("Customer", "tabCustomer"),
        ("Member", "tabMember"),
        ("Chapter", "tabChapter"),
    ]

    # Test name patterns
    test_patterns = """
        (dl.link_name LIKE 'Test %' OR dl.link_name LIKE 'TEST %'
         OR dl.link_name LIKE 'Debug %' OR dl.link_name LIKE 'Phase%'
         OR dl.link_name LIKE 'Security Test%' OR dl.link_name LIKE 'Performance Test%'
         OR dl.link_name LIKE 'Form Test%' OR dl.link_name LIKE 'Campaign Test%'
         OR dl.link_name LIKE 'SQL Test%' OR dl.link_name LIKE 'Sync Utils Test%'
         OR dl.link_name LIKE 'Orphaned Test%' OR dl.link_name LIKE 'Form Integration Test%'
         OR dl.link_name LIKE 'Fallback Test%')
    """

    total_deleted = 0

    for doctype, table in doctypes_to_check:
        try:
            # Find orphaned links for this doctype
            orphaned = frappe.db.sql(
                f"""
                SELECT dl.name, dl.link_name, dl.parent, dl.parenttype
                FROM `tabDynamic Link` dl
                WHERE dl.link_doctype = '{doctype}'
                  AND {test_patterns}
                  AND NOT EXISTS (SELECT 1 FROM `{table}` t WHERE t.name = dl.link_name)
            """,
                as_dict=True,
            )

            if orphaned:
                print(f"Found {len(orphaned)} orphaned {doctype} links")
                for link in orphaned:
                    try:
                        frappe.db.delete("Dynamic Link", {"name": link.name})
                        total_deleted += 1
                    except Exception as e:
                        print(f"  Failed to delete {link.name}: {e}")
        except Exception as e:
            print(f"Skipped {doctype}: {e}")

    frappe.db.commit()
    print(f"Cleanup complete: {total_deleted} orphaned links removed")


def _cleanup_mode_of_payment_accounts():
    """Remove Mode of Payment Account records pointing to non-existent accounts"""
    try:
        orphaned = frappe.db.sql(
            """
            SELECT mopa.name, mopa.parent, mopa.default_account, mopa.company
            FROM `tabMode of Payment Account` mopa
            WHERE NOT EXISTS (SELECT 1 FROM tabAccount a WHERE a.name = mopa.default_account)
        """,
            as_dict=True,
        )

        if orphaned:
            print(f"Found {len(orphaned)} orphaned Mode of Payment Account records")
            for o in orphaned:
                try:
                    frappe.db.delete("Mode of Payment Account", {"name": o.name})
                except Exception as e:
                    print(f"  Failed to delete {o.name}: {e}")
            frappe.db.commit()
    except Exception as e:
        print(f"Mode of Payment Account cleanup skipped: {e}")


if __name__ == "__main__":
    cleanup()
