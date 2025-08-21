import json

import frappe


def execute():
    """
    Fix workspace shortcuts that contain dict values in stats_filter fields
    which cause 'dict can not be used as parameter' errors during migration.
    """

    try:
        # Get all workspace shortcuts with stats_filter containing JSON dicts
        shortcuts = frappe.db.sql(
            """
            SELECT name, stats_filter
            FROM `tabWorkspace Shortcut`
            WHERE stats_filter IS NOT NULL
            AND stats_filter != ''
            AND stats_filter LIKE '{%'
        """,
            as_dict=True,
        )

        print(f"Found {len(shortcuts)} workspace shortcuts with potential dict issues")

        fixed_count = 0
        for shortcut in shortcuts:
            try:
                # Try to parse the stats_filter as JSON
                parsed = json.loads(shortcut.stats_filter)
                if isinstance(parsed, dict):
                    # This is problematic - clear the stats_filter
                    frappe.db.sql(
                        """
                        UPDATE `tabWorkspace Shortcut`
                        SET stats_filter = NULL
                        WHERE name = %s
                    """,
                        (shortcut.name,),
                    )
                    fixed_count += 1
                    print(f"Cleared stats_filter for shortcut: {shortcut.name}")

            except json.JSONDecodeError:
                # Not valid JSON, leave as is
                continue

        if fixed_count > 0:
            frappe.db.commit()
            print(f"Successfully fixed {fixed_count} workspace shortcuts")
        else:
            print("No workspace shortcuts needed fixing")

    except Exception as e:
        print(f"Error fixing workspace shortcuts: {str(e)}")
        frappe.log_error("Workspace Shortcuts Fix Error", str(e))
