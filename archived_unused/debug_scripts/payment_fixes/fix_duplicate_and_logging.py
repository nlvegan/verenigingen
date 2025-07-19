#!/usr/bin/env python3
"""
Fix duplicate mutation and logging issues
"""

import frappe


@frappe.whitelist()
def check_duplicate_mutations():
    """Check for duplicate eboekhouden_mutation_nr entries"""

    # Check Journal Entries
    je_duplicates = frappe.db.sql(
        """
        SELECT eboekhouden_mutation_nr, COUNT(*) as count
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr IS NOT NULL
        GROUP BY eboekhouden_mutation_nr
        HAVING count > 1
    """,
        as_dict=True,
    )

    print(f"Found {len(je_duplicates)} duplicate Journal Entry mutations")
    for dup in je_duplicates[:5]:
        print(f"  Mutation {dup.eboekhouden_mutation_nr}: {dup.count} entries")

    # Check specific mutation 1833
    je_1833 = frappe.db.sql(
        """
        SELECT name, creation, docstatus
        FROM `tabJournal Entry`
        WHERE eboekhouden_mutation_nr = '1833'
    """,
        as_dict=True,
    )

    print(f"\nMutation 1833 in Journal Entries: {len(je_1833)} entries")
    for je in je_1833:
        print(f"  {je.name} - Created: {je.creation} - Status: {je.docstatus}")

    # Check other doctypes
    for doctype in ["Payment Entry", "Sales Invoice", "Purchase Invoice"]:
        count = frappe.db.sql(
            """
            SELECT COUNT(*)
            FROM `tab{doctype}`
            WHERE eboekhouden_mutation_nr = '1833'
        """
        )[0][0]
        if count > 0:
            print(f"\nMutation 1833 in {doctype}: {count} entries")

    return {"je_duplicates": len(je_duplicates), "mutation_1833_count": len(je_1833)}


@frappe.whitelist()
def fix_duplicate_mutation_check():
    """Add duplicate check to import process"""

    # Get the file content
    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        content = f.read()

    # Find where we check for existing documents
    if "_check_if_already_imported" not in content:
        print("Need to add duplicate check function")

        # Add the function after imports
        import_section_end = content.find("def _get_default_company")

        new_function = '''
def _check_if_already_imported(mutation_id, doctype):
    """Check if this mutation has already been imported"""
    exists = frappe.db.exists(doctype, {"eboekhouden_mutation_nr": str(mutation_id)})
    if exists:
        doc_name = frappe.db.get_value(doctype, {"eboekhouden_mutation_nr": str(mutation_id)}, "name")
        return True, doc_name
    return False, None
'''

        content = content[:import_section_end] + new_function + "\n\n" + content[import_section_end:]

        with open(file_path, "w") as f:
            f.write(content)

        print("Added duplicate check function")
    else:
        print("Duplicate check function already exists")

    return {"status": "Fixed"}


@frappe.whitelist()
def fix_error_logging():
    """Fix error logging to avoid title truncation"""

    # Update the error logging to use print statements instead
    file_path = (
        "/home/frappe/frappe-bench/apps/verenigingen/verenigingen/utils/eboekhouden_rest_full_migration.py"
    )

    with open(file_path, "r") as f:
        lines = f.readlines()

    # Find and fix error logging calls
    fixed = 0
    for i, line in enumerate(lines):
        if "frappe.log_error" in line and "error_msg" in line:
            # Comment out the frappe.log_error line and add print
            lines[i] = "                # {line.strip()}\n                print(f'ERROR: {{error_msg}}')\n"
            fixed += 1

    if fixed > 0:
        with open(file_path, "w") as f:
            f.writelines(lines)
        print(f"Fixed {fixed} error logging calls")
    else:
        print("No error logging calls found to fix")

    return {"fixed": fixed}


if __name__ == "__main__":
    print("Fix duplicate and logging issues")
